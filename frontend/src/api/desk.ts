/**
 * Typed client for the Desk overlay routes (`/desk/*`).
 *
 * These routes exist only when the Scriba backend is started with the Desk
 * overlay (see backend/README.md). They are read-only. Shapes mirror
 * backend/desk_overlay/routes.py; the tests in backend/tests pin them.
 */
import { getJson, postJson } from './client'
import type { EmailItem, MailProvider } from './contract'

export type CapabilityId = 'gmail' | 'google_calendar' | 'outlook_mail' | 'outlook_calendar'
export type ConnectionState = 'connected' | 'reconnect_required' | 'disconnected' | 'unavailable'
export type CalendarProviderId = 'google' | 'outlook'

export interface DeskHealth {
  ok: boolean
  service: 'scriba-desk-overlay'
  version: string
  scribaCommit: string | null
  capabilities: string[]
  /**
   * False on every backend today: nothing is written to a real provider. From overlay 0.3 it
   * equals `externalWrites.enabled`.
   */
  writes: boolean
  /** 'enforced' when Scriba's chat agent is limited to the Desk's tools in this backend. */
  chatScope?: 'enforced' | 'off'
  chatTools?: { read: string[]; approval: string[] }

  // ── overlay 0.3 and later. Absent on an older backend, which means "off". ─
  /**
   * Whether approving a mail or calendar action reaches a real provider. Enforced in the server:
   * with `enabled` false an approve comes back `needs_info` with `external_writes_disabled`.
   */
  externalWrites?: {
    enabled: boolean
    /** The guarded path to a provider exists in this process. */
    capable?: boolean
    /** The project lead's switch. Not sufficient on its own. */
    authorized?: boolean
    /** The Scriba revision the safety fixes were verified in, when enabled. */
    revision?: string | null
    /** The first check that fails, and why, when disabled. */
    reason?: string | null
    message?: string | null
    checks?: Array<{ id: string; ok: boolean; detail: string }>
  }
  /** Approved actions can run against an isolated provider world. Simulated; never a real success. */
  sandboxExecution?: { available: boolean; worlds: number; note: string }
  /** What approving a mail or calendar action does for THIS user. */
  executionMode?: 'sandbox' | 'external' | 'held'
  sandbox?: { id: string; label: string } | null
  worker?: Pick<DeskWorkerStatus, 'enabled' | 'running' | 'reason' | 'intervalSeconds' | 'lastTickAt'>
  model?: { configured: boolean }
  // ── overlay 0.5 ──────────────────────────────────────────────────────────
  /**
   * Files, read and generated with Scriba's own readers and generators. `attachments` says
   * whether THIS user's mail attachments can be read on this backend: true in a sandbox world,
   * false on a real mailbox (not connected to the Desk yet).
   */
  files?: { attachments: boolean; generate: string[]; read: string[]; simulated: boolean }
  /** Whether a paired computer can be used. The detail is `fetchDeskDesktop`. */
  desktop?: Pick<DeskDesktopStatus, 'available' | 'reason' | 'simulated'>
}

export interface DeskCapability {
  id: CapabilityId
  vendor: 'google' | 'microsoft'
  label: string
  state: ConnectionState
  email: string | null
  reason: string | null
  /** Backend path that starts or repairs this connection (a navigation, not a fetch). */
  loginPath: string
}

export interface DeskConnections {
  email: string
  capabilities: DeskCapability[]
  /** One usable mailbox and one usable calendar. */
  ready: boolean
  mailboxes: Array<{
    provider: MailProvider
    email: string
    label: string
    providerAccountId: string
    isPrimary: boolean
  }>
}

export type TriageCategory =
  | 'meeting_request'
  | 'needs_reply'
  | 'action_item'
  | 'informational'
  | 'automated'

export interface Triage {
  category: TriageCategory
  /** What the message needs next. */
  outcome: 'schedule' | 'reply' | 'task' | 'none'
  priority: string
  needs_reply: boolean
  has_deadline: boolean
  /** Scriba's classifier reasons, e.g. question, direct_request, meeting_request. */
  reasons: string[]
  /** Present only for meeting_request. */
  meeting_intent?: 'new' | 'reschedule' | 'cancel'
}

export type TriagedEmail = EmailItem & { triage: Triage }

export interface MailSource {
  provider: MailProvider
  state: ConnectionState
  ok: boolean
  /** A connection state, or provider_error when a connected mailbox failed. */
  error: string | null
  count: number
  hasMore: boolean
}

export interface DeskInbox {
  account: string
  /** Both mailboxes merged, newest first. */
  items: TriagedEmail[]
  sources: MailSource[]
  counts: Record<TriageCategory, number>
  /** False when a connected mailbox could not be read: mail is known to be missing. */
  complete: boolean
}

export type CalendarError =
  | 'reconnect_required'
  | 'permission_missing'
  | 'provider_error'
  | 'range_too_large'

export interface CalendarRead {
  provider: CalendarProviderId
  account: string
  ok: boolean
  error: CalendarError | null
  busy_count: number
}

export interface BusyInterval {
  start: string
  end: string
  provider: CalendarProviderId
  account: string
  /** Outlook gives the event title; Google's free/busy does not. */
  title: string | null
}

export interface Slot {
  start: string
  end: string
}

export type IncompleteReason = 'no_calendar_connected' | 'calendar_unreadable' | 'invalid_preferences'

export interface DeskAvailability {
  timezone: string
  range: Slot
  duration_minutes: number
  buffer_minutes: number
  working_hours: { start: string; end: string; weekdays: number[] }
  calendars: CalendarRead[]
  /** True only when every connected calendar was read. */
  complete: boolean
  reason: IncompleteReason | null
  busy: BusyInterval[]
  busy_merged: Slot[]
  /** Double bookings that already exist between different calendars. */
  existing_conflicts: Array<Slot & { between: BusyInterval[] }>
  /** Empty unless `complete` is true. */
  slots: Slot[]
}

export interface DeskSlotCheck {
  timezone: string
  slot: Slot
  buffer_minutes: number
  /** true = free everywhere; false = a certain conflict; null = unknown (a calendar was unreadable). */
  free: boolean | null
  complete: boolean
  reason: IncompleteReason | null
  within_working_hours: boolean
  conflicts: BusyInterval[]
  calendars: CalendarRead[]
}

export interface DeskInboxItem {
  item: TriagedEmail
  thread: { id: string | null; messages: EmailItem[]; count: number }
  /** The mailbox any reply to this message must be sent from. */
  replyFrom: { provider: MailProvider; providerAccountId: string | null }
  /** Present for meeting requests: the next working days across both calendars. */
  calendar: null | {
    timezone?: string
    range?: Slot
    duration_minutes?: number
    calendars: CalendarRead[]
    complete: boolean
    reason: IncompleteReason | null
    slots: Slot[]
  }
  /** Present when the message needs a reply. */
  draftRequest: DraftRequest | null
}

