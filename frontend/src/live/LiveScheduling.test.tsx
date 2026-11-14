/**
 * The scheduling workspace, with the backend replaced at the client-function boundary.
 * The rule under test throughout: availability that was not fully read is unknown, never free.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClientError } from '../api/client'
import type { ProviderDescriptor, ProviderStatusPayload } from '../api/contract'
import type { DeskAvailability, DeskHealth, DeskSlotCheck } from '../api/desk'

vi.mock('../api/scriba', async original => ({
  ...(await original<typeof import('../api/scriba')>()),
  fetchProviderStatus: vi.fn(),
  fetchCalendarEvents: vi.fn(),
}))
vi.mock('../api/desk', async original => ({
  ...(await original<typeof import('../api/desk')>()),
  fetchDeskHealth: vi.fn(),
  fetchDeskConnections: vi.fn(),
  fetchDeskInbox: vi.fn(),
  fetchDeskBriefing: vi.fn(),
  fetchDeskRuns: vi.fn(),
  fetchDeskRun: vi.fn(),
  fetchDeskAvailability: vi.fn(),
  checkDeskSlot: vi.fn(),
}))
vi.mock('./scribaApi', async original => ({
  ...(await original<typeof import('./scribaApi')>()),
  fetchChatConversations: vi.fn(),
  fetchChatMessages: vi.fn(),
  fetchTasks: vi.fn(),
  fetchReminders: vi.fn(),
  fetchDrafts: vi.fn(),
}))

import App from '../App'
import { checkDeskSlot, fetchDeskAvailability, fetchDeskBriefing, fetchDeskConnections, fetchDeskHealth, fetchDeskInbox, fetchDeskRuns } from '../api/desk'
import { fetchCalendarEvents, fetchProviderStatus } from '../api/scriba'
import { addDays, byDay, calendarProblem, localEnd, offeredSlots, rangeFor, slotVerdict, weekdayNames } from './scheduling'
import { fetchChatConversations, fetchChatMessages, fetchDrafts, fetchReminders, fetchTasks } from './scribaApi'

const provider = (): ProviderDescriptor => ({ active: false, connected: false, available: true, configured: true, status: 'disconnected', reason: null })
const signedIn = () =>
  ({ authorized: true, email: 'exec@example.test', name: 'Rana Khoury', providers: { gmail: provider(), google_calendar: provider(), outlook: provider(), outlook_calendar: provider() } }) as unknown as ProviderStatusPayload

const GOOGLE = { provider: 'google' as const, account: 'exec@gmail.example', ok: true, error: null, busy_count: 2 }
const OUTLOOK = { provider: 'outlook' as const, account: 'exec@contoso.example', ok: true, error: null, busy_count: 1 }

const availability = (over: Partial<DeskAvailability> = {}): DeskAvailability => ({
  timezone: 'Asia/Beirut',
  range: { start: '2026-11-16T00:00:00+02:00', end: '2026-11-21T00:00:00+02:00' },
  duration_minutes: 30,
  buffer_minutes: 10,
  working_hours: { start: '09:00', end: '18:00', weekdays: [0, 1, 2, 3, 4] },
  calendars: [GOOGLE, OUTLOOK],
  complete: true,
  reason: null,
  busy: [
    { start: '2026-11-16T10:00:00+02:00', end: '2026-11-16T11:00:00+02:00', provider: 'google', account: 'exec@gmail.example', title: null },
    { start: '2026-11-16T10:30:00+02:00', end: '2026-11-16T11:30:00+02:00', provider: 'outlook', account: 'exec@contoso.example', title: 'Board prep' },
  ],
  busy_merged: [{ start: '2026-11-16T10:00:00+02:00', end: '2026-11-16T11:30:00+02:00' }],
  existing_conflicts: [
    {
      start: '2026-11-16T10:30:00+02:00',
      end: '2026-11-16T11:00:00+02:00',
      between: [
        { start: '2026-11-16T10:00:00+02:00', end: '2026-11-16T11:00:00+02:00', provider: 'google', account: 'exec@gmail.example', title: null },
        { start: '2026-11-16T10:30:00+02:00', end: '2026-11-16T11:30:00+02:00', provider: 'outlook', account: 'exec@contoso.example', title: 'Board prep' },
      ],
    },
  ],
  slots: [
    { start: '2026-11-16T14:00:00+02:00', end: '2026-11-16T14:30:00+02:00' },
    { start: '2026-11-17T09:00:00+02:00', end: '2026-11-17T09:30:00+02:00' },
  ],
  ...over,
})

const slotCheck = (over: Partial<DeskSlotCheck> = {}): DeskSlotCheck => ({
  timezone: 'Asia/Beirut',
  slot: { start: '2026-11-16T14:00:00+02:00', end: '2026-11-16T14:30:00+02:00' },
  buffer_minutes: 10,
  free: true,
  complete: true,
  reason: null,
  within_working_hours: true,
  conflicts: [],
  calendars: [GOOGLE, OUTLOOK],
  ...over,
})

function renderApp(hash: string) {
  window.location.hash = hash
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchProviderStatus).mockResolvedValue(signedIn())
  vi.mocked(fetchDeskHealth).mockResolvedValue({ ok: true, service: 'scriba-desk-overlay', version: '0.2.0', scribaCommit: null, capabilities: [], writes: false } as DeskHealth)
  vi.mocked(fetchDeskConnections).mockResolvedValue({ email: 'exec@example.test', capabilities: [], ready: true, mailboxes: [] })
  vi.mocked(fetchDeskInbox).mockResolvedValue({ account: 'x', items: [], sources: [], counts: { meeting_request: 0, needs_reply: 0, action_item: 0, informational: 0, automated: 0 }, complete: true })
  vi.mocked(fetchDeskBriefing).mockRejectedValue(new ApiClientError('not needed here'))
  vi.mocked(fetchDeskRuns).mockResolvedValue({ account: 'x', runs: [] })
  vi.mocked(fetchChatConversations).mockResolvedValue([])
  vi.mocked(fetchChatMessages).mockResolvedValue({ conversation: { id: 1, title: '', status: 'active' }, messages: [] })
  vi.mocked(fetchTasks).mockResolvedValue({ tasks: [] })
  vi.mocked(fetchReminders).mockResolvedValue([])
  vi.mocked(fetchDrafts).mockResolvedValue([])
  vi.mocked(fetchCalendarEvents).mockResolvedValue({ meetings: [], timezone: 'Asia/Beirut' } as never)
  vi.mocked(fetchDeskAvailability).mockResolvedValue(availability())
})

afterEach(() => {
  cleanup()
  window.location.hash = ''
})

describe('scheduling rules', () => {
  it('offers slots only from a complete read, even if the payload carries some', () => {
    const slots = availability().slots
    expect(offeredSlots({ complete: true, slots })).toHaveLength(2)
    expect(offeredSlots({ complete: false, slots })).toEqual([])
  })

  it('reads a slot check as free only when the backend says true', () => {
    expect(slotVerdict({ free: true })).toBe('free')
    expect(slotVerdict({ free: false })).toBe('conflict')
    expect(slotVerdict({ free: null })).toBe('unknown')
    expect(slotVerdict({ free: undefined as unknown as null })).toBe('unknown')
  })

  it('names working days the way the backend numbers them, Monday first', () => {
    expect(weekdayNames([0, 1, 2, 3, 4])).toBe('Monday to Friday')
    expect(weekdayNames([6, 0])).toBe('Monday, Sunday')
    expect(weekdayNames([])).toBe('every day')
  })

  it('asks for whole days without an offset and never more than 31', () => {
    expect(rangeFor('2026-11-16', 5)).toEqual({ start: '2026-11-16T00:00:00', end: '2026-11-21T00:00:00' })
    expect(rangeFor('2026-11-16', 90).end).toBe('2026-12-17T00:00:00')
    expect(addDays('2026-12-30', 3)).toBe('2027-01-02')
    expect(localEnd('2026-11-16T23:45', 30)).toBe('2026-11-17T00:15')
    expect(localEnd('not a time', 30)).toBeNull()
  })

  it('says what is wrong with a calendar, and groups by day in order', () => {
    expect(calendarProblem(GOOGLE)).toBeNull()
    expect(calendarProblem({ ...OUTLOOK, ok: false, error: 'reconnect_required' })).toBe('needs to be reconnected')
    expect(calendarProblem({ ...OUTLOOK, ok: false, error: 'something_new' as never })).toBe('failed (something_new)')
    expect(byDay([{ start: 'a1' }, { start: 'a2' }, { start: 'b1' }], iso => iso[0]).map(group => [group.day, group.items.length])).toEqual([['a', 2], ['b', 1]])
  })

  it('relies only on fields the backend builds', () => {
    const source = readFileSync(resolve(__dirname, '../../../backend/desk_overlay/service.py'), 'utf8')
    const body = (name: string, next: string) => source.slice(source.indexOf(`def ${name}(`), source.indexOf(`def ${next}(`))
    for (const key of ['timezone', 'range', 'duration_minutes', 'buffer_minutes', 'working_hours', 'calendars', 'complete', 'reason', 'busy', 'existing_conflicts', 'slots']) expect(body('availability', 'slot_check'), key).toContain(`"${key}"`)
    for (const key of ['timezone', 'slot', 'buffer_minutes', 'free', 'complete', 'reason', 'within_working_hours', 'conflicts', 'calendars']) expect(body('slot_check', 'inbox_item'), key).toContain(`"${key}"`)
    // The two rules the screen depends on are the backend's, not ours.
    expect(body('availability', 'slot_check')).toContain(') if complete else []')
    expect(body('slot_check', 'inbox_item')).toContain('False if conflicts else (True if complete else None)')
  })
})

describe('find a time', () => {
  it('is reached from the calendar and shows free times, busy time, existing double bookings and how it was read', async () => {
    const user = userEvent.setup()
    renderApp('#/calendar')
    await user.click(await screen.findByRole('link', { name: 'Find a time' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Find a time' })).toBeInTheDocument()

    const call = vi.mocked(fetchDeskAvailability).mock.calls[0][0]
    expect(call).toMatchObject({ max_slots: 20, duration_minutes: undefined })
    expect(call.start).toMatch(/^\d{4}-\d{2}-\d{2}T00:00:00$/) // no offset: the backend reads it in the user's zone
    expect((Date.parse(`${call.end}Z`) - Date.parse(`${call.start}Z`)) / 86_400_000).toBe(5)

    const free = await screen.findByRole('region', { name: 'Free times' })
    expect(within(free).getByRole('list', { name: 'Free times on Mon 16 Nov' })).toHaveTextContent('14:00 to 14:30')
    expect(within(free).getByRole('list', { name: 'Free times on Tue 17 Nov' })).toHaveTextContent('09:00 to 09:30')
    expect(free).toHaveTextContent('30 minutes, 10 minutes clear on each side, inside working hours')

    const conflicts = screen.getByRole('region', { name: 'Existing conflicts' })
    expect(conflicts).toHaveTextContent('Already double-booked (1)')
    expect(conflicts).toHaveTextContent('Board prep')
    expect(conflicts).toHaveTextContent('exec@gmail.example')

    const read = screen.getByRole('region', { name: 'How this was read' })
    expect(read).toHaveTextContent('Asia/Beirut')
    expect(read).toHaveTextContent('09:00 to 18:00, Monday to Friday')
    expect(within(read).getByRole('list', { name: 'Calendars read' })).toHaveTextContent('exec@contoso.example read, 1 busy period')
    expect(screen.getByRole('region', { name: 'Busy time' })).toHaveTextContent('Google reports busy time without titles')
  })

  it('offers no time when a calendar could not be read, and says availability is unknown rather than empty', async () => {
    vi.mocked(fetchDeskAvailability).mockResolvedValue(
      availability({ complete: false, reason: 'calendar_unreadable', calendars: [GOOGLE, { ...OUTLOOK, ok: false, error: 'reconnect_required', busy_count: 0 }], busy: [], existing_conflicts: [], slots: availability().slots }),
    )
    renderApp('#/calendar/find-a-time')
    const warning = await screen.findByRole('alert', { name: 'Availability is not known' })
    expect(warning).toHaveTextContent('A connected calendar could not be read')
    expect(warning).toHaveTextContent('Its availability is unknown, not free.')
    const free = screen.getByRole('region', { name: 'Free times' })
    expect(free).toHaveTextContent('None offered. A time is offered only when every connected calendar was read.')
    expect(within(free).queryByRole('button')).not.toBeInTheDocument() // slots in the payload are ignored
    expect(screen.getByRole('region', { name: 'Busy time' })).toHaveTextContent('Nothing was read. That does not mean the calendars are empty.')
    expect(within(screen.getByRole('region', { name: 'How this was read' })).getByRole('list', { name: 'Calendars read' })).toHaveTextContent('exec@contoso.example needs to be reconnected: availability unknown')
  })

  it('says when no calendar is connected, and shows a refused request as a failure', async () => {
    vi.mocked(fetchDeskAvailability).mockResolvedValue(availability({ complete: false, reason: 'no_calendar_connected', calendars: [], busy: [], existing_conflicts: [], slots: [] }))
    renderApp('#/calendar/find-a-time')
    expect(await screen.findByRole('alert', { name: 'Availability is not known' })).toHaveTextContent('No calendar is connected')
    cleanup()

    vi.mocked(fetchDeskAvailability).mockRejectedValue(new ApiClientError('Unknown time zone: Mars/Olympus', { status: 400 }))
    renderApp('#/calendar/find-a-time')
    expect(await screen.findByText(/Availability could not be read: Unknown time zone: Mars\/Olympus/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Free times' })).not.toBeInTheDocument()
  })

  it('reads again when the range or the meeting length changes', async () => {
    const user = userEvent.setup()
    renderApp('#/calendar/find-a-time')
    await screen.findByRole('region', { name: 'Free times' })
    await user.selectOptions(screen.getByLabelText('Meeting length'), '60')
    await waitFor(() => expect(vi.mocked(fetchDeskAvailability).mock.calls.at(-1)![0].duration_minutes).toBe(60))
    await user.selectOptions(screen.getByLabelText('Days to look at'), '14')
    await waitFor(() => {
      const last = vi.mocked(fetchDeskAvailability).mock.calls.at(-1)![0]
      expect((Date.parse(`${last.end}Z`) - Date.parse(`${last.start}Z`)) / 86_400_000).toBe(14)
    })
  })

  it('checks one time: free, a certain conflict, and unknown are three different answers', async () => {
    const user = userEvent.setup()
    vi.mocked(checkDeskSlot).mockResolvedValueOnce(slotCheck())
    renderApp('#/calendar/find-a-time')
    const free = await screen.findByRole('region', { name: 'Free times' })
    await user.click(within(free).getByRole('button', { name: 'Use Mon 16 Nov, 14:00 to 14:30' }))
    const form = screen.getByRole('form', { name: 'Check one time' })
    expect(within(form).getByLabelText('Start (Asia/Beirut)')).toHaveValue('2026-11-16T14:00')
    await user.click(within(form).getByRole('button', { name: 'Check this time' }))
    // Sent without an offset, so the backend reads it in the user's Scriba zone.
    expect(checkDeskSlot).toHaveBeenCalledWith({ start: '2026-11-16T14:00:00', end: '2026-11-16T14:30:00' })
    expect(await within(form).findByRole('status', { name: 'Result of the check' })).toHaveTextContent('Free on every connected calendar')
    expect(within(form).getByRole('button', { name: 'Take this time to the secretary chat' })).toBeInTheDocument()

    vi.mocked(checkDeskSlot).mockResolvedValueOnce(
      slotCheck({ free: false, conflicts: [{ start: '2026-11-16T14:00:00+02:00', end: '2026-11-16T15:00:00+02:00', provider: 'outlook', account: 'exec@contoso.example', title: 'Budget review' }] }),
    )
    await user.click(within(form).getByRole('button', { name: 'Check this time' }))
    const conflict = await within(form).findByText('Not free: it collides with an existing commitment')
    expect(conflict.closest('[role=status]')).toHaveTextContent('Budget review')
    expect(within(form).queryByRole('button', { name: 'Take this time to the secretary chat' })).not.toBeInTheDocument()

    vi.mocked(checkDeskSlot).mockResolvedValueOnce(slotCheck({ free: null, complete: false, reason: 'calendar_unreadable', within_working_hours: false, calendars: [GOOGLE, { ...OUTLOOK, ok: false, error: 'provider_error', busy_count: 0 }] }))
    await user.click(within(form).getByRole('button', { name: 'Check this time' }))
    const unknown = (await within(form).findByText('Unknown: a calendar could not be read')).closest('[role=status]') as HTMLElement
    expect(unknown).toHaveTextContent('that is not the same as free')
    expect(unknown).toHaveTextContent('exec@contoso.example did not answer: availability unknown')
    expect(unknown).toHaveTextContent('This is outside your working hours.')
    expect(unknown).not.toHaveTextContent('Free on every connected calendar')
    expect(within(form).queryByRole('button', { name: 'Take this time to the secretary chat' })).not.toBeInTheDocument()
  })

  it('does not turn a failed check into an answer', async () => {
    const user = userEvent.setup()
    vi.mocked(checkDeskSlot).mockRejectedValue(new ApiClientError('Request timed out'))
    renderApp('#/calendar/find-a-time')
    const free = await screen.findByRole('region', { name: 'Free times' })
    await user.click(within(free).getByRole('button', { name: 'Use Tue 17 Nov, 09:00 to 09:30' }))
    const form = screen.getByRole('form', { name: 'Check one time' })
    await user.click(within(form).getByRole('button', { name: 'Check this time' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent('The time could not be checked: Request timed out. That is not an answer about the time.')
    expect(within(form).queryByRole('status', { name: 'Result of the check' })).not.toBeInTheDocument()
  })
})
