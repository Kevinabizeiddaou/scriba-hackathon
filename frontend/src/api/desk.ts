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
  /** Always false: the overlay does not send mail or write calendars. */
  writes: false
  /** 'enforced' when Scriba's chat agent is limited to the Desk's tools in this backend. */
  chatScope?: 'enforced' | 'off'
  chatTools?: { read: string[]; approval: string[] }
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

export interface DeskAction {
  /** Scriba chat tool-call id. Approve, cancel and retry go through Scriba's chat routes. */
  toolCallId: number
  tool_name: 'create_task' | 'create_calendar_event' | 'send_email' | string
  /** Scriba's tool-call status (see BACKEND_CONTRACT section 3). */
  status: string
  requiresApproval: true
  input: Record<string, unknown>
  message: string | null
  error: string | null
  /** Present on calendar-event cards when the Desk chat scope is enforced. */
  availability: Partial<DeskSlotCheck> | null
  assistantActionId: number | null
  /** True only when the card executed AND Scriba recorded the action. Never inferred. */
  verified: boolean
  /** Present while the card can be approved. POST it with `{}` (or payload_overrides). */
  approve: { method: 'POST'; path: string } | null
}

export interface DeskRunHeld {
  reason:
    | 'calendar_conflict'
    | 'availability_unknown'
    | 'time_not_understood'
    | 'change_request'
    | 'invalid_preferences'
  message: string
  /** Verified free times to offer instead. Empty when calendars could not be read. */
  slots: Slot[]
  calendars: CalendarRead[]
  requested?: Slot
  conflicts?: BusyInterval[]
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
  }
  category: TriageCategory
  outcome: Triage['outcome']
  createdAt: string
  /** Why nothing was proposed for booking, for a meeting request. */
  held: DeskRunHeld | null
  draftRequest: DraftRequest | null
  actions: DeskAction[]
  /** 'advance': call advanceDeskRun. 'draft_reply': post draftRequest to Scriba. */
  next: Array<'advance' | 'draft_reply'>
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

export const fetchDeskRuns = () =>
  getJson<{ account: string; runs: Array<{ runId: number; subject: string; category: TriageCategory; created_at: string }> }>(
    '/desk/runs',
  )

export const fetchDeskRun = (runId: number) => getJson<DeskRun>(`/desk/runs/${runId}`)

export const advanceDeskRun = (runId: number) => postJson<DeskRun>(`/desk/runs/${runId}/advance`)

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

/** Approve body that accepts recipients the user confirmed or typed on the card. */
export const confirmDeskRecipients = (addresses: string[], extra: Record<string, unknown> = {}) => ({
  payload_overrides: { ...extra, desk_confirmed_recipients: addresses },
})
