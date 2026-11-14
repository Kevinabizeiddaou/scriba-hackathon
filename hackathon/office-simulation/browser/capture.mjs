#!/usr/bin/env node
/**
 * Screenshots of the Scriba Executive Desk frontend, running in LIVE mode against the
 * office-simulation sandbox backend.
 *
 *   node browser/capture.mjs --frontend http://localhost:5183 --api http://localhost:8924 \
 *        --out <dir> --name <label> [--run <runId>] [--approve <toolCallId>]
 *
 * What it does: signs in through the Desk's own sign-in form, opens each Desk screen, waits for
 * its data, stamps a SIMULATED banner above the application, and writes <label>-<screen>.png
 * plus <label>-capture.json (what was captured, what the browser logged, what failed).
 *
 * What it never does:
 *   - It changes no state. Every request to the API other than GET, and the sign-in POST, is
 *     aborted in the browser before it leaves. The one exception is --approve <toolCallId>,
 *     which lets exactly one request through: POST /chat/tool-calls/<that id>/approve, made by
 *     clicking the Desk's real Approve control.
 *   - It hides or rewrites nothing in the application. The banner is added above the page (the
 *     application is given less height, it is not covered), and the script checks that.
 *   - It fakes no result. A screen that shows an error, a sign-in form or a loader that never
 *     ends is still written to disk, is reported, and makes the exit code non-zero.
 *
 * The browser's clock is set to the sandbox world's clock (GET /sim/state) so that "today" and
 * "this week" in the Desk are the simulated day, not the day the capture was made. The banner
 * states that clock. --real-clock turns this off.
 *
 * Exit codes: 0 everything captured and settled; 1 a screen failed (see the message and the
 * JSON report); 2 bad arguments; 3 could not start a browser, reach the frontend or sign in.
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const BANNER_ID = 'officesim-capture-banner'
const BANNER_HEIGHT = 36
const BASE_VIEWPORT = { width: 1440, height: 900 }
const MAX_HEIGHT = 5000

const SCREENS = [
  { key: 'overview', hash: '#/overview', what: 'Overview: what needs the executive, the day, connections' },
  { key: 'inbox', hash: '#/inbox', what: 'Inbox: the sandbox mailboxes as the Desk reads them' },
  { key: 'work-queue', hash: '#/work', what: 'Work queue: the Desk runs opened from incoming mail' },
  { key: 'run', hash: null, what: 'Run detail: plan, proposed actions, evidence, timeline (needs --run)' },
  { key: 'approvals', hash: '#/approvals', what: 'Approval center: every action waiting for a decision' },
  { key: 'tasks', hash: '#/tasks', what: 'Tasks and follow-ups' },
  { key: 'activity', hash: '#/activity', what: 'Activity: what was executed, failed or cancelled' },
  { key: 'find-a-time', hash: '#/calendar/find-a-time', what: 'Find a time: free and busy across the sandbox calendars (GET /desk/availability)' },
  // Last on purpose: Scriba's /calendar/events names its own time zone, and the Desk adopts it for
  // every screen opened afterwards.
  { key: 'calendar', hash: '#/calendar', what: 'Calendar: the week grid, read from GET /calendar/events (Scriba, not the Desk overlay)' },
]

class Fatal extends Error {
  constructor(message, code = 3) {
    super(message)
    this.code = code
  }
}

/**
 * The seeded test user's password is defined by Scriba's own seeded server, not by this
 * repository. It is read from that file (SCRIBA_BACKEND_PATH, or ../.officesim.local.json) so
 * that no credential, even a test fixture's, is written here.
 */
function seededPassword() {
  let scriba = process.env.SCRIBA_BACKEND_PATH
  if (!scriba) {
    try {
      const local = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '.officesim.local.json')
      scriba = JSON.parse(fs.readFileSync(local, 'utf8')).SCRIBA_BACKEND_PATH
    } catch { /* no local configuration */ }
  }
  if (!scriba) return null
  try {
    const source = fs.readFileSync(path.join(scriba, 'e2e', 'seeded_server.py'), 'utf8')
    const found = source.match(/^ALICE_PASSWORD\s*=\s*["']([^"']+)["']/m)
    return found ? found[1] : null
  } catch {
    return null
  }
}

