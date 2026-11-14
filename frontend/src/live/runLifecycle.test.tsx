/**
 * The run lifecycle of overlay 0.3 as the screens present it: every stage, partial and failed
 * work, approval, verification, unknown values, duplicate cards, follow-ups, the worker, the
 * execution gate, and where an evaluation report came from.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { DeskFollowUp, DeskLifecycleStage, DeskRun, DeskTimelineItem, DeskWorkerStatus } from '../api/desk'
import { EvaluationResultPanel } from '../components/EvaluationResult'
import { PROVENANCE, metricsOf, provenanceOf } from '../evaluation/provenance'
import { evaluationSession } from '../evaluation/session'
import type { EvaluationReport } from '../harness/types'
import { deskAction, deskRun, executedAction } from '../test/deskFixtures'
import { HELD_REASON, QUEUE_GROUPS, groupOf, nextStepOf, runQueueRefetchInterval, toRunRow } from './deskRuns'
import { explainHold } from './deskHolds'
import { AgentActivity, ExecutionStep, FollowUpItem, RunProgress, RunStatus, RunTimeline, VerificationEvidence } from './RunParts'
import { FOLLOW_UP_STATE, LIFECYCLE, PROGRESS_PATH, effectsOf, followUpInfo, progressOf, stageInfo, stageOfRun, stageTimes, verificationOf, workerView } from './runLifecycle'
import { approvalGate, writePolicyFrom } from './writePolicy'

afterEach(() => {
  cleanup()
  evaluationSession.reset()
})

const lifecycle = (stage: string, over: Partial<NonNullable<DeskRun['lifecycle']>> = {}): DeskRun['lifecycle'] => ({ stage: stage as DeskLifecycleStage, reason: null, final: false, outcomeUnknown: false, compensation: null, ...over })
const at = (minute: number) => `2026-11-14T08:${String(minute).padStart(2, '0')}:00+00:00`
const event = (minute: number, kind: DeskTimelineItem['kind'], summary: string, data: Record<string, unknown> = {}): DeskTimelineItem => ({ at: at(minute), kind, summary, data })
const opening = [
  event(0, 'stage', 'Request received.', { stage: 'RECEIVED' }),
  event(1, 'stage', 'Request classified.', { stage: 'CLASSIFIED', category: 'action_item' }),
  event(2, 'stage', 'Context gathered.', { stage: 'CONTEXT_GATHERING' }),
  event(3, 'stage', 'Plan made.', { stage: 'PLANNING', planner: 'rules' }),
]

describe('every lifecycle stage the contract names', () => {
  const STAGES = Object.keys(LIFECYCLE) as DeskLifecycleStage[]

  it('has a name, a holder and a place in the queue for each of the fourteen stages', () => {
    expect(STAGES).toHaveLength(14)
    for (const stage of STAGES) {
      const run = deskRun({ lifecycle: lifecycle(stage), actions: stage === 'COMPLETED' ? [executedAction()] : [deskAction()] })
      expect(stageOfRun(run)).toBe(stage)
      expect(stageInfo(stage)!.label.length, stage).toBeGreaterThan(3)
      expect(QUEUE_GROUPS[groupOf(run)], stage).toBeDefined()
      expect(groupOf(run), stage).not.toBe('unknown')
    }
  })

  it('sorts each stage into the list a person would look for it in', () => {
    const group = (stage: string, over: Partial<DeskRun> = {}) => groupOf(deskRun({ lifecycle: lifecycle(stage), ...over }))
    expect(group('AWAITING_APPROVAL')).toBe('decision')
    expect(group('EXECUTING')).toBe('in_progress')
    expect(group('PLANNING')).toBe('in_progress')
    expect(group('VERIFYING')).toBe('in_progress')
    expect(group('AWAITING_REPLY')).toBe('awaiting_reply')
    expect(group('NEEDS_CLARIFICATION')).toBe('input')
    expect(group('ESCALATED')).toBe('input')
    expect(group('PARTIALLY_COMPLETED')).toBe('problem')
    expect(group('FAILED')).toBe('problem')
    expect(group('CANCELLED')).toBe('cancelled')
    expect(group('COMPLETED', { actions: [executedAction()] })).toBe('done')
    // Completed with nothing proposed is "no action needed", not finished work.
    expect(group('COMPLETED', { actions: [] })).toBe('no_action')
  })

  it('names each stage on its chip', () => {
    for (const stage of STAGES) {
      render(<RunStatus stage={stage} />)
      expect(screen.getByText(LIFECYCLE[stage].label)).toBeInTheDocument()
      cleanup()
    }
  })

  it('falls back to the run state on a backend that reports no lifecycle', () => {
    const old = deskRun({ state: 'executing' })
    expect(stageOfRun(old)).toBeNull()
    expect(progressOf(old)).toBeNull()
    expect(groupOf(old)).toBe('in_progress')
    const { container } = render(<RunStatus stage={null} fallback={<span>from state</span>} />)
    expect(container).toHaveTextContent('from state')
  })
})

describe('the stage names of the revised contract', () => {
  it('understands the three renamed stages as the stages they replace', () => {
    for (const [sent, means] of [['UNDERSTANDING', 'CLASSIFIED'], ['INVESTIGATING', 'CONTEXT_GATHERING'], ['WAITING_FOR_RESPONSE', 'AWAITING_REPLY']] as const) {
      const run = deskRun({ lifecycle: lifecycle(sent) })
      expect(stageOfRun(run), sent).toBe(means)
      expect(stageOfRun({ lifecycle: sent }), sent).toBe(means)
      expect(groupOf(run), sent).not.toBe('unknown')
    }
    expect(groupOf(deskRun({ lifecycle: lifecycle('WAITING_FOR_RESPONSE'), state: 'completed', actions: [executedAction()] }))).toBe('awaiting_reply')
    // Stage events written with the new names give the rail its times.
    const times = stageTimes([event(1, 'stage', 'Understood.', { stage: 'UNDERSTANDING' }), event(2, 'stage', 'Investigated.', { stage: 'INVESTIGATING' })])
    expect(times.get('CLASSIFIED')).toBe(at(1))
    expect(times.get('CONTEXT_GATHERING')).toBe(at(2))
  })

  it('shows HELD as held, asks for input, and never offers it as something to approve', () => {
    const run = deskRun({ lifecycle: lifecycle('HELD', { reason: 'proposal_changed' }), actions: [deskAction({ status: 'needs_info', approve: null, errorCode: 'proposal_changed' })], updatedAt: at(8), timeline: opening })
    expect(stageOfRun(run)).toBe('HELD')
    expect(groupOf(run)).toBe('input')
    expect(nextStepOf(run)).toMatchObject({ kind: 'complete_card' })
    expect(nextStepOf(run).detail).toContain('proposal changed')
    expect(nextStepOf(run).detail).toContain('Nothing can be approved as it stands')
    render(<RunStatus stage="HELD" />)
    expect(screen.getByText('Held')).toBeInTheDocument()
    expect(progressOf(run)!.at(-1)).toMatchObject({ label: 'Held', state: 'current' })
  })
})

describe('an unknown stage or state', () => {
  it('is shown as unrecognised with its raw value, and never as finished', () => {
    const run = deskRun({ lifecycle: lifecycle('ARCHIVED_BY_POLICY'), state: 'completed', actions: [executedAction()], updatedAt: at(9) })
    expect(groupOf(run)).toBe('unknown')
    expect(nextStepOf(run).kind).toBe('unknown')
    render(<RunStatus stage="ARCHIVED_BY_POLICY" />)
    expect(screen.getByText('Stage not recognised')).toBeInTheDocument()
    const steps = progressOf(run)!
    expect(steps.at(-1)).toMatchObject({ state: 'current', tone: 'danger' })
    expect(steps.at(-1)!.label).toContain('ARCHIVED_BY_POLICY')
    expect(steps.some(step => step.stage === 'COMPLETED')).toBe(false)
  })

  it('does not treat an unknown follow-up state as answered', () => {
    expect(followUpInfo('snoozed')).toMatchObject({ tone: 'danger' })
    expect(followUpInfo('snoozed').label).toContain('snoozed')
    render(<ul><FollowUpItem followUp={{ id: 'f1', state: 'snoozed' as DeskFollowUp['state'], waitingOn: 'sofia@lumen.example' }} timeZone="UTC" onClose={() => {}} /></ul>)
    expect(screen.queryByRole('button', { name: 'Stop waiting' })).toBeNull()
    expect(screen.queryByText('Answered')).toBeNull()
  })
})

describe('progress of a run', () => {
  it('gives each reached stage the time the server recorded, and none it did not', () => {
    const run = deskRun({ lifecycle: lifecycle('AWAITING_APPROVAL'), timeline: [...opening, event(4, 'proposal', 'Proposed create_task for approval.')] })
    const steps = progressOf(run)!
    expect(steps.map(step => step.stage)).toEqual(PROGRESS_PATH)
    expect(steps.map(step => step.state)).toEqual(['reached', 'reached', 'reached', 'reached', 'current', 'upcoming', 'upcoming', 'upcoming'])
    expect(steps[4].at).toBe(at(4))
    expect(steps.slice(5).every(step => step.at === null)).toBe(true)

    render(<RunProgress steps={steps} timeZone="UTC" />)
    const rail = screen.getByRole('list', { name: 'Progress of this run' })
    expect(within(rail).getByLabelText('Awaiting approval: now')).toHaveAttribute('aria-current', 'step')
    expect(within(rail).getByLabelText('Incoming: done')).toHaveTextContent('08:00')
    expect(within(rail).getByLabelText('Executing: not yet')).toHaveTextContent('not yet')
  })

  it('marks a stage the run passed without a recorded event as not recorded, not as done', () => {
    const run = deskRun({ lifecycle: lifecycle('EXECUTING'), timeline: [opening[0], opening[1], event(5, 'execution', 'Ran.')] })
    const byStage = Object.fromEntries(progressOf(run)!.map(step => [step.stage, step.state]))
    expect(byStage.RECEIVED).toBe('reached')
    expect(byStage.PLANNING).toBe('skipped')
    expect(byStage.AWAITING_APPROVAL).toBe('skipped')
    expect(byStage.EXECUTING).toBe('current')
  })

  it('ends on the stage a run rests in when that stage is off the path', () => {
    const run = deskRun({ lifecycle: lifecycle('ESCALATED'), timeline: opening, updatedAt: at(6), actions: [] })
    const steps = progressOf(run)!
    expect(steps.map(step => step.label)).toEqual(['Incoming', 'Understanding', 'Investigating', 'Planning', 'Escalated to you'])
    expect(steps.at(-1)).toMatchObject({ state: 'current', at: at(6) })
  })

  it('reads stage times only from events the server wrote', () => {
    expect([...stageTimes([event(1, 'decision', 'x'), event(2, 'read', 'y'), event(3, 'verification', 'z')]).keys()]).toEqual(['VERIFYING'])
    expect(stageTimes(undefined).size).toBe(0)
  })
})

describe('approval required', () => {
  it('asks for a decision when a card can be approved, and for input when every card is held', () => {
    const approvable = deskRun({ lifecycle: lifecycle('AWAITING_APPROVAL') })
    expect(groupOf(approvable)).toBe('decision')
    expect(nextStepOf(approvable)).toMatchObject({ kind: 'approve' })
    const held = deskRun({ lifecycle: lifecycle('AWAITING_APPROVAL'), actions: [deskAction({ status: 'needs_info', approve: null })] })
    expect(groupOf(held)).toBe('input')
  })

  it('records an approval the execution gate refused as held, with nothing run', () => {
    const action = deskAction({ tool_name: 'send_email', status: 'needs_info', errorCode: 'external_writes_disabled', proposedAt: at(4), decisions: [{ decision: 'approve', by: 'alice@example.test', at: at(5), result: 'held', code: 'external_writes_disabled' }] })
    render(<ExecutionStep action={action} timeZone="UTC" />)
    const record = screen.getByTestId('execution-31')
    expect(record).toHaveTextContent('Approved by alice@example.test')
    expect(record).toHaveTextContent('held by the execution gate (external writes disabled): nothing ran')
    expect(record).toHaveTextContent('Nothing to verify yet')
  })

  it('says when a proposal was edited before it was approved', () => {
    render(<ExecutionStep action={deskAction({ decisions: [{ decision: 'approve', by: 'alice@example.test', at: at(5), edited: ['body'] }] })} timeZone="UTC" />)
    expect(screen.getByTestId('execution-31')).toHaveTextContent('edited before approval: body')
  })
})

describe('partial completion and failed execution', () => {
  it('puts a partly completed run under "did not finish" and never under finished work', () => {
    const run = deskRun({
      state: 'partial',
      lifecycle: lifecycle('PARTIALLY_COMPLETED', { final: true, compensation: { policy: 'escalate', message: 'The event exists; the confirmation was not sent.' } }),
      actions: [executedAction({ toolCallId: 31, tool_name: 'create_calendar_event' }), deskAction({ toolCallId: 32, tool_name: 'send_email', status: 'failed', error: 'SMTP refused' })],
    })
    expect(groupOf(run)).toBe('problem')
    expect(nextStepOf(run)).toMatchObject({ kind: 'inspect_failure' })
    expect(progressOf(run)!.at(-1)).toMatchObject({ label: 'Partially completed', tone: 'danger' })
  })

  it('shows a failed execution with its error and never as verified', () => {
    const action = deskAction({ status: 'failed', error: 'SMTP refused', execution: { status: 'failed', at: at(6), error: 'SMTP refused', durationMs: 412 } })
    render(<ExecutionStep action={action} timeZone="UTC" />)
    const record = screen.getByTestId('execution-31')
    expect(record).toHaveTextContent('Failed in 412 ms: SMTP refused')
    expect(record).not.toHaveTextContent(/Verified/)
    expect(verificationOf(action).state).toBe('not_applicable')
  })

  it('treats a partly executed action as not verified, whatever its status says', () => {
    const action = deskAction({ status: 'partially_executed', verified: false, execution: { status: 'partially_executed', at: at(6) } })
    expect(verificationOf(action)).toMatchObject({ state: 'pending', label: 'Not verified' })
  })
})

describe('verification', () => {
  it('is pending for an action that ran without evidence, and the run waits', () => {
    const action = deskAction({ status: 'executed', verified: false, approve: null })
    expect(verificationOf(action).state).toBe('pending')
    render(<VerificationEvidence action={action} timeZone="UTC" />)
    expect(screen.getByTestId('verification-31')).toHaveTextContent('Not verified')
    const run = deskRun({ state: 'executing', lifecycle: lifecycle('VERIFYING'), actions: [action] })
    expect(groupOf(run)).toBe('in_progress')
    expect(nextStepOf(run)).toMatchObject({ kind: 'wait' })
    // The queue keeps reading while a run is verifying.
    expect(runQueueRefetchInterval({ entries: [{ row: toRunRow({ runId: 7 })!, run, error: null }], listed: 1, notRead: 0, failedReads: 0 })).toBe(4_000)
  })

  it('names the evidence when the server says verified, and says when a retry found it already done', () => {
    const readBack = executedAction({ assistantActionId: null, simulated: true, verification: { verified: true, method: 'sandbox_readback', reason: null, at: at(7) } })
    expect(verificationOf(readBack)).toMatchObject({ state: 'verified', detail: 'Evidence: the sandbox world was read back and the effect is there.' })
    const reconciled = executedAction({ verification: { verified: true, method: 'sandbox_readback', reason: null, at: at(7), reconciled: true } })
    expect(verificationOf(reconciled).label).toBe('Verified (already done; not repeated)')
    const recorded = executedAction({ verification: { verified: true, method: 'scriba_action_record', reason: null, at: at(7) } })
    expect(verificationOf(recorded).detail).toContain("Scriba's own record")
  })

  it('never calls an unconfirmed outcome a failure or a success: the person is told to look first', () => {
    const action = deskAction({ status: 'failed', outcomeUnknown: true, errorCode: 'outcome_unknown', execution: { status: 'unknown', at: at(6) } })
    expect(verificationOf(action).state).toBe('unknown_outcome')
    render(<ExecutionStep action={action} timeZone="UTC" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Outcome unknown. The provider did not confirm.')
    const run = deskRun({ state: 'failed', lifecycle: lifecycle('VERIFYING', { outcomeUnknown: true }), actions: [action] })
    expect(groupOf(run)).toBe('problem')
    expect(nextStepOf(run).label).toBe('Check whether it happened before doing anything else')
    expect(explainHold('outcome_unknown')).toMatchObject({ resolution: 'check_first' })
  })

  it('marks sandbox work as sandbox wherever it is recorded', () => {
    render(<ExecutionStep action={executedAction({ simulated: true, proposedAt: at(4), execution: { status: 'executed', at: at(6), simulated: true }, verification: { verified: true, method: 'sandbox_readback', reason: null, at: at(7) } })} timeZone="UTC" />)
    const record = screen.getByTestId('execution-31')
    expect(within(record).getByText('Sandbox')).toBeInTheDocument()
    expect(record).toHaveTextContent('Ran (sandbox: nothing real)')
  })
})

describe('duplicate action presentation', () => {
  it('shows two cards with one identity as one effect, standing where the newest card stands', () => {
    const first = deskAction({ toolCallId: 40, tool_name: 'send_email', status: 'failed', idempotencyKey: 'desk:abc:40' })
    const retry = deskAction({ toolCallId: 41, tool_name: 'send_email', status: 'executed', verified: true, idempotencyKey: 'desk:abc:40' })
    const other = deskAction({ toolCallId: 42, tool_name: 'create_task', idempotencyKey: 'desk:abc:42' })
    const effects = effectsOf([first, retry, other])
    expect(effects).toHaveLength(2)
    expect(effects[0]).toMatchObject({ key: 'desk:abc:40', primary: { toolCallId: 41 } })
    expect(effects[0].duplicates.map(action => action.toolCallId)).toEqual([40])
    render(<ExecutionStep action={effects[0].primary} timeZone="UTC" repeats={effects[0].duplicates.length} />)
    expect(screen.getByTestId('repeats-41')).toHaveTextContent('One effect, 2 cards')
  })

  it('never merges actions that carry no identity', () => {
    expect(effectsOf([deskAction({ toolCallId: 1 }), deskAction({ toolCallId: 2 })])).toHaveLength(2)
    expect(effectsOf([])).toEqual([])
  })
})

describe('the server record of a run', () => {
  it('lists each event with its time and kind, and marks a read that failed', () => {
    render(<RunTimeline timeZone="UTC" items={[...opening, event(4, 'read', 'calendar.read: failed.', { tool: 'calendar.read', ok: false, error: 'timeout' }), event(5, 'proposal', 'Proposed create_task for approval.', { tool: 'create_task', purpose: 'record_task' })]} />)
    const rows = screen.getAllByRole('listitem')
    expect(rows).toHaveLength(6)
    expect(rows[0]).toHaveTextContent('08:00')
    expect(rows[4]).toHaveTextContent('Read failed')
    expect(rows[4]).toHaveTextContent('Error: timeout')
    expect(rows[5]).toHaveTextContent('Proposed')
    expect(rows[5]).toHaveTextContent('Purpose: record_task')
  })

  it('says so when the server recorded nothing', () => {
    render(<RunTimeline timeZone="UTC" items={[]} />)
    expect(screen.getByText('The server recorded no events for this run.')).toBeInTheDocument()
  })
})

describe('follow-up states', () => {
  const followUp = (state: DeskFollowUp['state']): DeskFollowUp => ({ id: `f-${state}`, state, waitingOn: 'sofia@lumen.example', subject: 'Intro call', sentAt: at(1), dueAt: '2026-11-16T08:01:00+00:00', runId: 12 })

  it('names each of the four states and offers "stop waiting" only while a reply is still awaited', () => {
    for (const state of Object.keys(FOLLOW_UP_STATE) as DeskFollowUp['state'][]) {
      render(<ul><FollowUpItem followUp={followUp(state)} timeZone="UTC" onClose={() => {}} /></ul>)
      const item = screen.getByTestId(`follow-up-f-${state}`)
      expect(within(item).getByText(FOLLOW_UP_STATE[state].label)).toBeInTheDocument()
      expect(within(item).queryByRole('button', { name: 'Stop waiting' }) !== null, state).toBe(state === 'waiting' || state === 'overdue')
      expect(within(item).getByRole('link', { name: 'Open run 12' })).toHaveAttribute('href', '#/work/12')
      cleanup()
    }
  })

  it('says an overdue reminder is proposed, not sent', () => {
    render(<ul><FollowUpItem followUp={followUp('overdue')} timeZone="UTC" /></ul>)
    expect(screen.getByTestId('follow-up-f-overdue')).toHaveTextContent('A reminder is proposed for your approval; it has not been sent.')
  })

  it('makes a run waiting for a reply its own list, and asks for a decision only once it is overdue', () => {
    const waiting = deskRun({ state: 'completed', lifecycle: lifecycle('AWAITING_REPLY'), actions: [executedAction({ tool_name: 'send_email' })], followUps: [followUp('waiting')] })
    expect(groupOf(waiting)).toBe('awaiting_reply')
    expect(nextStepOf(waiting).kind).toBe('wait')
    expect(nextStepOf({ ...waiting, followUps: [followUp('overdue')] }).kind).toBe('approve')
  })
})

describe('list rows of overlay 0.3', () => {
  it('reads the stage, the held reason and the follow-up states from the row, and tolerates their absence', () => {
    const row = toRunRow({ runId: 22, provider: 'gmail', email_id: 'm', subject: 'Meeting request', state: 'no_action_proposed', lifecycle: 'ESCALATED', held: { reason: 'untrusted_instructions' }, simulated: true, trigger: 'worker', updatedAt: at(3), followUps: [{ id: 'a', state: 'waiting' }, { id: 'b' }] })!
    expect(row).toMatchObject({ stage: 'ESCALATED', state: 'no_action_proposed', heldReason: 'untrusted_instructions', simulated: true, trigger: 'worker', followUps: ['waiting'] })
    expect(toRunRow({ runId: 3 })).toMatchObject({ stage: null, state: null, heldReason: null, simulated: false, followUps: [] })
  })

  it('has words for every held reason overlay 0.3 adds', () => {
    for (const reason of ['event_not_found', 'event_ambiguous', 'not_organizer', 'calendar_lookup_failed', 'already_scheduled', 'task_exists', 'untrusted_instructions'] as const) {
      expect(HELD_REASON[reason].title.length, reason).toBeGreaterThan(10)
    }
    const run = deskRun({ state: 'no_action_proposed', lifecycle: lifecycle('ESCALATED'), actions: [], held: { reason: 'untrusted_instructions' as never, message: 'm', slots: [], calendars: [] } })
    expect(nextStepOf(run)).toMatchObject({ kind: 'held', label: 'The message contains text addressed to the assistant' })
  })
})

describe('background intake', () => {
  const worker = (over: Partial<DeskWorkerStatus> = {}): DeskWorkerStatus => ({ enabled: true, running: true, reason: null, intervalSeconds: 15, claims: { store: 'memory', durable: false }, you: { served: true, lastStatus: 'ok', lastAt: at(9), opened: 8, mailboxUnreadable: false, consecutiveFailures: 0 }, ...over })

  it('reports a running worker only as far as the server does, and never says it sends', () => {
    expect(workerView(worker())).toMatchObject({ running: true, tone: 'ok', headline: 'Background intake is running' })
    expect(workerView(worker()).detail).toContain('only proposes: it never sends or approves')
    render(<AgentActivity worker={worker()} timeZone="UTC" />)
    expect(screen.getByTestId('agent-activity')).toHaveTextContent('8 requests opened for you')
    expect(screen.getByTestId('agent-activity')).toHaveTextContent('runs are kept in this process only')
  })

  it('says why it is off, that it is not serving this user, or that a mailbox could not be read', () => {
    expect(workerView(worker({ running: false, reason: 'refused_production' }))).toMatchObject({ running: false, headline: 'Background intake is off' })
    expect(workerView(worker({ running: false, reason: 'refused_production' })).detail).toContain('refuses to start in a production process')
    expect(workerView(worker({ you: { served: false, lastStatus: null, lastAt: null, opened: 0, mailboxUnreadable: false, consecutiveFailures: 0 } })).headline).toContain('not for your account')
    expect(workerView(worker({ you: { served: true, lastStatus: 'mailbox_unreadable', lastAt: at(9), opened: 2, mailboxUnreadable: true, consecutiveFailures: 0 } }))).toMatchObject({ tone: 'danger' })
    expect(workerView(null).headline).toBe('Background intake status is not available')
  })

  it('shows a failed status read as a failure, not as "off"', () => {
    render(<AgentActivity worker={null} timeZone="UTC" unavailable="The server answered 502." />)
    expect(screen.getByTestId('agent-activity')).toHaveTextContent('Background intake status could not be read')
    expect(screen.getByTestId('agent-activity')).not.toHaveTextContent('Background intake is off')
  })
})

describe('the execution gate', () => {
  const health = (over: Record<string, unknown>) => writePolicyFrom({ ok: true, service: 'scriba-desk-overlay', version: '0.3.0', scribaCommit: null, capabilities: [], writes: false, ...over } as never)

  it('lets a mail or calendar action be approved in a sandbox, where nothing real is reached', () => {
    const sandbox = health({ executionMode: 'sandbox', externalWrites: { enabled: false, checks: [{ id: 'lead_authorization', ok: false, detail: 'Not authorized.' }] } })
    expect(sandbox).toMatchObject({ externalWritesEnabled: false, executionMode: 'sandbox' })
    expect(sandbox.readinessChecks).toHaveLength(1)
    expect(approvalGate('send_email', sandbox)).toEqual({ allowed: true, reason: null })
    expect(approvalGate('create_calendar_event', sandbox).allowed).toBe(true)
  })

  it('keeps those approvals off when the backend holds them, or does not say what an approval does', () => {
    expect(approvalGate('send_email', health({ executionMode: 'held', externalWrites: { enabled: false } })).allowed).toBe(false)
    expect(approvalGate('send_email', health({})).allowed).toBe(false)
    // A value this version does not know is not treated as a sandbox.
    expect(health({ executionMode: 'dry_run' }).executionMode).toBeNull()
    expect(approvalGate('send_email', health({ executionMode: 'dry_run' })).allowed).toBe(false)
  })

  it('never lets a sandbox unlock an integration the Desk leaves out, or an action it does not know', () => {
    const sandbox = health({ executionMode: 'sandbox' })
    expect(approvalGate('send_slack_message', sandbox).allowed).toBe(false)
    expect(approvalGate('launch_rocket', sandbox).allowed).toBe(false)
  })

  it('explains each gate code, and offers no approval past a closed gate', () => {
    expect(explainHold('external_writes_disabled')).toMatchObject({ resolution: 'gate_closed' })
    expect(explainHold('external_writes_disabled')!.detail).toContain('nothing was sent and nothing was changed')
    expect(explainHold('sandbox_world_gone')).toMatchObject({ resolution: 'try_later' })
    expect(explainHold('made_up_code')).toBeNull()
  })
})

describe('evaluation result provenance', () => {
  const recorded = JSON.parse(readFileSync(resolve(__dirname, '../../../docs/frontend/evaluation/rules-only-sandbox-overlay-0.3.0.simulated.json'), 'utf8')) as EvaluationReport
  const withTarget = (target: Partial<EvaluationReport['target']>): EvaluationReport => ({ ...recorded, target: { ...recorded.target, ...target } })

  it('places a report by what the target reported, never by its label', () => {
    expect(provenanceOf(recorded)).toBe('scripted')
    expect(provenanceOf(withTarget({ baseUrl: null }))).toBe('mock')
    expect(provenanceOf(withTarget({ dataSource: 'live' }))).toBe('real')
    expect(provenanceOf({ ...withTarget({ dataSource: 'live' }), label: 'mock run' } as EvaluationReport)).toBe('real')
    expect(provenanceOf({ ...withTarget({ baseUrl: null }), label: 'Real model, production' } as EvaluationReport)).toBe('mock')
    expect(provenanceOf(withTarget({ dataSource: 'guessed' as never }))).toBe('unknown')
    expect(provenanceOf({ target: null } as never)).toBe('unknown')
  })

  it('counts the recorded rules-only run as it is: ten of twenty, three unscorable, no safety violation, no cost', () => {
    expect(metricsOf(recorded)).toMatchObject({ executed: 20, passed: 10, failed: 7, errored: 3, skipped: 0, passRate: 0.5, safetyViolations: 0, totalCostUsd: null, casesWithUsage: 0 })
    expect(recorded.results.filter(result => result.verdict === 'error').every(result => result.errors.some(error => error.code === 'conversation_input_unsupported'))).toBe(true)
  })

  it('shows a scripted-model run in its own panel, with its numbers and the words "not an agent result"', () => {
    render(<EvaluationResultPanel report={recorded} timeZone="UTC" />)
    const panel = screen.getByTestId('evaluation-result-scripted')
    expect(within(panel).getByRole('heading', { name: 'Scripted-model evaluation' })).toBeInTheDocument()
    expect(panel).toHaveTextContent('Not an agent result')
    expect(panel).toHaveTextContent('10 of 20')
    expect(panel).toHaveTextContent('50%')
    expect(panel).toHaveTextContent('Of the rules alone, not of the agent')
    expect(panel).toHaveTextContent('No model call was recorded')
    expect(panel).not.toHaveTextContent('$')
    expect(panel).toHaveTextContent('10 cases did not pass')
  })

  it('gives a mock run counts and no pass rate, and calls only a real-model run the secretary\'s result', () => {
    render(<EvaluationResultPanel report={withTarget({ baseUrl: null })} timeZone="UTC" />)
    const mock = screen.getByTestId('evaluation-result-mock')
    expect(mock).toHaveTextContent('Not given for a mock run')
    expect(mock).not.toHaveTextContent('50%')
    expect(mock).toHaveTextContent('Not an agent result')
    cleanup()
    render(<EvaluationResultPanel report={withTarget({ dataSource: 'live' })} timeZone="UTC" />)
    expect(screen.getByTestId('evaluation-result-real')).toHaveTextContent("The secretary's result")
    expect(PROVENANCE.real.label).toBe('Real-model evaluation')
  })

  it('keeps an imported scripted report out of the headline results, and refuses a mock report', () => {
    evaluationSession.importJson(JSON.stringify(recorded))
    expect(evaluationSession.getState().scriptedReport?.id).toBe(recorded.id)
    expect(evaluationSession.getState().liveReport).toBeNull()
    expect(evaluationSession.getState().notice).toContain('not counted as an agent result')

    evaluationSession.reset()
    evaluationSession.importJson(JSON.stringify(withTarget({ baseUrl: null })))
    expect(evaluationSession.getState().error?.message).toContain('simulated report from the scripted mock')
    expect(evaluationSession.getState().scriptedReport).toBeNull()
    expect(evaluationSession.getState().liveReport).toBeNull()
  })
})
