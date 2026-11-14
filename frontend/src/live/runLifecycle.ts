/**
 * The run lifecycle of Desk overlay 0.3, as the screens present it.
 *
 * Overlay 0.3 reports where a run stands (`lifecycle.stage`), a timeline of recorded events with
 * their times, the evidence on each action (decisions, execution, verification) and the run's
 * follow-ups. This file turns those into what a person reads. It adds nothing of its own:
 *
 *   - a stage is the server's. A stage this file does not know is shown as unrecognised and is
 *     never treated as finished;
 *   - a time on the progress rail is a time the server recorded. A stage with no recorded event
 *     has no time, and is not marked reached unless the run has moved past it;
 *   - "verified" is the server's flag with its method. It is never inferred from a status;
 *   - on an overlay older than 0.3 a run has no lifecycle. `stageOfRun` then returns null and the
 *     screens fall back to the run state (deskRuns.ts).
 */
import type {
  DeskAction,
  DeskFollowUp,
  DeskHeldReason,
  DeskLifecycleStage,
  DeskRun,
  DeskTimelineItem,
  DeskWorkerStatus,
} from '../api/desk'

type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'accent'

/** Who has the next move. */
export type Holder = 'you' | 'secretary' | 'other_party' | 'nobody'

export interface StageInfo {
  /** The name shown to the user. */
  label: string
  tone: Tone
  holder: Holder
  /** One sentence: what this stage means for the person reading it. */
  blurb: string
}

/**
 * The stages the backend sends (BACKEND_CONTRACT section 6, `DeskRunStage` in the reconciled
 * client). These are the canonical names: the screens work in them and show them. The typed
 * client on `main` still declares three names from a first draft that were never sent; they are
 * accepted as aliases (STAGE_ALIASES) and never shown.
 */
export type RunStage =
  | 'RECEIVED'
  | 'UNDERSTANDING'
  | 'INVESTIGATING'
  | 'PLANNING'
  | 'AWAITING_APPROVAL'
  | 'HELD'
  | 'EXECUTING'
  | 'VERIFYING'
  | 'COMPLETED'
  | 'WAITING_FOR_RESPONSE'
  | 'NEEDS_CLARIFICATION'
  | 'ESCALATED'
  | 'PARTIALLY_COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export const LIFECYCLE: Record<RunStage, StageInfo> = {
  RECEIVED: { label: 'Incoming', tone: 'neutral', holder: 'secretary', blurb: 'The message has been picked up.' },
  UNDERSTANDING: { label: 'Understanding', tone: 'accent', holder: 'secretary', blurb: 'The secretary has worked out what kind of request this is.' },
  INVESTIGATING: { label: 'Investigating', tone: 'info', holder: 'secretary', blurb: 'The thread, calendars and tasks that bear on it are being read.' },
  PLANNING: { label: 'Planning', tone: 'info', holder: 'secretary', blurb: 'The secretary is deciding what to propose.' },
  AWAITING_APPROVAL: { label: 'Awaiting approval', tone: 'warn', holder: 'you', blurb: 'An action is proposed and waits for your decision. It does not run unless you approve it.' },
  HELD: { label: 'Held', tone: 'warn', holder: 'you', blurb: 'Every proposed action is held by a safety check, so nothing can be approved as it stands. The action card says why.' },
  EXECUTING: { label: 'Executing', tone: 'info', holder: 'secretary', blurb: 'An approved action is running, or the next step is about to be proposed.' },
  VERIFYING: { label: 'Verifying', tone: 'info', holder: 'secretary', blurb: 'An action ran and its result is not confirmed yet.' },
  COMPLETED: { label: 'Completed', tone: 'ok', holder: 'nobody', blurb: 'The server reports that everything proposed took effect and was verified, or that nothing was needed.' },
  WAITING_FOR_RESPONSE: { label: 'Waiting for a response', tone: 'info', holder: 'other_party', blurb: 'A reply went out and the other person has not answered yet.' },
  NEEDS_CLARIFICATION: { label: 'Needs clarification', tone: 'warn', holder: 'you', blurb: 'The request cannot be acted on as written, and nothing could be proposed.' },
  ESCALATED: { label: 'Escalated to you', tone: 'warn', holder: 'you', blurb: 'The secretary handed this to you and proposes nothing itself.' },
  PARTIALLY_COMPLETED: { label: 'Partially completed', tone: 'danger', holder: 'you', blurb: 'Some actions took effect and some did not. What ran is not undone.' },
  FAILED: { label: 'Failed', tone: 'danger', holder: 'you', blurb: 'An action failed.' },
  CANCELLED: { label: 'Cancelled', tone: 'neutral', holder: 'nobody', blurb: 'The proposed actions were cancelled. Nothing ran.' },
}