/**
 * A ready-made request for Scriba's EXISTING `POST /drafts/create`, which
 * writes a reply draft for review (stored in Scriba; nothing is sent).
 * For a meeting request, `user_context` lists only times verified free.
 */
export interface DraftRequest {
  method: 'POST'
  path: '/drafts/create'
  body: {
    provider: MailProvider
    email_id: string
    thread_id: string | null
    provider_account_id: string | null
    user_context: string
  }
}

export interface BriefingMailLine {
  id: string
  provider: MailProvider
  provider_account_id: string | null
  from_addr: string
  subject: string
  timestamp: string
  category: TriageCategory
  outcome: Triage['outcome']
  priority: string
}

export interface DeskBriefing {
  account: string
  generated_at: string
  /** One sentence built from the counts. No model call. */
  headline: string
  counts: {
    meeting_requests: number
    needs_reply: number
    action_items: number
    meetings_today: number
    open_tasks: number
    tasks_due_today: number
    reminders: number
  }
  /** Mail that needs a reply or an action: highest priority first, then newest. */
  needs_attention: BriefingMailLine[]
  meetings_today: Array<{
    event_id?: string | null
    title?: string
    start_time?: string
    end_time?: string
    provider?: string
    calendar_provider?: string | null
    provider_account_id?: string | null
    attendee_emails?: string[]
    meeting_link?: string | null
  }>
  tasks_due_today: Array<{ id: number; title: string; due_at: string | null; effective_priority?: string }>
  open_tasks: Array<{ id: number; title: string; due_at: string | null; effective_priority?: string }>
  reminders: Array<Record<string, unknown>>
  timezone: string | null
  /** False when a connected mailbox could not be read: mail counts are a floor. */
  inbox_complete: boolean
  sources: MailSource[]
  /** Sections that could not be loaded: any of agenda, tasks, reminders. */
  unavailable: string[]
}

export const fetchDeskBriefing = () => getJson<DeskBriefing>('/desk/briefing', { timeout: 90_000 })

export const fetchDeskHealth = () => getJson<DeskHealth>('/desk/health')

export const fetchDeskConnections = () => getJson<DeskConnections>('/desk/connections')

export const fetchDeskInbox = (options?: {
  provider?: 'all' | MailProvider
  limit?: number
  mailbox?: string
}) =>
  getJson<DeskInbox>('/desk/inbox', {
    params: { provider: options?.provider ?? 'all', limit: options?.limit ?? 25, mailbox: options?.mailbox },
    timeout: 90_000,
  })

export const fetchDeskInboxItem = (provider: MailProvider, id: string, options?: {
  mailbox?: string
  days?: number
}) =>
  getJson<DeskInboxItem>('/desk/inbox/item', {
    params: { provider, id, mailbox: options?.mailbox, days: options?.days },
    timeout: 90_000,
  })

export const fetchDeskAvailability = (params: {
  /** ISO 8601. A value without an offset is read in `timezone`. At most 31 days. */
  start: string
  end: string
  /** Default: the user's Scriba preference. 15 to 480. */
  duration_minutes?: number
  /** Default: the user's Scriba preference. 0 to 180. */
  buffer_minutes?: number
  /** IANA zone. Default: the user's Scriba preference. */
  timezone?: string
  /** 1 to 20, default 5. */
  max_slots?: number
}) => getJson<DeskAvailability>('/desk/availability', { params })

/** Reads calendars only; POST because the question has a body. */
export const checkDeskSlot = (body: {
  start: string
  end: string
  timezone?: string
  buffer_minutes?: number
}) => postJson<DeskSlotCheck>('/desk/slots/check', body)

// ── Desk workflow: one incoming email to proposed, approvable actions ───────

export type RunState =
  | 'awaiting_approval'
  | 'executing'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'cancelled'
  | 'no_action_proposed'

/** Why the Desk proposed an action (overlay 0.3). */
export type DeskActionPurpose =
  | 'book'
  | 'reschedule'
  | 'cancel'
  | 'confirm'
  | 'offer_times'
  | 'clarify'
  | 'nudge'
  | 'reply'
  | 'record_task'
  /** A review of a file that came with the message, built from the file itself (0.5). */
  | 'review_file'
  /** Telling a meeting's attendees about a change the person asked for in chat (0.4). */
  | 'notify'

/**
 * The explicit state of ONE action (overlay 0.3.1, BACKEND_CONTRACT section 6, "The lifecycle of
 * an action"). Sent as `DeskAction.lifecycle`, so a client does not work it out from a status, a
 * flag and an error code. `EXECUTED_UNVERIFIED` is "the call returned": only `VERIFIED` is done.
 */
export type DeskActionLifecycle =
  /** Waits for the person and can be approved as it stands. */
  | 'PROPOSED'
  /** A guard or a missing detail holds it: it cannot be approved as it stands (`errorCode` says why). */
  | 'HELD'
  | 'APPROVED'
  | 'EXECUTING'
  /** The call returned and there is no evidence yet that it took effect. Not done. */
  | 'EXECUTED_UNVERIFIED'
  /** It took effect, on evidence (`verification.method`). */
  | 'VERIFIED'
  /** The call returned and the state read back does not show it. Steps that depend on it are blocked. */
  | 'VERIFICATION_FAILED'
  /** Part of it took effect. Nothing is undone. */
  | 'PARTIALLY_EXECUTED'
  /** The provider did not confirm: it may or may not have happened. */
  | 'OUTCOME_UNKNOWN'
  /** The process stopped mid-action; the state was read back and the effect is not there. */
  | 'INTERRUPTED'
  | 'FAILED'
  /** The person rejected it. It never ran. */
  | 'REJECTED'

/**
 * What a retry of this action does first. Null on the action when there is nothing to retry.
 * - `rerun`: nothing happened, so it is run.
 * - `readback_first`: the outcome is unknown and the state can be read (a sandbox): the retry
 *   looks for the effect and does not repeat it.
 * - `confirm_first`: the outcome is unknown and cannot be read (a real provider): the retry is
 *   refused until the person says they checked (`DESK_RETRY_AFTER_UNKNOWN`).
 */
export interface DeskActionRetry {
  mode: 'rerun' | 'readback_first' | 'confirm_first'
  /** Execution attempts so far. */
  attempts: number
  /** Always true: a retry is the same effect (`idempotencyKey`), never a second one. */
  sameEffect: true
}

/** One recorded fact about an action, with the time it was recorded. `simulated` is true in a sandbox. */
export interface DeskActionDecision {
  decision: 'approve' | 'reject'
  by: string
  at: string
  toolCallId?: number
  tool?: string
  /** `held`: the approve was refused by the execution gate (see `code`). */
  result?: 'held'
  code?: string
  edited?: string[]
  simulated?: boolean
}

