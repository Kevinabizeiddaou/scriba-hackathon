#!/usr/bin/env node
/**
 * End-to-end walk through the integrated Desk, over HTTP, in the SANDBOX only.
 *
 *   SMOKE_EMAIL=... SMOKE_PASSWORD=... node scripts/e2e-sandbox.mjs --base http://localhost:8000
 *
 * The backend must be started with --demo (or DESK_DEMO=on). Everything happens in the caller's
 * isolated provider world: no mailbox, calendar or computer exists behind it, and every result
 * printed here is simulated. The script plays only the outside world (a sender) and the person at
 * the approval gate. It never writes a run, a card or an outcome.
 *
 *   1. meeting   synthetic mail -> background worker -> plan -> approvals -> execution ->
 *                verification -> completed run -> follow-up tracking
 *   2. file      mail with a workbook -> Scriba's reader -> review document -> reopened and
 *                verified -> downloaded -> reply proposed -> approved -> simulated send
 *   2a. workbook  a change to that workbook: suggested (nothing changes), applied by Scriba's Excel
 *                skills on a copy, reopened and verified; the original is untouched
 *   2b. follow-up times offered -> reply awaited -> the answer arrives -> the wait is closed
 *   3. desktop   the bridge on the sandbox's fake device: refused without confirm, a queued job
 *                is never shown as done or verified, and it can be cancelled. No computer runs
 *                anything here; a job running to a verified result is covered by the backend
 *                tests, where the fake device is stepped
 *
 * Credentials come from the environment (a seeded user of Scriba's e2e/seeded_server.py).
 * No dependencies: Node 22's built-in fetch. Exit code 0 only when every check held.
 */
