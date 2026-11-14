#!/usr/bin/env node
/**
 * One continuous video of the Scriba Executive Desk frontend handling mail in the
 * office-simulation sandbox, driven through the real UI.
 *
 *   node browser/record.mjs --frontend http://localhost:5183 --api http://localhost:8924 \
 *        --out evidence/demo/recording --name desk-demo [--frontend-rev <sha>] [--no-second-part]
 *
 * Writes <name>.webm, <name>.json and <name>-still-*.png into --out.
 *
 * What is real: the frontend, the backend, the Desk's own background intake worker (the sandbox
 * must be started with --worker thread), and every approval, which is a click on the Desk's
 * Approve control. What the script does itself, outside the page, playing the outside world:
 * POST /sim/clock once and POST /sim/deliver once per message. Those requests are listed in the
 * JSON under scriptRequests. The page is allowed two kinds of write: the sign-in POST and
 * POST /chat/tool-calls/<id>/approve for the action being approved at that moment; anything else
 * is aborted and listed under blockedWrites.
 *
 * Every frame carries a yellow bar: the SIMULATED label and a caption naming the step. The bar is
 * installed before the page's own scripts on every load, above the application, not over it.
 * Nothing is faked: if a step does not happen (no run within the wait, a control missing or
 * disabled, a status other than executed) the caption says so, the JSON records it, and the exit
 * code is 1.
 *
 * The browser's Date.now() is set to the sandbox clock so that "today" in the Desk is the
 * simulated day. Times the backend stamps with the real clock (the worker's "last pass") stay real.
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const VIEWPORT = { width: 1280, height: 800 }
/** The video is scaled to this, to keep a two-minute file near 20 MB. */
const VIDEO_SIZE = { width: 1152, height: 720 }
/** The sandbox world's time zone. Checked against GET /sim/meta after sign-in. */
const WORLD_TIME_ZONE = 'Europe/Paris'
const BAR_HEIGHT = 58
const CLOCK = '2026-11-16T08:30:20+01:00'
const SIM_LINE = 'SIMULATED: sandbox data, fictional office, nothing real was sent or changed'

const MEI = {
  message_id: 'demo-mei-intro', thread_id: 'thread-demo-mei-intro',
  from_addr: 'Mei Tanaka <mei.tanaka@brightwavefoods.example>',
  subject: 'Cold-chain lanes: intro call',
  body: 'Hi Layla, would you be free on Wednesday at 14:00 for a 30 minute call to walk through the new cold-chain lanes?',
}
const GRETA = {
  message_id: 'demo-greta-forecast', thread_id: 'thread-demo-greta-forecast',
  from_addr: 'Greta Lindqvist <greta.lindqvist@nordlicht-retail.example>',
  subject: 'Peak-season forecast',
  body: 'Hi Layla, could we meet tomorrow at 14:30 for an hour to go over the peak-season forecast?',
}

class Fatal extends Error {
  constructor(message, code = 3) { super(message); this.code = code }
}

/** The seeded test user's password, read from the Scriba checkout. It is never written anywhere. */
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
  } catch { return null }
}

function parseArgs(argv) {
  const flags = new Set(['no-second-part', 'headed'])
  const values = new Set(['frontend', 'api', 'out', 'name', 'frontend-rev', 'channel', 'email', 'password'])
  const out = {}
  for (let i = 0; i < argv.length; i += 1) {
    const name = argv[i].replace(/^--/, '')
    if (flags.has(name)) { out[name] = true; continue }
    if (!values.has(name) || argv[i + 1] === undefined) throw new Fatal(`Bad option ${argv[i]}.`, 2)
    out[name] = argv[++i]
  }
  for (const name of ['frontend', 'api', 'out', 'name']) if (!out[name]) throw new Fatal(`--${name} is required.`, 2)
  if (new URL(out.frontend).hostname !== new URL(out.api).hostname) throw new Fatal('--frontend and --api must use the same host name ("localhost"), or the session cookie is not sent.', 2)
  return out
}