export interface DeskActionExecution {
  /** `unknown`: the provider did not confirm; the action may or may not have happened. */
  status: 'executed' | 'partially_executed' | 'failed' | 'unknown' | 'held'
  at: string
  error?: string | null
  durationMs?: number
  simulated?: boolean
  toolCallId?: number
  tool?: string
  /** For `held`: the code of the guard that held it. */
  code?: string | null
  assistantActionId?: number | null
  /** True when the worker settled this after an interruption (BACKEND_CONTRACT section 8). */
  recovered?: boolean
}

export interface DeskActionVerification {
  verified: boolean
  /** `sandbox_readback`: the isolated world was read back. `scriba_action_record`: Scriba's own record. */
  /** `file_reopened` (0.5): a generated file was opened again and shows what was approved. */
  method: 'sandbox_readback' | 'scriba_action_record' | 'user_confirmed' | 'file_reopened' | null
  reason: string | null
  at: string
  /** True when a retry found the effect already there and did not repeat it. */
  reconciled?: boolean
  toolCallId?: number
  tool?: string
  simulated?: boolean
  /** True when the worker's recovery found the effect after an interruption. */
  recovered?: boolean
  /** The id of the object the effect was found as (an event, a sent message, a task). */
  objectId?: string | null
}

export interface DeskAction {
  /** Scriba chat tool-call id. Approve, cancel and retry go through Scriba's chat routes. */
  toolCallId: number
  tool_name:
    | 'create_task'
    | 'create_reminder'
    | 'create_calendar_event'
    | 'update_calendar_event'
    | 'cancel_calendar_event'
    | 'send_email'
    /** Scriba's own file tools (0.5): a Word document or a workbook in the person's own records. */
    | 'create_document'
    | 'create_spreadsheet'
    | string
  /** Scriba's tool-call status (see BACKEND_CONTRACT section 3). */
  status: string
  requiresApproval: true
  input: Record<string, unknown>
  message: string | null
  error: string | null
  /** Present on calendar-event cards when the Desk chat scope is enforced. */
  availability: Partial<DeskSlotCheck> | null
  assistantActionId: number | null
  /**
   * True only on evidence: a read-back of the provider state where one exists (a sandbox),
   * otherwise Scriba's record of the executed action. Never inferred from the status, and
   * false for a partly executed action.
   */
  verified: boolean
  /** Present while the card can be approved. POST it with `{}` (or payload_overrides). */
  approve: { method: 'POST'; path: string } | null

  // ── overlay 0.3 and later. Absent on an older backend. ──────────────────
  purpose?: DeskActionPurpose | null
  /** One sentence: why this was proposed. */
  reason?: string | null
  /** For a reply that offers times: the times, each verified free on every calendar. */
  proposedSlots?: Slot[] | null
  /** The card's whole output, so no second request per action is needed. */
  output?: Record<string, unknown>
  /** `output.error_code` for a held or failed card. */
  errorCode?: string | null
  /** One identity per real-world effect. A retry of the card reuses it. */
  idempotencyKey?: string
  verification?: DeskActionVerification | null

  // ── overlay 0.3.0 at 0282558 and later ──────────────────────────────────
  /** Its step in `DeskRun.plan.steps`. */
  stepId?: string | null
  /** A guard holds it: it cannot be approved as it stands. */
  held?: boolean
  /** How many times execution was attempted. A retry is one more. */
  attempts?: number

  // ── overlay 0.3.1 and later ─────────────────────────────────────────────
  /** The explicit state of this action. Prefer it to working the state out from `status`. */
  lifecycle?: DeskActionLifecycle
  /** True only for `VERIFIED` and `REJECTED`: nothing more can happen to this action. */
  final?: boolean
  retry?: DeskActionRetry | null
  /** The fields the person changed in the approve request. `input` stays as proposed. */
  edited?: string[]
  /** The action as it ran, or will run: `input` with the person's edit applied. */
  effectiveInput?: Record<string, unknown>
  /** The provider did not confirm: it may or may not have happened. Check before retrying. */
  outcomeUnknown?: boolean
  /** True when the action ran, or would run, against an isolated provider world. */
  simulated?: boolean
  proposedAt?: string | null
  decisions?: DeskActionDecision[]
  execution?: DeskActionExecution | null
  /** 0.4: the existing event a calendar change is about, as it was when proposed. Use its title on the card. */
  target?: DeskEventTarget | null
  /** 0.4: on a reminder (`purpose: 'nudge'`), the follow-up it chases. */
  followUpId?: string | null
}

/** Reasons overlay 0.3 adds. `change_request` is no longer sent: a change is resolved or held for one of these. */
export type DeskHeldReasonV3 =
  | 'event_not_found'
  | 'event_ambiguous'
  | 'not_organizer'
  | 'calendar_lookup_failed'
  | 'already_scheduled'
  | 'task_exists'
  | 'untrusted_instructions'

/** The reasons of overlay 0.2. */
export type DeskHeldReasonV2 =
  | 'calendar_conflict'
  | 'availability_unknown'
  | 'time_not_understood'
  | 'change_request'
  | 'invalid_preferences'

/**
 * Reasons added after the first draft of 0.3. Kept apart so that a `Record<DeskHeldReason, ...>`
 * written before them still compiles; `DeskRunHeld.reason` can be any of `DeskAnyHeldReason`.
 */
export type DeskHeldReasonRevised =
  /** A model's reading was below the confidence needed to act. `held.missing` lists what is absent. */
  | 'intent_unclear'
  /** A detail needed to act is not in the message. Nothing is filled in. */
  | 'details_missing'
  /** The message contradicts itself or takes an instruction back (0.3.1). Nothing is picked. */
  | 'conflicting_instructions'
  /** Written by a person and the Desk cannot tell what it needs (0.4). Not filed: read it. */
  | 'needs_review'
  /** A reply is needed and none could be drafted from what the Desk can verify (0.4). */
  | 'reply_needs_author'
  /** The same sender already asked for this in the conversation and that run is open (0.4). `held.target.runId`. */
  | 'already_in_progress'
  /** ...and that run is finished (0.4). */
  | 'already_handled'
  /** Several requests were read and not every one could be acted on (0.5). `held.unresolved[]`. */
  | 'unresolved_requests'

/** Every reason a run can be held for, on the first draft of overlay 0.3. */
export type DeskHeldReason = DeskHeldReasonV2 | DeskHeldReasonV3

/** Every reason the backend sends in `held.reason` today. */
export type DeskAnyHeldReason = DeskHeldReason | DeskHeldReasonRevised

/** The reason a run is held for, as the backend sends it (wider than the declared field). */
export const heldReasonOf = (held: { reason: string } | null | undefined): DeskAnyHeldReason | string | null =>
  held ? held.reason : null

