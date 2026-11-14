/**
 * The execution plan of a run and the rest of the revised contract (agent1/autonomous-engine at
 * 0282558): the plan and its step states, the action fields that go with it, the reasons and hold
 * codes it adds, and the events it records. The plan payloads follow
 * backend/desk_overlay/plans.py (build, step_states) on that branch.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { DeskAction, DeskRun, DeskTimelineItem } from '../api/desk'
import { deskAction, deskRun, executedAction } from '../test/deskFixtures'
import { describeAction } from './describeAction'
import { explainFailure, explainHold, HOLD_CODES } from './deskHolds'
import { groupOf, heldReasonInfo, nextStepOf } from './deskRuns'
import { RunPlan } from './PlanView'
import { ExecutionStep, RunTimeline } from './RunParts'
import { LIFECYCLE, LIFECYCLE_REASON } from './runLifecycle'
import { confidenceText, intentLabel, planFieldsOf, planOf, planSummary, plannerLabel, standingOf, stepsOf, tallyOf, type RunPlanData } from './runPlan'

afterEach(cleanup)

const step = (over: Record<string, unknown> = {}) => ({
  id: 's1', tool: 'create_calendar_event', purpose: 'book', dependsOn: [], deferred: false, requiresApproval: true, external: true,
  expected: 'The meeting exists on the named calendar at the proposed time.', onFailure: 'Dependent steps are not proposed; the run is handed to the person.',
  state: 'awaiting_approval', toolCallId: 41, ...over,
})
const confirm = (over: Record<string, unknown> = {}) => step({ id: 's2', tool: 'send_email', purpose: 'confirm', dependsOn: ['s1'], deferred: true, expected: 'The sender has a reply in the original thread stating what was done.', state: 'waiting', toolCallId: null, ...over })
const rawPlan = (over: Record<string, unknown> = {}) => ({
  version: 1,
  message: { provider: 'gmail', provider_account_id: 'acct-1', email_id: 'm-7', thread_id: 't-7' },
  planner: 'rules',
  intents: [{ type: 'new_meeting', confidence: null, evidence: ['meeting_request'], missing: [], source: 'rules' }],
  unsupported: [],
  facts: ['The requested time is free on every connected calendar (2 read).'],
  assumptions: ['The length was not stated; your default of 30 minutes is used.'],
  missing: [],
  tools: ['calendar.check_availability', 'calendar.find_free_slots'],
  steps: [step(), confirm()],
  approvals: 2,
  escalation: ['A calendar cannot be read: availability is unknown and nothing is booked.'],
  ...over,
})
/** A run as the newer backend sends it: `plan` beside the fields the typed client declares. */
const runWith = (plan: unknown, over: Partial<DeskRun> = {}): DeskRun => ({ ...deskRun(over), plan }) as DeskRun
const planned = (action: DeskAction, extra: Record<string, unknown>): DeskAction => ({ ...action, ...extra }) as DeskAction
const view = (plan: unknown, actions: DeskAction[] = []) => stepsOf(planOf({ plan })!, actions)