async function launch(args) {
  const errors = []
  for (const channel of args.channel ? [args.channel] : ['bundled', 'chrome', 'msedge']) {
    try {
      if (channel === 'bundled') {
        if (!fs.existsSync(chromium.executablePath())) throw new Error('not downloaded')
        return { browser: await chromium.launch({ headless: !args.headed }), channel }
      }
      return { browser: await chromium.launch({ channel, headless: !args.headed }), channel }
    } catch (error) { errors.push(`${channel}: ${String(error.message).split('\n')[0]}`) }
  }
  throw new Fatal(`No browser could be started (${errors.join('; ')}).`)
}

/** Runs in the page before its own scripts, on every load: the bar is there from the first frame. */
function installBar({ height, simLine }) {
  const make = () => {
    if (document.getElementById('officesim-bar')) return
    const style = document.createElement('style')
    style.textContent = `html{box-sizing:border-box !important;padding-top:${height}px !important;}`
    const bar = document.createElement('div')
    bar.id = 'officesim-bar'
    bar.setAttribute('role', 'note')
    bar.style.cssText = `position:fixed;top:0;left:0;right:0;height:${height}px;z-index:2147483647;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;padding:0 14px;background:#f5b301;color:#111;border-bottom:2px solid #111;font-family:system-ui,-apple-system,"Segoe UI",Arial,sans-serif;pointer-events:none;text-align:center`
    const top = document.createElement('div')
    top.id = 'officesim-bar-sim'
    top.style.cssText = 'font-weight:800;font-size:12.5px;line-height:1;letter-spacing:.03em;white-space:nowrap'
    top.textContent = simLine
    const caption = document.createElement('div')
    caption.id = 'officesim-bar-caption'
    caption.style.cssText = 'font-weight:600;font-size:15px;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%'
    let stored = ''
    try { stored = sessionStorage.getItem('officesim-caption') || '' } catch { /* about:blank */ }
    caption.textContent = stored
    bar.append(top, caption)
    document.documentElement.append(style, bar)
  }
  if (document.documentElement) make()
  else new MutationObserver((_, observer) => { if (document.documentElement) { observer.disconnect(); make() } }).observe(document, { childList: true })
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  const frontend = new URL(args.frontend).origin
  const api = new URL(args.api).origin
  const outDir = path.resolve(args.out)
  fs.mkdirSync(outDir, { recursive: true })
  const credentials = { email: args.email ?? process.env.OFFICESIM_EMAIL ?? 'alice@example.com', password: args.password ?? process.env.OFFICESIM_PASSWORD ?? seededPassword() }
  if (!credentials.password) throw new Fatal('No sign-in password: set OFFICESIM_PASSWORD (it is not kept in this repository).', 2)

  const report = {
    simulated: true,
    name: args.name,
    recordedAt: new Date().toISOString(),
    video: `${args.name}.webm`,
    viewport: VIEWPORT,
    videoSize: VIDEO_SIZE,
    browserTimeZone: { set: WORLD_TIME_ZONE, why: 'the Desk shows times in the zone of the browser until a response names another; the browser is put in the zone of the sandbox world so that 14:00 in the message reads 14:00 on screen' },
    frontend: { url: frontend, revision: args['frontend-rev'] ?? null },
    backend: { url: api, overlay: null, revision: null, sim: null, executionMode: null, externalWritesEnabled: null, workerAtStart: null },
    browser: null,
    browserClock: { fixedTo: CLOCK, why: 'the Desk computes "today" from the browser clock; the sandbox world is on its own date. Times stamped by the backend with the real clock (the worker\'s last pass) are real.' },
    steps: [],
    runs: {},
    approvals: [],
    stills: [],
    scriptRequests: [],
    pageWrites: [],
    blockedWrites: [],
    problems: [],
    console: [],
    world: null,
    durationSeconds: null,
  }
  const reportFile = path.join(outDir, `${args.name}.json`)
  const save = () => fs.writeFileSync(reportFile, `${JSON.stringify(report, null, 1)}\n`)

  const { browser, channel } = await launch(args)
  report.browser = `${channel} ${browser.version()}`
  const videoTmp = path.join(outDir, `.${args.name}-video-tmp`)
  let page = null
  let context = null
  let failed = false
  try {
    context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1, locale: 'en-GB', colorScheme: 'dark', timezoneId: WORLD_TIME_ZONE, recordVideo: { dir: videoTmp, size: VIDEO_SIZE } })
    await context.addInitScript(installBar, { height: BAR_HEIGHT, simLine: SIM_LINE })
    const guard = { approve: null }
    await context.route(url => url.href.startsWith(api), async route => {
      const request = route.request()
      const method = request.method()
      const pathname = new URL(request.url()).pathname
      if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') return route.continue()
      const allowed = (method === 'POST' && pathname === '/auth/signin') || (method === 'POST' && guard.approve !== null && pathname === `/chat/tool-calls/${guard.approve}/approve`)
      if (allowed) { report.pageWrites.push({ at: now(), method, path: pathname, by: 'the page (a click in the Desk)' }); return route.continue() }
      report.blockedWrites.push({ at: now(), method, path: pathname })
      return route.abort('blockedbyclient')
    })
    page = await context.newPage()
    const t0 = Date.now()
    function now() { return Math.round((Date.now() - t0) / 100) / 10 }
    page.on('console', message => { if (message.type() === 'error') report.console.push({ at: now(), text: message.text().slice(0, 300) }) })
    page.on('pageerror', error => report.console.push({ at: now(), text: `uncaught: ${String(error.message).slice(0, 300)}` }))

    const main$ = page.locator('#main')
    const hold = ms => page.waitForTimeout(ms)
    const caption = async text => {
      await page.evaluate(value => {
        try { sessionStorage.setItem('officesim-caption', value) } catch { /* ignore */ }
        const el = document.getElementById('officesim-bar-caption')
        if (el) el.textContent = value
      }, text)
    }
    const step = async (id, text) => {
      await caption(text)
      report.steps.push({ at: now(), id, caption: text })
      console.log(`${String(now()).padStart(6)}s  ${id}: ${text}`)
      save()
    }
    const problem = async (id, text) => {
      failed = true
      report.problems.push({ at: now(), step: id, problem: text })
      await step(`${id}-problem`, `Did not happen: ${text}`)
      await hold(3000)
    }
    const still = async label => {
      const file = `${args.name}-still-${String(report.stills.length + 1).padStart(2, '0')}-${label}.png`
      await page.screenshot({ path: path.join(outDir, file) })
      report.stills.push({ at: now(), file })
    }
    /** Requests the script makes itself, as the outside world. Never from the page. */
    const script = async (method, pathname, data) => {
      const response = await context.request.fetch(`${api}${pathname}`, { method, headers: { Origin: frontend }, data, failOnStatusCode: false })
      const body = await response.json().catch(() => null)
      if (method !== 'GET') report.scriptRequests.push({ at: now(), method, path: pathname, status: response.status(), by: 'the script, outside the page (the simulator playing the outside world)', body: data })
      return { status: response.status(), ok: response.ok(), body }
    }
    const get = async pathname => (await script('GET', pathname)).body
    const settle = async (timeout = 20000) => {
      const started = Date.now()
      let quiet = 0
      while (Date.now() - started < timeout) {
        const busy = await page.evaluate(() => {
          const main = document.getElementById('main')
          if (!main) return true
          const visible = el => el.getClientRects().length > 0
          return [...main.querySelectorAll('.animate-pulse')].some(visible) || [...main.querySelectorAll('[role="status"]')].some(el => visible(el) && /…\s*$/.test((el.textContent ?? '').trim()))
        }).catch(() => true)
        quiet = busy ? 0 : quiet + 1
        if (quiet >= 4) return true
        await hold(200)
      }
      return false
    }
    /** A fresh load of one Desk screen (the same as typing its address): nothing is read from a cache. */
    const open = async hash => {
      await page.goto(`${frontend}/?v=${Date.now()}${hash}`, { waitUntil: 'domcontentloaded' })
      await main$.waitFor({ state: 'visible', timeout: 30000 })
      await settle()
    }
    const scrollTo = async (target, ms = 1500) => {
      const handle = typeof target === 'number' || target === 'bottom' ? null : await target.elementHandle({ timeout: 8000 }).catch(() => null)
      await page.evaluate(async ({ target, ms, element }) => {
        const main = document.getElementById('main')
        if (!main) return
        const max = main.scrollHeight - main.clientHeight
        let to = target === 'bottom' ? max : typeof target === 'number' ? target : 0
        if (element) to = element.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop - 16
        to = Math.max(0, Math.min(max, to))
        const from = main.scrollTop
        const started = performance.now()
        await new Promise(resolve => {
          const tick = time => {
            const p = Math.min(1, (time - started) / ms)
            main.scrollTop = from + (to - from) * (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2)
            if (p < 1) requestAnimationFrame(tick); else resolve()
          }
          requestAnimationFrame(tick)
        })
      }, { target: handle ? null : target, ms, element: handle })
    }
    const toolCall = async id => (await get(`/chat/tool-calls/${id}`))?.tool_call ?? null
    const runOf = async id => get(`/desk/runs/${id}`)
    const waitFor = async (probe, timeout, every = 1000) => {
      const started = Date.now()
      while (Date.now() - started < timeout) {
        const value = await probe().catch(() => null)
        if (value) return value
        await hold(every)
      }
      return null
    }
    const runForMessage = messageId => waitFor(async () => {
      const rows = (await get('/desk/runs?limit=50'))?.runs ?? []
      return rows.find(row => row.email_id === messageId) ?? null
    }, 45000, 1500)
    const awaiting = run => (run?.actions ?? []).find(action => action.status === 'awaiting_approval') ?? null

    /** Clicks the Desk's Approve control on one card and reports what the server says afterwards. */
    const approveCard = async (stepId, card, action, runId) => {
      const record = { step: stepId, runId, toolCallId: action.toolCallId, tool: action.tool_name, purpose: action.purpose ?? null, control: null, clickedAt: null, httpStatus: null, statusAfter: null, verified: null, verification: null, simulated: null, runStageAfter: null }
      report.approvals.push(record)
      const button = card.getByRole('button', { name: /^Approve/ })
      if ((await button.count()) !== 1) { await problem(stepId, 'the action card has no Approve control'); return record }
      record.control = (await button.innerText()).trim()
      if (await button.isDisabled()) { await problem(stepId, `the Approve control ("${record.control}") is disabled`); return record }
      await scrollTo(button, 900)
      await hold(1500)
      guard.approve = action.toolCallId
      const responded = page.waitForResponse(response => new URL(response.url()).pathname === `/chat/tool-calls/${action.toolCallId}/approve`, { timeout: 30000 }).catch(() => null)
      await button.hover()
      await hold(500)
      record.clickedAt = now()
      await button.click()
      const response = await responded
      guard.approve = null
      record.httpStatus = response ? response.status() : null
      const after = await waitFor(async () => { const call = await toolCall(action.toolCallId); return call && !['awaiting_approval', 'approved', 'executing'].includes(call.status) ? call : null }, 20000, 500)
      record.statusAfter = after?.status ?? (await toolCall(action.toolCallId))?.status ?? null
      const run = await runOf(runId)
      const done = (run?.actions ?? []).find(item => item.toolCallId === action.toolCallId)
      record.verified = done?.verified ?? null
      record.verification = done?.verification ?? null
      record.simulated = done?.simulated ?? null
      record.runStageAfter = run?.lifecycle?.stage ?? null
      if (record.statusAfter !== 'executed') await problem(stepId, `after the click the server reports the action as "${record.statusAfter}", not executed`)
      return record
    }

    // ---- 0. Sign in through the Desk's own form.
    await page.goto(`${frontend}/#/overview`, { waitUntil: 'domcontentloaded' })
    await step('sign-in', 'Signing in to the Desk as the sandbox backend\'s seeded test user')
    const shell = page.locator('nav[aria-label="Main"]').first()
    await shell.or(page.locator('#desk-email')).first().waitFor({ state: 'visible', timeout: 30000 })
    if (!(await shell.isVisible())) {
      await page.locator('#desk-email').fill(credentials.email)
      await page.locator('#desk-password').fill(credentials.password)
      await hold(600)
      await page.getByRole('button', { name: 'Sign in with email' }).click()
      await shell.waitFor({ state: 'visible', timeout: 30000 }).catch(() => { throw new Fatal('Sign-in failed.') })
    }

    const [health, meta] = [await get('/desk/health'), await get('/sim/meta')]
    if (!meta?.simulated) throw new Fatal('GET /sim/meta does not report a simulated backend: this is not the office-simulation sandbox. Nothing was recorded against it.')
    Object.assign(report.backend, { overlay: health?.version ?? null, revision: meta.deskBackend ?? null, sim: { worldId: meta.worldId, day: meta.day, timezone: meta.timezone, workerMode: meta.workerMode, model: meta.model }, executionMode: health?.executionMode ?? null, externalWritesEnabled: health?.externalWrites?.enabled ?? null })
    if (health?.executionMode !== 'sandbox' || health?.externalWrites?.enabled) throw new Fatal('The backend is not in sandbox execution mode. Stopping before any approval.')
    if (meta.timezone !== WORLD_TIME_ZONE) report.problems.push({ at: now(), step: 'time-zone', problem: `the world is in ${meta.timezone}; the browser was set to ${WORLD_TIME_ZONE}, so times on screen are shifted` })
    const clock = await script('POST', '/sim/clock', { now: CLOCK })
    if (!clock.ok) report.problems.push({ at: now(), step: 'clock', problem: `POST /sim/clock answered ${clock.status}; the world stays on its own clock` })
    const worldNow = (await get('/sim/state'))?.world?.now ?? CLOCK
    report.browserClock.fixedTo = worldNow
    await page.clock.setFixedTime(new Date(worldNow))
    const worker = (await get('/desk/worker'))?.worker ?? null
    report.backend.workerAtStart = worker ? { enabled: worker.enabled, running: worker.running, intervalSeconds: worker.intervalSeconds } : null
    const workerRuns = worker?.running === true

    // ---- 1. Overview, before anything arrives.
    await open('#/overview')
    await step('overview-before', workerRuns
      ? 'Overview before any mail arrives. The Desk\'s background intake is running on its own 15-second timer'
      : 'Overview before any mail arrives. Background intake is NOT running on this backend')
    await hold(3500)
    await still('overview-before')
    if (!workerRuns) throw new Fatal('The Desk\'s background worker is not running (start the sandbox with --worker thread).')

    // ---- 2. A message arrives.
    const delivered = await script('POST', '/sim/deliver', MEI)
    if (!delivered.ok) throw new Fatal(`POST /sim/deliver answered ${delivered.status}.`)
    await step('mei-arrives', 'A message arrives in the sandbox mailbox (delivered by the simulator, playing the outside world)')
    await open('#/inbox')
    await hold(3500)
    await still('inbox-mei')

    // ---- 3. The worker picks it up.
    await step('waiting-for-worker', 'Nobody asks the Desk to look. Waiting for its own background worker (15-second timer)…')
    const meiRow = await runForMessage(MEI.message_id)
    if (!meiRow) { await problem('worker-pickup', 'no run was opened for the message within 45 s'); throw new Fatal('The worker did not open a run.', 1) }
    report.runs.mei = { runId: meiRow.runId, trigger: meiRow.trigger ?? null, openedAfterDeliverySeconds: Math.round((now() - report.steps.find(s => s.id === 'mei-arrives').at) * 10) / 10 }
    await open('#/work')
    await step('work-queue', `The Desk's background worker picked it up: nobody asked. Run ${meiRow.runId} is in the work queue`)
    await hold(3500)
    await still('work-queue')

    // ---- 4. Run detail.
    await page.locator(`#main a[href="#/work/${meiRow.runId}"]`).first().click()
    await page.locator('#main').getByText(new RegExp(`\\bRun ${meiRow.runId}\\b`)).first().waitFor({ timeout: 20000 })
    await settle()
    await step('run-detail', 'The run: what the Desk understood, and what it proposes. Nothing has happened yet')
    await hold(3000)
    await still('run-proposed')
    await step('run-plan', 'Scrolling the run: the proposed action, the plan (two steps, each needs an approval), every read the Desk made')
    await scrollTo('bottom', 11000)
    await hold(2000)
    await still('run-record')

    // ---- 5. Approve the calendar action.
    let run = await runOf(meiRow.runId)
    report.runs.mei.plan = run?.plan ? { planner: run.plan.planner, approvals: run.plan.approvals, steps: (run.plan.steps ?? []).map(s => ({ id: s.id, tool: s.tool, purpose: s.purpose, dependsOn: s.dependsOn })) } : null
    let action = awaiting(run)
    const cards = page.locator('#main [data-testid="tool-call"][data-status="awaiting_approval"]')
    if (!action || (await cards.count()) !== 1) { await problem('approve-booking', 'the run does not show exactly one action awaiting approval'); throw new Fatal('No single action to approve.', 1) }
    await step('approve-booking', 'The executive approves the calendar invitation (the real button; it runs in the sandbox)')
    const first = await approveCard('approve-booking', cards.first(), action, meiRow.runId)
    const verifiedText = page.locator('#main').getByText(/Verified/).first()
    if (!(await verifiedText.waitFor({ timeout: 8000 }).then(() => true, () => false))) {
      await page.getByRole('button', { name: 'Refresh' }).first().click().catch(() => {})
      report.steps.push({ at: now(), id: 'clicked-refresh', caption: '(the script clicked the page\'s Refresh button: the result had not appeared by itself after 8 s)' })
      await verifiedText.waitFor({ timeout: 10000 }).catch(() => {})
    }
    if (first.statusAfter === 'executed') {
      await step('booking-executed', first.verified
        ? 'Executed in the sandbox calendar, and verified: the Desk read the sandbox calendar back and the event is there'
        : 'Executed in the sandbox calendar. The server does not report it as verified')
      await scrollTo(verifiedText, 1200).catch(() => {})
      await hold(4000)
      await still('booking-verified')
    }

    // ---- 6. The confirmation email is proposed next.
    const second = await waitFor(async () => awaiting(await runOf(meiRow.runId)), 20000, 1000)
    if (!second) { await problem('confirmation', 'the backend did not propose the confirmation email within 20 s') } else {
      if (!(await cards.first().waitFor({ timeout: 6000 }).then(() => true, () => false))) {
        await page.getByRole('button', { name: 'Refresh' }).first().click().catch(() => {})
        report.steps.push({ at: now(), id: 'clicked-refresh', caption: '(the script clicked the page\'s Refresh button: the new proposal had not appeared by itself after 6 s)' })
        await cards.first().waitFor({ timeout: 10000 }).catch(() => {})
      }
      await step('confirmation-proposed', 'Second step of the plan: now that the event exists, the Desk proposes the confirmation email to Mei Tanaka')
      await scrollTo(cards.first(), 1500)
      await hold(4000)
      await still('confirmation-proposed')
      await step('approve-confirmation', 'The executive approves the confirmation email (the real button; "sent" means sent inside the sandbox)')
      const confirmation = await approveCard('approve-confirmation', cards.first(), second, meiRow.runId)
      await hold(1500)
      run = await runOf(meiRow.runId)
      report.runs.mei.stageAtEnd = run?.lifecycle?.stage ?? null
      report.runs.mei.stateAtEnd = run?.state ?? null
      if (confirmation.statusAfter === 'executed') {
        await page.locator('#main').getByText(/Completed/).first().waitFor({ timeout: 8000 }).catch(() => {})
        await step('run-completed', `The server reports run ${meiRow.runId} as ${run?.lifecycle?.stage ?? 'unknown'}: both steps ran in the sandbox. No real mailbox or calendar was reached`)
        await scrollTo(0, 2500)
        await hold(4000)
        await still('run-completed')
      }
    }

    // ---- 7. Overview again.
    await open('#/overview')
    await step('overview-after', 'Overview again: the request is under "Handled by the secretary" (other entries there are the test backend\'s own seed data)')
    await hold(4000)
    await still('overview-after')

    // ---- Part two: a busy time. Only when part one went through cleanly.
    if (!failed && !args['no-second-part']) {
      const greta = await script('POST', '/sim/deliver', GRETA)
      if (!greta.ok) await problem('greta-arrives', `POST /sim/deliver answered ${greta.status}`)
      else {
        await step('greta-arrives', 'A second message arrives (delivered by the simulator): Greta Lindqvist asks to meet tomorrow at 14:30, a time that is busy')
        await open('#/inbox')
        await hold(3000)
        await step('waiting-for-worker-2', 'Again nobody asks. Waiting for the Desk\'s background worker…')
        const gretaRow = await runForMessage(GRETA.message_id)
        if (!gretaRow) await problem('worker-pickup-2', 'no run was opened for the second message within 45 s')
        else {
          report.runs.greta = { runId: gretaRow.runId, trigger: gretaRow.trigger ?? null, held: gretaRow.held ?? null }
          const gretaRun = await runOf(gretaRow.runId)
          const offer = awaiting(gretaRun)
          report.runs.greta.proposedSlots = offer?.proposedSlots ?? null
          await open('#/approvals')
          const card = page.locator('#main [data-testid="tool-call"][data-status="awaiting_approval"]').filter({ hasText: 'Peak-season forecast' })
          if (!offer || (await card.count()) !== 1) await problem('offer-times', 'the Approval center does not show exactly one waiting card for this message')
          else {
            await step('offer-times', 'Approval center: the time is busy, so the Desk books nothing. It proposes a reply offering times it verified free')
            await scrollTo(card.first(), 1500)
            await hold(5000)
            await still('offer-times')
            await step('approve-offer', 'The executive approves the reply (the real button; it is sent inside the sandbox only)')
            const sent = await approveCard('approve-offer', card.first(), offer, gretaRow.runId)
            await hold(1500)
            if (sent.statusAfter === 'executed') {
              await open(`#/work/${gretaRow.runId}`)
              const after = await runOf(gretaRow.runId)
              report.runs.greta.stageAtEnd = after?.lifecycle?.stage ?? null
              report.runs.greta.followUps = (after?.followUps ?? []).map(f => ({ id: f.id, state: f.state }))
              await step('waiting-for-response', `The reply went out inside the sandbox. The run now waits for Greta's answer (server stage ${after?.lifecycle?.stage ?? 'unknown'}); the Desk tracks it`)
              await hold(3500)
              await still('greta-run')
              await scrollTo('bottom', 5000)
              await hold(2500)
            }
          }
        }
      }
    }

    await step('end', 'End of the recording. Everything shown ran against the sandbox world; its operation log is in the report file')
    await hold(2500)

    const state = await get('/sim/state')
    report.world = {
      id: state?.world?.id ?? null,
      now: state?.world?.now ?? null,
      operations: state?.world?.operations ?? null,
      isolationViolations: state?.world?.isolationViolations ?? null,
      gate: state?.gate ?? null,
    }
    report.durationSeconds = now()
  } catch (error) {
    failed = true
    report.problems.push({ step: 'fatal', problem: String(error.message).split('\n')[0] })
    console.error(`record failed: ${String(error.message).split('\n')[0]}`)
  } finally {
    const video = page ? page.video() : null
    if (context) await context.close().catch(() => {})
    if (video) {
      const target = path.join(outDir, `${args.name}.webm`)
      await video.saveAs(target).catch(error => { failed = true; report.problems.push({ step: 'video', problem: String(error.message).split('\n')[0] }) })
      if (fs.existsSync(target)) report.videoBytes = fs.statSync(target).size
    }
    fs.rmSync(videoTmp, { recursive: true, force: true })
    await browser.close().catch(() => {})
    save()
  }
  console.log(`${failed ? 'Recorded WITH PROBLEMS' : 'Recorded'}: ${args.name}.webm (${report.durationSeconds ?? '?'} s, ${report.videoBytes ?? '?'} bytes), report ${args.name}.json`)
  return failed ? 1 : 0
}

main().then(code => { process.exitCode = code }, error => {
  console.error(`record failed: ${error.message}`)
  process.exitCode = error instanceof Fatal ? error.code : 3
})
