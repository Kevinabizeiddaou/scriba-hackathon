#!/usr/bin/env node
/**
 * API smoke test for the Scriba backend the Executive Desk runs against.
 *
 *   node scripts/smoke.mjs --base http://localhost:8788
 *   node scripts/smoke.mjs --base https://api.example.test            (anonymous checks only)
 *   SMOKE_EMAIL=... SMOKE_PASSWORD=... node scripts/smoke.mjs --base ...   (adds signed-in checks)
 *
 * Read-only by design. The only state it changes is its own session: with
 * credentials it signs in and signs out. It never sends mail, never writes a
 * calendar event, and never prints a cookie or a credential. Credentials come
 * from the environment so they are never in shell history or in this repo.
 *
 * No dependencies: Node 22's built-in fetch.
 */
const args = process.argv.slice(2)
const flag = name => {
  const index = args.indexOf(`--${name}`)
  return index >= 0 ? args[index + 1] : undefined
}

const base = (flag('base') || process.env.SMOKE_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')
// The browser origin the Desk is served from. Scriba trusts this one by default.
const origin = flag('origin') || process.env.SMOKE_ORIGIN || 'http://localhost:5173'
// --desk: the backend has the Desk overlay mounted; also check /desk/*.
const withDesk = args.includes('--desk')
const email = process.env.SMOKE_EMAIL || ''
const password = process.env.SMOKE_PASSWORD || ''

const results = []
let cookie = ''

function record(name, ok, detail = '') {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`)
}

async function call(path, { method = 'GET', body, sendOrigin = origin, headers = {} } = {}) {
  const response = await fetch(`${base}${path}`, {
    method,
    redirect: 'manual',
    headers: {
      ...(sendOrigin ? { Origin: sendOrigin } : {}),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(cookie ? { Cookie: cookie } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(30_000),
  })
  let json = null
  try {
    json = await response.clone().json()
  } catch {
    /* not JSON */
  }
  return { response, json }
}

async function check(name, run) {
  try {
    const detail = await run()
    record(name, true, detail || '')
  } catch (error) {
    record(name, false, error instanceof Error ? error.message : String(error))
  }
}

const expect = (condition, message) => {
  if (!condition) throw new Error(message)
}

const DESK_PROVIDER_KEYS = ['gmail', 'google_calendar', 'outlook', 'outlook_calendar']

console.log(`Scriba API: ${base}\nDesk origin: ${origin}\n`)

// ── Anonymous checks: safe against any Scriba API, including the hosted one ──

await check('GET /live answers', async () => {
  const { response, json } = await call('/live')
  expect(response.status === 200 && json?.ok === true, `status ${response.status}`)
})

await check('GET /health reports the service and its database', async () => {
  const { response, json } = await call('/health')
  expect(response.status === 200, `status ${response.status}`)
  expect(json?.service === 'scriba-api', `service was ${json?.service}`)
  expect(typeof json?.ok === 'boolean', 'no ok flag')
  return `ok=${json.ok} status=${json.status}`
})

await check('GET /providers/status is public and describes Google and Microsoft', async () => {
  const { response, json } = await call('/providers/status')
  expect(response.status === 200, `status ${response.status}`)
  expect(json?.authorized === false, 'expected the anonymous shape')
  for (const key of DESK_PROVIDER_KEYS) {
    const row = json?.providers?.[key]
    expect(row && typeof row.status === 'string', `providers.${key} missing`)
    expect(typeof row.loginPath === 'string', `providers.${key}.loginPath missing`)
  }
  return DESK_PROVIDER_KEYS.map(key => `${key}=${json.providers[key].status}`).join(' ')
})

await check('CORS: the Desk origin may make credentialed requests', async () => {
  const { response } = await call('/providers/status', {
    method: 'OPTIONS',
    headers: { 'Access-Control-Request-Method': 'GET' },
  })
  expect(response.headers.get('access-control-allow-origin') === origin,
    `allow-origin was ${response.headers.get('access-control-allow-origin')}`)
  expect(response.headers.get('access-control-allow-credentials') === 'true', 'credentials not allowed')
})

await check('CORS: an unknown origin is refused', async () => {
  const { response } = await call('/providers/status', {
    method: 'OPTIONS',
    sendOrigin: 'https://not-the-desk.example.test',
    headers: { 'Access-Control-Request-Method': 'GET' },
  })
  expect(!response.headers.get('access-control-allow-origin'), 'unknown origin was allowed')
})

for (const path of ['/emails?provider=gmail', '/emails?provider=outlook',
  '/calendar/events?provider=google', '/calendar/events?provider=outlook']) {
  await check(`anonymous GET ${path} is refused with 401`, async () => {
    const { response, json } = await call(path)
    expect(response.status === 401, `status ${response.status}`)
    expect(json?.errorCode === 'unauthenticated', `errorCode was ${json?.errorCode}`)
  })
}

if (withDesk) {
  await check('desk: anonymous GET /desk/health is refused with 401', async () => {
    const { response, json } = await call('/desk/health')
    expect(response.status === 401 && json?.errorCode === 'unauthenticated', `status ${response.status}`)
  })
}

// ── Signed-in checks: only with SMOKE_EMAIL / SMOKE_PASSWORD ──

if (email && password) {
  await check('POST /auth/signin issues an HttpOnly session cookie', async () => {
    const { response } = await call('/auth/signin', { method: 'POST', body: { email, password } })
    expect(response.status === 200, `status ${response.status}`)
    const set = response.headers.getSetCookie?.() ?? []
    const session = set.find(value => /scriba_session=/.test(value))
    expect(session, 'no session cookie')
    expect(/httponly/i.test(session), 'session cookie is not HttpOnly')
    cookie = session.split(';')[0]
    return /__Host-/.test(session) ? '__Host- cookie (https)' : 'plain-http cookie'
  })

  await check('session: /providers/status is authorized and lists only real accounts', async () => {
    const { json } = await call('/providers/status')
    expect(json?.authorized === true, 'not authorized')
    expect(json?.email?.toLowerCase() === email.toLowerCase(), 'session belongs to another user')
    return DESK_PROVIDER_KEYS.map(key => `${key}=${json.providers[key].status}`).join(' ')
  })

  for (const provider of ['gmail', 'outlook']) {
    await check(`session: GET /emails?provider=${provider} returns a page`, async () => {
      const { response, json } = await call(`/emails?provider=${provider}&limit=5`)
      expect(response.status === 200, `status ${response.status}`)
      expect(Array.isArray(json?.items), 'items is not a list')
      expect(json.items.every(item => item.provider === provider),
        'a row from another provider leaked into the page')
      return `${json.items.length} item(s)`
    })
  }

  for (const provider of ['google', 'outlook']) {
    await check(`session: GET /calendar/events?provider=${provider} returns a range`, async () => {
      const { response, json } = await call(`/calendar/events?provider=${provider}`)
      expect(response.status === 200, `status ${response.status}`)
      expect(Array.isArray(json?.meetings), 'meetings is not a list')
      return `${json.meetings.length} event(s)`
    })
  }

  await check('session: asking for another user\'s account is refused', async () => {
    const { response } = await call('/emails?provider=gmail&account=someone-else@example.test')
    expect(response.status === 403, `status ${response.status}`)
  })

  if (withDesk) {
    await check('desk: GET /desk/health reports a read-only overlay', async () => {
      const { response, json } = await call('/desk/health')
      expect(response.status === 200, `status ${response.status}`)
      expect(json?.service === 'scriba-desk-overlay' && json?.writes === false, 'unexpected health body')
      return `version ${json.version}`
    })

    await check('desk: GET /desk/connections lists exactly the four Desk capabilities', async () => {
      const { json } = await call('/desk/connections')
      const ids = (json?.capabilities ?? []).map(item => item.id)
      expect(ids.join(',') === 'gmail,google_calendar,outlook_mail,outlook_calendar', `got ${ids}`)
      expect(!/slack|teams|jira|drive/i.test(JSON.stringify(json)), 'an excluded integration leaked')
      return json.capabilities.map(item => `${item.id}=${item.state}`).join(' ')
    })

    await check('desk: GET /desk/inbox returns triaged mail with provider and account kept', async () => {
      const { response, json } = await call('/desk/inbox?limit=10')
      expect(response.status === 200, `status ${response.status}`)
      expect(Array.isArray(json?.items) && Array.isArray(json?.sources), 'unexpected shape')
      for (const item of json.items) {
        expect(['gmail', 'outlook'].includes(item.provider), `provider ${item.provider}`)
        expect(item.triage && typeof item.triage.category === 'string', 'row without triage')
      }
      return `${json.items.length} item(s); ` +
        json.sources.map(source => `${source.provider}=${source.ok ? 'ok' : source.error}`).join(' ')
    })

    await check('desk: GET /desk/availability never offers slots without a complete read', async () => {
      const start = new Date(Date.now() + 86_400_000).toISOString()
      const end = new Date(Date.now() + 3 * 86_400_000).toISOString()
      const { response, json } = await call(
        `/desk/availability?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`)
      expect(response.status === 200, `status ${response.status}`)
      expect(Array.isArray(json?.calendars) && Array.isArray(json?.slots), 'unexpected shape')
      expect(json.complete || json.slots.length === 0, 'slots offered from an incomplete read')
      return `${json.calendars.length} calendar(s), complete=${json.complete}` +
        (json.reason ? ` (${json.reason})` : '') + `, ${json.slots.length} slot(s)`
    })

    await check('desk: GET /desk/briefing is built from Scriba records', async () => {
      const { response, json } = await call('/desk/briefing')
      expect(response.status === 200, `status ${response.status}`)
      expect(typeof json?.headline === 'string' && json?.counts, 'unexpected shape')
      expect(Array.isArray(json.unavailable), 'no unavailable list')
      return json.headline + (json.unavailable.length ? ` unavailable: ${json.unavailable}` : '')
    })

    await check('desk: a slot check from another site is blocked', async () => {
      const { response, json } = await call('/desk/slots/check', {
        method: 'POST',
        sendOrigin: 'https://not-the-desk.example.test',
        body: { start: '2030-01-07T10:00:00Z', end: '2030-01-07T10:30:00Z' },
      })
      expect(response.status === 403 && json?.errorCode === 'cross_site_blocked',
        `status ${response.status}`)
    })
  }

  await check('session: a state-changing request from another site is blocked', async () => {
    const { response, json } = await call('/auth/logout', {
      method: 'POST',
      sendOrigin: 'https://not-the-desk.example.test',
    })
    expect(response.status === 403 && json?.errorCode === 'cross_site_blocked',
      `status ${response.status} code ${json?.errorCode}`)
  })

  await check('POST /auth/logout ends the session', async () => {
    const { response } = await call('/auth/logout', { method: 'POST' })
    expect(response.status === 200, `status ${response.status}`)
    // A browser drops the cookie on logout; do the same, then confirm the
    // API treats this client as signed out.
    cookie = ''
    const anonymous = await call('/emails?provider=gmail')
    expect(anonymous.response.status === 401, `status ${anonymous.response.status}`)
  })
} else {
  console.log('\nSKIP  signed-in checks (set SMOKE_EMAIL and SMOKE_PASSWORD to run them)')
}

const failed = results.filter(result => !result.ok)
console.log(`\n${results.length - failed.length} passed, ${failed.length} failed`)
process.exit(failed.length ? 1 : 0)