function usage() {
  return [
    'usage: node capture.mjs --frontend <url> --api <url> --out <dir> --name <label>',
    '                        [--run <runId>] [--approve <toolCallId>]',
    '                        [--screens overview,inbox,work-queue,run,approvals,tasks,activity,find-a-time,calendar]',
    '                        [--email <e>] [--password <p>] [--channel chrome|msedge|bundled]',
    '                        [--timeout <ms per screen, default 30000>] [--real-clock] [--headed]',
  ].join('\n')
}

function parseArgs(argv) {
  const flags = new Set(['real-clock', 'headed', 'help'])
  const values = new Set(['frontend', 'api', 'out', 'name', 'run', 'approve', 'screens', 'email', 'password', 'channel', 'timeout'])
  const out = {}
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (!arg.startsWith('--')) throw new Fatal(`Unexpected argument "${arg}".\n${usage()}`, 2)
    const [name, inline] = arg.slice(2).split(/=(.*)/s)
    if (flags.has(name)) { out[name] = true; continue }
    if (!values.has(name)) throw new Fatal(`Unknown option --${name}.\n${usage()}`, 2)
    const value = inline !== undefined ? inline : argv[++i]
    if (value === undefined || value === '') throw new Fatal(`--${name} needs a value.\n${usage()}`, 2)
    out[name] = value
  }
  return out
}

function requireArgs(args) {
  for (const name of ['frontend', 'api', 'out', 'name']) {
    if (!args[name]) throw new Fatal(`--${name} is required.\n${usage()}`, 2)
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(args.name)) throw new Fatal('--name may hold letters, digits, dot, dash and underscore only.', 2)
  for (const name of ['run', 'approve']) {
    if (args[name] !== undefined && !/^\d+$/.test(args[name])) throw new Fatal(`--${name} must be a number.`, 2)
  }
  const frontend = new URL(args.frontend)
  const api = new URL(args.api)
  if (frontend.hostname !== api.hostname) {
    // Scriba's session cookie is SameSite=Lax: localhost and 127.0.0.1 are different sites, and
    // the browser would not send the cookie from one to the other.
    throw new Fatal(`--frontend (${frontend.hostname}) and --api (${api.hostname}) must use the same host name, or the session cookie is not sent. Use "localhost" for both.`, 2)
  }
  return { frontend: frontend.origin, api: api.origin }
}

async function launch(args) {
  const wanted = args.channel ? [args.channel] : ['bundled', 'chrome', 'msedge']
  const errors = []
  for (const channel of wanted) {
    try {
      if (channel === 'bundled') {
        if (!fs.existsSync(chromium.executablePath())) throw new Error('Playwright\'s own Chromium is not downloaded')
        return { browser: await chromium.launch({ headless: !args.headed }), channel }
      }
      return { browser: await chromium.launch({ channel, headless: !args.headed }), channel }
    } catch (error) {
      errors.push(`${channel}: ${String(error.message).split('\n')[0]}`)
    }
  }
  throw new Fatal(`No browser could be started (${errors.join('; ')}). Install Chrome or Edge, or run "npx playwright install chromium" in browser/.`)
}

/** In-flight API requests, so "the data is in" can be observed instead of guessed. */
function trackApi(page, apiOrigin, log) {
  const inflight = new Set()
  let lastActivity = Date.now()
  const touch = () => { lastActivity = Date.now() }
  page.on('request', request => {
    if (request.url().startsWith(apiOrigin)) { inflight.add(request); touch() }
  })
  const done = request => { if (inflight.delete(request)) touch() }
  page.on('requestfinished', done)
  page.on('requestfailed', request => {
    done(request)
    if (request.url().startsWith(apiOrigin)) {
      log.failedRequests.push({ method: request.method(), url: request.url(), error: request.failure()?.errorText ?? 'failed', screen: log.screen })
    }
  })
  // What two of Scriba's own routes gave the page, so that a screen that is empty because the
  // route is empty can be told from a screen that failed to draw what it was given.
  const seen = { calendar: {}, tasks: null }
  page.on('response', response => {
    if (!response.url().startsWith(apiOrigin)) return
    if (response.status() >= 400) {
      log.httpErrors.push({ status: response.status(), method: response.request().method(), url: response.url(), screen: log.screen })
      return
    }
    if (response.request().method() !== 'GET') return
    const url = new URL(response.url())
    if (url.pathname === '/calendar/events') {
      response.json().then(body => { seen.calendar[url.searchParams.get('provider') ?? 'default'] = { meetings: (body.meetings ?? []).length, timezone: body.timezone ?? null, range: body.range ?? null } }, () => {})
    } else if (url.pathname === '/tasks') {
      response.json().then(body => { seen.tasks = (body.tasks ?? []).map(task => String(task.title ?? '')) }, () => {})
    }
  })
  page.on('console', message => {
    if (message.type() === 'error' || message.type() === 'warning') {
      log.console.push({ type: message.type(), text: message.text().slice(0, 500), screen: log.screen })
    }
  })
  page.on('pageerror', error => log.pageErrors.push({ text: String(error.message).slice(0, 500), screen: log.screen }))
  return { quietFor: () => (inflight.size === 0 ? Date.now() - lastActivity : 0), pending: () => inflight.size, seen }
}

