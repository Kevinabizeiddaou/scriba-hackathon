import { describe, expect, it } from 'vitest'
import type { CalendarEntry } from '../api/contract'
import type { DeskConnections, TriagedEmail } from '../api/desk'
import { describeAction, heldByAvailability } from './describeAction'
import { weekRange } from './liveDesk'
import { emailKey, markCrossCalendarConflicts, parseEmailKey, parseSender, toAccounts, toAgendaEvent, toInboxEmail, toPriority, toReminder, toWorkTask } from './mappers'
import { CHAT_TOOL_STATUSES, type ChatToolCall } from './scribaApi'
import { WORK_STAGES, cardsOfConversation, isWorkItem, needsIntervention, needsUser, stageOf } from './workQueue'
import { approvalGate, toolEffect, writePolicyFrom } from './writePolicy'

const mail = (over: Partial<TriagedEmail> = {}): TriagedEmail => ({
  id: 'm-1',
  threadId: 't-1',
  from_addr: '"Dana Haddad" <dana@example.test>',
  subject: 'Board pack',
  snippet: 'Could you send the pack by Thursday?',
  timestamp: '2026-11-13T09:00:00Z',
  provider: 'outlook',
  is_read: false,
  reply_supported: true,
  provider_account_id: 'acct-outlook-1',
  account_email: 'exec@contoso.example',
  source_item_id: null,
  triage: { category: 'needs_reply', outcome: 'reply', priority: 'high', needs_reply: true, has_deadline: true, reasons: ['direct_request'] },
  ...over,
})

const call = (over: Partial<ChatToolCall> = {}): ChatToolCall => ({
  id: 7,
  message_id: 3,
  conversation_id: 2,
  tool_name: 'send_email',
  status: 'awaiting_approval',
  input: {},
  output: {},
  ...over,
})

describe('mail mapping', () => {
  it('keeps the provider, the provider account and the mailbox with the message', () => {
    const email = toInboxEmail(mail())
    expect(email.provider).toBe('outlook')
    expect(email.account).toBe('exec@contoso.example')
    expect(email.source).toMatchObject({ messageId: 'm-1', providerAccountId: 'acct-outlook-1', replySupported: true })
    expect(email.id).toBe('outlook:m-1')
    expect(parseEmailKey(email.id)).toEqual({ provider: 'outlook', id: 'm-1' })
  })

  it('does not present the provider snippet as a secretary summary, or invent a work status or action items', () => {
    const email = toInboxEmail(mail())
    expect(email.summaryKind).toBe('snippet')
    expect(email.summary).toBe('Could you send the pack by Thursday?')
    expect(email.status).toBe('untracked')
    expect(email.actionItems).toEqual([])
    expect(email.draft).toBeNull()
    expect(email.requestId).toBeNull()
  })

  it('maps every triage category the backend can return', () => {
    const categories = ['meeting_request', 'needs_reply', 'action_item', 'informational', 'automated'] as const
    const mapped = categories.map(category => toInboxEmail(mail({ triage: { ...mail().triage, category } })).category)
    expect(mapped).toEqual(['meeting', 'reply_needed', 'action_required', 'fyi', 'low_priority'])
  })

  it('keeps Gmail and Outlook ids apart even when they are equal', () => {
    expect(emailKey('gmail', 'abc')).not.toBe(emailKey('outlook', 'abc'))
    expect(parseEmailKey('req-001')).toBeNull()
    expect(parseEmailKey('slack:1')).toBeNull()
  })

  it('reads a sender with or without a display name and never invents a name', () => {
    expect(parseSender('"Dana Haddad" <dana@example.test>')).toEqual({ name: 'Dana Haddad', email: 'dana@example.test' })
    expect(parseSender('dana@example.test')).toEqual({ name: 'dana@example.test', email: 'dana@example.test' })
    expect(parseSender('<dana@example.test>')).toEqual({ name: 'dana@example.test', email: 'dana@example.test' })
    expect(parseSender('')).toEqual({ name: 'Unknown sender', email: '' })
  })

  it('treats an unknown priority as normal rather than urgent', () => {
    expect(['urgent', 'HIGH', 'medium', 'low', '', undefined, 'p0'].map(p => toPriority(p))).toEqual(['urgent', 'high', 'normal', 'low', 'normal', 'normal', 'normal'])
  })
})

