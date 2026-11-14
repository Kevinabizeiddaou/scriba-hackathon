/**
 * Where the live workspace reads the calendar and the tasks from. In a sandbox they are the
 * sandbox world's own records (GET /desk/memory, or the briefing on a backend without that
 * route), never Scriba's seeded stores; outside one they are Scriba's. The backend is replaced at
 * the client-function boundary.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DeskBriefing, DeskConnections } from '../api/desk'

vi.mock('../api/scriba', async original => ({
  ...(await original<typeof import('../api/scriba')>()),
  fetchCalendarEvents: vi.fn(),
}))
vi.mock('../api/desk', async original => ({
  ...(await original<typeof import('../api/desk')>()),
  fetchDeskBriefing: vi.fn(),
  fetchDeskConnections: vi.fn(),
}))
vi.mock('./deskContract', async original => ({
  ...(await original<typeof import('./deskContract')>()),
  fetchDeskMemory: vi.fn(),
}))
vi.mock('./scribaApi', async original => ({
  ...(await original<typeof import('./scribaApi')>()),
  fetchTasks: vi.fn(),
  fetchReminders: vi.fn(),
  completeTask: vi.fn(),
  cancelReminder: vi.fn(),
}))

import { fetchDeskBriefing, fetchDeskConnections } from '../api/desk'
import { fetchCalendarEvents } from '../api/scriba'
import { WorkspaceUnavailable } from '../harness/workspace'
import { fetchDeskMemory, type DeskMemory } from './deskContract'
import { LiveDesk, ScribaWorkspace } from './liveDesk'
import { completeTask, fetchReminders, fetchTasks } from './scribaApi'

const memory = (over: Partial<DeskMemory> = {}): DeskMemory => ({
  account: 'exec@desk.example',
  asOf: '2026-11-16T07:00:00+00:00',
  meetings: {
    ok: true,
    items: [
      { id: 'evt-1', title: 'Budget review', start: '2026-11-17T10:00:00+02:00', end: '2026-11-17T11:00:00+02:00', attendees: ['sofia@lumen.example'], organizer: true, provider: 'google' },
      { id: 'evt-2', title: '', start: '2026-11-18T09:00:00+02:00', end: '2026-11-18T09:30:00+02:00', attendees: [], organizer: false, provider: 'outlook_calendar' },
    ],
  },
  tasks: { ok: true, items: [{ id: 't-9', title: 'Send the board pack', dueAt: '2026-11-19T15:00:00Z', overdue: false }, { id: 't-10', title: null, dueAt: null, overdue: false }] },
  waiting: { ok: true, items: [] },
  ...over,
})

const briefing = (over: Partial<DeskBriefing> = {}): DeskBriefing =>
  ({
    account: 'exec@desk.example', generated_at: '2026-11-16T07:00:00Z', headline: '', counts: { meeting_requests: 0, needs_reply: 0, action_items: 0, meetings_today: 1, open_tasks: 1, tasks_due_today: 0, reminders: 0 },
    needs_attention: [], tasks_due_today: [], reminders: [], timezone: 'Asia/Beirut', inbox_complete: true, sources: [], unavailable: [],
    meetings_today: [{ event_id: 'evt-5', title: 'Stand-up', start_time: '2026-11-16T09:00:00+02:00', end_time: '2026-11-16T09:15:00+02:00', calendar_provider: 'google', attendee_emails: ['omar@lumen.example'] }],
    open_tasks: [{ id: 5, title: 'Prepare board slides', due_at: null, effective_priority: 'high' }],
    ...over,
  }) as DeskBriefing

const connections = (): DeskConnections => ({
  email: 'exec@desk.example', ready: true, mailboxes: [],
  capabilities: [{ id: 'google_calendar', vendor: 'google', label: 'Google Calendar', state: 'connected', email: 'exec@gmail.example', reason: null, loginPath: '/auth/login' }],
})

const NOW = Date.parse('2026-11-16T07:00:00Z') // a Monday
const open = () => {
  const desk = new LiveDesk({ email: 'exec@desk.example', name: 'Rana Khoury' }, 'http://localhost:8000')
  return { desk, workspace: new ScribaWorkspace(desk, () => NOW) }
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchDeskConnections).mockResolvedValue(connections())
  vi.mocked(fetchCalendarEvents).mockResolvedValue({ meetings: [], timezone: 'Asia/Beirut' })
  vi.mocked(fetchTasks).mockResolvedValue({ tasks: [{ id: 5, title: 'A task in Scriba', status: 'active' }] })
  vi.mocked(fetchReminders).mockResolvedValue([])
})

describe('outside a sandbox', () => {
  it("reads Scriba's own calendar and tasks, for the week asked for or the one that contains now", async () => {
    const { workspace } = open()
    expect(workspace.inSandbox).toBe(false)
    await workspace.listAgenda()
    expect(fetchCalendarEvents).toHaveBeenLastCalledWith('google', { start: '2026-11-16', end: '2026-11-23' })
    await workspace.listAgenda({ start: '2026-11-23', end: '2026-11-30' })
    expect(fetchCalendarEvents).toHaveBeenLastCalledWith('google', { start: '2026-11-23', end: '2026-11-30' })
    expect(workspace.calendarSource).toBe('scriba')
    expect((await workspace.listTasks()).map(task => task.title)).toEqual(['A task in Scriba'])
    expect(workspace.tasksSource).toBe('scriba')
    expect(fetchDeskMemory).not.toHaveBeenCalled()
  })
})

describe('in a sandbox', () => {
  it("shows the sandbox world's meetings and tasks, and asks Scriba's stores for nothing", async () => {
    vi.mocked(fetchDeskMemory).mockResolvedValue(memory())
    const { workspace } = open()
    const told = vi.fn()
    workspace.subscribe(told)
    workspace.setSandbox(true)
    expect(workspace.inSandbox).toBe(true)
    expect(told).toHaveBeenCalledTimes(1) // every screen loads again
    workspace.setSandbox(true)
    expect(told).toHaveBeenCalledTimes(1) // saying it twice changes nothing

    const agenda = await workspace.listAgenda({ start: '2026-11-16', end: '2026-11-23' })
    expect(workspace.calendarSource).toBe('sandbox')
    expect(agenda.map(event => [event.id, event.title, event.provider, event.calendar])).toEqual([
      ['google:evt-1', 'Budget review', 'google', 'Sandbox Google Calendar'],
      ['outlook:evt-2', '(no title)', 'outlook', 'Sandbox Outlook Calendar'],
    ])
    expect(agenda[0].attendees).toEqual([{ name: 'sofia@lumen.example', email: 'sofia@lumen.example' }])

    const tasks = await workspace.listTasks()
    expect(workspace.tasksSource).toBe('sandbox')
    expect(tasks.map(task => [task.id, task.title, task.dueAt, task.status])).toEqual([['t-9', 'Send the board pack', '2026-11-19T15:00:00Z', 'open'], ['t-10', '(untitled task)', null, 'open']])

    expect(await workspace.listReminders()).toEqual([])
    expect(fetchCalendarEvents).not.toHaveBeenCalled()
    expect(fetchTasks).not.toHaveBeenCalled()
    expect(fetchReminders).not.toHaveBeenCalled()
  })

  it("falls back to today's briefing on a backend without /desk/memory, and says that is all it shows", async () => {
    vi.mocked(fetchDeskMemory).mockResolvedValue(null)
    vi.mocked(fetchDeskBriefing).mockResolvedValue(briefing())
    const { desk, workspace } = open()
    workspace.setSandbox(true)
    const agenda = await workspace.listAgenda()
    expect(workspace.calendarSource).toBe('sandbox_today')
    expect(agenda.map(event => [event.id, event.title, event.calendar])).toEqual([['google:evt-5', 'Stand-up', 'Sandbox Google Calendar']])
    // The briefing names the executive's zone, and the desk takes it.
    expect(desk.info.principal.timezone).toBe('Asia/Beirut')
    expect(desk.timeZoneSource).toBe('executive')
    const tasks = await workspace.listTasks()
    expect(tasks.map(task => [task.id, task.title, task.priority])).toEqual([['5', 'Prepare board slides', 'high']])
    expect(workspace.tasksSource).toBe('sandbox')
    expect(fetchTasks).not.toHaveBeenCalled()
  })

  it('reports a part that could not be read as unknown, never as empty', async () => {
    const { workspace } = open()
    workspace.setSandbox(true)
    vi.mocked(fetchDeskMemory).mockResolvedValue(memory({ meetings: { ok: false, items: [], error: 'timeout' }, tasks: { ok: false, items: [] } }))
    await expect(workspace.listAgenda()).rejects.toThrow('The sandbox calendar could not be read (timeout). It is unknown, not empty.')
    await expect(workspace.listTasks()).rejects.toThrow('The sandbox tasks could not be read (no reason given). They are unknown, not empty.')

    vi.mocked(fetchDeskMemory).mockResolvedValue(null)
    vi.mocked(fetchDeskBriefing).mockResolvedValue(briefing({ unavailable: ['agenda', 'tasks'] }))
    await expect(workspace.listAgenda()).rejects.toThrow('The sandbox calendar could not be read. It is unknown, not empty.')
    await expect(workspace.listTasks()).rejects.toThrow('They are unknown, not empty.')
  })

  it('does not change a task or a reminder from the lists, and goes back to Scriba when the sandbox ends', async () => {
    vi.mocked(fetchDeskMemory).mockResolvedValue(memory())
    const { workspace } = open()
    workspace.setSandbox(true)
    await expect(workspace.setTaskStatus('t-9', 'done')).rejects.toBeInstanceOf(WorkspaceUnavailable)
    await expect(workspace.setReminderStatus('r-1', 'dismissed')).rejects.toBeInstanceOf(WorkspaceUnavailable)
    expect(completeTask).not.toHaveBeenCalled()

    workspace.setSandbox(false)
    await workspace.listTasks()
    expect(fetchTasks).toHaveBeenCalledTimes(1)
    expect(workspace.tasksSource).toBe('scriba')
  })
})

describe("the desk's time zone and clock", () => {
  it("is the browser's zone until a backend response names the executive's", () => {
    const { desk } = open()
    const told = vi.fn()
    desk.subscribe(told)
    expect(desk.timeZoneSource).toBe('browser')
    const browserZone = desk.info.principal.timezone

    desk.setTimeZone(null)
    desk.setTimeZone('Not/AZone')
    expect(desk.timeZoneSource).toBe('browser')
    expect(desk.info.principal.timezone).toBe(browserZone)
    expect(told).not.toHaveBeenCalled()

    const zone = browserZone === 'Asia/Beirut' ? 'Europe/Paris' : 'Asia/Beirut'
    desk.setTimeZone(zone)
    expect(desk.timeZoneSource).toBe('executive')
    expect(desk.info.principal.timezone).toBe(zone)
    expect(told).toHaveBeenCalledTimes(1)
    desk.setTimeZone(zone)
    expect(told).toHaveBeenCalledTimes(1) // the same answer again is not news
  })

  it('tells the screens when the backend confirms the zone the browser already had', () => {
    const { desk } = open()
    const told = vi.fn()
    desk.subscribe(told)
    desk.setTimeZone(desk.info.principal.timezone)
    expect(desk.timeZoneSource).toBe('executive')
    expect(told).toHaveBeenCalledTimes(1) // "(browser zone)" comes off the shell
  })

  it("follows a sandbox world's fixed clock, and the real one when there is none", () => {
    const { desk } = open()
    const told = vi.fn()
    desk.subscribe(told)
    expect(desk.info.simulatedNow).toBeNull()
    desk.setSimulatedNow('2026-11-16T09:00:00+02:00')
    expect(desk.info.simulatedNow).toBe('2026-11-16T09:00:00+02:00')
    desk.setSimulatedNow('2026-11-16T09:00:00+02:00')
    expect(told).toHaveBeenCalledTimes(1)
    desk.setSimulatedNow(null)
    expect(desk.info.simulatedNow).toBeNull()
    expect(told).toHaveBeenCalledTimes(2)
  })
})