/**
 * Nothing but reads leaves the browser. Returns the list of requests that were stopped, and a
 * switch that lets exactly one approve through.
 */
async function guardWrites(context, apiOrigin, log) {
  const guard = { allowApprove: null, approveSeen: null }
  await context.route(url => url.href.startsWith(apiOrigin), async route => {
    const request = route.request()
    const method = request.method()
    const pathname = new URL(request.url()).pathname
    if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') return route.continue()
    if (method === 'POST' && pathname === '/auth/signin') return route.continue()
    if (method === 'POST' && guard.allowApprove !== null && pathname === `/chat/tool-calls/${guard.allowApprove}/approve` && guard.approveSeen === null) {
      guard.approveSeen = pathname
      return route.continue()
    }
    log.blockedWrites.push({ method, path: pathname, screen: log.screen })
    return route.abort('blockedbyclient')
  })
  return guard
}

async function signIn(page, context, origins, credentials, timeout) {
  const shell = page.locator('nav[aria-label="Main"]').first()
  const form = page.locator('#desk-email')
  const response = await page.goto(`${origins.frontend}/#/overview`, { waitUntil: 'domcontentloaded', timeout }).catch(error => {
    throw new Fatal(`The frontend at ${origins.frontend} could not be opened: ${String(error.message).split('\n')[0]}`)
  })
  if (response && !response.ok()) throw new Fatal(`The frontend at ${origins.frontend} answered ${response.status()}.`)
  await shell.or(form).first().waitFor({ state: 'visible', timeout }).catch(() => {
    throw new Fatal(`The frontend at ${origins.frontend} showed neither the Desk nor its sign-in form within ${timeout} ms. Is it the Desk, in live mode?`)
  })
  if (await shell.isVisible()) return 'existing session'

  const unreachable = page.getByText(/could not be reached/i)
  if (await unreachable.isVisible().catch(() => false)) {
    throw new Fatal(`The Desk says its API could not be reached: "${(await unreachable.first().innerText()).trim()}". Is the sandbox running at ${origins.api}, started with ALLOWED_ORIGINS=${origins.frontend}?`)
  }
  await form.fill(credentials.email)
  await page.locator('#desk-password').fill(credentials.password)
  await page.getByRole('button', { name: 'Sign in with email' }).click()
  try {
    await shell.waitFor({ state: 'visible', timeout })
    return 'sign-in form'
  } catch {
    const alert = await page.locator('[role="alert"]').first().innerText().catch(() => '')
    // The form is the Desk's own path. If it failed for a reason that is not the password, try
    // Scriba's sign-in route directly in the same browser context (same cookie jar), once.
    const direct = await context.request.post(`${origins.api}/auth/signin`, {
      headers: { Origin: origins.frontend }, data: credentials, failOnStatusCode: false,
    }).catch(() => null)
    if (direct && direct.ok()) {
      await page.reload({ waitUntil: 'domcontentloaded' })
      if (await shell.waitFor({ state: 'visible', timeout }).then(() => true, () => false)) return `API sign-in (the form failed: ${alert || 'no message'})`
    }
    throw new Fatal(`Sign-in as ${credentials.email} failed${alert ? `: "${alert.trim()}"` : ''}${direct ? ` (POST /auth/signin answered ${direct.status()})` : ''}.`)
  }
}

/** The sandbox world's clock, or null when the backend has no /sim control surface. */
async function sandboxInfo(context, origins) {
  const read = async pathname => {
    const response = await context.request.get(`${origins.api}${pathname}`, { headers: { Origin: origins.frontend }, failOnStatusCode: false }).catch(() => null)
    return response && response.ok() ? response.json().catch(() => null) : null
  }
  const [state, health, meta] = await Promise.all([read('/sim/state'), read('/desk/health'), read('/sim/meta')])
  return {
    now: state?.world?.now ?? null,
    timezone: state?.world?.timezone ?? meta?.timezone ?? null,
    worldId: state?.world?.id ?? health?.sandbox?.id ?? null,
    executionMode: health?.executionMode ?? null,
    externalWritesEnabled: health?.externalWrites?.enabled ?? null,
    overlay: health?.version ?? null,
    simulated: meta?.simulated ?? null,
    world: state?.world ? {
      events: (state.world.events ?? []).length,
      tasks: (state.world.tasks ?? []).map(task => String(task.title ?? '')),
      operations: (state.world.operations ?? []).length,
      isolationViolations: (state.world.isolationViolations ?? []).length,
    } : null,
  }
}