describe('reading the plan', () => {
  it('reads every part the backend writes', () => {
    const plan = planOf(runWith(rawPlan()))!
    expect(plan.planner).toBe('rules')
    expect(plan.intents).toEqual([{ type: 'new_meeting', confidence: null, evidence: ['meeting_request'], missing: [], source: 'rules' }])
    expect(plan.facts).toHaveLength(1)
    expect(plan.assumptions).toHaveLength(1)
    expect(plan.steps.map(s => [s.id, s.tool, s.purpose, s.dependsOn, s.deferred, s.state, s.toolCallId])).toEqual([
      ['s1', 'create_calendar_event', 'book', [], false, 'awaiting_approval', 41],
      ['s2', 'send_email', 'confirm', ['s1'], true, 'waiting', null],
    ])
    expect(plan.approvals).toBe(2)
  })

  it('treats a missing or null plan as no plan, not as an empty one', () => {
    expect(planOf(deskRun())).toBeNull() // an overlay that sends no plan at all
    expect(planOf(runWith(null))).toBeNull() // a run opened before the plan existed
    expect(planOf(runWith('s1, s2'))).toBeNull()
    expect(planOf(runWith([step()]))).toBeNull()
    expect(planOf(null)).toBeNull()
  })

  it('leaves out malformed entries instead of guessing them', () => {
    const plan = planOf(runWith(rawPlan({ intents: [{ confidence: 0.9 }, 'task', { type: 'task', confidence: '0.9', evidence: 'x' }], steps: [{ tool: 'send_email' }, { id: 's9' }, step({ state: undefined, requiresApproval: undefined })], facts: 'free', approvals: 'two' })))!
    expect(plan.intents).toEqual([{ type: 'task', confidence: null, evidence: [], missing: [], source: null }])
    expect(plan.steps).toHaveLength(1)
    // No state reported is not "ready", and nothing is presented as automatic unless the server says so.
    expect(plan.steps[0].state).toBe('unknown')
    expect(plan.steps[0].requiresApproval).toBe(true)
    expect(plan.facts).toEqual([])
    expect(plan.approvals).toBeNull()
  })
})

describe('where each step stands', () => {
  it('names the three states of a step that has no card yet', () => {
    expect(view(rawPlan({ steps: [step(), confirm({ state: 'waiting' })] }))[1]).toMatchObject({ standing: 'waiting', tone: 'neutral' })
    expect(view(rawPlan({ steps: [step({ state: 'executed' }), confirm({ state: 'ready' })] }))[1]).toMatchObject({ standing: 'ready', label: 'Ready to be proposed' })
    const blocked = view(rawPlan({ steps: [step({ state: 'cancelled' }), confirm({ state: 'blocked' })] }))
    expect(blocked[0]).toMatchObject({ standing: 'cancelled' })
    expect(blocked[1]).toMatchObject({ standing: 'blocked', tone: 'danger' })
    expect(blocked[1].label).toContain('will not be proposed')
  })

  it('calls a step done only on the evidence of its action', () => {
    const ran = rawPlan({ steps: [step({ state: 'executed' })] })
    expect(view(ran, [executedAction({ toolCallId: 41, verified: true })])[0]).toMatchObject({ standing: 'verified', tone: 'ok' })
    // Executed with no evidence, or with no action on the run at all, is "ran", never "done".
    expect(view(ran, [executedAction({ toolCallId: 41, verified: false, assistantActionId: null })])[0]).toMatchObject({ standing: 'ran_unverified', tone: 'warn' })
    expect(view(ran, [])[0]).toMatchObject({ standing: 'ran_unverified' })
    expect(view(ran, [executedAction({ toolCallId: 41, verified: false, outcomeUnknown: true })])[0]).toMatchObject({ standing: 'outcome_unknown', tone: 'danger' })
    expect(view(rawPlan({ steps: [step({ state: 'failed' })] }), [deskAction({ toolCallId: 41, status: 'failed', outcomeUnknown: true })])[0]).toMatchObject({ standing: 'outcome_unknown' })
  })

  it('maps every card status a step can take, and no other state to a finished one', () => {
    const standing = (state: string, action?: DeskAction) => view(rawPlan({ steps: [step({ state })] }), action ? [action] : [])[0].standing
    expect(standing('awaiting_approval')).toBe('your_decision')
    expect(standing('proposed')).toBe('your_decision')
    expect(standing('needs_info')).toBe('held')
    expect(standing('awaiting_approval', planned(deskAction({ toolCallId: 41 }), { held: true }))).toBe('held')
    expect(standing('approved')).toBe('running')
    expect(standing('executing')).toBe('running')
    expect(standing('partially_executed')).toBe('partly')
    expect(standing('failed')).toBe('failed')
    expect(standing('unsupported')).toBe('failed')
    expect(standing('cancelled')).toBe('cancelled')
    const unknown = view(rawPlan({ steps: [step({ state: 'archived' })] }))[0]
    expect(unknown).toMatchObject({ standing: 'unknown', tone: 'danger' })
    expect(unknown.label).toContain('archived')
    expect(unknown.blurb).toContain('not treated as done')
  })

  it('finds the action of a step by its card, or by the step the action names', () => {
    const plan = rawPlan({ steps: [step({ state: 'executed', toolCallId: null })] })
    const action = planned(executedAction({ toolCallId: 77, verified: true }), { stepId: 's1' })
    expect(view(plan, [action])[0].action).toBe(action)
    expect(view(plan, [executedAction({ toolCallId: 77 })])[0].action).toBeNull()
    expect(planFieldsOf(planned(deskAction(), { stepId: 's2', held: true, attempts: 3 }))).toEqual({ stepId: 's2', held: true, attempts: 3 })
    expect(planFieldsOf(deskAction())).toEqual({ stepId: null, held: false, attempts: null })
  })
})