export interface DeskRunHeld {
  /**
   * DECLARED NARROW ON PURPOSE. The backend sends any `DeskAnyHeldReason` here. The field keeps
   * the five reasons of 0.2 because the frontend on `main` builds a `Record` over this exact
   * type; widening it breaks that build. Read it as `DeskAnyHeldReason` (`heldReasonOf`), and
   * treat a reason this client does not know as held, never as done. To be widened to
   * `DeskAnyHeldReason` once the frontend that labels every reason is merged (see
   * docs/handoff/AGENT2_INTEGRATION_HANDOFF.md).
   */
  reason: DeskHeldReasonV2
  message: string
  /** Verified free times to offer instead. Empty when calendars could not be read. */
  slots: Slot[]
  calendars: CalendarRead[]
  requested?: Slot
  conflicts?: BusyInterval[]
  /** The existing meeting a change request is about, when one was found. */
  target?: { id: string; title: string; start: string; end: string; provider: 'google' | 'outlook' }
  /** For `event_ambiguous`: the meetings that match. For `event_not_found` with a named meeting: the sender's other meetings, none of which was touched. */
  candidates?: Array<{ id: string; title: string; start: string; end: string; provider: 'google' | 'outlook' }>
  /** For `intent_unclear` and `details_missing`: what the message does not state. */
  missing?: string[]
  /** For `event_not_found` when the meeting meant was already cancelled or has taken place (0.3.1). */
  gone?: Array<{ id: string; title: string; start: string; end: string; provider: 'google' | 'outlook'; status?: string }>
}

/** Where a run stands (overlay 0.3). Derived from the cards and the recorded evidence. */
export type DeskLifecycleStage =
  | 'RECEIVED'
  | 'CLASSIFIED'
  | 'CONTEXT_GATHERING'
  | 'PLANNING'
  | 'AWAITING_APPROVAL'
  | 'EXECUTING'
  | 'VERIFYING'
  | 'COMPLETED'
  | 'AWAITING_REPLY'
  | 'NEEDS_CLARIFICATION'
  | 'ESCALATED'
  | 'PARTIALLY_COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

/**
 * The stage names the backend SENDS (BACKEND_CONTRACT section 6). `DeskLifecycleStage` above
 * keeps the three names of the first draft (`CLASSIFIED`, `CONTEXT_GATHERING`, `AWAITING_REPLY`),
 * which were never sent, only so that code written against them still compiles. New code should
 * use this type; the old one is removed once nothing reads it.
 */
export type DeskRunStage =
  | 'RECEIVED'
  | 'UNDERSTANDING'
  | 'INVESTIGATING'
  | 'PLANNING'
  | 'AWAITING_APPROVAL'
  /** Every open action is held by a guard. `lifecycle.reason` is the first one's `errorCode`. */
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

export interface DeskLifecycle {
  stage: DeskLifecycleStage | DeskRunStage
  reason: string | null
  final: boolean
  outcomeUnknown: boolean
  /** Set for PARTIALLY_COMPLETED. The Desk never undoes an executed action by itself. */
  compensation: { policy: 'escalate'; message: string } | null
}

export type DeskEvidenceKind =
  | 'stage'
  | 'decision'
  | 'read'
  /** The plan, written once when the run is opened. `data` is the plan. */
  | 'plan'
  | 'proposal'
  | 'approval'
  | 'execution'
  | 'verification'
  | 'human'
  | 'followup'
  | 'usage'
  | 'error'

/**
 * Kinds added after `DeskEvidenceKind` was first used to key a `Record` in the frontend. Kept
 * apart so that code keeps compiling; `timeline[].kind` can be any `DeskAnyEvidenceKind`.
 * `task`: a change to one of the person's existing tasks (`DeskTaskUpdate`).
 */
export type DeskRevisedEvidenceKind = 'task' | 'file'

export type DeskAnyEvidenceKind = DeskEvidenceKind | DeskRevisedEvidenceKind

/** One recorded event of a run. `summary` never contains message text. */
export interface DeskTimelineItem {
  at: string
  kind: DeskEvidenceKind
  summary: string
  data: Record<string, unknown>
}

/**
 * A follow-up state the backend sends since 0.4 that `DeskFollowUp.state` does not list, so
 * that exhaustive tables over the four original states still compile: reminded once, still no
 * answer, now the person's. The Desk never proposes a second reminder.
 */
export type DeskFollowUpStateRevised = 'escalated'

export interface DeskFollowUp {
  id: string
  /** Also `DeskFollowUpStateRevised` ('escalated') since 0.4. */
  state: 'waiting' | 'overdue' | 'satisfied' | 'closed'
  /** 0.4: always 'reply' today. */
  kind?: 'reply'
  /** 0.4: 'desk' was opened by a run; 'external' is a wait the Desk did not open (`runId` null). */
  source?: 'desk' | 'external'
  /** 0.4: reminders sent for it, counted from executed cards across the person's runs. */
  nudges?: number
  /** 0.4: a reminder for it is waiting for approval. */
  nudgePending?: boolean
  lastNudgeAt?: string | null
  /** 0.4: 'no_answer_after_reminder' on an escalated one. 0.5: 'holding_reply' when the person only acknowledged. */
  reason?: string | null
  waitingOnName?: string | null
  satisfiedAt?: string
  /** 0.5: the awaited person wrote but did not answer ("still working on it"). The wait stays open. */
  lastHoldingReplyAt?: string | null
  lastHoldingReplyId?: string | null
  threadId?: string | null
  waitingOn?: string | null
  subject?: string | null
  sentAt?: string
  dueAt?: string
  satisfiedBy?: string
  updatedAt?: string
  runId?: number
  /** The reply card this follow-up was opened for. */
  toolCallId?: number
  /** True for an awaited reply Scriba tracked before the Desk (not opened by a Desk run). */
  external?: boolean
}

/**
 * A change the run suggests to one of the person's EXISTING tasks (overlay 0.3.1): a message
 * reported work as finished and exactly one open task is about it. Only the person's own records
 * are written. `suggested` waits for the person (`applyDeskTaskUpdate` or `dismissDeskTaskUpdate`)
 * unless the Desk is set to keep own records without asking.
 */
export interface DeskTaskUpdate {
  op: 'complete'
  taskId: string
  title?: string | null
  /** The words of the message that matched the task. */
  matched?: unknown
  source?: 'rules' | 'model'
  /**
   * `completed`: marked done AND read back as no longer open. `unverified`: the change was sent
   * and the tasks could not be read back, so it is not known to be done. `failed`: it is still open.
   */
  state: 'suggested' | 'completed' | 'unverified' | 'failed' | 'dismissed'
  /** True only when the tasks were read back. Null: they could not be read. */
  verified?: boolean | null
  by?: string
  error?: string | null
  updatedAt?: string
}

