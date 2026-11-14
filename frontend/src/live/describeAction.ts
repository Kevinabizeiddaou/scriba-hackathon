/**
 * Turns one Scriba action record (a chat tool call) into what an approver needs to read:
 * what will happen, who receives it, which calendar changes, and from which account.
 *
 * It only reads fields Scriba puts on the card (`input`, and `output.operation`,
 * `output.outcome`, `output.availability`, `output.message`). A field that is absent is absent
 * from the description; nothing is filled in.
 */
import type { ChatToolCall } from './scribaApi'

export const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}

export const readString = (value: unknown): string => (typeof value === 'string' ? value.trim() : typeof value === 'number' ? String(value) : '')

export function readList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map(item => (typeof item === 'string' ? item : readString(asRecord(item).email) || readString(asRecord(item).address)))
      .map(item => item.trim())
      .filter(Boolean)
  }
  if (typeof value === 'string') return value.split(/[,;]/).map(item => item.trim()).filter(Boolean)
  return []
}

export type ActionKind = 'email' | 'email_reply' | 'calendar_create' | 'calendar_update' | 'calendar_cancel' | 'task' | 'reminder' | 'read' | 'other'

export interface OutcomeRow {
  /** ok: the provider confirmed it. failed: it did not happen. unknown: nobody knows; do not assume either. skipped: not requested. */
  state: 'ok' | 'failed' | 'unknown' | 'skipped'
  label: string
  detail: string
}

export interface AvailabilityFinding {
  free: boolean | null
  complete: boolean
  overriddenByUser: boolean
  conflicts: { title: string | null; provider: string; account: string; start: string; end: string }[]
  unreadable: { provider: string; account: string; error: string }[]
}

export interface ActionDescription {
  kind: ActionKind
  /** "Send an email", "Create a calendar event". Imperative, about what approval will do. */
  title: string
  /** The one line that identifies it: the subject, the event title, the task. */
  headline: string
  recipients: string[]
  /** Mail body or event description, as it will be sent. */
  body: string
  /** Provider name as Scriba reports it (gmail, outlook, google, outlook_calendar...), or ''. */
  provider: string
  /** The account the action will run as, when the card names one. */
  account: string
  when: { start: string; end: string; timezone: string } | null
  location: string
  /** For a calendar update: the fields that change. */
  changes: { field: string; value: string }[]
  /** The id of the event or message this action targets, when it targets one. */
  target: string
  /** The backend's own note to the user (why it is waiting, what is missing). */
  message: string
  errorCode: string
  outcome: OutcomeRow[]
  availability: AvailabilityFinding | null
  /** Every input field not shown above, so nothing on the card is hidden from the approver. */
  otherInput: { field: string; value: string }[]
}

const TITLES: Record<string, { kind: ActionKind; title: string }> = {
  send_email: { kind: 'email', title: 'Send an email' },
  draft_email_reply: { kind: 'email_reply', title: 'Send a reply' },
  create_calendar_event: { kind: 'calendar_create', title: 'Create a calendar event' },
  update_calendar_event: { kind: 'calendar_update', title: 'Change a calendar event' },
  cancel_calendar_event: { kind: 'calendar_cancel', title: 'Cancel a calendar event' },
  create_task: { kind: 'task', title: 'Create a task' },
  create_reminder: { kind: 'reminder', title: 'Set a reminder' },
  search_sources: { kind: 'read', title: 'Searched your records' },
  show_agenda: { kind: 'read', title: 'Read your agenda' },
  show_meetings: { kind: 'read', title: 'Read your meetings' },
  provider_status: { kind: 'read', title: 'Checked your connections' },
  list_tasks: { kind: 'read', title: 'Read your tasks' },
  summarize_emails: { kind: 'read', title: 'Read your mail' },
  check_availability: { kind: 'read', title: 'Checked a time against your calendars' },
  find_free_slots: { kind: 'read', title: 'Looked for free time across your calendars' },
  executive_briefing: { kind: 'read', title: 'Prepared your briefing' },
}

const SHOWN_INPUT = new Set([
  'to', 'cc', 'bcc', 'subject', 'body', 'text', 'draft_text', 'provider', 'provider_account_id', 'summary', 'title', 'description',
  'start', 'end', 'start_time', 'end_time', 'timezone', 'attendees', 'location', 'event_id', 'email_id', 'thread_id', 'message_id',
  'remind_at', 'due_at', 'due', 'when', 'note', 'subject_auto', 'desk_availability_override', 'event_title',
])

function outcomeRows(output: Record<string, unknown>): OutcomeRow[] {
  const components = asRecord(output.outcome).components
  if (!Array.isArray(components)) return []
  return components.map(raw => {
    const component = asRecord(raw)
    const status = readString(component.status)
    const kind = readString(component.kind).replace(/_/g, ' ') || 'step'
    const state: OutcomeRow['state'] =
      status === 'sent' || status === 'created' || status === 'saved' || status === 'succeeded' ? 'ok'
        : status === 'not_requested' ? 'skipped'
          : status === 'unknown' ? 'unknown'
            : 'failed'
    const detail = [
      readString(component.message) || readString(component.error_code),
      readString(component.from_account ?? component.organizer_account) && `account ${readString(component.from_account ?? component.organizer_account)}`,
      readString(component.event_id) && `event ${readString(component.event_id)}`,
      component.already_booked === true && 'already booked: nothing new was created',
    ].filter(Boolean).join(' · ')
    return { state, label: `${kind.charAt(0).toUpperCase()}${kind.slice(1)}: ${status || 'no status reported'}`, detail }
  })
}