describe('the wording of a plan', () => {
  it('says how a request was read, and shows a confidence only when one was measured', () => {
    expect(confidenceText({ confidence: null, source: 'rules' })).toBe('Read by rules, which do not measure confidence')
    expect(confidenceText({ confidence: null, source: 'model' })).toBe('Confidence not measured')
    expect(confidenceText({ confidence: 0.9, source: 'model' })).toBe('Confidence 90%')
    expect(confidenceText({ confidence: 0.4, source: 'model' })).toContain('too low to act on')
    expect(confidenceText({ confidence: 0.6, source: 'model' })).toBe('Confidence 60%')
    expect(intentLabel('reschedule')).toBe('Move a meeting')
    expect(intentLabel('budget_question')).toBe('budget question')
  })

  it('names each planner the contract lists and shows any other as reported', () => {
    for (const planner of ['rules', 'rules+model', 'model+rules', 'rules+agent']) expect(plannerLabel(planner), planner).not.toContain('Planner reported')
    expect(plannerLabel('rules')).toContain('No model took part')
    expect(plannerLabel('committee')).toBe('Planner reported: committee.')
    expect(plannerLabel(null)).toContain('not recorded')
  })

  it('summarises the steps and the approvals without claiming anything is automatic', () => {
    expect(planSummary(planOf({ plan: rawPlan() })!)).toBe('2 steps, each needing your approval.')
    expect(planSummary(planOf({ plan: rawPlan({ steps: [step()], approvals: 1 }) })!)).toBe('1 step, which needs your approval.')
    expect(planSummary(planOf({ plan: rawPlan({ approvals: 1 }) })!)).toBe('2 steps, 1 needing your approval.')
    expect(planSummary(planOf({ plan: rawPlan({ steps: [], approvals: 0 }) })!)).toContain('proposes nothing')
  })
})