// ── files (overlay 0.5; BACKEND_CONTRACT section 12) ───────────────────────

/** A file that came with the message, as it was read. Facts about the file only: never its text. */
export interface DeskAttachment {
  id: string
  filename: string
  /** Decided by the file's bytes, not its name. Null when it was not accepted. */
  kind: 'pdf' | 'docx' | 'xlsx' | 'pptx' | 'csv' | 'text' | 'image' | string | null
  sizeBytes: number
  sha256: string | null
  /** False: it was not read. `error` says why (`file_blocked`, `file_type_mismatch`, `file_too_large`, `file_unreadable`, `too_many_attachments`). */
  read: boolean
  error: string | null
  /** What was counted: `page`, `sheet`, `slide`, ... and how many. */
  unit: string | null
  unitCount: number | null
  truncated: boolean
  /** Scanned pages with no text layer. They were NOT read. */
  unreadParts: number
  /** Passages written to an assistant. More than zero: the run is held and nothing was proposed. */
  untrustedFindings: number
  /** For a table: how many things the fixed checks raised. */
  unusual: number
  readAt: string
}

/** A file the Desk generated in this run. Not done until `verified`. */
export interface DeskFile {
  id: string
  filename: string
  mimeType: string
  sizeBytes: number
  /** The action that made it, and its step in the plan. Null for the result of a workbook change (`changeId`). */
  toolCallId: number | null
  stepId: string | null
  /** Set when this file is the changed copy a `DeskFileChange` produced. */
  changeId?: string
  state: DeskActionLifecycle
  /** True only after the file was reopened and showed the title and headings that were approved. */
  verified: boolean
  /** True in a sandbox world: the file exists only there. */
  simulated: boolean
  /** Owner only. Always served as a download (`Content-Disposition: attachment`), never rendered. */
  download: { method: 'GET'; path: string }
}

/** One change to a workbook. A value is data: text that starts like a formula is refused. */
export type DeskWorkbookOperation =
  | { op: 'update_cell'; sheet: string; cell: string; value: string | number | boolean | null }
  /** Adds one row by column header. A totals row stays last and its range grows. */
  | { op: 'append_row'; sheet: string; values: Record<string, string | number | boolean | null> }
  /** Updates the row whose `key` column equals `values[key]`, or adds it. */
  | { op: 'upsert_row'; sheet: string; key: string; values: Record<string, string | number | boolean | null> }

/** What Scriba's Excel skill reported for one operation. */
export interface DeskWorkbookStep {
  index: number
  op: DeskWorkbookOperation['op']
  sheet: string
  status: string
  /** The skill read the written cells back and every sheet and formula was still there. */
  verified: boolean
  cell: string | null
  row: number | null
  matched: boolean | null
  oldValue: unknown
  oldValues: Record<string, unknown> | null
  formulasKept: number | null
  cellsChecked: number | null
  error: string | null
  stage: string | null
}

/**
 * A change to a workbook of a run (overlay 0.5.1). `suggested`: nothing was changed; the person
 * applies or dismisses it. `applied`: Scriba's Excel skills ran on a COPY, the result was reopened
 * and compared with the original, and it is kept as a NEW file (`resultFileId`). The original is
 * never changed. `failed`: nothing was kept. `unverified`: the store did not confirm.
 */
export interface DeskFileChange {
  id: string
  state: 'suggested' | 'applied' | 'unverified' | 'failed' | 'dismissed'
  sourceFileId: string
  filename: string
  operations: DeskWorkbookOperation[]
  resultFileId: string | null
  resultFilename: string | null
  verified: boolean
  verification:
    | { ok: boolean; reason: string | null; method?: 'workbook_reopened'; verified?: boolean; sheets?: number; rowsAdded?: number; formulas?: number; sheet?: string }
    | null
  steps: DeskWorkbookStep[]
  /** For `failed`: the 1-based operation that did not take effect. Later ones never ran. */
  failedAt: number | null
  error: string | null
  message: string | null
  /** For `dismissed`: what the change was when the person set it aside. Not a success. */
  dismissedFrom: 'suggested' | 'failed' | 'unverified' | null
  by: string | null
  updatedAt: string
  simulated: boolean
  /** Present while `suggested`. POST it to apply. */
  apply: { method: 'POST'; path: string } | null
}

// ── the desktop bridge (overlay 0.5; BACKEND_CONTRACT section 14) ──────────

/**
 * Where a desktop job stands, by what its record proves. `ACCEPTED` is queued, not started.
 * `VERIFIED` needs the recording's own checks to have passed; a task with no check that reports
 * success is `SUCCEEDED_UNVERIFIED`; one whose step fell back to a recorded position is
 * `NEEDS_REVIEW`; one that started and went silent is `OUTCOME_UNKNOWN`.
 */
export type DeskDesktopJobState =
  | 'ACCEPTED'
  | 'STARTED'
  | 'RUNNING'
  | 'AWAITING_APPROVAL'
  | 'VERIFIED'
  | 'SUCCEEDED_UNVERIFIED'
  | 'NEEDS_REVIEW'
  | 'OUTCOME_UNKNOWN'
  | 'FAILED'
  | 'CANCELLED'

export interface DeskDesktopDevice {
  id: number
  name: string
  kind: 'desktop' | 'browser' | string
  presence: string
  ready: boolean
  state: string
  session: 'unlocked' | 'locked' | 'unknown' | string
  agentVersion: string | null
  updateRequired: boolean
  lastSeenAt: string | null
  /** Online, up to date, and the desktop agent (not the browser extension). */
  canRunRecordedTasks: boolean
  allowedFolders: number
  /** True: a FAKE device in a sandbox world. Nothing ran on a real computer. */
  simulated: boolean
}

export interface DeskDesktopTask {
  id: number
  name: string
  kind: string
  ready: boolean
  steps: number
  hasPassword: boolean
  /** Checks the recording carries. Zero: a run of it can finish but never be verified. */
  checks: number
  apps: string[]
  runsWhileLocked: boolean
  simulated: boolean
}

export interface DeskDesktopStatus {
  account?: string
  available: boolean
  /** Why not: `desktop_agent_disabled`, `no_device_paired`, `no_device_ready`, `no_desktop_in_sandbox`, `desktop_backend_unreachable`, ... */
  reason: string | null
  message: string | null
  simulated: boolean
  devices: DeskDesktopDevice[]
  tasks: DeskDesktopTask[]
  /** Always `supported: false`: Scriba's agent keeps no checkpoint for a recorded task. */
  resume: { supported: boolean; reason: string }
  states: DeskDesktopJobState[]
}