/**
 * First-draft names that the typed client on `main` still declares. No backend sends them; they
 * are mapped to the canonical names so that code and fixtures written against them keep working.
 */
export const STAGE_ALIASES: Record<string, RunStage> = {
  CLASSIFIED: 'UNDERSTANDING',
  CONTEXT_GATHERING: 'INVESTIGATING',
  AWAITING_REPLY: 'WAITING_FOR_RESPONSE',
}

export const HELD_STAGE: StageInfo = LIFECYCLE.HELD

/** The backend's own name for a stage, whichever spelling arrived. */
export const canonicalStage = (stage: string): string => STAGE_ALIASES[stage] ?? stage

export const UNKNOWN_STAGE: StageInfo = {
  label: 'Stage not recognised',
  tone: 'danger',
  holder: 'you',
  blurb: 'The backend reported a stage this version of the Desk does not know. It is not treated as finished.',
}

export const isKnownStage = (stage: unknown): stage is RunStage => typeof stage === 'string' && Object.prototype.hasOwnProperty.call(LIFECYCLE, stage)

/**
 * The stage the server reports for a run or a list row. Null when the backend reports none
 * (an overlay before 0.3). A string that is not a known stage is returned as it is, so the caller
 * can show it as unrecognised.
 */
export function stageOfRun(run: { lifecycle?: DeskRun['lifecycle'] | DeskLifecycleStage | string | null }): RunStage | string | null {
  const lifecycle = run.lifecycle
  if (!lifecycle) return null
  const stage = typeof lifecycle === 'string' ? lifecycle : lifecycle.stage
  return typeof stage === 'string' && stage ? canonicalStage(stage) : null
}

export function stageInfo(stage: string | null): StageInfo | null {
  if (stage === null) return null
  const canonical = canonicalStage(stage)
  return isKnownStage(canonical) ? LIFECYCLE[canonical] : UNKNOWN_STAGE
}

// ── the progress rail ───────────────────────────────────────────────────────

/** The path a run follows when nothing stops it. */
export const PROGRESS_PATH: RunStage[] = ['RECEIVED', 'UNDERSTANDING', 'INVESTIGATING', 'PLANNING', 'AWAITING_APPROVAL', 'EXECUTING', 'VERIFYING', 'COMPLETED']

/** Stages a run can rest in that are not on that path. */
const OFF_PATH: RunStage[] = ['HELD', 'WAITING_FOR_RESPONSE', 'NEEDS_CLARIFICATION', 'ESCALATED', 'PARTIALLY_COMPLETED', 'FAILED', 'CANCELLED']

export type ProgressState = 'reached' | 'current' | 'skipped' | 'upcoming'

export interface ProgressStep {
  stage: RunStage | string
  label: string
  state: ProgressState
  /** When the server recorded it. Null when no event was recorded for this stage. */
  at: string | null
  tone: Tone
}

/** The first recorded time of each stage. Only events the server wrote count. */
export function stageTimes(timeline: DeskTimelineItem[] | undefined): Map<string, string> {
  const times = new Map<string, string>()
  const note = (stage: string, at: string) => {
    if (!times.has(stage)) times.set(stage, at)
  }
  for (const item of timeline ?? []) {
    if (item.kind === 'stage' && typeof item.data?.stage === 'string') note(canonicalStage(item.data.stage), item.at)
    // The later stages are recorded as evidence, not as stage events.
    if (item.kind === 'proposal') note('AWAITING_APPROVAL', item.at)
    if (item.kind === 'execution') note('EXECUTING', item.at)
    if (item.kind === 'verification') note('VERIFYING', item.at)
  }
  return times
}