describe('the plan on screen', () => {
  const show = (plan: unknown, actions: DeskAction[] = []) => render(<RunPlan plan={planOf({ plan }) as RunPlanData} actions={actions} />)

  it('shows what was understood, what it rests on, and the steps in order with what each waits for', () => {
    show(rawPlan())
    const plan = screen.getByRole('region', { name: 'Plan of this run' })
    expect(plan).toHaveTextContent('Planner: Rules only. No model took part.')
    expect(within(plan).getByRole('list', { name: 'What the message asks for' })).toHaveTextContent('A new meeting · Read by rules, which do not measure confidence')
    expect(plan).toHaveTextContent('Rules matched: meeting request')
    expect(within(plan).getByRole('list', { name: 'Facts verified by reading' })).toHaveTextContent('free on every connected calendar')
    expect(within(plan).getByRole('list', { name: 'Assumptions' })).toHaveTextContent('default of 30 minutes')
    expect(within(plan).queryByRole('list', { name: 'Missing details' })).toBeNull()
    const steps = within(within(plan).getByRole('list', { name: 'Steps of the plan' })).getAllByRole('listitem')
    expect(steps.map(li => li.getAttribute('aria-label'))).toEqual(['Step 1: Book the meeting. Awaiting your approval', 'Step 2: Tell the sender what was done. Waits for an earlier step'])
    expect(steps[1]).toHaveTextContent('only after step 1')
    expect(steps[1]).toHaveTextContent('Done when: The sender has a reply in the original thread stating what was done.')
    expect(steps[0]).toHaveTextContent('reaches a mailbox or calendar')
    // What happens on failure is said on a step that failed, not on one that has not run.
    expect(steps[0]).not.toHaveTextContent('Dependent steps are not proposed')
    expect(steps[1]).not.toHaveTextContent('Dependent steps are not proposed')
    expect(plan).toHaveTextContent('A calendar cannot be read: availability is unknown and nothing is booked.')
  })

  it('never shows a step as done before its action is verified', () => {
    show(rawPlan({ steps: [step({ state: 'executed' }), confirm({ state: 'ready' })] }), [executedAction({ toolCallId: 41, verified: false, assistantActionId: null })])
    expect(screen.getByTestId('plan-step-s1')).toHaveTextContent('Ran, not verified')
    expect(screen.getByTestId('plan-step-s1')).not.toHaveTextContent('Done and verified')
    expect(screen.getByRole('region', { name: 'Plan of this run' })).not.toHaveTextContent('Sandbox')
    expect(screen.getByTestId('plan-step-s2')).toHaveTextContent('Ready to be proposed')
    expect(screen.getByTestId('plan-step-s2')).toHaveTextContent('proposing it sends nothing')
  })

  it('says a blocked step will never be proposed, and what happens to a failed one', () => {
    show(rawPlan({ steps: [step({ state: 'failed' }), confirm({ state: 'blocked' })] }), [deskAction({ toolCallId: 41, status: 'failed' })])
    expect(screen.getByTestId('plan-step-s1')).toHaveTextContent('Failed')
    expect(screen.getByTestId('plan-step-s1')).toHaveTextContent('Dependent steps are not proposed; the run is handed to the person.')
    expect(screen.getByTestId('plan-step-s2')).toHaveTextContent('Blocked: will not be proposed')
    expect(screen.getByTestId('plan-step-s2')).toHaveTextContent('never proposed')
  })

  it('shows a model reading with its quote and confidence, what is missing, and what was left out', () => {
    show(rawPlan({
      planner: 'model+rules',
      intents: [
        { type: 'new_meeting', confidence: 0.92, evidence: ['Could we meet Tuesday at 10:00'], missing: [], source: 'model' },
        { type: 'reminder', confidence: 0.41, evidence: ['remind me'], missing: ['reminder time'], source: 'model' },
      ],
      unsupported: [{ type: 'task', why: 'evidence_not_in_message' }],
      missing: ['reminder time'],
    }))
    const asks = screen.getByRole('list', { name: 'What the message asks for' })
    expect(asks).toHaveTextContent('Confidence 92%')
    expect(asks).toHaveTextContent('Quoted from the message: “Could we meet Tuesday at 10:00”')
    expect(asks).toHaveTextContent('Confidence 41%: too low to act on')
    expect(asks).toHaveTextContent('Not stated: reminder time')
    expect(screen.getByRole('list', { name: 'Readings that were left out' })).toHaveTextContent('A task: the quote given for it is not in the message. Nothing was proposed from it.')
    const missing = screen.getByRole('list', { name: 'Missing details' })
    expect(missing).toHaveTextContent('reminder time')
    expect(missing.parentElement).toHaveTextContent('It is never made up.')
  })

  it('marks the plan of a sandbox run, so a verified step there is not read as a real one', () => {
    render(<RunPlan plan={planOf({ plan: rawPlan({ steps: [step({ state: 'executed' })] }) }) as RunPlanData} actions={[executedAction({ toolCallId: 41, verified: true, simulated: true })]} simulated />)
    const plan = screen.getByRole('region', { name: 'Plan of this run' })
    expect(within(plan).getByText('Sandbox')).toBeInTheDocument()
    expect(plan).toHaveTextContent('Done and verified')
  })

  it('says so when no step is planned, and shows no step list', () => {
    show(rawPlan({ steps: [], approvals: 0, facts: [], assumptions: [] }))
    expect(screen.getByRole('region', { name: 'Plan of this run' })).toHaveTextContent('No step is planned')
    expect(screen.queryByRole('list', { name: 'Steps of the plan' })).toBeNull()
  })
})