function availabilityOf(output: Record<string, unknown>): AvailabilityFinding | null {
  const raw = output.availability
  if (!raw || typeof raw !== 'object') return null
  const finding = asRecord(raw)
  const free = finding.free === true ? true : finding.free === false ? false : null
  return {
    free,
    complete: finding.complete === true,
    overriddenByUser: finding.overridden_by_user === true,
    conflicts: (Array.isArray(finding.conflicts) ? finding.conflicts : []).map(item => {
      const c = asRecord(item)
      return { title: readString(c.title) || null, provider: readString(c.provider), account: readString(c.account), start: readString(c.start), end: readString(c.end) }
    }),
    unreadable: (Array.isArray(finding.calendars) ? finding.calendars : [])
      .map(asRecord)
      .filter(c => c.ok === false)
      .map(c => ({ provider: readString(c.provider), account: readString(c.account), error: readString(c.error) })),
  }
}

export function describeAction(toolCall: ChatToolCall): ActionDescription {
  const input = asRecord(toolCall.input)
  const output = asRecord(toolCall.output)
  const operation = asRecord(output.operation)
  const known = TITLES[toolCall.tool_name]
  let kind: ActionKind = known?.kind ?? 'other'
  let title = known?.title ?? `Action: ${toolCall.tool_name.replace(/_/g, ' ')}`

  // Scriba turns an email that carries meeting fields into a calendar invitation: no separate
  // message is sent. The card says what will really run.
  if (readString(operation.kind) === 'calendar_invitation') {
    kind = 'calendar_create'
    title = 'Send a calendar invitation'
  }

  const start = readString(input.start ?? input.start_time)
  const end = readString(input.end ?? input.end_time)
  const calendar = kind === 'calendar_create' || kind === 'calendar_update' || kind === 'calendar_cancel'
  const headline =
    kind === 'task' || kind === 'reminder' ? readString(input.title ?? input.note ?? input.text)
      // A change or a cancellation is about an existing meeting: the Desk names it in `event_title`.
      : calendar ? (kind !== 'calendar_create' && readString(input.event_title)) || readString(input.summary ?? input.title ?? input.subject)
        : readString(input.subject)

  const changes: { field: string; value: string }[] = []
  if (kind === 'calendar_update') {
    for (const field of ['summary', 'title', 'start', 'end', 'start_time', 'end_time', 'timezone', 'location', 'attendees', 'description']) {
      const value = Array.isArray(input[field]) ? readList(input[field]).join(', ') : readString(input[field])
      if (value) changes.push({ field: field.replace(/_/g, ' '), value })
    }
  }

  const otherInput = Object.entries(input)
    .filter(([field, value]) => !SHOWN_INPUT.has(field) && value !== null && value !== '' && value !== undefined)
    .map(([field, value]) => ({ field, value: typeof value === 'string' ? value : JSON.stringify(value) }))

  const when = kind === 'reminder'
    ? (readString(input.remind_at ?? input.when) ? { start: readString(input.remind_at ?? input.when), end: '', timezone: readString(input.timezone) } : null)
    : kind === 'task'
      ? (readString(input.due_at ?? input.due) ? { start: readString(input.due_at ?? input.due), end: '', timezone: readString(input.timezone) } : null)
      : start ? { start, end, timezone: readString(input.timezone) } : null

  return {
    kind,
    title,
    headline,
    recipients: calendar ? readList(input.attendees ?? input.to) : [...readList(input.to), ...readList(input.cc), ...readList(input.bcc)],
    body: readString(input.body ?? input.text ?? input.draft_text ?? input.description),
    provider: readString(input.provider) || readString(operation.provider),
    account: readString(input.provider_account_id) || readString(operation.from_account ?? operation.organizer_account),
    when,
    location: readString(input.location),
    changes,
    target: readString(input.event_id ?? input.email_id ?? input.message_id ?? input.thread_id),
    message: readString(output.message),
    errorCode: readString(output.error_code) || readString(toolCall.error),
    outcome: outcomeRows(output),
    availability: availabilityOf(output),
    otherInput,
  }
}

const PROVIDER_LABEL: Record<string, string> = {
  gmail: 'Gmail',
  google: 'Google Calendar',
  google_calendar: 'Google Calendar',
  outlook: 'Outlook',
  outlook_calendar: 'Outlook Calendar',
  outlook_mail: 'Outlook Mail',
}

export function providerLabel(provider: string): string {
  return PROVIDER_LABEL[provider] ?? provider
}

/** The key the Desk chat scope reads to record that the user chose to book despite a finding. */
export const AVAILABILITY_OVERRIDE_FLAG = 'desk_availability_override'

/** True when the card is held by the backend's availability check rather than by a missing field. */
export function heldByAvailability(description: ActionDescription): boolean {
  return description.errorCode === 'calendar_conflict' || description.errorCode === 'availability_unknown'
}