function clockLabel(iso, timezone) {
  if (!iso) return null
  try {
    return `${new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: timezone ?? 'UTC' }).format(new Date(iso))} ${timezone ?? 'UTC'}`
  } catch {
    return iso
  }
}

/**
 * The label on every screenshot. It sits above the application: the document is given a top
 * padding of its height, so the application is shorter, not covered.
 */
async function ensureBanner(page, text) {
  const layout = await page.evaluate(({ id, height, text }) => {
    let bar = document.getElementById(id)
    if (!bar) {
      const style = document.createElement('style')
      style.id = `${id}-style`
      style.textContent = `html{box-sizing:border-box !important;padding-top:${height}px !important;}`
      document.head.appendChild(style)
      bar = document.createElement('div')
      bar.id = id
      bar.setAttribute('role', 'note')
      bar.setAttribute('aria-label', 'Capture label: simulated data')
      bar.style.cssText = [
        'position:fixed', 'top:0', 'left:0', 'right:0', `height:${height}px`, 'z-index:2147483647', 'box-sizing:border-box',
        'display:flex', 'align-items:center', 'justify-content:center', 'gap:10px', 'padding:0 16px',
        'background:#f5b301', 'color:#111111', 'border-bottom:2px solid #111111',
        'font:700 13px/1 system-ui,-apple-system,"Segoe UI",Arial,sans-serif', 'letter-spacing:0.02em',
        'white-space:nowrap', 'overflow:hidden', 'text-overflow:ellipsis', 'pointer-events:none',
      ].join(';')
      document.body.appendChild(bar)
    }
    bar.textContent = text
    const box = bar.getBoundingClientRect()
    const root = document.getElementById('root')?.getBoundingClientRect()
    return { barBottom: box.bottom, barWidth: box.width, rootTop: root ? root.top : null, text: bar.textContent }
  }, { id: BANNER_ID, height: BANNER_HEIGHT, text })
  if (!(layout.barWidth > 0) || layout.barBottom < BANNER_HEIGHT - 1) throw new Error('the SIMULATED banner is not visible')
  if (layout.rootTop === null || layout.rootTop < layout.barBottom - 1) throw new Error('the SIMULATED banner would cover the application')
  return layout
}

/** Waits until the screen has its data: no placeholder rows, no "reading…" notes, API quiet. */
async function settle(page, api, timeout) {
  const started = Date.now()
  let state = null
  while (Date.now() - started < timeout) {
    state = await page.evaluate(() => {
      const main = document.getElementById('main')
      if (!main) return { main: false }
      const visible = element => element.getClientRects().length > 0
      const loaders = [...main.querySelectorAll('.animate-pulse')].filter(visible).length
      const reading = [...main.querySelectorAll('[role="status"]')].filter(visible).map(el => el.textContent ?? '').filter(text => /…\s*$|\.\.\.\s*$/.test(text.trim())).length
      return { main: true, loaders, reading }
    }).catch(() => ({ main: false }))
    if (state.main && state.loaders === 0 && state.reading === 0 && api.quietFor() >= 700) return { settled: true, ms: Date.now() - started }
    await page.waitForTimeout(150)
  }
  return { settled: false, ms: Date.now() - started, state, pendingRequests: api.pending() }
}