export interface DeskDesktopJob {
  id: number
  deviceId: number | null
  recordingId: number | null
  task: string | null
  state: DeskDesktopJobState
  final: boolean
  /** Scriba's own job status, as stored. */
  scribaStatus: string
  failureStage: string | null
  error: string | null
  cancelRequested: boolean
  progress: unknown
  result: {
    stepsReplayed: number | null
    needsReview: boolean
    healedClicks: number | null
    retried: boolean | null
    filesDone: number | null
    filesTotal: number | null
  }
  verified: boolean
  verification: { method: 'recording_checks' | null; checks: number; passed: number; reason: string | null }
  resume: { supported: boolean; reason: string }
  createdAt: string | null
  startedAt: string | null
  finishedAt: string | null
  updatedAt: string | null
  /** What the device reported, newest last. Recorded steps are never included. */
  events: Array<{ at: string | null; action: string | null; status: string | null; message: string | null }>
  simulated: boolean
}

// ── the plan of a run (BACKEND_CONTRACT section 6, "The plan") ─────────────

export type DeskIntentType =
  | 'new_meeting'
  | 'reschedule'
  | 'cancellation'
  | 'reply_needed'
  | 'information_request'
  | 'task'
  | 'reminder'
  | 'follow_up'
  | 'fyi'

/** What a message asks for, with where the reading came from. */
export interface DeskPlanIntent {
  type: DeskIntentType | string
  /** Null from the rules, which do not measure confidence. A model's is 0 to 1; below 0.6 nothing is proposed. */
  confidence: number | null
  /** From the rules: the names of the rules that matched. From a model: quotes of the message. */
  evidence: string[]
  /** What this intent needs and the message does not state. */
  missing: string[]
  source: 'rules' | 'model' | string | null
}

/**
 * Where a step stands. Once the step has a card this is the card's Scriba status; before that it
 * is `ready` (every step it depends on took effect and was not found unverified), `waiting`, or
 * `blocked` (a step it depends on failed, was rejected, or ran and failed verification). A
 * blocked step is never proposed.
 */
export type DeskPlanStepState = 'ready' | 'waiting' | 'blocked' | string

export interface DeskPlanStep {
  id: string
  /** Scriba tool name, as on the action card. */
  tool: string
  purpose: DeskActionPurpose | null
  dependsOn: string[]
  /** Its content depends on another step's result, so it is proposed only after that step took effect. */
  deferred: boolean
  requiresApproval: boolean
  /** A mail or calendar write, as opposed to the executive's own records. */
  external: boolean
  /** What is true when this step is done. */
  expected: string
  onFailure: string
  state: DeskPlanStepState
  /** The step's action card, once it is proposed. */
  toolCallId: number | null
}

export interface DeskPlan {
  version: number
  message: { provider: MailProvider; provider_account_id: string | null; email_id: string; thread_id: string | null }
  planner: 'rules' | 'rules+model' | 'model+rules' | 'rules+agent' | string | null
  intents: DeskPlanIntent[]
  /** Intents a model reported without a quote that is in the message. They were dropped. */
  unsupported: Array<{ type: string; why: string }>
  /** What the Desk verified by reading (a calendar, the thread). */
  facts: string[]
  /** What it filled in because the message did not say. */
  assumptions: string[]
  /** What is needed and absent. It leads to a question or a hand-over, never to an invented detail. */
  missing: string[]
  /** The reads that were made. */
  tools: string[]
  steps: DeskPlanStep[]
  /** How many steps a person must approve. */
  approvals: number
  /** The conditions under which the Desk stops and hands over. */
  escalation: string[]
}

export type DeskRunFlag = 'prompt_injection_suspected' | 'duplicate' | 'outside_working_hours'

/** Model usage of a run, from Scriba's own telemetry and price table. Null: no model call was recorded. */
export interface DeskRunUsage {
  models: Array<{ model: string; calls: number; inputTokens: number | null; outputTokens: number | null; cachedInputTokens: number | null }>
  /** Null when any call has no known price. Null is not zero. */
  estimatedCostUsd: number | null
  priceSource: string | null
}

export interface DeskRun {
  runId: number
  /** True when this message already had a run and nothing new was proposed. */
  duplicate: boolean
  state: RunState
  email: {
    provider: MailProvider
    email_id: string
    thread_id: string | null
    provider_account_id: string | null
    from_addr: string
    subject: string
    /** When the message arrived, where the mailbox says. */
    received_at?: string | null
  }
  category: TriageCategory
  outcome: Triage['outcome']
  createdAt: string
  /** Why nothing was proposed for booking, for a meeting request. */
  held: DeskRunHeld | null
  draftRequest: DraftRequest | null
  actions: DeskAction[]
  /**
   * 'advance': call advanceDeskRun. 'draft_reply': post draftRequest to Scriba.
   * 'complete_task' (0.3.1): a `taskUpdates` entry is `suggested`; call applyDeskTaskUpdate or dismissDeskTaskUpdate.
   */
  next: Array<'advance' | 'draft_reply' | 'complete_task' | 'apply_file_change'>

  // ── overlay 0.3 and later. Absent on an older backend. ──────────────────
  lifecycle?: DeskLifecycle
  /** What started the run. `worker`: the background intake worker, with no client open. `chat` (0.4): POST /desk/commands. */
  trigger?: 'manual' | 'sweep' | 'worker' | 'evaluation' | 'chat'
  /** 0.4: 'command' for a run opened by an instruction; its `email.email_id` and `from_addr` are then empty. */
  kind?: 'email' | 'command'
  /** 0.4, command runs: what was typed and the operations read from it. */
  command?: { text: string; operations: DeskCommandOperation[] }
  /** 0.4, command runs: one paragraph composed by code from the run's state. Changes as the run advances. */
  assistantMessage?: string
  /** True when the run lives in an isolated provider world: nothing real is read or written. */
  simulated?: boolean
  flags?: DeskRunFlag[]
  /** Written once when the run is opened. Null for a run opened before plans existed. */
  plan?: DeskPlan | null
  /** Changes this run suggests to existing tasks, each in its latest state (0.3.1). */
  taskUpdates?: DeskTaskUpdate[]
  /** Files that came with the message, as they were read (0.5). Empty on a backend that cannot read attachments. */
  attachments?: DeskAttachment[]
  /** Files the Desk generated in this run (0.5). */
  files?: DeskFile[]
  /**
   * 0.5: requests the Desk identified in the message and could not act on. While one is not
   * `resolved` the run is not complete (`lifecycle.reason: 'unresolved_requests'`), and `next`
   * contains 'resolve_unresolved': POST /desk/runs/{runId}/unresolved/resolve when the person takes them over.
   */
  unresolved?: Array<{ id: string; text: string; why: string; resolved: boolean }>
  /** Changes to a workbook of this run, each in its latest state (0.5.1). */
  fileChanges?: DeskFileChange[]
  updatedAt?: string
  /** Number of actions by Scriba status. */
  actionCounts?: Record<string, number>
  followUps?: DeskFollowUp[]
  timeline?: DeskTimelineItem[]
  usage?: DeskRunUsage | null
}

