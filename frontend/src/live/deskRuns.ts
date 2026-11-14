/**
 * Desk runs: the administrative work the backend has picked up, one run per incoming message.
 *
 * Everything here is read from the Desk overlay (BACKEND_CONTRACT sections 6 and 7) through the
 * typed client in src/api/desk.ts. Nothing is inferred beyond what a run reports:
 *
 *   - a run's state is the server's; this file only sorts runs into the lists a person works from
 *     and says what the next step is;
 *   - "verified" is the server's flag (the action executed AND Scriba recorded it). It is never
 *     derived from a status here;
 *   - a state or status this file does not know is shown as unrecognised, never as finished.
 *
 * GET /desk/runs lists runs without their state, so the queue reads each listed run once
 * (bounded by RUN_DETAIL_LIMIT). A state on the list row is a backend requirement, recorded in
 * docs/frontend/AGENT2_FRONTEND_STATUS.md.
 */
import {
  fetchDeskRun,
  fetchDeskRuns,
  type CalendarRead,
  type DeskAction,
  type DeskInbox,
  type DeskRun,
  type DeskHeldReason,
  type DeskSweep,
  type RunState,
  type TriageCategory,
  type TriagedEmail,
} from '../api/desk'
import type { MailProvider } from '../api/contract'
import { explainHold } from './deskHolds'
import { HELD_REASON_REVISED, HELD_REASON_V3, LIFECYCLE, LIFECYCLE_REASON, isKnownStage, stageOfRun } from './runLifecycle'
import { tallyOf } from './runPlan'
import { stageOf, type WorkStage } from './workQueue'

// ── the run list ────────────────────────────────────────────────────────────

/**
 * One row of GET /desk/runs as the backend emits it (workflow.list_runs): the run id and the
 * identifying fields of its message. The typed client declares only some of these; the others are
 * read defensively. A compatibility test pins this against the backend source.
 */
export interface RunRow {
  runId: number
  provider: MailProvider | null
  emailId: string | null
  subject: string | null
  fromAddr: string | null
  category: string | null
  createdAt: string | null
  /** Overlay 0.3 puts where the run stands on the row. Null on an older backend. */
  state: string | null
  stage: string | null
  heldReason: string | null
  simulated: boolean
  trigger: string | null
  updatedAt: string | null
  /** Follow-up states on the row, as the server lists them. */
  followUps: string[]
}

const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value : null)

export function toRunRow(raw: unknown): RunRow | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Record<string, unknown>
  const runId = Number(row.runId)
  if (!Number.isInteger(runId)) return null
  const provider = row.provider === 'gmail' || row.provider === 'outlook' ? row.provider : null
  return {
    runId,
    provider,
    emailId: text(row.email_id),
    subject: text(row.subject),
    fromAddr: text(row.from_addr),
    category: text(row.category),
    createdAt: text(row.created_at),
    state: text(row.state),
    stage: text(row.lifecycle),
    heldReason: row.held && typeof row.held === 'object' ? text((row.held as Record<string, unknown>).reason) : null,
    simulated: row.simulated === true,
    trigger: text(row.trigger),
    updatedAt: text(row.updatedAt),
    followUps: Array.isArray(row.followUps) ? row.followUps.map(item => (item && typeof item === 'object' ? text((item as Record<string, unknown>).state) : null)).filter((state): state is string => state !== null) : [],
  }
}

/** How many of the newest runs are read in full. Older runs are listed by subject only. */
export const RUN_DETAIL_LIMIT = 20
const DETAIL_CONCURRENCY = 4

export interface RunEntry {
  row: RunRow
  /** Null when the run could not be read, or when it is beyond RUN_DETAIL_LIMIT. */
  run: DeskRun | null
  /** Why `run` is null, when a read was attempted and failed. */
  error: string | null
}

export interface RunQueue {
  entries: RunEntry[]
  /** Rows the backend listed. */
  listed: number
  /** Runs that were not read in full because of RUN_DETAIL_LIMIT. */
  notRead: number
  /** Runs whose read failed. Their state is unknown, not "nothing to do". */
  failedReads: number
}