/** What the screen says, read from the page itself, for the report and the failure checks. */
async function describe(page) {
  return page.evaluate(() => {
    const main = document.getElementById('main')
    const visible = element => element.getClientRects().length > 0
    const text = element => (element.textContent ?? '').replace(/\s+/g, ' ').trim()
    // innerText, not textContent: adjacent elements must not run together into one word.
    const shellNote = document.querySelector('[data-testid="data-source"]')
    const marker = element => (element && visible(element) ? /sandbox|simulated/i.test(element.innerText ?? '') : false)
    return {
      signInForm: document.getElementById('desk-email') !== null,
      heading: main ? [...main.querySelectorAll('h1')].filter(visible).map(text)[0] ?? null : null,
      alerts: main ? [...main.querySelectorAll('[role="alert"]')].filter(visible).map(el => text(el).slice(0, 300)) : [],
      toolCalls: main ? [...main.querySelectorAll('[data-testid="tool-call"]')].map(el => ({ status: el.getAttribute('data-status'), label: (el.getAttribute('aria-label') ?? text(el)).slice(0, 160) })) : [],
      // Whether the application itself says the data is a sandbox, apart from the capture banner:
      // in the shell's data-source note (left column), and in the screen's own content.
      uiSandboxMarker: { shell: marker(shellNote), screen: marker(main) },
      shellUser: (() => { const el = document.querySelector('aside span.truncate'); return el ? text(el) : null })(),
      mainTextLength: main ? text(main).length : 0,
    }
  })
}

/** The Desk scrolls inside <main>. The window is made tall enough that the whole screen is in the picture. */
async function fitHeight(page) {
  await page.setViewportSize(BASE_VIEWPORT)
  for (let pass = 0; pass < 3; pass += 1) {
    const extra = await page.evaluate(() => {
      let most = 0
      for (const element of document.querySelectorAll('#main, #main *, aside nav')) {
        const style = getComputedStyle(element)
        if (!/(auto|scroll)/.test(style.overflowY)) continue
        most = Math.max(most, element.scrollHeight - element.clientHeight)
      }
      return most
    })
    if (extra <= 0) break
    const current = page.viewportSize().height
    if (current >= MAX_HEIGHT) break
    await page.setViewportSize({ width: BASE_VIEWPORT.width, height: Math.min(MAX_HEIGHT, current + extra + 8) })
    await page.waitForTimeout(150)
  }
  return page.viewportSize()
}

async function captureScreen(page, api, screen, ctx) {
  const { origins, args, bannerText, log, timeout } = ctx
  const entry = { screen: screen.key, route: screen.hash, what: screen.what, file: null, ok: false, problems: [], warnings: [] }
  log.screen = screen.key
  try {
    await page.setViewportSize(BASE_VIEWPORT)
    await page.goto(`${origins.frontend}/${screen.hash}`, { waitUntil: 'domcontentloaded', timeout })
    // Same document, new hash: the router reacts to hashchange. Make sure the route is the one asked for.
    await page.waitForFunction(hash => window.location.hash === hash, screen.hash, { timeout })
    await page.locator('#main').waitFor({ state: 'visible', timeout }).catch(() => {})
    const settled = await settle(page, api, timeout)
    if (!settled.settled) entry.problems.push(`still loading after ${timeout} ms (${JSON.stringify(settled.state)}, ${settled.pendingRequests} API request(s) pending)`)
    entry.settleMs = settled.ms

    if (screen.afterSettle) await screen.afterSettle(page, entry)
    if (screen.compare) screen.compare(api.seen, ctx.sandbox, entry)

    entry.viewport = await fitHeight(page)
    await ensureBanner(page, bannerText)
    const seen = await describe(page)
    Object.assign(entry, { heading: seen.heading, alerts: seen.alerts, toolCalls: seen.toolCalls, uiSandboxMarker: seen.uiSandboxMarker, shellUser: seen.shellUser })
    if (seen.signInForm) entry.problems.push('the sign-in form is showing: the session was not accepted')
    if (seen.mainTextLength < 20) entry.problems.push('the screen is empty')
    if (seen.alerts.length > 0) entry.problems.push(`the screen shows ${seen.alerts.length} error note(s): ${seen.alerts.map(a => `"${a}"`).join(' | ')}`)

    const file = path.join(args.out, `${args.name}-${screen.file ?? screen.key}.png`)
    await page.screenshot({ path: file, animations: 'disabled', caret: 'hide' })
    entry.file = path.basename(file)
    entry.ok = entry.problems.length === 0
  } catch (error) {
    entry.problems.push(String(error.message).split('\n')[0])
    // A picture of what went wrong is more use than no picture. It is named as a failure.
    const file = path.join(args.out, `${args.name}-${screen.file ?? screen.key}-FAILED.png`)
    await ensureBanner(page, bannerText).catch(() => {})
    if (await page.screenshot({ path: file }).then(() => true, () => false)) entry.file = path.basename(file)
  }
  return entry
}

/**
 * --approve: click the Desk's real Approve control for one action. The action is found on its
 * run's own screen; the click is refused unless the control is there and enabled, and the write
 * guard lets through only POST /chat/tool-calls/<id>/approve for that id.
 */