/** The operations an instruction can be read into (0.4, BACKEND_CONTRACT section 12). */
export type DeskCommandOperation = 'reminder' | 'task' | 'reschedule' | 'cancel' | 'notify' | 'chase_overdue'

/** The existing event a calendar change is about, as it was when proposed (0.4). */
export interface DeskEventTarget {
  id?: string | null
  title?: string | null
  start?: string | null
  end?: string | null
  provider?: string | null
  provider_account_id?: string | null
}

interface DeskMemoryPart<T> {
  /** False: this part could not be read. `items` is then empty and that does NOT mean there is nothing. */
  ok: boolean
  items: T[]
  error?: string
}

export interface DeskMemoryAction {
  runId: number
  subject: string | null
  tool: string
  purpose: string | null
  status: string
  verified?: boolean
  toolCallId: number
  start?: string | null
  title?: string | null
}

/** GET /desk/memory: what the Desk knows right now, read from records (0.4). */
export interface DeskMemory {
  account: string
  asOf: string
  scope: { threadId: string | null; sender: string | null }
  meetings: DeskMemoryPart<{ id: string; title: string; start: string; end: string; attendees: string[]; organizer: boolean; provider: string }>
  tasks: DeskMemoryPart<{ id: string; title: string; dueAt: string | null; overdue: boolean }>
  waiting: DeskMemoryPart<DeskFollowUp>
  pending: DeskMemoryPart<DeskMemoryAction>
  done: DeskMemoryPart<DeskMemoryAction>
  decisions: DeskMemoryPart<{ runId: number; subject: string | null; at: string; decision: string; tool?: string; toolCallId?: number; fields?: string[] }>
  runs: DeskMemoryPart<{ runId: number; kind: 'email' | 'command'; subject: string | null; from: string | null; threadId: string | null; createdAt: string; stage: string; reason: string | null }>
}

/** A row of GET /desk/runs. From overlay 0.3 a row says where the run stands. */
export interface DeskRunRow {
  runId: number
  provider: MailProvider
  email_id: string
  subject: string
  from_addr: string
  category: TriageCategory
  created_at: string
  // ── overlay 0.3 and later ───────────────────────────────────────────────
  state?: RunState
  lifecycle?: DeskLifecycleStage | DeskRunStage
  next?: DeskRun['next']
  trigger?: DeskRun['trigger']
  simulated?: boolean
  held?: { reason: DeskAnyHeldReason } | null
  actionCounts?: Record<string, number>
  updatedAt?: string
  followUps?: Array<{ id: string; state: DeskFollowUp['state'] }>
}

export const startDeskIntake = (body: { provider: MailProvider; id: string; mailbox?: string }) =>
  postJson<DeskRun>('/desk/intake', body, { timeout: 120_000 })

export interface DeskSweepItem {
  provider: MailProvider
  id: string
  subject: string | null
  category: string
}

/** Result of POST /desk/intake/sweep. Nothing is sent or written by a sweep. */
export interface DeskSweep {
  account: string
  /** `already_running`: another sweep for this user is in progress and nothing was done. */
  status: 'completed' | 'already_running'
  examined: number
  opened: Array<DeskSweepItem & { runId: number; state: string }>
  existing: number
  skipped: number
  /** Need a run but were over `max_new`; call again to take them. */
  deferred: DeskSweepItem[]
  failed: Array<DeskSweepItem & { error: string }>
  sources: DeskInbox['sources']
  /** False when a connected mailbox could not be read. */
  complete: boolean
}

/** Open runs for recent mail that needs one. Bounded (`max_new` 1-10, default 5) and safe to repeat. */
export const sweepDeskInbox = (
  body: { provider?: 'all' | MailProvider; limit?: number; max_new?: number; mailbox?: string } = {},
) => postJson<DeskSweep>('/desk/intake/sweep', body, { timeout: 300_000 })

/** The user's runs, newest first. `limit` 1 to 200, default 50. */
export const fetchDeskRuns = (limit?: number) =>
  getJson<{ account: string; runs: DeskRunRow[] }>('/desk/runs', { params: { limit }, timeout: 90_000 })

export const fetchDeskRun = (runId: number) => getJson<DeskRun>(`/desk/runs/${runId}`)

export const advanceDeskRun = (runId: number) => postJson<DeskRun>(`/desk/runs/${runId}/advance`)

/** Suggest a change to a workbook that came with this run's message, or that the run made. Changes nothing. */
export const suggestDeskFileChange = (runId: number, body: { fileId: string; operations: DeskWorkbookOperation[] }) =>
  postJson<DeskRun>(`/desk/runs/${runId}/file-changes`, body)

/** Apply it: a changed COPY is made, verified and kept as a new file. Safe to repeat. */
export const applyDeskFileChange = (runId: number, changeId: string) =>
  postJson<DeskRun>(`/desk/runs/${runId}/file-changes/${encodeURIComponent(changeId)}/apply`)

export const dismissDeskFileChange = (runId: number, changeId: string) =>
  postJson<DeskRun>(`/desk/runs/${runId}/file-changes/${encodeURIComponent(changeId)}/dismiss`)

/** The path of a file of the caller's own records. Fetch it with credentials; it is always a download. */
export const deskFilePath = (fileId: string) => `/desk/files/${encodeURIComponent(fileId)}`

/** Paired computers, recorded tasks, and whether anything can be run. Never throws for "not connected": read `available`. */
export const fetchDeskDesktop = () => getJson<DeskDesktopStatus>('/desk/desktop')

/**
 * Queue one of the person's recorded tasks on one of their computers. `confirm` must be true: it
 * is the person's explicit go-ahead. Rejects with 409 and the header `X-Desk-Error-Code` when no
 * desktop can take it; nothing was queued then.
 */
export const startDeskDesktopJob = (body: { recordingId: number; deviceId?: number; confirm: true }) =>
  postJson<DeskDesktopJob>('/desk/desktop/jobs', body)

export const fetchDeskDesktopJob = (jobId: number) => getJson<DeskDesktopJob>(`/desk/desktop/jobs/${jobId}`)

/** Ask the device to stop. A running job stops at its next step: read `cancelRequested`, then poll. */
export const cancelDeskDesktopJob = (jobId: number) => postJson<DeskDesktopJob>(`/desk/desktop/jobs/${jobId}/cancel`)

/** Mark done the existing task this run matched. Writes only the person's own records. Safe to repeat. */
export const applyDeskTaskUpdate = (runId: number, taskId: string) =>
  postJson<DeskRun>(`/desk/runs/${runId}/task-updates/${encodeURIComponent(taskId)}/apply`)

/** Decline the suggestion. The task is left as it is. */
export const dismissDeskTaskUpdate = (runId: number, taskId: string) =>
  postJson<DeskRun>(`/desk/runs/${runId}/task-updates/${encodeURIComponent(taskId)}/dismiss`)

