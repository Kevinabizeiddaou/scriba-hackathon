/**
 * The execution plan of a run (`DeskRun.plan`, docs/BACKEND_CONTRACT.md, "The plan").
 *
 * The backend writes the plan once, when the run is opened: what it understood, what that rests
 * on, and the steps in order with what each depends on. This file turns it into what a person
 * reads, and adds nothing of its own:
 *
 *   - the typed client (src/api/desk.ts) does not declare `plan`, `stepId`, `held` or `attempts`
 *     yet, so they are read here from the run as untyped data and checked field by field. A plan
 *     that is absent, null or not an object is "no plan" (a run opened before the plan existed),
 *     and the screens then show nothing rather than an empty plan;
 *   - a step's state is the server's. A state this file does not know is shown as unrecognised
 *     and is never treated as done;
 *   - a step is shown as verified only when its action carries the server's `verified` flag.
 *     "The call returned" is "ran", not "done";
 *   - a confidence is shown only when the server measured one. The rules do not, and that is said.
 */
import type { DeskAction, DeskRun } from '../api/desk'
import { actionExtras } from './deskContract'

type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'accent'

export interface PlanIntent {
  type: string
  /** Null when it was not measured: the rules do not measure confidence. */
  confidence: number | null
  /** Rule names when the rules read it; quotes from the message when a model did. */
  evidence: string[]
  missing: string[]
  source: string | null
}

export interface PlanStep {
  id: string
  tool: string
  purpose: string | null
  dependsOn: string[]
  /** Its content depends on the result of another step, so it is proposed only after that one took effect. */
  deferred: boolean
  requiresApproval: boolean
  /** A mail or calendar write, as opposed to the executive's own records. */
  external: boolean
  expected: string | null
  onFailure: string | null
  state: string
  toolCallId: number | null
}

export interface RunPlanData {
  version: number | null
  planner: string | null
  intents: PlanIntent[]
  /** Intents a model reported without a quote that is in the message. They were dropped. */
  unsupported: { type: string; why: string | null }[]
  facts: string[]
  assumptions: string[]
  missing: string[]
  tools: string[]
  steps: PlanStep[]
  approvals: number | null
  escalation: string[]
}

const record = (value: unknown): Record<string, unknown> | null => (value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null)
const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value : null)
const texts = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim() !== '') : [])
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)

/** The plan of a run, or null when the backend sent none. Malformed entries are left out, never guessed. */
export function planOf(run: unknown): RunPlanData | null {
  const plan = record(record(run)?.plan)
  if (!plan) return null
  const list = (value: unknown) => (Array.isArray(value) ? value.map(record).filter((item): item is Record<string, unknown> => item !== null) : [])
  return {
    version: numberOrNull(plan.version),
    planner: text(plan.planner),
    intents: list(plan.intents)
      .filter(intent => text(intent.type))
      .map(intent => ({ type: text(intent.type)!, confidence: numberOrNull(intent.confidence), evidence: texts(intent.evidence), missing: texts(intent.missing), source: text(intent.source) })),
    unsupported: list(plan.unsupported)
      .filter(intent => text(intent.type))
      .map(intent => ({ type: text(intent.type)!, why: text(intent.why) })),
    facts: texts(plan.facts),
    assumptions: texts(plan.assumptions),
    missing: texts(plan.missing),
    tools: texts(plan.tools),
    steps: list(plan.steps)
      .filter(step => text(step.id) && text(step.tool))
      .map(step => ({
        id: text(step.id)!,
        tool: text(step.tool)!,
        purpose: text(step.purpose),
        dependsOn: texts(step.dependsOn),
        deferred: step.deferred === true,
        // Absent is read as "needs approval": nothing is presented as automatic unless the server says so.
        requiresApproval: step.requiresApproval !== false,
        external: step.external === true,
        expected: text(step.expected),
        onFailure: text(step.onFailure),
        // A step with no state is not known to stand anywhere.
        state: text(step.state) ?? 'unknown',
        toolCallId: numberOrNull(step.toolCallId),
      })),
    approvals: numberOrNull(plan.approvals),
    escalation: texts(plan.escalation),
  }
}