async function approveThroughUi(page, api, context, guard, ctx) {
  const { origins, args, bannerText, log, timeout } = ctx
  const id = Number(args.approve)
  const entry = { screen: 'approve', toolCallId: id, ok: false, clicked: false, problems: [], files: [] }
  log.screen = 'approve'
  const fail = message => { entry.problems.push(message); return entry }

  const get = async pathname => {
    const response = await context.request.get(`${origins.api}${pathname}`, { headers: { Origin: origins.frontend }, failOnStatusCode: false })
    return response.ok() ? response.json() : null
  }
  const runs = (await get('/desk/runs?limit=200'))?.runs ?? []
  let runId = null
  for (const row of runs) {
    const run = await get(`/desk/runs/${row.runId}`)
    if ((run?.actions ?? []).some(action => Number(action.toolCallId) === id)) { runId = row.runId; break }
  }
  if (runId === null) return fail(`no Desk run has an action with tool call ${id}`)
  entry.runId = runId
  const before = (await get(`/chat/tool-calls/${id}`))?.tool_call
  if (!before) return fail(`GET /chat/tool-calls/${id} did not return the action`)
  entry.statusBefore = before.status
  if (before.status !== 'awaiting_approval') return fail(`tool call ${id} is "${before.status}", not awaiting approval: there is nothing to approve`)

  await page.setViewportSize(BASE_VIEWPORT)
  await page.goto(`${origins.frontend}/#/work/${runId}`, { waitUntil: 'domcontentloaded', timeout })
  await settle(page, api, timeout)
  const cards = page.locator('#main [data-testid="tool-call"][data-status="awaiting_approval"]')
  const count = await cards.count()
  if (count !== 1) return fail(`run ${runId} shows ${count} action card(s) awaiting approval; exactly one is needed to be sure which is tool call ${id}`)
  const button = cards.first().getByRole('button', { name: /^Approve/ })
  if ((await button.count()) !== 1) return fail('the action card has no Approve control')
  entry.control = (await button.innerText()).trim()
  if (await button.isDisabled()) {
    const reason = await cards.first().locator('[data-testid="gate-reason"]').innerText().catch(() => '')
    await fitHeight(page); await ensureBanner(page, bannerText)
    const file = path.join(args.out, `${args.name}-approve-${id}-disabled.png`)
    await page.screenshot({ path: file }); entry.files.push(path.basename(file))
    return fail(`the Approve control ("${entry.control}") is disabled${reason ? `: ${reason.trim()}` : ''}`)
  }

  await fitHeight(page); await ensureBanner(page, bannerText)
  const beforeFile = path.join(args.out, `${args.name}-approve-${id}-before.png`)
  await page.screenshot({ path: beforeFile, animations: 'disabled' }); entry.files.push(path.basename(beforeFile))

  guard.allowApprove = id
  const responded = page.waitForResponse(response => new URL(response.url()).pathname === `/chat/tool-calls/${id}/approve` && response.request().method() === 'POST', { timeout })
  await button.click()
  entry.clicked = true
  const response = await responded.catch(() => null)
  guard.allowApprove = null
  if (!response) return fail(`the click did not produce POST /chat/tool-calls/${id}/approve within ${timeout} ms`)
  entry.approveStatus = response.status()
  await settle(page, api, timeout)
  const after = (await get(`/chat/tool-calls/${id}`))?.tool_call
  entry.statusAfter = after?.status ?? null
  await fitHeight(page); await ensureBanner(page, bannerText)
  const afterFile = path.join(args.out, `${args.name}-approve-${id}-after.png`)
  await page.screenshot({ path: afterFile, animations: 'disabled' }); entry.files.push(path.basename(afterFile))
  // The result is whatever the server says it is. Nothing here decides that it succeeded.
  if (!response.ok()) return fail(`POST /chat/tool-calls/${id}/approve answered ${response.status()}`)
  if (entry.statusAfter !== 'executed') return fail(`after the approve the action is "${entry.statusAfter}", not executed`)
  entry.ok = true
  return entry
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  if (args.help) { console.log(usage()); return 0 }
  const origins = requireArgs(args)
  const timeout = Number(args.timeout ?? 30000)
  if (!Number.isFinite(timeout) || timeout < 1000) throw new Fatal('--timeout must be a number of milliseconds, at least 1000.', 2)
  args.out = path.resolve(args.out)
  fs.mkdirSync(args.out, { recursive: true })

  const credentials = {
    email: args.email ?? process.env.OFFICESIM_EMAIL ?? 'alice@example.com',
    password: args.password ?? process.env.OFFICESIM_PASSWORD ?? seededPassword(),
  }
  if (!credentials.password) {
    throw new Fatal('No sign-in password: set OFFICESIM_PASSWORD or pass --password (the seeded test ' +
      "user's password is in Scriba's e2e/seeded_server.py; it is not kept in this repository).", 2)
  }

  let screens = SCREENS.map(screen => ({ ...screen }))
  if (args.screens) {
    const wanted = args.screens.split(',').map(s => s.trim()).filter(Boolean)
    const unknown = wanted.filter(key => !SCREENS.some(screen => screen.key === key))
    if (unknown.length) throw new Fatal(`Unknown screen(s): ${unknown.join(', ')}. Known: ${SCREENS.map(s => s.key).join(', ')}.`, 2)
    if (wanted.includes('run') && !args.run) throw new Fatal('--screens run needs --run <runId>.', 2)
    screens = screens.filter(screen => wanted.includes(screen.key))
  }
  screens = screens.filter(screen => screen.key !== 'run' || args.run)
  // Two screens read Scriba's own routes, not the Desk overlay. When such a route does not answer
  // from the sandbox world the screen is honest but is not showing the simulation: say so.
  for (const screen of screens) {
    if (screen.key === 'calendar') {
      screen.compare = (seen, sandbox, entry) => {
        const answers = Object.entries(seen.calendar)
        entry.calendarEvents = seen.calendar
        const shown = answers.reduce((sum, [, answer]) => sum + answer.meetings, 0)
        if (sandbox?.world && sandbox.world.events > 0 && answers.length > 0 && shown === 0) {
          entry.warnings.push(`the week grid is empty: GET /calendar/events gave the page ${answers.map(([provider, answer]) => `${answer.meetings} meeting(s) for ${provider} (time zone ${answer.timezone})`).join(', ')}, while the sandbox world holds ${sandbox.world.events} event(s)`)
        }
      }
    }
    if (screen.key === 'tasks') {
      screen.compare = (seen, sandbox, entry) => {
        entry.tasksFromApi = seen.tasks
        if (!sandbox?.world || seen.tasks === null) return
        const missing = sandbox.world.tasks.filter(title => !seen.tasks.includes(title))
        if (missing.length > 0) {
          entry.warnings.push(`GET /tasks gave the page ${seen.tasks.length} task(s) (${seen.tasks.map(t => `"${t}"`).join(', ') || 'none'}); ${missing.length} of the sandbox world's ${sandbox.world.tasks.length} task(s) are not among them (${missing.map(t => `"${t}"`).join(', ')})`)
        }
      }
    }
  }
  for (const screen of screens) {
    if (screen.key !== 'run') continue
    screen.hash = `#/work/${args.run}`
    screen.file = `run-${args.run}`
    // The run screen must be the run that was asked for, not the queue's "no such run" fallback.
    screen.afterSettle = async (page, entry) => {
      const cards = await page.locator('#main [data-testid="tool-call"], #main [data-testid="action-fallback"]').count()
      entry.actionCards = cards
      const run = await page.context().request.get(`${origins.api}/desk/runs/${args.run}`, { headers: { Origin: origins.frontend }, failOnStatusCode: false })
      if (!run.ok()) { entry.problems.push(`run ${args.run} does not exist on this backend (GET /desk/runs/${args.run} answered ${run.status()})`); return }
      const data = await run.json()
      entry.run = { runId: data.runId ?? Number(args.run), subject: data.subject ?? null, state: data.state ?? null, stage: data.lifecycle?.stage ?? null, simulated: data.simulated ?? null, actions: (data.actions ?? []).map(a => ({ toolCallId: a.toolCallId, tool: a.tool_name, status: a.status, simulated: a.simulated ?? null })) }
      // The picture must be of this run: its number is in the screen's subtitle ("Run 11. ...").
      const named = await page.locator('#main').getByText(new RegExp(`\\bRun ${args.run}\\b`)).first().isVisible().catch(() => false)
      if (!named) entry.problems.push(`the screen does not show run ${args.run}`)
      if (cards < entry.run.actions.length) entry.problems.push(`run ${args.run} has ${entry.run.actions.length} action(s) on the server but the screen shows ${cards} card(s)`)
    }
  }

  const log = { screen: 'start', console: [], pageErrors: [], failedRequests: [], httpErrors: [], blockedWrites: [] }
  const report = {
    simulated: true,
    label: args.name,
    capturedAt: new Date().toISOString(),
    frontend: origins.frontend,
    api: origins.api,
    user: credentials.email,
    browser: null,
    signIn: null,
    sandbox: null,
    browserClock: null,
    banner: null,
    screens: [],
    approve: null,
    log,
  }
  const reportFile = path.join(args.out, `${args.name}-capture.json`)
  const writeReport = () => fs.writeFileSync(reportFile, `${JSON.stringify(report, null, 1)}\n`)

  const { browser, channel } = await launch(args)
  report.browser = `${channel} ${browser.version()}`
  let exit = 0
  try {
    const context = await browser.newContext({ viewport: BASE_VIEWPORT, deviceScaleFactor: 1, locale: 'en-GB', colorScheme: 'dark' })
    const guard = await guardWrites(context, origins.api, log)
    const page = await context.newPage()
    const api = trackApi(page, origins.api, log)

    report.signIn = await signIn(page, context, origins, credentials, timeout)
    report.sandbox = await sandboxInfo(context, origins)

    const clock = clockLabel(report.sandbox.now, report.sandbox.timezone)
    if (report.sandbox.now && !args['real-clock']) {
      // Date.now() in the page is the sandbox world's time; timers keep running normally.
      await page.clock.setFixedTime(new Date(report.sandbox.now))
      report.browserClock = { fixedTo: report.sandbox.now, why: 'the Desk computes "today" and "this week" from the browser clock; the sandbox world is on its own date' }
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.locator('nav[aria-label="Main"]').first().waitFor({ state: 'visible', timeout })
    } else {
      report.browserClock = { fixedTo: null, why: report.sandbox.now ? '--real-clock' : 'the backend has no /sim/state: not an office-simulation sandbox, or not reachable' }
    }
    const bannerText = [
      'SIMULATED: sandbox data, fictional office, nothing real was sent or changed',
      clock && !args['real-clock'] ? `sandbox clock ${clock}` : null,
      `capture ${args.name}`,
    ].filter(Boolean).join('  ·  ')
    report.banner = bannerText
    const ctx = { origins, args, bannerText, log, timeout, sandbox: report.sandbox }

    if (args.approve) {
      report.approve = await approveThroughUi(page, api, context, guard, ctx)
      report.sandboxAfterApprove = await sandboxInfo(context, origins)
      console.log(`${report.approve.ok ? 'ok  ' : 'FAIL'} approve ${args.approve}${report.approve.problems.length ? `: ${report.approve.problems.join('; ')}` : ` -> ${report.approve.statusAfter} (clicked "${report.approve.control}")`}`)
      if (!report.approve.ok) exit = 1
    }

    for (const screen of screens) {
      const entry = await captureScreen(page, api, screen, ctx)
      report.screens.push(entry)
      console.log(`${entry.ok ? 'ok  ' : 'FAIL'} ${screen.key.padEnd(10)} ${entry.file ? path.basename(entry.file) : '(no file)'}${entry.heading ? `  "${entry.heading}"` : ''}${entry.problems.length ? `\n     ${entry.problems.join('\n     ')}` : ''}${entry.warnings.length ? `\n     warn: ${entry.warnings.join('\n     warn: ')}` : ''}`)
      if (!entry.ok) exit = 1
      writeReport()
    }
    log.screen = 'end'

    if (log.blockedWrites.length) {
      console.log(`note: ${log.blockedWrites.length} write request(s) from the page were stopped by the read-only guard: ${[...new Set(log.blockedWrites.map(w => `${w.method} ${w.path}`))].join(', ')}`)
    }
    if (log.httpErrors.length) console.log(`note: ${log.httpErrors.length} API response(s) with an error status; see ${path.basename(reportFile)}`)
    if (log.pageErrors.length) console.log(`note: ${log.pageErrors.length} uncaught page error(s); see ${path.basename(reportFile)}`)
    await context.close()
  } finally {
    writeReport()
    await browser.close().catch(() => {})
  }
  console.log(`${exit === 0 ? 'Captured' : 'Captured WITH FAILURES'}: ${report.screens.filter(s => s.file).length} screenshot(s) in ${args.out} (report: ${path.basename(reportFile)})`)
  return exit
}

main().then(
  code => { process.exitCode = code },
  error => {
    console.error(`capture failed: ${error.message}`)
    process.exitCode = error instanceof Fatal ? error.code : 3
  },
)