// ── Worker, follow-ups and the sandbox (overlay 0.3) ────────────────────────

/** The background intake worker. With it running, mail becomes runs with no client open. */
export interface DeskWorkerStatus {
  enabled: boolean
  running: boolean
  /** Why it is not running: `not_requested`, `refused_production`, `no_users`, `stopped`, `not_installed`. */
  reason: string | null
  intervalSeconds?: number
  limits?: { maxNewPerTick: number; maxPerHour: number; maxPending: number }
  /** `durable` is false when claims live in this process only (the seeded backend). */
  claims: { store: 'memory' | 'sqlite' | 'scriba_receipts' | string; durable: boolean }
  users?: number
  ticks?: number
  skippedTicks?: number
  lastTickAt?: string | null
  lastTickMs?: number | null
  opened?: number
  existing?: number
  failed?: number
  deferred?: number
  advanced?: number
  lastError?: string | null
  /** The caller's own row. Another user's is never included. */
  you?: {
    served: boolean
    lastStatus: 'ok' | 'backpressure' | 'rate_limited' | 'mailbox_unreadable' | 'backing_off' | 'failed' | 'sweep_in_progress' | null
    lastAt: string | null
    opened: number
    mailboxUnreadable: boolean
    consecutiveFailures: number
  }
}

export const fetchDeskWorker = () =>
  getJson<{ account: string; worker: DeskWorkerStatus; runs: Partial<Record<DeskLifecycleStage, number>> }>(
    '/desk/worker',
    { timeout: 90_000 },
  )

/** Replies awaited on mail the Desk sent. Reads mail; sends nothing. */
export const fetchDeskFollowUps = (options?: { refresh?: boolean; limit?: number }) =>
  getJson<{ account: string; followUps: DeskFollowUp[]; counts: Record<DeskFollowUp['state'], number> }>(
    '/desk/follow-ups',
    { params: { refresh: options?.refresh, limit: options?.limit }, timeout: 90_000 },
  )

export const closeDeskFollowUp = (runId: number, followUpId: string) =>
  postJson<DeskRun>(`/desk/runs/${runId}/follow-ups/${encodeURIComponent(followUpId)}/close`)

/** The caller's isolated provider world. 404 when this backend has none for them. */
export interface DeskSandbox {
  id: string
  label: string
  now: string
  fixedClock: boolean
  accounts: { gmail: string[]; outlook: string | null }
  counts: { inbox: number; sent: number; events: number; tasks: number; reminders: number }
  /** Everything executed against the world, in order. Every entry is simulated. */
  operations: Array<{ seq: number; at: string; op: string; status: 'executed' | 'failed' | 'unknown'; object_id: string | null; error: string | null; simulated: true }>
  /** Real provider clients reached from the sandbox. Must be empty. */
  isolationViolations: string[]
}

export const fetchDeskSandbox = () => getJson<{ account: string; world: DeskSandbox }>('/desk/sandbox')

/** Put a synthetic message in the caller's own sandbox mailbox. The worker, or a sweep, takes it in. */
export const deliverToDeskSandbox = (body: {
  provider?: MailProvider
  from_addr: string
  subject: string
  body: string
  thread_id?: string
}) => postJson<{ delivered: { id: string; threadId: string; provider: MailProvider; timestamp: string; provider_account_id: string } }>(
  '/desk/sandbox/deliver',
  body,
)

/** "Book anyway" for a calendar card held by the booking gate. */
export const DESK_AVAILABILITY_OVERRIDE = { payload_overrides: { desk_availability_override: true } } as const

// ── Desk safeguards (BACKEND_CONTRACT section 7) ────────────────────────────

/** `output.error_code` values with which the Desk holds a card. */
export type DeskHoldCode =
  | 'unverified_recipient'
  | 'reply_target_changed'
  | 'reply_target_unverified'
  | 'recipient_required'
  | 'body_required'
  | 'title_required'
  | 'reminder_incomplete'
  | 'start_required'
  | 'calendar_conflict'
  | 'availability_unknown'
  | 'desk_check_failed'

/**
 * Hold codes overlay 0.3 adds (BACKEND_CONTRACT section 7). Kept apart from `DeskHoldCode` so
 * that code written against 0.2 still compiles; a card can carry any of `DeskAnyHoldCode`.
 */
export type DeskGateHoldCode =
  | 'reply_target_missing'
  /** Mail and calendar writes are switched off on this backend. Nothing was executed. */
  | 'external_writes_disabled'
  /** The provider did not confirm. The action may or may not have happened. */
  | 'outcome_unknown'
  /** The card was prepared in a sandbox that no longer exists. */
  | 'sandbox_world_gone'

export type DeskAnyHoldCode = DeskHoldCode | DeskGateHoldCode

/**
 * Codes added after the first draft of 0.3, kept apart for the same reason as the held reasons.
 * `proposal_changed` holds a card (it cannot be approved past). `interrupted` is on a FAILED card
 * the worker settled after an interruption: read back, the effect is not there; a retry runs it.
 */
export type DeskRevisedCardCode = 'proposal_changed' | 'interrupted'

/** Every `errorCode` the Desk itself puts on an action. Scriba's own error codes can appear too. */
export type DeskCardCode = DeskAnyHoldCode | DeskRevisedCardCode

/** Approve body for a card whose outcome is unknown, on a real provider, after the user checked. */
export const DESK_RETRY_AFTER_UNKNOWN = { payload_overrides: { desk_retry_after_unknown_confirmed: true } } as const

/** Approve body that accepts recipients the user confirmed or typed on the card. */
export const confirmDeskRecipients = (addresses: string[], extra: Record<string, unknown> = {}) => ({
  payload_overrides: { ...extra, desk_confirmed_recipients: addresses },
})

// ── overlay 0.4: instructions, memory (BACKEND_CONTRACT section 12) ─────────

/**
 * Open a run for an instruction the signed-in person typed ("remind me...", "move my 1:1 with
 * Omar to Wednesday at 14:00 and let him know", "chase what is overdue"). Proposes cards; sends
 * nothing. The same `requestId` returns the same run, so a retried send plans nothing twice.
 */
export const postDeskCommand = (text: string, requestId?: string) =>
  postJson<DeskRun>('/desk/commands', { text, requestId })

/** What the Desk knows right now, read from records. `thread` and `sender` narrow it. */
export const getDeskMemory = (query: { thread?: string; sender?: string } = {}) => {
  const params = new URLSearchParams()
  if (query.thread) params.set('thread', query.thread)
  if (query.sender) params.set('sender', query.sender)
  const suffix = params.toString()
  return getJson<DeskMemory>(`/desk/memory${suffix ? `?${suffix}` : ''}`)
}