describe('reasons and codes the revised contract adds', () => {
  it('explains a changed proposal and never offers a way to approve past it', () => {
    const hold = explainHold('proposal_changed')!
    expect(hold.resolution).toBe('gate_closed')
    expect(hold.detail).toContain('Do not approve it as it is')
    // The two holds an approval can pass are unchanged.
    expect(HOLD_CODES).not.toContain('proposal_changed')
    expect(explainHold('interrupted')).toBeNull() // a failure, not a hold
    expect(explainFailure('interrupted')!.detail).toContain('It was not run again by itself')
    expect(explainFailure('provider_error')).toBeNull()
  })

  it('names the two reasons a model reading can be held for, and treats an unknown reason as held', () => {
    expect(heldReasonInfo('intent_unclear')!.title).toContain('not clear enough')
    expect(heldReasonInfo('details_missing')!.next).toContain('Nothing was filled in')
    expect(heldReasonInfo('calendar_conflict')).not.toBeNull()
    expect(heldReasonInfo('made_up_reason')).toBeNull()
    const unclear = deskRun({ state: 'no_action_proposed', actions: [], lifecycle: { stage: 'NEEDS_CLARIFICATION', reason: 'intent_unclear', final: false, outcomeUnknown: false, compensation: null }, held: { reason: 'intent_unclear', message: 'It is not clear enough what this message asks for.', slots: [], calendars: [] } as unknown as DeskRun['held'] })
    expect(groupOf(unclear)).toBe('input')
    expect(nextStepOf(unclear)).toMatchObject({ kind: 'held', label: heldReasonInfo('intent_unclear')!.title })
  })

  it('does not report a run as done when an action ran and its verification failed', () => {
    const run = deskRun({ state: 'completed', actions: [executedAction({ verified: false })], lifecycle: { stage: 'ESCALATED', reason: 'verification_failed', final: false, outcomeUnknown: false, compensation: null } })
    expect(groupOf(run)).toBe('input')
    const next = nextStepOf(run)
    expect(next.kind).toBe('held')
    expect(next.label).toBe(LIFECYCLE.ESCALATED.label)
    expect(next.detail).toBe(LIFECYCLE_REASON.verification_failed)
    expect(next.detail).toContain('not counted as done')
  })

  it('does not say nothing has changed once an earlier step of the run has run', () => {
    const first = deskRun({ lifecycle: { stage: 'AWAITING_APPROVAL', reason: null, final: false, outcomeUnknown: false, compensation: null }, actions: [deskAction()] })
    expect(nextStepOf(first).detail).toContain('Nothing has been sent or changed')
    const second = deskRun({ lifecycle: { stage: 'AWAITING_APPROVAL', reason: null, final: false, outcomeUnknown: false, compensation: null }, actions: [executedAction({ toolCallId: 41, tool_name: 'cancel_calendar_event' }), deskAction({ toolCallId: 42, tool_name: 'send_email' })] })
    expect(nextStepOf(second).kind).toBe('approve')
    expect(nextStepOf(second).detail).not.toContain('Nothing has been sent or changed')
    // The run is half done, and says so: the first step counts, the second is the person's.
    expect(nextStepOf(second).label).toBe('Review the next step and decide')
    expect(nextStepOf(second).detail).toBe('1 of 2 steps verified · 1 awaiting your decision. One earlier step has already been executed. What is waiting now runs only if you approve it.')
    // In a sandbox the earlier step is said to have been executed there.
    expect(nextStepOf({ ...second, simulated: true }).detail).toContain('One earlier step has already been executed in the sandbox.')
    expect(LIFECYCLE.AWAITING_APPROVAL.blurb).not.toContain('Nothing has happened')
  })
})