describe('account mapping', () => {
  const connections: DeskConnections = {
    email: 'exec@example.test',
    ready: false,
    mailboxes: [],
    capabilities: [
      { id: 'gmail', vendor: 'google', label: 'Gmail', state: 'connected', email: 'exec@gmail.example', reason: null, loginPath: '/auth/login' },
      { id: 'google_calendar', vendor: 'google', label: 'Google Calendar', state: 'reconnect_required', email: 'exec@gmail.example', reason: 'token_expired', loginPath: '/auth/login' },
      { id: 'outlook_mail', vendor: 'microsoft', label: 'Outlook Mail', state: 'disconnected', email: null, reason: null, loginPath: '/auth/outlook/login' },
      { id: 'outlook_calendar', vendor: 'microsoft', label: 'Outlook Calendar', state: 'unavailable', email: null, reason: 'not_configured', loginPath: '/auth/outlook/login' },
    ],
  }

  it('keeps all four capabilities with the state, reason and login path the backend gave', () => {
    const accounts = toAccounts(connections)
    expect(accounts.map(a => [a.kind, a.provider, a.status])).toEqual([
      ['mail', 'gmail', 'connected'],
      ['calendar', 'google', 'reconnect_required'],
      ['mail', 'outlook', 'disconnected'],
      ['calendar', 'outlook', 'unavailable'],
    ])
    expect(accounts[1].reason).toBe('token_expired')
    expect(accounts[2].loginPath).toBe('/auth/outlook/login')
  })
})

describe('calendar mapping', () => {
  const entry = (over: Partial<CalendarEntry> = {}): CalendarEntry => ({ key: 'k1', event_id: 'ev-1', title: 'Budget review', start_time: '2026-11-16T09:00:00Z', end_time: '2026-11-16T10:00:00Z', provider_account_id: 'acct-g', account_email: 'exec@gmail.example', attendee_emails: ['dana@example.test'], ...over })

  it('keeps the event id and account needed for a later change', () => {
    const event = toAgendaEvent(entry(), 'google')!
    expect(event.provider).toBe('google')
    expect(event.source).toEqual({ eventId: 'ev-1', providerAccountId: 'acct-g', joinUrl: null })
    expect(event.attendees).toEqual([{ name: 'dana@example.test', email: 'dana@example.test' }])
  })

  it('drops an entry without a start or an end instead of placing it somewhere', () => {
    expect(toAgendaEvent(entry({ start_time: undefined }), 'google')).toBeNull()
    expect(toAgendaEvent(entry({ end_time: undefined }), 'google')).toBeNull()
  })

  it('marks a clash only between different calendars, and never for an all-day entry', () => {
    const google = toAgendaEvent(entry(), 'google')!
    const sameCalendar = toAgendaEvent(entry({ key: 'k2', event_id: 'ev-2', start_time: '2026-11-16T09:30:00Z', end_time: '2026-11-16T10:30:00Z' }), 'google')!
    const outlook = toAgendaEvent(entry({ key: 'k3', event_id: 'ev-3', start_time: '2026-11-16T09:30:00Z', end_time: '2026-11-16T10:30:00Z', account_email: 'exec@contoso.example', calendar_provider: 'outlook' }), 'outlook')!
    const allDay = toAgendaEvent(entry({ key: 'k4', event_id: 'ev-4', start_time: '2026-11-16T00:00:00Z', end_time: '2026-11-17T00:00:00Z', all_day: true, account_email: 'exec@contoso.example' }), 'outlook')!
    const marked = markCrossCalendarConflicts([google, sameCalendar, outlook, allDay])
    expect(marked.find(e => e.id === google.id)!.conflictsWith).toEqual([outlook.id])
    expect(marked.find(e => e.id === outlook.id)!.conflictsWith.sort()).toEqual([google.id, sameCalendar.id].sort())
    expect(marked.find(e => e.id === allDay.id)!.conflictsWith).toEqual([])
  })

  it('asks for Monday to Monday in the user time zone, not the browser one', () => {
    // 23:30 UTC on Sunday is already Monday in Beirut.
    expect(weekRange(Date.parse('2026-11-15T23:30:00Z'), 'Asia/Beirut')).toEqual({ start: '2026-11-16', end: '2026-11-23' })
    expect(weekRange(Date.parse('2026-11-15T23:30:00Z'), 'UTC')).toEqual({ start: '2026-11-09', end: '2026-11-16' })
  })
})

describe('task and reminder mapping', () => {
  it('leaves discarded tasks out and maps completed ones to done', () => {
    expect(toWorkTask({ id: 1, title: 'A', status: 'discarded' })).toBeNull()
    expect(toWorkTask({ id: 2, title: 'B', status: 'completed', updated_at: '2026-11-13T10:00:00Z' })).toMatchObject({ id: '2', status: 'done', completedAt: '2026-11-13T10:00:00Z' })
    expect(toWorkTask({ id: 3, title: 'C', status: 'active', source_item_id: 9 })).toMatchObject({ status: 'open', origin: 'extracted', sourceEmailId: null, dueAt: null })
  })

  it('does not show a reminder that has no time', () => {
    expect(toReminder({ id: 1, title: 'Call Karim' })).toBeNull()
    expect(toReminder({ id: 1, title: 'Call Karim', remind_at: '2026-11-14T09:00:00Z', status: 'scheduled' })).toMatchObject({ id: '1', status: 'scheduled' })
    expect(toReminder({ id: 2, remind_at: '2026-11-14T09:00:00Z', status: 'cancelled' })!.status).toBe('dismissed')
  })
})