// ── wording ─────────────────────────────────────────────────────────────────

const words = (value: string) => value.replace(/_/g, ' ')

const INTENT: Record<string, string> = {
  new_meeting: 'A new meeting',
  reschedule: 'Move a meeting',
  cancellation: 'Cancel a meeting',
  reply_needed: 'A reply is needed',
  information_request: 'A request for information',
  task: 'A task',
  reminder: 'A reminder',
  follow_up: 'A follow-up',
  fyi: 'For information only',
}

export const intentLabel = (type: string): string => INTENT[type] ?? words(type)

/** Below this a model's reading is not acted on (contract, "Model understanding"). */
export const MIN_CONFIDENCE = 0.6

export function confidenceText(intent: Pick<PlanIntent, 'confidence' | 'source'>): string {
  if (intent.confidence === null) return intent.source === 'rules' ? 'Read by rules, which do not measure confidence' : 'Confidence not measured'
  const percent = `${Math.round(intent.confidence * 100)}%`
  return intent.confidence < MIN_CONFIDENCE ? `Confidence ${percent}: too low to act on` : `Confidence ${percent}`
}

const PLANNER: Record<string, string> = {
  rules: 'Rules only. No model took part.',
  'rules+model': 'Rules, with a model reading the details of the request.',
  'model+rules': 'A model read what is asked; the rules checked and planned each step.',
  'rules+agent': 'Rules, followed by one bounded model step.',
}

export const plannerLabel = (planner: string | null): string => (planner ? PLANNER[planner] ?? `Planner reported: ${planner}.` : 'The planner is not recorded.')

const PURPOSE: Record<string, string> = {
  book: 'Book the meeting',
  reschedule: 'Move the meeting',
  cancel: 'Cancel the meeting',
  confirm: 'Tell the sender what was done',
  offer_times: 'Offer times verified free',
  clarify: 'Ask for the missing detail',
  nudge: 'Send one reminder',
  reply: 'Send the reply',
  record_task: 'Record it in your own records',
}

export const purposeLabel = (step: Pick<PlanStep, 'purpose' | 'tool'>): string => (step.purpose && PURPOSE[step.purpose]) || words(step.purpose ?? step.tool)

const DROPPED: Record<string, string> = {
  evidence_not_in_message: 'the quote given for it is not in the message',
}

export const droppedReason = (why: string | null): string => (why ? DROPPED[why] ?? words(why) : 'no reason recorded')

// ── where a step stands ─────────────────────────────────────────────────────

export type StepStanding = 'waiting' | 'ready' | 'blocked' | 'your_decision' | 'held' | 'running' | 'verified' | 'ran_unverified' | 'verification_failed' | 'outcome_unknown' | 'partly' | 'interrupted' | 'failed' | 'cancelled' | 'unknown'

export interface StepView extends PlanStep {
  standing: StepStanding
  label: string
  tone: Tone
  /** One sentence on what that means for the person. */
  blurb: string
  /** The action card of this step, when it has one and the run carries it. */
  action: DeskAction | null
}

const STANDING: Record<Exclude<StepStanding, 'unknown'>, { label: string; tone: Tone; blurb: string }> = {
  waiting: { label: 'Waits for an earlier step', tone: 'neutral', blurb: 'It is proposed only after the step it depends on has taken effect.' },
  ready: { label: 'Ready to be proposed', tone: 'accent', blurb: 'Every step it depends on took effect. It has not been proposed yet, and proposing it sends nothing.' },
  blocked: { label: 'Blocked: will not be proposed', tone: 'danger', blurb: 'A step it depends on did not take effect, was rejected, or ran and could not be verified. This one is never proposed.' },
  your_decision: { label: 'Awaiting your approval', tone: 'warn', blurb: 'Proposed. Nothing has happened; it runs only if you approve it.' },
  held: { label: 'Held', tone: 'warn', blurb: 'Proposed, and held for a detail or by a safety check. The action card says why.' },
  running: { label: 'Running', tone: 'info', blurb: 'Approved and being carried out.' },
  verified: { label: 'Done and verified', tone: 'ok', blurb: 'It ran and the server has evidence that it took effect.' },
  ran_unverified: { label: 'Ran, not verified', tone: 'warn', blurb: 'The call returned, but there is no evidence yet that it took effect. It is not counted as done.' },
  verification_failed: { label: 'Verification failed', tone: 'danger', blurb: 'The call returned, but the state read back does not show its effect. It is not done, and the steps that depend on it are blocked. Check it yourself.' },
  interrupted: { label: 'Interrupted', tone: 'danger', blurb: 'The process stopped while this was running. The state was read back and the effect is not there. A retry carries the same identity.' },
  outcome_unknown: { label: 'Outcome unknown', tone: 'danger', blurb: 'The provider did not confirm. It may or may not have happened; check before any retry.' },
  partly: { label: 'Partly ran', tone: 'danger', blurb: 'Only part of it took effect. What ran is not undone.' },
  failed: { label: 'Failed', tone: 'danger', blurb: 'It did not take effect.' },
  cancelled: { label: 'Rejected or cancelled', tone: 'neutral', blurb: 'It was not carried out.' },
}