/**
 * The rail for one run: the path up to where it stands, then either the rest of the path or the
 * off-path stage it rests in. Null when the backend reports no lifecycle.
 */
export function progressOf(run: Pick<DeskRun, 'lifecycle' | 'timeline' | 'updatedAt'>): ProgressStep[] | null {
  const stage = stageOfRun(run)
  if (stage === null) return null
  const times = stageTimes(run.timeline)
  const onPath = PROGRESS_PATH.indexOf(stage as RunStage)
  const step = (s: RunStage, state: ProgressState): ProgressStep => ({ stage: s, label: LIFECYCLE[s].label, state, at: times.get(s) ?? null, tone: LIFECYCLE[s].tone })

  if (onPath >= 0) {
    return PROGRESS_PATH.map((s, index) => {
      if (index === onPath) return { ...step(s, 'current'), at: times.get(s) ?? (LIFECYCLE[s].holder === 'nobody' ? run.updatedAt ?? null : null) }
      if (index > onPath) return step(s, 'upcoming')
      // Behind the current stage: reached when the server recorded it, otherwise passed over.
      return step(s, times.has(s) ? 'reached' : 'skipped')
    })
  }

  // Resting off the path (or in a stage this version does not know): show what was recorded, then where it stopped.
  const behind = PROGRESS_PATH.filter(s => times.has(s)).map(s => step(s, 'reached'))
  const info = stageInfo(stage)!
  const known = (OFF_PATH as string[]).includes(stage)
  return [...behind, { stage, label: known ? info.label : `${info.label}: ${stage}`, state: 'current', at: run.updatedAt ?? null, tone: info.tone }]
}

/**
 * What `lifecycle.reason` means, for the reasons that need saying in a sentence. A reason not
 * listed is shown as reported.
 */
export const LIFECYCLE_REASON: Record<string, string> = {
  verification_failed: 'An action ran, but reading the mailbox or calendar back did not show its effect. It is not counted as done: check it yourself.',
  not_yet_verified: 'An action ran and there is no evidence yet that it took effect.',
  next_step_pending: 'A step took effect and the next one is about to be proposed.',
  proposal_changed: 'The stored action is no longer what was proposed, and no edit of yours is on record. It cannot be approved as it is.',
  external_writes_disabled: 'Sending mail and changing calendars are switched off on this backend, so the proposed action cannot run.',
  reply_needs_author: 'The message needs a reply that only you can write. The secretary proposes none by itself.',
  untrusted_instructions: 'The message contains text addressed to an assistant, so nothing was proposed from it.',
  unresolved_requests: 'The message asked for more than one thing and not every request could be acted on. What is left is listed below; the run is not complete until you take it over.',
}

// ── held reasons added by overlay 0.3 ───────────────────────────────────────

export const HELD_REASON_V3: Record<Exclude<DeskHeldReason, 'calendar_conflict' | 'availability_unknown' | 'time_not_understood' | 'change_request' | 'invalid_preferences'>, { title: string; next: string }> = {
  event_not_found: { title: 'No meeting with this sender could be found to change', next: 'Ask the sender which meeting they mean, or change it yourself in the calendar.' },
  event_ambiguous: { title: 'More than one meeting matches this request', next: 'Decide which meeting is meant. The candidates are listed below; nothing is changed until you say.' },
  not_organizer: { title: 'You are not the organizer of that meeting', next: 'Only the organizer can move or cancel it. Reply to the sender or to the organizer.' },
  calendar_lookup_failed: { title: 'The calendar could not be searched for the meeting', next: 'Reconnect the calendar, then check for new work again. An unread calendar is never treated as empty.' },
  already_scheduled: { title: 'This meeting is already on the calendar at that time', next: 'Nothing: the same request came in again and no second event was created.' },
  task_exists: { title: 'An open task with this title already exists', next: 'Nothing: no second task was proposed.' },
  untrusted_instructions: { title: 'The message contains text addressed to the assistant', next: 'Read it yourself before acting. The secretary proposed nothing and the text was not passed to a model.' },
}

/**
 * Reasons the revised contract adds (0282558) that the typed client does not declare yet. They
 * are sent in `held.reason` when a model reads the message (`DESK_UNDERSTANDING=model`).
 */