const args = process.argv.slice(2)
const flag = name => (args.indexOf(`--${name}`) >= 0 ? args[args.indexOf(`--${name}`) + 1] : undefined)
const base = (flag('base') || process.env.SMOKE_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')
const origin = flag('origin') || process.env.SMOKE_ORIGIN || 'http://localhost:5173'
const email = process.env.SMOKE_EMAIL || ''
const password = process.env.SMOKE_PASSWORD || ''
let cookie = ''
let failed = 0

async function call(path, { method = 'GET', body, raw = false } = {}) {
  const response = await fetch(`${base}${path}`, {
    method,
    redirect: 'manual',
    headers: { Origin: origin, ...(body ? { 'Content-Type': 'application/json' } : {}), ...(cookie ? { Cookie: cookie } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(60_000),
  })
  if (raw) return { response, bytes: new Uint8Array(await response.arrayBuffer()) }
  let json = null
  try { json = await response.clone().json() } catch { /* not JSON */ }
  return { response, json }
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const expect = (condition, message) => { if (!condition) throw new Error(message) }
const say = line => console.log(`      ${line}`)

async function section(name, run) {
  console.log(`\n== ${name}`)
  try {
    await run()
    console.log(`PASS  ${name}`)
  } catch (error) {
    failed += 1
    console.log(`FAIL  ${name}\n      ${error.message}`)
  }
}

const getRun = async id => (await call(`/desk/runs/${id}`)).json

async function waitForRun(subject) {
  for (let attempt = 0; attempt < 45; attempt += 1) {
    const row = (await call('/desk/runs?limit=200')).json.runs.find(candidate => candidate.subject === subject)
    if (row) return row
    await sleep(2000)
  }
  throw new Error(`the worker did not open a run for "${subject}" within 90 seconds`)
}

/** Play the person: approve what waits, one card at a time, until nothing waits. Returns the tools approved, in order. */
async function approveAll(runId, { expectHeld = false } = {}) {
  const approved = []
  for (let round = 0; round < 12; round += 1) {
    const run = await getRun(runId)
    const waiting = run.actions.find(action => action.status === 'awaiting_approval' && !action.held)
    if (!waiting) {
      if ((run.next || []).includes('advance')) { await call(`/desk/runs/${runId}/advance`, { method: 'POST' }); await sleep(500); continue }
      break
    }
    expect(waiting.approve?.path, `card ${waiting.id} has no approve path`)
    const result = await call(waiting.approve.path, { method: 'POST', body: {} })
    const status = result.json?.tool_call?.status
    say(`approved ${waiting.tool_name}${waiting.purpose ? ` (${waiting.purpose})` : ''} -> ${status}`)
    expect(expectHeld || status === 'executed', `approve of ${waiting.tool_name} gave ${status} (HTTP ${result.response.status})`)
    approved.push(waiting.tool_name)
    await sleep(2500)
  }
  return approved
}

function assertTruthful(run) {
  for (const action of run.actions) {
    if (action.status === 'executed') {
      expect(action.simulated === true, `executed action ${action.tool_name} is not marked simulated`)
      expect(action.verified === true && action.verification?.method, `executed action ${action.tool_name} has no verification`)
    }
    expect(!(action.verified && action.status !== 'executed'), `${action.tool_name} is called verified without having run`)
  }
}

async function main() {
  expect(email && password, 'set SMOKE_EMAIL and SMOKE_PASSWORD (a seeded user of Scriba\'s test backend)')
  const signin = await call('/auth/signin', { method: 'POST', body: { email, password } })
  expect(signin.response.status === 200, `sign-in gave HTTP ${signin.response.status}`)
  cookie = (signin.response.headers.getSetCookie?.() || []).map(value => value.split(';')[0]).join('; ')

  const health = (await call('/desk/health')).json
  console.log(`Desk overlay ${health.version}; execution mode ${health.executionMode}; external writes enabled: ${health.externalWrites?.enabled}; model configured: ${health.model?.configured}`)
  expect(health.executionMode === 'sandbox', 'this backend is not in sandbox mode: start it with --demo')
  expect(health.externalWrites?.enabled === false, 'external writes are enabled: this script only runs with them off')
  const before = (await call('/desk/sandbox')).json.world

  await section('1. meeting request with a second request: worker -> plan -> approvals -> execution -> verification -> follow-up', async () => {
    const stamp = Date.now()
    const subject = `Supplier review ${stamp}`
    const from = new Date(Date.now() + 24 * 3600 * 1000), to = new Date(Date.now() + 8 * 24 * 3600 * 1000)
    const availability = (await call(`/desk/availability?start=${encodeURIComponent(from.toISOString())}&end=${encodeURIComponent(to.toISOString())}&duration_minutes=30&max_slots=10`)).json || {}
    const slots = availability.slots || []
    expect(slots.length > 0, 'the sandbox calendar offers no free slot to ask for')
    const start = new Date(slots[Math.min(2, slots.length - 1)].start)
    const written = start.toLocaleString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: availability.timezone || 'UTC' })
    const delivered = await call('/desk/sandbox/deliver', { method: 'POST', body: {
      from_addr: `Nadia Karam <nadia.karam.${stamp}@lumen.example>`, subject,
      body: `Hello,\n\nCould we meet on ${written.replace(',', '')} for 30 minutes to go through the supplier review?\n\nOne more thing: please send me the signed agreement for contract ${String(stamp).slice(-6)} by Friday.\n\nThanks,\nNadia` } })
    expect(delivered.response.status === 200, `deliver gave HTTP ${delivered.response.status}`)
    const row = await waitForRun(subject)
    expect(row.trigger === 'worker' && row.simulated === true, `trigger ${row.trigger}, simulated ${row.simulated}`)
    let run = await getRun(row.runId)
    say(`run ${run.runId} opened by the ${run.trigger}; stage ${run.lifecycle.stage}; intents: ${(run.plan?.intents || []).map(i => i.intent || i.kind).join(', ') || 'n/a'}`)
    say(`plan steps: ${(run.plan?.steps || []).map(step => `${step.id}:${step.tool}${step.dependsOn?.length ? `<-${step.dependsOn.join('+')}` : ''}`).join('  ')}`)
    say(`reads recorded: ${(run.plan?.reads || []).length}; unresolved: ${(run.unresolved || []).length}; held: ${run.held?.reason || 'no'}`)
    expect(run.actions.every(action => action.status !== 'executed' || action.simulated), 'something ran before any approval')
    expect((run.plan?.steps || []).length >= 2, 'the plan has fewer than two steps')
    const approved = await approveAll(run.runId)
    run = await getRun(run.runId)
    assertTruthful(run)
    say(`after approvals: stage ${run.lifecycle.stage}${run.lifecycle.reason ? ` (${run.lifecycle.reason})` : ''}; actions: ${run.actions.map(a => `${a.tool_name}=${a.lifecycle || a.status}/${a.verification?.method || '-'}`).join('  ')}`)
    say(`follow-ups: ${(run.followUps || []).map(f => `${f.state} on ${f.waitingOn || f.waitingOnName}`).join('; ') || 'none'}; unresolved: ${(run.unresolved || []).map(u => `${u.why}${u.resolved ? ' (resolved)' : ''}`).join('; ') || 'none'}`)
    expect(approved.includes('create_calendar_event'), `no meeting was booked (approved: ${approved.join(', ') || 'nothing'})`)
    expect(run.actions.some(a => a.tool_name === 'create_calendar_event' && a.verified), 'the booking is not verified')
    // The second request must be accounted for: a task, an unresolved entry, or the recorded finding that
    // an open task already covers it (a repeat of this walk on the same server).
    const alreadyRecorded = (run.timeline || []).some(event => event.kind === 'decision' && event.data?.reason === 'task_exists')
    const secondary = run.actions.some(a => a.tool_name === 'create_task') || (run.unresolved || []).length > 0 || alreadyRecorded
    if (alreadyRecorded) say('the second request matched an open task from an earlier walk: recorded as task_exists, no duplicate task')
    expect(secondary, 'the second request (the agreement by Friday) was dropped: neither a task nor an unresolved entry')
    const world = (await call('/desk/sandbox')).json.world
    expect(world.counts.events === before.counts.events + 1, `the meeting is not in the sandbox calendar (${before.counts.events} -> ${world.counts.events})`)
    expect(world.isolationViolations.length === 0, 'the sandbox reached a real provider client')
    const done = ['COMPLETED', 'WAITING_FOR_REPLY', 'FOLLOW_UP_WAITING', 'ESCALATED']
    expect(done.includes(run.lifecycle.stage) || run.lifecycle.stage.startsWith('WAIT'), `the run is left at ${run.lifecycle.stage}`)
    if ((run.unresolved || []).some(u => !u.resolved)) expect(run.lifecycle.stage !== 'COMPLETED', 'a run with an unresolved request is called COMPLETED')
  })

  await section('2. mail with a workbook: read -> review document -> reopened and verified -> reply approved -> simulated send', async () => {
    const row = (await call('/desk/runs?limit=200')).json.runs.find(candidate => /Q4 budget figures/i.test(candidate.subject || ''))
    expect(row, 'the demo world\'s "Q4 budget figures" message has no run (was the server started with --demo?)')
    let run = await getRun(row.runId)
    const attachment = (run.attachments || [])[0]
    expect(attachment?.read === true, `the attachment was not read: ${JSON.stringify(attachment)}`)
    say(`run ${run.runId} (${run.trigger}); attachment ${attachment.filename}: kind ${attachment.kind}, ${attachment.unitCount} ${attachment.unit}(s), read by Scriba's reader, sha256 ${String(attachment.sha256).slice(0, 12)}…`)
    expect(!run.actions.some(a => a.tool_name === 'send_email' && a.purpose === 'reply' && !(run.files || []).some(f => f.verified)), 'a reply was proposed before any review was verified')
    const approved = await approveAll(run.runId)
    run = await getRun(run.runId)
    assertTruthful(run)
    const file = (run.files || [])[0]
    expect(file, 'no generated file is on the run')
    say(`generated ${file.filename}: state ${file.state}, verified ${file.verified}, ${file.sizeBytes} bytes, simulated ${file.simulated}`)
    expect(file.verified === true && file.state === 'VERIFIED', `the review is ${file.state}, not VERIFIED`)
    const review = run.actions.find(a => a.tool_name === 'create_document')
    expect(review?.verification?.method === 'file_reopened', `the review was verified by ${review?.verification?.method}, not by reopening it`)
    const download = await call(file.download.path, { raw: true })
    expect(download.response.status === 200, `download gave HTTP ${download.response.status}`)
    expect(download.bytes[0] === 0x50 && download.bytes[1] === 0x4b, 'the downloaded file is not an Office (zip) file')
    expect(/attachment/i.test(download.response.headers.get('content-disposition') || ''), 'the file is not served as a download')
    say(`downloaded ${download.bytes.length} bytes; origin ${download.response.headers.get('x-desk-file-origin')}; served as an attachment`)
    const reply = run.actions.find(a => a.tool_name === 'send_email')
    expect(reply, 'no reply was proposed after the review was verified')
    say(`reply: ${reply.lifecycle || reply.status}, simulated ${reply.simulated}, verified by ${reply.verification?.method || '-'}; approvals given in this pass: ${approved.join(', ') || 'none (already decided earlier)'}`)
    expect(reply.status === 'executed' && reply.simulated === true && reply.verified === true, `the reply is ${reply.status}`)
    say(`run stage ${run.lifecycle.stage}; follow-ups: ${(run.followUps || []).map(f => f.state).join(', ') || 'none'}`)
    const original = await call(`/desk/files/${encodeURIComponent(attachment.id)}`, { raw: true })
    expect(original.response.status === 200 && original.bytes.length === attachment.sizeBytes, 'the original attachment changed size or cannot be read')
  })

  await section('2a. a change to the workbook: suggested -> nothing changed -> applied on a copy -> reopened and verified', async () => {
    const row = (await call('/desk/runs?limit=200')).json.runs.find(candidate => /Q4 budget figures/i.test(candidate.subject || ''))
    expect(row, 'the demo world\'s "Q4 budget figures" message has no run')
    let run = await getRun(row.runId)
    const attachment = (run.attachments || [])[0]
    const value = 5000 + (Date.now() % 1000)          // another value on each walk, so a repeat is a new change
    const suggested = await call(`/desk/runs/${run.runId}/file-changes`, { method: 'POST', body: {
      fileId: attachment.id, operations: [{ op: 'update_cell', sheet: 'Budget', cell: 'D6', value }] } })
    expect(suggested.response.status === 200, `suggesting a change gave HTTP ${suggested.response.status}`)
    run = suggested.json
    const change = (run.fileChanges || []).find(candidate => candidate.state === 'suggested')
    expect(change, 'the suggestion is not on the run')
    say(`suggested ${change.id}: ${change.operations.map(o => `${o.op} ${o.sheet}!${o.cell} = ${o.value}`).join('; ')}; run stage ${run.lifecycle.stage} (${run.lifecycle.reason}); next: ${run.next.join(', ')}`)
    expect(run.lifecycle.stage !== 'COMPLETED' && run.next.includes('apply_file_change'), 'a run with a suggested change is called complete')
    expect(!change.resultFileId && !change.verified, 'a suggested change already has a result')
    const formula = await call(`/desk/runs/${run.runId}/file-changes`, { method: 'POST', body: {
      fileId: attachment.id, operations: [{ op: 'update_cell', sheet: 'Budget', cell: 'D6', value: '=1+1' }] } })
    expect(formula.response.status === 400, `a value that starts like a formula gave HTTP ${formula.response.status}`)
    run = (await call(change.apply.path, { method: 'POST' })).json
    const applied = (run.fileChanges || []).find(candidate => candidate.id === change.id)
    say(`applied: state ${applied.state}, verified ${applied.verified} by ${applied.verification?.method}, result "${applied.resultFilename}", simulated ${applied.simulated}; step: ${JSON.stringify((applied.steps || []).map(s => ({ cell: s.cell, old: s.oldValue, verified: s.verified })))}`)
    expect(applied.state === 'applied' && applied.verified === true && applied.verification?.method === 'workbook_reopened', `the change is ${applied.state}`)
    expect(applied.resultFileId && applied.resultFileId !== attachment.id, 'the result is not a new file')
    const result = await call(`/desk/files/${encodeURIComponent(applied.resultFileId)}`, { raw: true })
    expect(result.response.status === 200 && result.bytes[0] === 0x50 && result.bytes[1] === 0x4b, 'the changed copy cannot be downloaded as a workbook')
    const original = await call(`/desk/files/${encodeURIComponent(attachment.id)}`, { raw: true })
    expect(original.response.headers.get('x-desk-file-sha256') === attachment.sha256, 'the original attachment was changed')
    say(`the changed copy downloads (${result.bytes.length} bytes); the original attachment has the same sha256 as when it was read; run stage ${run.lifecycle.stage}`)
  })

  await section('2b. follow-up tracking: times offered -> reply awaited -> the answer arrives -> the wait is closed', async () => {
    const subject = `Intro call ${Date.now()}`
    const sender = `Omar Haddad <omar.haddad.${Date.now()}@lumen.example>`
    const delivered = await call('/desk/sandbox/deliver', { method: 'POST', body: {
      from_addr: sender, subject, body: 'Hello,\n\nCould we find 30 minutes for an intro call sometime next week? Any day works for me.\n\nBest,\nOmar' } })
    expect(delivered.response.status === 200, `deliver gave HTTP ${delivered.response.status}`)
    const row = await waitForRun(subject)
    const approved = await approveAll(row.runId)
    let run = await getRun(row.runId)
    assertTruthful(run)
    say(`run ${run.runId}: approved ${approved.join(', ') || 'nothing'}; stage ${run.lifecycle.stage}; follow-ups: ${(run.followUps || []).map(f => `${f.state} (due ${f.dueAt})`).join('; ') || 'none'}`)
    expect(approved.includes('send_email'), 'no reply offering times was proposed')
    const waiting = (run.followUps || []).find(f => f.state === 'waiting')
    expect(waiting, 'the sent reply is not tracked as an awaited answer')
    expect(run.lifecycle.stage !== 'COMPLETED', 'a run that still waits for an answer is called COMPLETED')
    const listed = (await call('/desk/follow-ups')).json
    expect(JSON.stringify(listed).includes(waiting.id), 'the wait is not on GET /desk/follow-ups')
    const answer = await call('/desk/sandbox/deliver', { method: 'POST', body: {
      from_addr: sender, subject: `Re: ${subject}`, thread_id: delivered.json.delivered.threadId,
      body: 'Thanks. The first time you offered works for me, please go ahead and book it.\n\nOmar' } })
    expect(answer.response.status === 200, `deliver of the answer gave HTTP ${answer.response.status}`)
    let state = 'waiting'
    for (let attempt = 0; attempt < 45 && state === 'waiting'; attempt += 1) {
      await sleep(2000)
      run = await getRun(row.runId)
      state = (run.followUps || []).find(f => f.id === waiting.id)?.state
    }
    say(`after the answer arrived: follow-up ${state}; first run stage ${run.lifecycle.stage}`)
    expect(state === 'satisfied', `the follow-up is ${state} after the answer arrived`)
  })

  await section('3. desktop bridge on the sandbox fake device (SIMULATED: no computer ran anything)', async () => {
    const status = (await call('/desk/desktop')).json
    say(`available ${status.available}; simulated ${status.simulated}; devices ${status.devices?.length}; recorded tasks ${status.tasks?.length}; resume supported ${status.resume?.supported}`)
    expect(status.available === true && status.simulated === true, `the sandbox desktop is not available as a simulation (${status.reason})`)
    const refused = await call('/desk/desktop/jobs', { method: 'POST', body: { recordingId: status.tasks[0].id } })
    expect(refused.response.status === 400 && refused.response.headers.get('x-desk-error-code') === 'confirmation_required', `a job without confirm gave HTTP ${refused.response.status}`)
    say('a job without the person\'s explicit confirm is refused (400 confirmation_required); nothing was queued')
    const queued = await call('/desk/desktop/jobs', { method: 'POST', body: { recordingId: status.tasks[0].id, confirm: true } })
    expect(queued.response.status === 200, `queueing gave HTTP ${queued.response.status}`)
    let job = queued.json
    expect(job.state === 'ACCEPTED' && job.final === false && job.simulated === true, `a queued job is ${job.state}, final ${job.final}`)
    // No device reports in this server (the fake one is only stepped inside the test suite), so the
    // job must stay "queued, not started": never done, never verified.
    for (let attempt = 0; attempt < 4; attempt += 1) { await sleep(1000); job = (await call(`/desk/desktop/jobs/${job.id}`)).json }
    say(`job ${job.id} after 4 s with no device report: ${job.state}, final ${job.final}, verified ${job.verified}, simulated ${job.simulated}`)
    expect(job.state === 'ACCEPTED' && job.final === false && !job.verified, `a job no device reported on is shown as ${job.state}`)
    const cancelled = (await call(`/desk/desktop/jobs/${job.id}/cancel`, { method: 'POST' })).json
    say(`cancel: state ${cancelled.state}, cancelRequested ${cancelled.cancelRequested}, final ${cancelled.final}`)
    expect(cancelled.state === 'CANCELLED' || cancelled.cancelRequested === true, `cancel gave ${cancelled.state}`)
    expect(!cancelled.verified, 'a cancelled job is called verified')
  })

  const world = (await call('/desk/sandbox')).json.world
  console.log(`\nSandbox world after the walk: ${JSON.stringify(world.counts)}; isolation violations: ${world.isolationViolations.length}`)
  if (world.isolationViolations.length) failed += 1
  await call('/auth/logout', { method: 'POST' })
  console.log(failed ? `\n${failed} section(s) FAILED` : '\nAll sections passed. Everything above ran in the sandbox: nothing was sent, booked or run anywhere real.')
  process.exit(failed ? 1 : 0)
}

main().catch(error => { console.error(`ERROR ${error.message}`); process.exit(2) })