describe('work stages', () => {
  it('maps every status Scriba defines, and shows only stages the backend reports', () => {
    for (const status of CHAT_TOOL_STATUSES) expect(WORK_STAGES[stageOf(status)].supported, status).toBe(true)
    expect(CHAT_TOOL_STATUSES.map(stageOf)).toEqual([
      'planning', 'needs_info', 'planning', 'awaiting_approval', 'executing', 'executing', 'completed', 'partially_completed', 'failed', 'cancelled', 'unsupported',
    ])
  })

  it('does not claim verification, awaited replies or escalation, which the backend cannot report', () => {
    for (const stage of ['received', 'verifying', 'awaiting_reply', 'escalated'] as const) expect(WORK_STAGES[stage].supported).toBe(false)
  })

  it('never turns an unknown status into a finished one', () => {
    expect(stageOf('something_new')).toBe('planning')
  })

  it('builds cards with the request and the assistant text that led to them, and separates reads from work', () => {
    const cards = cardsOfConversation({ id: 2, title: 'Monday' }, [
      { id: 1, conversation_id: 2, role: 'user', content: 'Tell Dana I will send it Thursday', status: 'complete' },
      { id: 3, conversation_id: 2, role: 'assistant', content: 'I drafted a reply to Dana.', status: 'complete', tool_calls: [call(), call({ id: 8, tool_name: 'show_agenda', status: 'executed' }), call({ id: 9, status: 'failed' }), call({ id: 10, status: 'partially_executed' })] },
    ])
    expect(cards.map(c => c.requestText)).toEqual(Array(4).fill('Tell Dana I will send it Thursday'))
    expect(cards[0].assistantText).toBe('I drafted a reply to Dana.')
    expect(cards.filter(isWorkItem).map(c => c.toolCall.id)).toEqual([7, 9, 10])
    expect(cards.filter(needsUser).map(c => c.toolCall.id)).toEqual([7])
    expect(cards.filter(needsIntervention).map(c => c.toolCall.id)).toEqual([9, 10])
  })
})

describe('write policy', () => {
  const off = writePolicyFrom({ ok: true, service: 'scriba-desk-overlay', version: '0.2.0', scribaCommit: null, capabilities: [], writes: false })
  const on = writePolicyFrom({ ok: true, service: 'scriba-desk-overlay', version: '0.3.0', scribaCommit: null, capabilities: [], writes: false, externalWrites: { enabled: true }, chatScope: 'enforced' })

  it('is off for every backend that does not explicitly report verified external writes', () => {
    expect(off.externalWritesEnabled).toBe(false)
    expect(writePolicyFrom(null).externalWritesEnabled).toBe(false)
    expect(writePolicyFrom(undefined).externalWritesEnabled).toBe(false)
    // A truthy-looking value is not enough: it must be exactly true.
    expect(writePolicyFrom({ externalWrites: { enabled: 'yes' } } as never).externalWritesEnabled).toBe(false)
    expect(on).toMatchObject({ externalWritesEnabled: true, chatScopeEnforced: true, executionMode: null })
  })

  it('blocks approval of mail and calendar actions while external writes are off, and says why', () => {
    for (const tool of ['send_email', 'draft_email_reply', 'create_calendar_event', 'update_calendar_event', 'cancel_calendar_event']) {
      expect(toolEffect(tool)).toBe('external_write')
      expect(approvalGate(tool, off).allowed, tool).toBe(false)
      expect(approvalGate(tool, off).reason).toMatch(/switched off/)
      expect(approvalGate(tool, on).allowed, tool).toBe(true)
    }
  })

  it('allows tasks and reminders, which stay inside Scriba', () => {
    expect(approvalGate('create_task', off)).toEqual({ allowed: true, reason: null })
    expect(approvalGate('create_reminder', off)).toEqual({ allowed: true, reason: null })
  })

  it('never approves an excluded integration or a tool it does not know, even when writes are on', () => {
    for (const tool of ['send_slack_message', 'send_teams_message', 'create_jira_issue', 'run_automation_with_file', 'brand_new_tool']) {
      expect(approvalGate(tool, on).allowed, tool).toBe(false)
    }
    expect(toolEffect('brand_new_tool')).toBe('unknown')
  })
})

