/**
 * The mapping layer: Scriba and Desk-overlay responses in, workspace view models out.
 *
 * Pure functions, so every rule here is tested without a backend (mappers.test.ts). Three rules
 * hold throughout:
 *
 *  1. Identity is carried, never rebuilt. Each view model keeps the provider, the provider
 *     account id and the mailbox it came from, because any later action on the item must be sent
 *     to that same provider and account.
 *  2. Nothing is invented. Where the backend gives no value (a secretary-written summary, a work
 *     status per message, an attendee's name) the view model says so (`summaryKind: 'snippet'`,
 *     status `untracked`, the address as the name) instead of filling the gap.
 *  3. Server state wins. Approval and execution status are the backend's strings, mapped to
 *     labels in one table; the frontend never advances a status on its own.
 */
import type { CalendarEntry, EmailItem } from '../api/contract'
import type { DeskCapability, DeskConnections, TriageCategory, TriagedEmail } from '../api/desk'
import type { Participant, RequestPriority } from '../harness/types'
import type { AgendaEvent, CalendarProvider, ConnectedAccount, EmailCategory, InboxEmail, MailProvider, Reminder, ThreadMessage, WorkTask } from '../harness/workspace'
import { overlaps } from '../lib/time'
import type { ScribaReminder, ScribaTask } from './scribaApi'

// ── People ──────────────────────────────────────────────────────────────────

/** `"Dana Haddad" <dana@example.test>` or a bare address. The address is the name when none is given. */
export function parseSender(fromAddr: string | null | undefined): Participant {
  const raw = (fromAddr ?? '').trim()
  const match = raw.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/)
  if (match) {
    const email = match[2].trim()
    return { name: match[1].trim() || email, email }
  }
  return { name: raw || 'Unknown sender', email: raw.includes('@') ? raw : '' }
}

// ── Mail ────────────────────────────────────────────────────────────────────

const CATEGORY: Record<TriageCategory, EmailCategory> = {
  meeting_request: 'meeting',
  needs_reply: 'reply_needed',
  action_item: 'action_required',
  informational: 'fyi',
  automated: 'low_priority',
}

/** Scriba's priorities are high, medium and low (and sometimes urgent). Anything else is normal. */
export function toPriority(priority: string | null | undefined): RequestPriority {
  switch ((priority ?? '').toLowerCase()) {
    case 'urgent': return 'urgent'
    case 'high': return 'high'
    case 'low': return 'low'
    default: return 'normal'
  }
}

export function toMailProvider(provider: string): MailProvider {
  return provider === 'outlook' ? 'outlook' : 'gmail'
}

/**
 * The Desk's id for a message: provider and message id together. Gmail and Outlook ids can
 * collide in principle, and the provider is needed to read the message again.
 */
export function emailKey(provider: string, id: string): string {
  return `${toMailProvider(provider)}:${id}`
}

export function parseEmailKey(key: string): { provider: MailProvider; id: string } | null {
  const at = key.indexOf(':')
  if (at <= 0) return null
  const provider = key.slice(0, at)
  if (provider !== 'gmail' && provider !== 'outlook') return null
  return { provider, id: key.slice(at + 1) }
}

export function toThreadMessage(item: EmailItem, ownAddresses: readonly string[]): ThreadMessage {
  const from = parseSender(item.from_addr)
  return {
    id: item.id,
    from,
    sentAt: item.timestamp,
    // The list endpoints return the provider's snippet, not the body.
    bodyText: item.snippet,
    outbound: ownAddresses.some(address => address && address.toLowerCase() === from.email.toLowerCase()),
  }
}

export function toInboxEmail(item: TriagedEmail): InboxEmail {
  return {
    id: emailKey(item.provider, item.id),
    provider: toMailProvider(item.provider),
    account: item.account_email ?? item.provider_account_id ?? '',
    threadId: item.threadId ?? item.id,
    from: parseSender(item.from_addr),
    subject: item.subject || '(no subject)',
    receivedAt: item.timestamp,
    unread: !item.is_read,
    category: CATEGORY[item.triage.category] ?? 'fyi',
    priority: toPriority(item.triage.priority),
    summary: item.snippet,
    summaryKind: 'snippet',
    actionItems: [],
    // Scriba does not track where each message stands in the secretary's work.
    status: 'untracked',
    flags: [],
    requestId: null,
    thread: [],
    draft: null,
    taskIds: [],
    followUpId: null,
    source: {
      messageId: item.id,
      providerAccountId: item.provider_account_id,
      replySupported: item.reply_supported,
      triage: item.triage,
    },
  }
}