/** The server's explicit action state (overlay 0.3.1), when it sends one this client knows. */
const BY_LIFECYCLE: Record<string, StepStanding> = {
  PROPOSED: 'your_decision',
  HELD: 'held',
  APPROVED: 'running',
  EXECUTING: 'running',
  EXECUTED_UNVERIFIED: 'ran_unverified',
  VERIFIED: 'verified',
  VERIFICATION_FAILED: 'verification_failed',
  PARTIALLY_EXECUTED: 'partly',
  OUTCOME_UNKNOWN: 'outcome_unknown',
  INTERRUPTED: 'interrupted',
  FAILED: 'failed',
  REJECTED: 'cancelled',
}

export function standingOf(state: string, action: DeskAction | null, held: boolean): StepStanding {
  // The server's own state of the action wins over anything worked out from a status.
  const lifecycle = action ? actionExtras(action).lifecycle : null
  if (lifecycle) {
    // "Verified" needs the evidence flag as well as the word.
    if (lifecycle === 'VERIFIED') return action!.verified === true ? 'verified' : 'ran_unverified'
    return BY_LIFECYCLE[lifecycle] ?? 'unknown'
  }
  switch (state) {
    case 'waiting':
    case 'ready':
    case 'blocked':
      return state
    case 'awaiting_approval':
    case 'proposed':
      return held ? 'held' : 'your_decision'
    case 'needs_info':
      return 'held'
    case 'approved':
    case 'executing':
      return 'running'
    case 'executed':
      if (action?.outcomeUnknown) return 'outcome_unknown'
      return action?.verified === true ? 'verified' : 'ran_unverified'
    case 'partially_executed':
      return 'partly'
    case 'failed':
    case 'unsupported':
      return action?.outcomeUnknown ? 'outcome_unknown' : 'failed'
    case 'cancelled':
      return 'cancelled'
    default:
      return 'unknown'
  }
}

/** What the backend adds to an action for the plan. Read as untyped data: the typed client does not declare them yet. */
export function planFieldsOf(action: DeskAction): { stepId: string | null; held: boolean; attempts: number | null } {
  const raw = action as unknown as Record<string, unknown>
  return { stepId: text(raw.stepId), held: raw.held === true, attempts: numberOrNull(raw.attempts) }
}

/** Each step with where it stands, joined to its action card for the evidence. */
export function stepsOf(plan: RunPlanData, actions: DeskAction[]): StepView[] {
  return plan.steps.map(step => {
    const action = (step.toolCallId !== null ? actions.find(candidate => candidate.toolCallId === step.toolCallId) : undefined) ?? actions.find(candidate => planFieldsOf(candidate).stepId === step.id) ?? null
    const standing = standingOf(step.state, action, action ? planFieldsOf(action).held : false)
    const info = standing === 'unknown' ? { label: `State not recognised: ${step.state}`, tone: 'danger' as Tone, blurb: 'This version of the Desk does not know this step state. It is not treated as done.' } : STANDING[standing]
    return { ...step, standing, action, ...info }
  })
}