describe('describing an action', () => {
  it('shows who receives an email, from which account, and the exact text', () => {
    const d = describeAction(call({ input: { to: 'dana@example.test, omar@example.test', cc: ['legal@example.test'], subject: 'Board pack', body: 'Thursday works.', provider: 'outlook', provider_account_id: 'acct-outlook-1', thread_id: 't-1' } }))
    expect(d.title).toBe('Send an email')
    expect(d.recipients).toEqual(['dana@example.test', 'omar@example.test', 'legal@example.test'])
    expect(d.provider).toBe('outlook')
    expect(d.account).toBe('acct-outlook-1')
    expect(d.body).toBe('Thursday works.')
    expect(d.target).toBe('t-1')
  })

  it('says a meeting-bearing email is a calendar invitation, because that is what will run', () => {
    const d = describeAction(call({ input: { to: 'dana@example.test', subject: 'Sync', start: '2026-11-17T09:00:00+02:00', end: '2026-11-17T09:30:00+02:00' }, output: { operation: { kind: 'calendar_invitation', organizer_account: 'exec@gmail.example' } } }))
    expect(d.title).toBe('Send a calendar invitation')
    expect(d.kind).toBe('calendar_create')
    expect(d.account).toBe('exec@gmail.example')
    expect(d.when).toEqual({ start: '2026-11-17T09:00:00+02:00', end: '2026-11-17T09:30:00+02:00', timezone: '' })
  })

  it('lists the fields a calendar update changes and the event it applies to', () => {
    const d = describeAction(call({ tool_name: 'update_calendar_event', input: { event_id: 'ev-9', start: '2026-11-18T10:00:00Z', end: '2026-11-18T11:00:00Z', location: 'Room 4' } }))
    expect(d.target).toBe('ev-9')
    expect(d.changes).toEqual([{ field: 'start', value: '2026-11-18T10:00:00Z' }, { field: 'end', value: '2026-11-18T11:00:00Z' }, { field: 'location', value: 'Room 4' }])
  })

  it('reports each part of a partial outcome, and keeps unknown apart from failed and done', () => {
    const d = describeAction(call({ status: 'partially_executed', output: { outcome: { components: [
      { kind: 'calendar_event', status: 'created', event_id: 'ev-1', organizer_account: 'exec@gmail.example' },
      { kind: 'email', status: 'failed', message: 'Mailbox refused the message' },
      { kind: 'conference', status: 'unknown' },
      { kind: 'reminder', status: 'not_requested' },
    ] } } }))
    expect(d.outcome.map(row => row.state)).toEqual(['ok', 'failed', 'unknown', 'skipped'])
    expect(d.outcome[1].detail).toContain('Mailbox refused')
    expect(d.outcome[0].detail).toContain('ev-1')
  })

  it('reads the availability finding, including an unknown result and a user override', () => {
    const conflict = describeAction(call({ tool_name: 'create_calendar_event', status: 'needs_info', output: { error_code: 'calendar_conflict', message: 'This time conflicts with Budget review.', availability: { free: false, complete: true, conflicts: [{ title: 'Budget review', provider: 'outlook', account: 'exec@contoso.example', start: '2026-11-17T09:00:00+02:00', end: '2026-11-17T10:00:00+02:00' }], calendars: [] } } }))
    expect(conflict.availability).toMatchObject({ free: false, overriddenByUser: false })
    expect(conflict.availability!.conflicts[0].title).toBe('Budget review')
    expect(heldByAvailability(conflict)).toBe(true)

    const unknown = describeAction(call({ tool_name: 'create_calendar_event', status: 'needs_info', output: { error_code: 'availability_unknown', availability: { free: null, complete: false, conflicts: [], calendars: [{ provider: 'google', account: 'exec@gmail.example', ok: false, error: 'reconnect_required' }] } } }))
    expect(unknown.availability!.free).toBeNull()
    expect(unknown.availability!.unreadable).toEqual([{ provider: 'google', account: 'exec@gmail.example', error: 'reconnect_required' }])

    const missingField = describeAction(call({ status: 'needs_info', output: { message: 'Who should receive this?' } }))
    expect(heldByAvailability(missingField)).toBe(false)
  })

  it('hides nothing: input it does not recognise is listed as other details', () => {
    const d = describeAction(call({ input: { to: 'dana@example.test', subject: 'x', reply_mode: 'reply_all', attachments: [{ filename: 'pack.pdf' }] } }))
    expect(d.otherInput.map(i => i.field)).toEqual(['reply_mode', 'attachments'])
  })
})