export const HELD_REASON_REVISED: Record<string, { title: string; next: string }> = {
  intent_unclear: { title: 'It is not clear enough what this message asks for', next: 'Read the message and decide. Nothing was proposed, because acting on an unclear reading would be a guess.' },
  details_missing: { title: 'A detail needed to act is not in the message', next: 'Ask the sender for the missing detail, or handle it yourself. Nothing was filled in for you.' },
}

// ── evidence ────────────────────────────────────────────────────────────────

/** `plan` is sent by the backend from 0282558; the typed client does not declare it yet. */
export const EVIDENCE_KIND: Record<DeskTimelineItem['kind'] | 'plan', { label: string; tone: Tone }> = {
  plan: { label: 'Plan', tone: 'accent' },
  stage: { label: 'Stage', tone: 'neutral' },
  decision: { label: 'Secretary decided', tone: 'accent' },
  read: { label: 'Read', tone: 'info' },
  proposal: { label: 'Proposed', tone: 'warn' },
  approval: { label: 'Approval', tone: 'warn' },
  execution: { label: 'Executed', tone: 'info' },
  verification: { label: 'Verified', tone: 'ok' },
  human: { label: 'You decided', tone: 'accent' },
  followup: { label: 'Follow-up', tone: 'info' },
  usage: { label: 'Model usage', tone: 'neutral' },
  error: { label: 'Error', tone: 'danger' },
}

export interface VerificationView {
  state: 'verified' | 'pending' | 'failed' | 'unknown_outcome' | 'not_applicable'
  label: string
  detail: string
}

const METHOD: Record<string, string> = {
  sandbox_readback: 'the sandbox world was read back and the effect is there (simulated: no real mailbox or calendar was involved)',
  scriba_action_record: "Scriba's own record of the executed action",
  user_confirmed: 'you confirmed it',
}

/** What can be said about whether an action really took effect. */
export function verificationOf(action: DeskAction): VerificationView {
  if (action.outcomeUnknown) {
    return { state: 'unknown_outcome', label: 'Outcome unknown', detail: 'The provider did not confirm. This may or may not have happened. Check the mailbox or calendar before retrying.' }
  }
  // The state was read back and does not show the effect: said in its own words, never "pending".
  if ((action as unknown as { lifecycle?: unknown }).lifecycle === 'VERIFICATION_FAILED') {
    return { state: 'failed', label: 'Verification failed', detail: action.verification?.reason ?? 'The call returned, but the mailbox or calendar read back does not show its effect. It is not counted as done. Check it yourself; the steps that depend on it are blocked.' }
  }
  if (action.verified) {
    const method = action.verification?.method ? METHOD[action.verification.method] ?? action.verification.method : action.assistantActionId ? `Scriba action record #${action.assistantActionId}` : 'the server reports it verified'
    return { state: 'verified', label: action.verification?.reconciled ? 'Verified (already done; not repeated)' : 'Verified', detail: `Evidence: ${method}.` }
  }
  const ran = action.status === 'executed' || action.status === 'partially_executed' || action.execution?.status === 'executed' || action.execution?.status === 'partially_executed'
  if (ran) {
    return { state: 'pending', label: 'Not verified', detail: action.verification?.reason ?? 'It ran, but there is no evidence yet that it took effect.' }
  }
  return { state: 'not_applicable', label: 'Nothing to verify yet', detail: 'This action has not run.' }
}

/**
 * Actions grouped by the real-world effect they stand for. Overlay 0.3 gives each effect one
 * `idempotencyKey`, and a retry reuses it, so two cards with the same key are one effect and are
 * shown once with a count, never as two sends. Actions without a key are each their own effect.
 */
export function effectsOf(actions: DeskAction[]): { key: string; primary: DeskAction; duplicates: DeskAction[] }[] {
  const groups = new Map<string, DeskAction[]>()
  for (const action of actions) {
    const key = action.idempotencyKey || `tool-call-${action.toolCallId}`
    groups.set(key, [...(groups.get(key) ?? []), action])
  }
  // The newest card of an effect is the one that says where it stands.
  return [...groups.entries()].map(([key, group]) => ({ key, primary: group[group.length - 1], duplicates: group.slice(0, -1) }))
}

