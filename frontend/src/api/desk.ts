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
}

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