describe('how far a run has got', () => {
  const withLifecycle = (action: DeskAction, lifecycle: string): DeskAction => planned(action, { lifecycle })

  it('counts one verified step and one awaiting a decision as half done, never as done', () => {
    const tally = tallyOf(deskRun({ actions: [executedAction({ toolCallId: 41, tool_name: 'create_calendar_event' }), deskAction({ toolCallId: 42, tool_name: 'send_email' })] }))
    expect(tally.total).toBe(2)
    expect(tally.summary).toBe('1 of 2 steps verified · 1 awaiting your decision')
    expect(tally.allVerified).toBe(false)
    expect(tally.counts).toMatchObject({ verified: 1, you: 1, unverified: 0, problem: 0 })
    expect(tally.steps.map(step => step.kind)).toEqual(['verified', 'you'])
  })

  it('is complete only when every step ran and carries verification evidence', () => {
    const all = tallyOf(runWith(rawPlan({ steps: [step({ state: 'executed' }), confirm({ state: 'executed', toolCallId: 42 })] }), { state: 'completed', actions: [executedAction({ toolCallId: 41 }), executedAction({ toolCallId: 42, tool_name: 'send_email' })] }))
    expect(all.summary).toBe('2 of 2 steps verified')
    expect(all.allVerified).toBe(true)
    // The same run with one step executed and not verified is not complete.
    const one = tallyOf(deskRun({ state: 'completed', actions: [executedAction({ toolCallId: 41 }), executedAction({ toolCallId: 42, verified: false, assistantActionId: null })] }))
    expect(one.summary).toBe('1 of 2 steps verified · 1 ran, not verified')
    expect(one.allVerified).toBe(false)
    expect(tallyOf(deskRun({ actions: [] }))).toMatchObject({ total: 0, summary: 'No step is planned.', allVerified: false })
  })

  it('counts a step whose verification failed as a problem, on the word of the server', () => {
    const failed = withLifecycle(executedAction({ toolCallId: 41, verified: false }), 'VERIFICATION_FAILED')
    expect(standingOf('executed', failed, false)).toBe('verification_failed')
    const tally = tallyOf(deskRun({ state: 'completed', actions: [failed] }))
    expect(tally.counts.problem).toBe(1)
    expect(tally.counts.verified).toBe(0)
    expect(tally.summary).toBe('0 of 1 step verified · 1 did not finish cleanly')
    expect(tally.allVerified).toBe(false)
    // The server's state of the action wins over the card status, and "VERIFIED" still needs the evidence flag.
    expect(standingOf('executed', withLifecycle(executedAction({ verified: true }), 'INTERRUPTED'), false)).toBe('interrupted')
    expect(standingOf('executed', withLifecycle(executedAction({ verified: false }), 'VERIFIED'), false)).toBe('ran_unverified')
    expect(standingOf('executed', withLifecycle(executedAction({ verified: true }), 'VERIFIED'), false)).toBe('verified')
    expect(standingOf('executed', withLifecycle(executedAction(), 'SOMETHING_NEW'), false)).toBe('unknown')
  })

  it('counts a step blocked by the one it depends on, and does not call it awaiting anything', () => {
    const tally = tallyOf(runWith(rawPlan({ steps: [step({ state: 'executed' }), confirm({ state: 'blocked' })] }), { actions: [withLifecycle(executedAction({ toolCallId: 41, verified: false }), 'VERIFICATION_FAILED')] }))
    expect(tally.steps.map(entry => entry.standing)).toEqual(['verification_failed', 'blocked'])
    expect(tally.counts).toMatchObject({ problem: 1, blocked: 1, you: 0, later: 0, verified: 0 })
    expect(tally.summary).toBe('0 of 2 steps verified · 1 did not finish cleanly · 1 blocked')
    expect(tally.allVerified).toBe(false)
    // The plan shows the failed step with what happens next, and the dependent one as never proposed.
    render(<RunPlan plan={planOf({ plan: rawPlan({ steps: [step({ state: 'executed' }), confirm({ state: 'blocked' })] }) }) as RunPlanData} actions={[withLifecycle(executedAction({ toolCallId: 41, verified: false }), 'VERIFICATION_FAILED')]} />)
    expect(screen.getByTestId('plan-step-s1')).toHaveTextContent('Verification failed')
    expect(screen.getByTestId('plan-step-s1')).toHaveTextContent('Dependent steps are not proposed; the run is handed to the person.')
    expect(screen.getByTestId('plan-step-s2')).toHaveTextContent('Blocked: will not be proposed')
  })
})