// ── follow-ups ──────────────────────────────────────────────────────────────

export const FOLLOW_UP_STATE: Record<DeskFollowUp['state'], { label: string; tone: Tone; blurb: string }> = {
  waiting: { label: 'Waiting for a reply', tone: 'info', blurb: 'The reply went out and no answer has arrived.' },
  overdue: { label: 'Overdue', tone: 'danger', blurb: 'No answer after two days. A reminder is proposed for your approval; it has not been sent.' },
  satisfied: { label: 'Answered', tone: 'ok', blurb: 'A message from that person arrived in the thread.' },
  closed: { label: 'Closed by you', tone: 'neutral', blurb: 'You closed this follow-up.' },
}

export const FOLLOW_UP_ORDER: DeskFollowUp['state'][] = ['overdue', 'waiting', 'satisfied', 'closed']

/** States added after the typed client was written (overlay 0.4). */
const FOLLOW_UP_STATE_REVISED: Record<string, { label: string; tone: Tone; blurb: string }> = {
  escalated: { label: 'Reminded once, still no answer', tone: 'danger', blurb: 'One reminder went out and no answer came. The secretary never sends a second one: this is yours now.' },
}

export function followUpInfo(state: string): { label: string; tone: Tone; blurb: string } {
  return FOLLOW_UP_STATE[state as DeskFollowUp['state']] ?? FOLLOW_UP_STATE_REVISED[state] ?? { label: `State not recognised: ${state}`, tone: 'danger', blurb: 'This version of the Desk does not know this follow-up state. It is not treated as answered.' }
}

// ── the worker ──────────────────────────────────────────────────────────────

const WORKER_OFF: Record<string, string> = {
  not_requested: 'It was not switched on for this backend.',
  refused_production: 'It refuses to start in a production process.',
  no_users: 'No user is enrolled for it.',
  stopped: 'It was stopped.',
  not_installed: 'This backend does not have it.',
}

const WORKER_YOU: Record<string, { text: string; tone: Tone }> = {
  ok: { text: 'Your mail is being picked up.', tone: 'ok' },
  backpressure: { text: 'Paused for you: enough requests already wait for your decision.', tone: 'warn' },
  rate_limited: { text: 'Paused for you: the hourly limit was reached.', tone: 'warn' },
  mailbox_unreadable: { text: 'A connected mailbox could not be read. What was readable was handled.', tone: 'danger' },
  backing_off: { text: 'Skipped the last pass for you after a failure. It will try again.', tone: 'warn' },
  failed: { text: 'The last pass for you failed.', tone: 'danger' },
  sweep_in_progress: { text: 'A check you started is still running.', tone: 'info' },
}

export interface WorkerView {
  running: boolean
  tone: Tone
  headline: string
  detail: string
}

/** What to say about background intake. Only what the server reports. */
export function workerView(worker: DeskWorkerStatus | null | undefined): WorkerView {
  if (!worker) return { running: false, tone: 'neutral', headline: 'Background intake status is not available', detail: 'This backend does not report a worker. New mail is picked up when you check for new work.' }
  if (!worker.running) {
    const why = worker.reason ? WORKER_OFF[worker.reason] ?? `Reason reported: ${worker.reason}.` : ''
    return { running: false, tone: 'neutral', headline: 'Background intake is off', detail: `${why} New mail is picked up when you check for new work.`.trim() }
  }
  const you = worker.you
  if (you && !you.served) return { running: true, tone: 'warn', headline: 'Background intake is running, but not for your account', detail: 'Your mail is picked up when you check for new work.' }
  const status = you?.lastStatus ? WORKER_YOU[you.lastStatus] ?? { text: `Last status reported: ${you.lastStatus}.`, tone: 'warn' as Tone } : { text: 'It has not made a pass for you yet.', tone: 'info' as Tone }
  const every = worker.intervalSeconds ? ` It looks every ${worker.intervalSeconds} seconds and only proposes: it never sends or approves.` : ' It only proposes: it never sends or approves.'
  return { running: true, tone: status.tone, headline: 'Background intake is running', detail: `${status.text}${every}` }
}