async function pooled<T, R>(items: T[], limit: number, work: (item: T) => Promise<R>): Promise<PromiseSettledResult<R>[]> {
  const results: PromiseSettledResult<R>[] = new Array(items.length)
  let next = 0
  const worker = async () => {
    while (next < items.length) {
      const index = next++
      try {
        results[index] = { status: 'fulfilled', value: await work(items[index]) }
      } catch (reason) {
        results[index] = { status: 'rejected', reason }
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return results
}

export async function loadRunQueue(): Promise<RunQueue> {
  // Every run the backend will list: the list also says which action cards are the Desk's (ownership.ts).
  const listing = await fetchDeskRuns(200)
  const rows = (listing?.runs ?? []).map(toRunRow).filter((row): row is RunRow => row !== null)
  const head = rows.slice(0, RUN_DETAIL_LIMIT)
  const details = await pooled(head, DETAIL_CONCURRENCY, row => fetchDeskRun(row.runId))
  const entries: RunEntry[] = rows.map((row, index) => {
    const result = details[index]
    if (!result) return { row, run: null, error: null }
    if (result.status === 'fulfilled') return { row, run: result.value, error: null }
    return { row, run: null, error: result.reason instanceof Error ? result.reason.message : String(result.reason) }
  })
  // Reading none of them is a failure to load the queue, not an empty queue.
  if (head.length > 0 && details.every(result => result.status === 'rejected')) {
    const first = details[0] as PromiseRejectedResult
    throw first.reason instanceof Error ? first.reason : new Error(String(first.reason))
  }
  return {
    entries,
    listed: rows.length,
    notRead: Math.max(0, rows.length - head.length),
    failedReads: details.filter(result => result.status === 'rejected').length,
  }
}

export const RUNS_KEY = ['desk', 'runs'] as const
export const runKey = (runId: number) => ['desk', 'runs', 'detail', runId] as const
export const runToolCallKey = (toolCallId: number) => ['desk', 'runs', 'tool-call', toolCallId] as const

const KNOWN_STATES: readonly RunState[] = ['awaiting_approval', 'executing', 'completed', 'partial', 'failed', 'cancelled', 'no_action_proposed']

export function isKnownState(state: string): state is RunState {
  return (KNOWN_STATES as readonly string[]).includes(state)
}

/** Poll while something is executing; otherwise leave the list alone until asked. */
export function runQueueRefetchInterval(queue: RunQueue | undefined): number | false {
  return queue?.entries.some(entry => entry.run?.state === 'executing' || ['EXECUTING', 'VERIFYING'].includes(String(entry.run ? stageOfRun(entry.run) : entry.row.stage))) ? 4_000 : false
}

// ── where a run sits in the queue ───────────────────────────────────────────

export type QueueGroup = 'decision' | 'input' | 'in_progress' | 'awaiting_reply' | 'problem' | 'unverified' | 'done' | 'no_action' | 'cancelled' | 'unknown'

export const QUEUE_GROUPS: Record<QueueGroup, { label: string; blurb: string; tone: 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'accent' }> = {
  decision: { label: 'Awaiting your approval', blurb: 'The secretary has proposed an action and is waiting for your decision. Nothing has happened yet.', tone: 'warn' },
  input: { label: 'Needs your input', blurb: 'The secretary could not go further on its own: a time is taken or unverified, a detail is missing, or a reply has to be written.', tone: 'warn' },
  in_progress: { label: 'In progress', blurb: 'The secretary is working on it, or an approved action is running.', tone: 'info' },
  awaiting_reply: { label: 'Waiting for a response', blurb: 'A reply went out. The secretary is waiting for the other person and will propose a reminder if none comes.', tone: 'info' },
  problem: { label: 'Did not finish', blurb: 'An action failed, or only part of the work ran.', tone: 'danger' },
  unknown: { label: 'State not recognised', blurb: 'The backend reported a state this version of the Desk does not know. It is not treated as finished.', tone: 'danger' },
  unverified: { label: 'Executed, not verified', blurb: 'The server reports this finished, but an action that ran has no verification evidence. It is not shown as completed: check the result yourself.', tone: 'warn' },
  done: { label: 'Completed and verified', blurb: 'Every proposed action took effect, with verification evidence on record.', tone: 'ok' },
  no_action: { label: 'No action needed', blurb: 'The secretary read the message and found nothing to do.', tone: 'neutral' },
  cancelled: { label: 'Cancelled', blurb: 'Every proposed action was cancelled. Nothing ran.', tone: 'neutral' },
}

/** The order the lists appear in: what needs the person first, finished work last. */
export const QUEUE_ORDER: QueueGroup[] = ['decision', 'input', 'problem', 'unverified', 'unknown', 'in_progress', 'awaiting_reply', 'done', 'no_action', 'cancelled']

/**
 * A finished run is drawn as completed only when every step that ran carries verification
 * evidence. The server's word alone is not evidence.
 */
function finished(run: DeskRun): QueueGroup {
  if (run.actions.length === 0) return 'no_action'
  const tally = tallyOf(run)
  if (tally.counts.problem > 0) return 'problem'
  return tally.counts.unverified > 0 || tally.counts.verified === 0 ? 'unverified' : 'done'
}

const stagesOf = (run: DeskRun): WorkStage[] => run.actions.map(action => stageOf(action.status))

/**
 * Where a run sits when the backend reports its lifecycle stage (overlay 0.3). Null when it does
 * not, so the caller falls back to the run state.
 */
function groupOfStage(run: DeskRun): QueueGroup | null {
  const stage = stageOfRun(run)
  if (stage === null) return null
  if (!isKnownStage(stage)) return 'unknown'
  switch (stage) {
    case 'AWAITING_APPROVAL':
      return stagesOf(run).includes('awaiting_approval') ? 'decision' : 'input'
    case 'NEEDS_CLARIFICATION':
    case 'ESCALATED':
    case 'HELD':
      return 'input'
    case 'VERIFYING':
      // An outcome the provider did not confirm needs a person to look before anything is retried.
      return run.lifecycle?.outcomeUnknown ? 'problem' : 'in_progress'
    case 'PARTIALLY_COMPLETED':
    case 'FAILED':
      return 'problem'
    case 'WAITING_FOR_RESPONSE':
      return 'awaiting_reply'
    case 'COMPLETED':
      return finished(run)
    case 'CANCELLED':
      return 'cancelled'
    default:
      return 'in_progress'
  }
}

export function groupOf(run: DeskRun): QueueGroup {
  const byStage = groupOfStage(run)
  if (byStage) return byStage
  if (!isKnownState(run.state)) return 'unknown'
  switch (run.state) {
    case 'failed':
    case 'partial':
      return 'problem'
    case 'executing':
      return 'in_progress'
    case 'awaiting_approval':
      // Something can be approved as it is; otherwise every open card is held for a detail.
      return stagesOf(run).includes('awaiting_approval') ? 'decision' : 'input'
    case 'completed': {
      // The backend counts a partially executed action as done, so a run can be "completed" while
      // one of its actions only partly ran. That is not shown as finished work.
      const stages = stagesOf(run)
      if (stages.includes('partially_completed') || stages.includes('failed')) return 'problem'
      // The event exists but the confirmation reply has not been proposed yet.
      return run.next.includes('advance') ? 'input' : finished(run)
    }
    case 'no_action_proposed':
      return run.held || run.next.includes('draft_reply') ? 'input' : 'no_action'
    case 'cancelled':
      return 'cancelled'
  }
}

export const CATEGORY_LABEL: Record<TriageCategory, string> = {
  meeting_request: 'Meeting request',
  needs_reply: 'Needs a reply',
  action_item: 'Action item',
  informational: 'For information',
  automated: 'Automated message',
}

export function categoryLabel(category: string | null | undefined): string {
  return (category && CATEGORY_LABEL[category as TriageCategory]) || (category ? category.replace(/_/g, ' ') : 'Not classified')
}

export const RUN_STATE_LABEL: Record<RunState, string> = {
  awaiting_approval: 'Awaiting approval',
  executing: 'Executing',
  completed: 'Completed',
  partial: 'Partly completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  no_action_proposed: 'No action proposed',
}

export const HELD_REASON: Record<DeskHeldReason, { title: string; next: string }> = {
  ...HELD_REASON_V3,
  calendar_conflict: {
    title: 'The requested time is already taken',
    next: 'Offer one of the verified free times in a reply. No event is proposed for the requested time.',
  },
  availability_unknown: {
    title: 'A calendar could not be read, so the requested time is not verified',
    next: 'Reconnect the calendar that failed, or reply without confirming a time. An unread calendar is never treated as free.',
  },
  time_not_understood: {
    title: 'No specific time could be read from the message',
    next: 'Reply offering free times, or ask the sender which time they mean.',
  },
  change_request: {
    title: 'This asks to move or cancel a meeting',
    next: 'Moving and cancelling are not proposed automatically yet. Handle it in the secretary chat.',
  },
  invalid_preferences: {
    title: 'The time zone in your Scriba preferences is not valid',
    next: 'Correct the time zone in Scriba, then check for new work again.',
  },
}

/** The wording for a held reason, including the ones the typed client does not declare yet. Null for a reason this version does not know. */
export function heldReasonInfo(reason: string | null | undefined): { title: string; next: string } | null {
  if (!reason) return null
  return HELD_REASON[reason as DeskHeldReason] ?? HELD_REASON_REVISED[reason] ?? null
}

export interface NextStep {
  /** What the person can do now. `none` means nothing is asked of them. */
  kind: 'approve' | 'complete_card' | 'held' | 'draft_reply' | 'advance' | 'wait' | 'inspect_failure' | 'check_result' | 'none' | 'unknown'
  label: string
  detail: string
}

export function nextStepOf(run: DeskRun): NextStep {
  const group = groupOf(run)
  const stages = stagesOf(run)
  if (group === 'unknown') {
    return { kind: 'unknown', label: `The backend reports "${run.state}"`, detail: 'This version of the Desk does not know that state. Open the actions below to see what Scriba has on record.' }
  }
  const stage = stageOfRun(run)
  if (stage === 'VERIFYING' && run.lifecycle?.outcomeUnknown) {
    return { kind: 'inspect_failure', label: 'Check whether it happened before doing anything else', detail: 'The provider did not confirm an action, so it may or may not have taken effect. Look in the mailbox or calendar first. A retry in a sandbox reads the result back and does not repeat it; on a real provider it asks you to confirm you checked.' }
  }
  if (stage === 'VERIFYING') return { kind: 'wait', label: 'Nothing: the result is being verified', detail: 'An action ran and the secretary is confirming that it took effect.' }
  if (stage === 'WAITING_FOR_RESPONSE') {
    const overdue = (run.followUps ?? []).some(followUp => followUp.state === 'overdue')
    return overdue
      ? { kind: 'approve', label: 'A reply is overdue: review the proposed reminder', detail: 'No answer came in two days. A reminder is proposed below; it is not sent unless you approve it.' }
      : { kind: 'wait', label: 'Nothing: waiting for the other person to answer', detail: 'A reply went out. If no answer arrives in two days, a reminder is proposed for your approval.' }
  }
  if (stage === 'HELD') {
    const reason = run.lifecycle?.reason
    const known = explainHold(reason)
    return {
      kind: 'complete_card',
      label: known?.title ?? 'Every proposed action is held by a safety check',
      detail: `${known ? '' : reason ? `Reason reported: ${reason.replace(/_/g, ' ')}. ` : ''}The action card says what can be done. Nothing can be approved as it stands.`,
    }
  }
  if (stage === 'NEEDS_CLARIFICATION' || stage === 'ESCALATED') {
    const held = heldReasonInfo(run.held?.reason)
    if (held) return { kind: 'held', label: held.title, detail: held.next }
    if (run.next.includes('draft_reply')) return { kind: 'draft_reply', label: 'Write a reply draft', detail: 'The message needs a reply. A draft is stored in Scriba for you to review; nothing is sent.' }
    return { kind: 'held', label: LIFECYCLE[stage].label, detail: (run.lifecycle?.reason && (LIFECYCLE_REASON[run.lifecycle.reason] ?? `Reason reported: ${run.lifecycle.reason.replace(/_/g, ' ')}.`)) || LIFECYCLE[stage].blurb }
  }
  if (group === 'decision') {
    const waiting = stages.filter(stage => stage === 'awaiting_approval').length
    // An earlier step of the same run may already have run: "nothing has changed" would then be false.
    const ran = stages.filter(stage => stage === 'completed' || stage === 'partially_completed').length
    const where = run.simulated ? ' in the sandbox' : ''
    return {
      kind: 'approve',
      label: ran > 0 ? (waiting === 1 ? 'Review the next step and decide' : `Review the next ${waiting} steps and decide`) : waiting === 1 ? 'Review the proposed action and decide' : `Review ${waiting} proposed actions and decide`,
      detail: ran > 0 ? `${tallyOf(run).summary}. ${ran === 1 ? 'One earlier step has' : `${ran} earlier steps have`} already been executed${where}. What is waiting now runs only if you approve it.` : `Nothing has been ${run.simulated ? 'executed' : 'sent or changed'}. Each action runs only if you approve it${run.simulated ? ', and then only in the sandbox' : ''}.`,
    }
  }
  if (run.state === 'awaiting_approval') {
    return { kind: 'complete_card', label: 'A proposed action is held for a detail', detail: 'A safety check or a missing field stopped it. The action card says which.' }
  }
  if (run.state === 'completed' && run.next.includes('advance')) {
    return { kind: 'advance', label: 'Propose the confirmation reply', detail: 'The calendar event exists. The reply to the sender has not been proposed yet; proposing it sends nothing until you approve it.' }
  }
  if (run.state === 'no_action_proposed' && run.held) {
    const held = heldReasonInfo(run.held.reason)
    return { kind: 'held', label: held?.title ?? 'The meeting request is held', detail: held?.next ?? run.held.message }
  }
  if (run.state === 'no_action_proposed' && run.next.includes('draft_reply')) {
    return { kind: 'draft_reply', label: 'Write a reply draft', detail: 'The message needs a reply. A draft is stored in Scriba for you to review; nothing is sent.' }
  }
  if (group === 'in_progress') return { kind: 'wait', label: stage && stage !== 'EXECUTING' ? 'Nothing: the secretary is working on it' : 'Nothing: an approved action is running', detail: 'This page reads the status again every few seconds.' }
  if (group === 'problem') {
    return {
      kind: 'inspect_failure',
      label: run.state === 'failed' ? 'Look at what failed' : 'Check what ran and what did not',
      detail: 'What succeeded is real and is not undone. A retry on an action card runs immediately, without a second approval.',
    }
  }
  if (group === 'done' || group === 'unverified') {
    const executed = run.actions.filter(action => stageOf(action.status) === 'completed')
    const unverified = executed.filter(action => !action.verified)
    return unverified.length > 0
      ? { kind: 'check_result', label: 'Check the result yourself', detail: `${unverified.length === executed.length ? 'The action ran' : 'Part of the work ran'}, but there is no verification evidence that it took effect.` }
      : { kind: 'none', label: 'Nothing', detail: run.simulated ? 'Every action was executed in the sandbox and read back there. Nothing real was sent or changed.' : 'Every action ran and its effect was verified.' }
  }
  if (group === 'cancelled') return { kind: 'none', label: 'Nothing', detail: 'The proposed actions were cancelled. Nothing was sent or changed.' }
  return { kind: 'none', label: 'Nothing', detail: 'The message was read and needs no action.' }
}

/** One line for the queue: what the run is proposing or why it stopped. */
export function runHeadline(run: DeskRun): string {
  if (run.actions.length > 0) return run.actions.map(action => ACTION_LABEL[action.tool_name] ?? action.tool_name.replace(/_/g, ' ')).join(', then ')
  if (run.held) return heldReasonInfo(run.held.reason)?.title ?? run.held.message
  if (run.next.includes('draft_reply')) return 'Needs a reply; no draft written yet'
  return 'Nothing to do'
}

export const ACTION_LABEL: Record<string, string> = {
  create_task: 'Record a task',
  create_reminder: 'Set a reminder',
  create_calendar_event: 'Create a calendar event',
  update_calendar_event: 'Move a calendar event',
  cancel_calendar_event: 'Cancel a calendar event',
  send_email: 'Send an email',
  draft_email_reply: 'Draft a reply',
}

// ── the timeline of one run ─────────────────────────────────────────────────

export type StepState = 'done' | 'current' | 'held' | 'failed' | 'not_needed' | 'upcoming'

export interface TimelineStep {
  id: 'received' | 'classified' | 'context' | 'proposed' | 'approval' | 'execution' | 'verified'
  label: string
  state: StepState
  detail: string
  /** Where the fact comes from, shown as the tool or service used. */
  source: string
}

const unreadable = (calendars: CalendarRead[] | undefined) => (calendars ?? []).filter(calendar => !calendar.ok)

/**
 * The stages of a run that the backend actually reports. "Reading context" appears only for a
 * meeting request whose calendar reads are on the run. There is no separate "verifying" stage:
 * the backend reports verification as a fact on an executed action, so it is shown as one.
 */
export function timelineOf(run: DeskRun): TimelineStep[] {
  const stages = stagesOf(run)
  const steps: TimelineStep[] = []
  const has = (stage: WorkStage) => stages.includes(stage)

  steps.push({
    id: 'received',
    label: 'Picked up',
    state: 'done',
    detail: `From ${run.email.from_addr || 'an unknown sender'}, in ${run.email.provider === 'outlook' ? 'Outlook' : 'Gmail'}.`,
    source: 'POST /desk/intake',
  })
  steps.push({
    id: 'classified',
    label: 'Classified',
    state: 'done',
    detail: `${categoryLabel(run.category)}. Classification is rule-based on the subject and preview; no model reads the message here.`,
    source: 'Desk triage',
  })

  const calendars = run.held?.calendars ?? run.actions.flatMap(action => action.availability?.calendars ?? [])
  if (run.category === 'meeting_request' && (calendars.length > 0 || run.held)) {
    const failed = unreadable(calendars)
    steps.push({
      id: 'context',
      label: 'Calendars read',
      state: failed.length > 0 || run.held?.reason === 'availability_unknown' ? 'held' : 'done',
      detail:
        calendars.length === 0
          ? 'No calendar read is recorded on this run.'
          : failed.length > 0
            ? `${failed.length} of ${calendars.length} calendar${calendars.length === 1 ? '' : 's'} could not be read. An unread calendar is unknown, not free.`
            : `${calendars.length} calendar${calendars.length === 1 ? '' : 's'} read.`,
      source: 'Google and Outlook calendars',
    })
  }

  if (run.actions.length > 0) {
    steps.push({ id: 'proposed', label: 'Actions proposed', state: 'done', detail: runHeadline(run), source: 'Scriba action cards' })
  } else if (run.held) {
    steps.push({ id: 'proposed', label: 'Nothing proposed', state: 'held', detail: run.held.message, source: 'Desk booking rules' })
  } else if (run.next.includes('draft_reply')) {
    steps.push({ id: 'proposed', label: 'Reply needed', state: 'current', detail: 'No action card is proposed. A reply draft can be written for review.', source: 'Desk triage' })
  } else {
    steps.push({ id: 'proposed', label: 'No action needed', state: 'not_needed', detail: 'The message is informational or automated.', source: 'Desk triage' })
  }

  if (run.actions.length === 0) return steps

  const open = has('awaiting_approval') || has('needs_info') || has('planning')
  const allCancelled = stages.every(stage => stage === 'cancelled' || stage === 'unsupported')
  steps.push({
    id: 'approval',
    label: 'Approval',
    state: open ? (has('awaiting_approval') ? 'current' : 'held') : allCancelled ? 'not_needed' : 'done',
    detail: open
      ? has('awaiting_approval')
        ? 'Waiting for your decision.'
        : 'Held: a proposed action needs a detail before it can be approved.'
      : allCancelled
        ? 'Every proposed action was cancelled.'
        : 'Decided through Scriba.',
    source: 'POST /chat/tool-calls/{id}/approve',
  })

  const executed = run.actions.filter(action => stageOf(action.status) === 'completed')
  const problems = run.actions.filter(action => ['failed', 'partially_completed'].includes(stageOf(action.status)))
  steps.push({
    id: 'execution',
    label: 'Execution',
    state: has('executing') ? 'current' : problems.length > 0 ? 'failed' : executed.length > 0 ? 'done' : allCancelled ? 'not_needed' : 'upcoming',
    detail: has('executing')
      ? 'An approved action is running.'
      : problems.length > 0
        ? `${executed.length} ran, ${problems.length} did not finish, ${run.actions.length - executed.length - problems.length} not run.`
        : executed.length > 0
          ? `${executed.length} of ${run.actions.length} action${run.actions.length === 1 ? '' : 's'} ran.`
          : allCancelled
            ? 'Nothing ran.'
            : 'Nothing has run yet.',
    source: "Scriba's action engine",
  })

  const verified = executed.filter(action => action.verified)
  steps.push({
    id: 'verified',
    label: 'Verified',
    state: executed.length === 0 ? (allCancelled ? 'not_needed' : 'upcoming') : verified.length === executed.length ? 'done' : 'held',
    detail:
      executed.length === 0
        ? 'Nothing to verify yet.'
        : verified.length === executed.length
          ? `Scriba recorded ${verified.length === 1 ? 'the action' : `all ${verified.length} actions`} (${verified.map(action => `#${action.assistantActionId}`).join(', ')}).`
          : `${executed.length - verified.length} executed action${executed.length - verified.length === 1 ? ' has' : 's have'} no record in Scriba. Not counted as verified.`,
    source: "Scriba's action records",
  })
  return steps
}

/** What ran, what failed and what was never attempted, for a run that did not finish cleanly. */
export function partialBreakdown(run: DeskRun): { ran: DeskAction[]; failed: DeskAction[]; notRun: DeskAction[] } {
  const ran: DeskAction[] = []
  const failed: DeskAction[] = []
  const notRun: DeskAction[] = []
  for (const action of run.actions) {
    const stage = stageOf(action.status)
    if (stage === 'completed') ran.push(action)
    else if (stage === 'failed' || stage === 'partially_completed') failed.push(action)
    else notRun.push(action)
  }
  return { ran, failed, notRun }
}

// ── mail that has arrived but has no run yet ────────────────────────────────

/** The categories a sweep opens a run for (workflow.SWEEP_CATEGORIES). */
export const INTAKE_CATEGORIES: readonly TriageCategory[] = ['meeting_request', 'action_item', 'needs_reply']

/**
 * Inbox messages that need a run and have none among the listed runs. The run list has no account
 * field, so a message is matched by provider and id.
 */
export function unstartedMail(inbox: DeskInbox | undefined, rows: RunRow[]): TriagedEmail[] {
  if (!inbox) return []
  const started = new Set(rows.filter(row => row.provider && row.emailId).map(row => `${row.provider}:${row.emailId}`))
  return inbox.items.filter(item => INTAKE_CATEGORIES.includes(item.triage?.category) && !started.has(`${item.provider}:${item.id}`))
}

// ── what a sweep did ────────────────────────────────────────────────────────

export interface SweepLine {
  id: 'examined' | 'opened' | 'existing' | 'skipped' | 'deferred' | 'failed'
  label: string
  count: number
  note: string
}

export function sweepLines(sweep: DeskSweep): SweepLine[] {
  return [
    { id: 'examined', label: 'Messages examined', count: sweep.examined, note: 'The recent inbox, newest first.' },
    { id: 'opened', label: 'New runs opened', count: sweep.opened.length, note: 'Each one proposes actions for approval. Nothing was sent or written.' },
    { id: 'existing', label: 'Already had a run', count: sweep.existing, note: 'Left alone: a message gets one run.' },
    { id: 'skipped', label: 'Need no run', count: sweep.skipped, note: 'Informational and automated mail.' },
    { id: 'deferred', label: 'Left for the next check', count: sweep.deferred.length, note: 'A check opens a limited number of runs. Check again to take these.' },
    { id: 'failed', label: 'Could not be processed', count: sweep.failed.length, note: 'They are tried again by the next check.' },
  ]
}

/** Mailboxes the sweep could not read. Mail from them may be missing from the count. */
export function sweepGaps(sweep: DeskSweep): string[] {
  if (sweep.complete) return []
  const failed = (sweep.sources ?? []).filter(source => !source.ok && source.state === 'connected')
  if (failed.length === 0) return ['A connected mailbox could not be read, so some mail may be missing from this check.']
  return failed.map(source => `${source.provider === 'outlook' ? 'Outlook' : 'Gmail'} could not be read (${source.error ?? 'provider error'}), so its mail was not examined.`)
}