// ── Accounts ────────────────────────────────────────────────────────────────

const CAPABILITY_KIND: Record<DeskCapability['id'], { kind: ConnectedAccount['kind']; provider: MailProvider | CalendarProvider }> = {
  gmail: { kind: 'mail', provider: 'gmail' },
  outlook_mail: { kind: 'mail', provider: 'outlook' },
  google_calendar: { kind: 'calendar', provider: 'google' },
  outlook_calendar: { kind: 'calendar', provider: 'outlook' },
}

/**
 * One row per capability, in the backend's order. A capability the server is not set up for is
 * kept, as `unavailable`, so the screen can say why it cannot be connected.
 */
export function toAccounts(connections: DeskConnections): ConnectedAccount[] {
  return connections.capabilities.map(capability => ({
    id: capability.id,
    ...CAPABILITY_KIND[capability.id],
    address: capability.email ?? '',
    label: capability.label,
    status: capability.state,
    reason: capability.reason,
    loginPath: capability.loginPath,
  }))
}

// ── Calendar ────────────────────────────────────────────────────────────────

export function toAgendaEvent(entry: CalendarEntry, requested: CalendarProvider): AgendaEvent | null {
  if (!entry.start_time || !entry.end_time) return null
  const provider: CalendarProvider = (entry.calendar_provider ?? entry.provider ?? requested).toString().includes('outlook') ? 'outlook' : requested
  return {
    id: `${provider}:${entry.event_id ?? entry.key}`,
    title: entry.title || '(no title)',
    start: entry.start_time,
    end: entry.end_time,
    provider,
    calendar: entry.account_email ?? entry.provider_account_id ?? (provider === 'google' ? 'Google Calendar' : 'Outlook Calendar'),
    attendees: (entry.attendee_emails ?? []).map(email => ({ name: email, email })),
    location: entry.location ?? null,
    kind: 'event',
    conflictsWith: [],
    approvalId: null,
    allDay: entry.all_day === true,
    source: { eventId: entry.event_id ?? null, providerAccountId: entry.provider_account_id ?? null, joinUrl: entry.join_url ?? entry.meeting_link ?? null },
  }
}

/**
 * Marks timed events that overlap an event on a DIFFERENT calendar. Two events on the same
 * calendar are that calendar's own business; the clash neither calendar shows is the one across.
 * All-day entries are left out: they are markers, not meetings.
 */
export function markCrossCalendarConflicts(events: AgendaEvent[]): AgendaEvent[] {
  const timed = events.filter(event => !event.allDay)
  return events.map(event => {
    if (event.allDay) return event
    const clashes = timed
      .filter(other => other.id !== event.id && (other.provider !== event.provider || other.calendar !== event.calendar) && overlaps(event, other))
      .map(other => other.id)
    return clashes.length ? { ...event, conflictsWith: clashes } : event
  })
}

// ── Tasks and reminders ─────────────────────────────────────────────────────

const DONE_TASK_STATUSES = new Set(['done', 'completed', 'complete'])
const HIDDEN_TASK_STATUSES = new Set(['discarded', 'archived', 'dismissed', 'deleted'])

/** Null for a task Scriba has discarded or archived: it is not part of the work list. */
export function toWorkTask(task: ScribaTask): WorkTask | null {
  const status = (task.status ?? '').toLowerCase()
  if (HIDDEN_TASK_STATUSES.has(status)) return null
  const done = DONE_TASK_STATUSES.has(status)
  return {
    id: String(task.id),
    title: task.title || task.source_item_title || '(untitled task)',
    detail: task.description || null,
    dueAt: task.due_at || null,
    status: done ? 'done' : 'open',
    priority: toPriority(task.effective_priority ?? task.priority),
    origin: task.source_item_id != null ? 'extracted' : 'manual',
    // A Scriba source item is not a Desk inbox id, so no link to the message is offered.
    sourceEmailId: null,
    createdAt: task.created_at ?? '',
    completedAt: done ? (task.updated_at ?? null) : null,
  }
}

export function toReminder(reminder: ScribaReminder): Reminder | null {
  if (reminder.id == null || !reminder.remind_at) return null
  const status = (reminder.status ?? '').toLowerCase()
  return {
    id: String(reminder.id),
    text: reminder.title || reminder.message || 'Reminder',
    remindAt: reminder.remind_at,
    status: status === 'cancelled' || status === 'canceled' ? 'dismissed' : status === 'sent' || status === 'delivered' ? 'done' : 'scheduled',
    sourceEmailId: null,
  }
}