// ── how far a run has got ──────────────────────────────────────────────────

export type TallyKind = 'verified' | 'unverified' | 'problem' | 'you' | 'running' | 'later' | 'blocked' | 'cancelled'

const TALLY_OF: Record<StepStanding, TallyKind> = {
  verified: 'verified',
  ran_unverified: 'unverified',
  verification_failed: 'problem',
  outcome_unknown: 'problem',
  partly: 'problem',
  interrupted: 'problem',
  failed: 'problem',
  unknown: 'problem',
  your_decision: 'you',
  held: 'you',
  running: 'running',
  waiting: 'later',
  ready: 'later',
  blocked: 'blocked',
  cancelled: 'cancelled',
}

export interface RunTally {
  /** One entry per step (or per action, for a run without a plan), in order. */
  steps: { kind: TallyKind; standing: StepStanding; label: string }[]
  total: number
  counts: Record<TallyKind, number>
  /** "1 of 2 steps verified · 1 awaiting your decision". Says only what the server reported. */
  summary: string
  /** Every step ran and carries verification evidence. The only state drawn as complete. */
  allVerified: boolean
}

const TALLY_WORDS: [TallyKind, (n: number) => string][] = [
  ['unverified', n => `${n} ran, not verified`],
  ['problem', n => `${n} did not finish cleanly`],
  ['running', n => `${n} running`],
  ['you', n => `${n} awaiting your decision`],
  ['later', n => `${n} not proposed yet`],
  ['blocked', n => `${n} blocked`],
  ['cancelled', n => `${n} rejected or cancelled`],
]

/**
 * How far a run has really got, step by step: the plan's steps joined to their action cards, or
 * the action cards alone when the run has no plan. A step counts as verified only on the server's
 * evidence, so "1 of 2 verified" is never rounded up to done and never down to "nothing happened".
 */
export function tallyOf(run: DeskRun): RunTally {
  const plan = planOf(run)
  const seen = new Set<number>()
  const steps: RunTally['steps'] = []
  if (plan) {
    for (const step of stepsOf(plan, run.actions)) {
      if (step.action) seen.add(step.action.toolCallId)
      steps.push({ kind: TALLY_OF[step.standing], standing: step.standing, label: purposeLabel(step) })
    }
  }
  // Actions that belong to no step (a run without a plan, or a card added later) still count.
  const byEffect = new Map<string, DeskAction>()
  for (const action of run.actions) if (!seen.has(action.toolCallId)) byEffect.set(action.idempotencyKey || `tool-call-${action.toolCallId}`, action)
  const planned = new Set(plan ? stepsOf(plan, run.actions).map(step => step.action?.idempotencyKey).filter(Boolean) : [])
  for (const [key, action] of byEffect) {
    if (planned.has(key)) continue
    const standing = standingOf(action.status, action, planFieldsOf(action).held)
    steps.push({ kind: TALLY_OF[standing], standing, label: words(action.purpose ?? action.tool_name) })
  }
  const counts: Record<TallyKind, number> = { verified: 0, unverified: 0, problem: 0, you: 0, running: 0, later: 0, blocked: 0, cancelled: 0 }
  for (const step of steps) counts[step.kind] += 1
  const total = steps.length
  const parts = [`${counts.verified} of ${total} step${total === 1 ? '' : 's'} verified`, ...TALLY_WORDS.filter(([kind]) => counts[kind] > 0).map(([kind, say]) => say(counts[kind]))]
  return { steps, total, counts, summary: total === 0 ? 'No step is planned.' : parts.join(' · '), allVerified: total > 0 && counts.verified === total }
}

/** One line for the head of the plan: how much there is to do and how much of it is the person's to approve. */
export function planSummary(plan: RunPlanData): string {
  const steps = plan.steps.length
  if (steps === 0) return 'No step is planned: the secretary proposes nothing for this message.'
  const approvals = plan.approvals ?? plan.steps.filter(step => step.requiresApproval).length
  return `${steps} step${steps === 1 ? '' : 's'}, ${approvals === steps ? (steps === 1 ? 'which needs' : 'each needing') : `${approvals} needing`} your approval.`
}
