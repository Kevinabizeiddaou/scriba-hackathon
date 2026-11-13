/**
 * Wire types for the Scriba API endpoints the Executive Desk uses.
 *
 * Every field here was observed on a real response from Scriba at commit
 * 3ae3a2aa (the seeded server, Gmail/e2e/seeded_server.py) or read from the
 * route's request model. Fields the Desk does not use are omitted, not
 * guessed. Human-readable version: docs/BACKEND_CONTRACT.md.
 */

/** `status` values observed: connected, disconnected, unavailable, reconnect_required. */
export interface ProviderDescriptor {
  active: boolean
  connected: boolean
  available: boolean
  configured: boolean
  status: string
  reason: string | null
  reconnectRequired?: boolean
  email?: string | null
  displayName?: string | null
  providerAccountId?: string | null
  /** Backend path that starts this provider's OAuth flow. */
  loginPath?: string
  missingEnvVars?: string[]
}

export interface EmailSenderAccount {
  provider: string
  email: string
  label: string
  providerAccountId: string
  isPrimary: boolean
}

export interface GmailAccount {
  providerAccountId: string
  email: string
  displayName: string | null
  status: string
  connected: boolean
  isPrimary: boolean
  reason: string | null
}

/** GET /providers/status. Public: the anonymous shape has `authorized: false`. */
export interface ProviderStatusPayload {
  authorized: boolean
  email: string | null
  accountEmail: string | null
  name?: string | null
  calendarAuthorized: boolean
  gmailConnected: boolean
  gmailEmail: string | null
  outlookConnected: boolean
  outlookEmail: string | null
  outlookDisplayName: string | null
  /** Present only when authenticated. */
  emailAccounts?: EmailSenderAccount[]
  gmailAccounts?: GmailAccount[]
  openaiConfigured?: boolean
  /**
   * Scriba reports every integration it knows. The Desk reads only the four
   * keys below; Slack, Teams, Jira, Drive and OneDrive are ignored on purpose.
   */
  providers: {
    gmail: ProviderDescriptor
    google_calendar: ProviderDescriptor
    outlook: ProviderDescriptor
    outlook_calendar: ProviderDescriptor
    [other: string]: ProviderDescriptor
  }
}

/** GET /health. Public. */
export interface HealthPayload {
  ok: boolean
  status: string
  service: string
  database?: { ok?: boolean }
  maintenance?: { maintenanceMode?: boolean }
}

export type MailProvider = 'gmail' | 'outlook'
export type CalendarProvider = 'google' | 'outlook'

export interface EmailItem {
  id: string
  threadId: string | null
  from_addr: string
  subject: string
  snippet: string
  timestamp: string
  provider: string
  is_read: boolean
  reply_supported: boolean
  /** The mailbox that received the message. Send replies from this account. */
  provider_account_id: string | null
  account_email: string | null
  source_item_id: number | string | null
  priority?: string
}

/** GET /emails?provider=gmail|outlook&limit=&cursor=&mailbox= */
export interface EmailListResponse {
  account: string
  items: EmailItem[]
  returnedCount: number
  unreadCount: number
  hasMore: boolean
  nextCursor: string | null
}

export interface CalendarEntry {
  key: string
  event_id?: string | null
  title?: string
  start_time?: string
  end_time?: string
  all_day?: boolean
  provider?: string
  calendar_provider?: string | null
  provider_account_id?: string | null
  account_email?: string | null
  attendee_emails?: string[]
  meeting_link?: string | null
  join_url?: string | null
  location?: string | null
}

/** GET /calendar/events?provider=google|outlook&start=&end= */
export interface CalendarEventsPayload {
  account?: string
  timezone?: string | null
  range?: { start?: string | null; end?: string | null; label?: string }
  meetings: CalendarEntry[]
}

/** Error envelope on 4xx/5xx. */
export interface ErrorEnvelope {
  error?: string
  errorCode?: string
  detail?: string
  requestId?: string
}