describe('the record of a run on the revised contract', () => {
  const at = (minute: number) => `2026-11-14T08:${String(minute).padStart(2, '0')}:00+00:00`
  const event = (minute: number, kind: string, summary: string, data: Record<string, unknown> = {}) => ({ at: at(minute), kind, summary, data }) as DeskTimelineItem

  it('names the plan event, a blocked step and an edit the person made', () => {
    render(<RunTimeline timeZone="UTC" items={[
      event(1, 'plan', 'Plan written: 2 steps, 2 to approve.', { planner: 'rules' }),
      event(2, 'decision', 'A step was not proposed.', { decision: 'step_blocked', stepId: 's2', tool: 'send_email', dependsOn: ['s1'] }),
      event(3, 'human', 'You edited the action.', { action: 'edit', fields: ['start', 'end'], tool: 'create_calendar_event' }),
      event(4, 'audit', 'A kind this version does not know.'),
    ]} />)
    const items = screen.getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Plan')
    expect(items[0]).toHaveTextContent('Planner: rules')
    expect(items[1]).toHaveTextContent('Plan step: s2')
    expect(items[1]).toHaveTextContent('Depends on: s1')
    // An approved action is never changed silently: the fields the person changed are on the record.
    expect(items[2]).toHaveTextContent('You decided')
    expect(items[2]).toHaveTextContent('Fields you changed: start, end')
    expect(items[3]).toHaveTextContent('audit')
  })

  it('says how many times execution was attempted, only when it was more than once', () => {
    const { unmount } = render(<ExecutionStep timeZone="UTC" action={planned(executedAction({ toolCallId: 41, idempotencyKey: 'desk:abc:41', proposedAt: at(1) }), { attempts: 2 })} />)
    expect(screen.getByTestId('attempts-41')).toHaveTextContent('attempted 2 times')
    expect(screen.getByTestId('attempts-41')).toHaveTextContent('at most once')
    unmount()
    render(<ExecutionStep timeZone="UTC" action={planned(executedAction({ toolCallId: 41, idempotencyKey: 'desk:abc:41', proposedAt: at(1) }), { attempts: 1 })} />)
    expect(screen.queryByTestId('attempts-41')).toBeNull()
  })

  it('names the meeting a change or a cancellation is about, and keeps a new event on its own title', () => {
    const card = (tool_name: string, input: Record<string, unknown>) => describeAction({ id: 1, message_id: 1, conversation_id: 1, tool_name, status: 'awaiting_approval', input, output: {} })
    expect(card('cancel_calendar_event', { event_id: 'evt-1', event_title: 'Design workshop' }).headline).toBe('Design workshop')
    expect(card('update_calendar_event', { event_id: 'evt-1', event_title: 'Budget review', start: at(5) }).headline).toBe('Budget review')
    expect(card('cancel_calendar_event', { event_id: 'evt-1' }).headline).toBe('')
    expect(card('create_calendar_event', { title: 'Intro call', event_title: 'Something else' }).headline).toBe('Intro call')
    expect(card('cancel_calendar_event', { event_id: 'evt-1', event_title: 'Design workshop' }).otherInput.map(item => item.field)).not.toContain('event_title')
  })
})
