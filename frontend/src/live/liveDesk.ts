/**
 * The live Desk: what the screens talk to once the user is signed in to Scriba.
 *
 * LiveDesk supplies who the desk belongs to (from Scriba's session) and refuses the
 * predecessor's contract-v1 operations (requests, runs, evaluation runs), because no Scriba
 * backend serves them. The live screens do not use those: chat and approvals run on Scriba's own
 * chat endpoints (src/live/scribaApi.ts).
 *
 * ScribaWorkspace maps the Desk overlay and Scriba's existing API to the workspace view models.
 * A request that fails rejects with its own error. Nothing here returns mock data.
 */
import { fetchCalendarEvents } from '../api/scriba'
import {
  fetchDeskBriefing,
  fetchDeskConnections,
  fetchDeskInbox,
  type DeskConnections,
  type DeskInbox,
} from '../api/desk'
import type { ProviderStatusPayload } from '../api/contract'
import { ApiError, type ApiInfo, type ExecutiveDeskApi } from '../harness/client'
import type { ActivityEntry, AgendaEvent, ConnectedAccount, FollowUp, InboxEmail, MeetingPrep, Reminder, WorkTask, WorkspaceApi } from '../harness/workspace'
import { WorkspaceUnavailable } from '../harness/workspace'
import { localParts } from '../lib/time'
import { fetchDeskMemory } from './deskContract'
import { markCrossCalendarConflicts, toAccounts, toAgendaEvent, toInboxEmail, toPriority, toReminder, toWorkTask } from './mappers'
import { cancelReminder, completeTask, fetchReminders, fetchTasks } from './scribaApi'

function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

function isValidTimeZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat('en-GB', { timeZone: zone })
    return true
  } catch {
    return false
  }
}

type Listener = () => void

export class LiveDesk implements ExecutiveDeskApi {
  private listeners = new Set<Listener>()
  private state: ApiInfo
  private zoneSource: 'executive' | 'browser' = 'browser'

  constructor(status: Pick<ProviderStatusPayload, 'email' | 'name'>, baseUrl: string) {
    const email = status.email ?? ''
    this.state = {
      name: 'Scriba',
      dataSource: 'live',
      baseUrl,
      // Until the backend reports the executive's time zone, times are shown in the browser's, and
      // the shell says so (timeZoneSource).
      principal: { name: status.name || email || 'Signed in', email, timezone: browserTimeZone() },
      simulatedNow: null,
      suggestedPrompts: [
        'What needs my attention today?',
        'When am I free for 30 minutes this week?',
        'Draft a reply to the latest email that needs one.',
        'Remind me tomorrow at 9 to review the board pack.',
      ],
      contractVersion: null,
    }
  }

  get info(): ApiInfo {
    return this.state
  }

  /** `executive` once a backend response has named the executive's zone; `browser` until then. */
  get timeZoneSource(): 'executive' | 'browser' {
    return this.zoneSource
  }

  /** Called when a backend response names the executive's time zone. */
  setTimeZone(zone: string | null | undefined): void {
    if (!zone || !isValidTimeZone(zone)) return
    const confirmed = this.zoneSource !== 'executive'
    this.zoneSource = 'executive'
    if (zone === this.state.principal.timezone) {
      if (confirmed) this.emit()
      return
    }
    this.state = { ...this.state, principal: { ...this.state.principal, timezone: zone } }
    this.emit()
  }

  /**
   * A sandbox world with a fixed clock has its own "now". The screens work out today, this week
   * and overdue from it (components/workspace.ts nowMs), so a simulated day reads as that day.
   * Null on a real backend and in a sandbox that runs on the real clock.
   */
  setSimulatedNow(now: string | null): void {
    if (now === this.state.simulatedNow) return
    this.state = { ...this.state, simulatedNow: now }
    this.emit()
  }

  emit(): void {
    for (const listener of [...this.listeners]) listener()
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  private unsupported(what: string): Promise<never> {
    return Promise.reject(new ApiError(`${what} is part of the evaluation contract, which the Scriba backend does not serve.`, null, 'not_supported'))
  }

  getMeta = () => this.unsupported('GET /meta')
  listRequests = () => this.unsupported('The request list')
  getRequest = () => this.unsupported('A request')
  processRequest = () => this.unsupported('Starting an agent run')
  getRun = () => this.unsupported('An agent run')
  listRuns = () => this.unsupported('The run list')
  listApprovals = () => this.unsupported('The contract approval list')
  decideApproval = () => this.unsupported('A contract approval decision')
  listConversations = () => this.unsupported('The contract conversation list')
  createConversation = () => this.unsupported('A contract conversation')
  listMessages = () => this.unsupported('Contract messages')
  sendMessage = () => this.unsupported('A contract message')
  startEvaluationRun = () => this.unsupported('A sandbox evaluation run')
}

/** Monday 00:00 to the following Monday 00:00 around `now`, as dates in `timeZone`. */
export function weekRange(nowMs: number, timeZone: string): { start: string; end: string } {
  const today = localParts(new Date(nowMs).toISOString(), timeZone)
  const monday = Date.parse(`${today.date}T00:00:00Z`) - (today.weekday - 1) * 86_400_000
  const day = (offset: number) => new Date(monday + offset * 86_400_000).toISOString().slice(0, 10)
  return { start: day(0), end: day(7) }
}

const INBOX_TTL_MS = 30_000

export class ScribaWorkspace implements WorkspaceApi {
  readonly availability = 'live' as const
  private listeners = new Set<Listener>()
  private inboxCache: { at: number; promise: Promise<DeskInbox> } | null = null
  /** Why part of the last answer is known to be incomplete. Read by the screens after a load. */
  lastInbox: DeskInbox | null = null
  lastCalendarErrors: { provider: 'google' | 'outlook'; message: string }[] = []
  /**
   * Where the calendar and task lists came from on the last read, for the screen to state.
   * `sandbox`: the sandbox world's own records. `sandbox_today`: this backend exposes only
   * today's sandbox meetings and the open tasks (no /desk/memory). `scriba`: Scriba's own routes.
   */
  calendarSource: 'scriba' | 'sandbox' | 'sandbox_today' = 'scriba'
  tasksSource: 'scriba' | 'sandbox' = 'scriba'
  private sandbox = false
  /** False once this backend answered 404 for /desk/memory (before overlay 0.4): it is not asked again. */
  private hasMemory = true

  private async memory() {
    if (!this.hasMemory) return null
    const memory = await fetchDeskMemory()
    if (memory === null) this.hasMemory = false
    return memory
  }

  constructor(private readonly desk: LiveDesk, private readonly now: () => number = Date.now) {}

  private emit(): void {
    this.inboxCache = null
    for (const listener of [...this.listeners]) listener()
  }

  /**
   * In a sandbox the calendar and the tasks are the sandbox world's. Scriba's own
   * `/calendar/events` and `/tasks` hold unrelated seeded records there, so they are not read.
   */
  setSandbox(on: boolean): void {
    if (on === this.sandbox) return
    this.sandbox = on
    this.emit()
  }

  get inSandbox(): boolean {
    return this.sandbox
  }

  /** The sandbox world's meetings: the next two weeks from /desk/memory, or today's from the briefing. */
  private async sandboxAgenda(): Promise<AgendaEvent[]> {
    this.lastCalendarErrors = []
    const memory = await this.memory()
    if (memory) {
      if (!memory.meetings.ok) throw new Error(`The sandbox calendar could not be read (${memory.meetings.error ?? 'no reason given'}). It is unknown, not empty.`)
      this.calendarSource = 'sandbox'
      return markCrossCalendarConflicts(
        memory.meetings.items
          .filter(meeting => meeting.start && meeting.end)
          .map(meeting => {
            const provider = String(meeting.provider ?? '').includes('outlook') ? ('outlook' as const) : ('google' as const)
            return {
              id: `${provider}:${meeting.id}`,
              title: meeting.title || '(no title)',
              start: meeting.start,
              end: meeting.end,
              provider,
              calendar: provider === 'google' ? 'Sandbox Google Calendar' : 'Sandbox Outlook Calendar',
              attendees: (meeting.attendees ?? []).map(email => ({ name: email, email })),
              location: null,
              kind: 'event' as const,
              conflictsWith: [],
              approvalId: null,
              source: { eventId: meeting.id, providerAccountId: null, joinUrl: null },
            }
          }),
      )
    }
    const briefing = await fetchDeskBriefing()
    if (briefing.unavailable.includes('agenda')) throw new Error('The sandbox calendar could not be read. It is unknown, not empty.')
    this.desk.setTimeZone(briefing.timezone)
    this.calendarSource = 'sandbox_today'
    const events: AgendaEvent[] = []
    for (const meeting of briefing.meetings_today) {
      const provider = String(meeting.calendar_provider ?? meeting.provider ?? '').includes('outlook') ? ('outlook' as const) : ('google' as const)
      if (!meeting.start_time || !meeting.end_time) continue
      events.push({
        id: `${provider}:${meeting.event_id ?? meeting.title ?? events.length}`,
        title: meeting.title || '(no title)',
        start: meeting.start_time,
        end: meeting.end_time,
        provider,
        calendar: provider === 'google' ? 'Sandbox Google Calendar' : 'Sandbox Outlook Calendar',
        attendees: (meeting.attendee_emails ?? []).map(email => ({ name: email, email })),
        location: null,
        kind: 'event',
        conflictsWith: [],
        approvalId: null,
        source: { eventId: meeting.event_id ?? null, providerAccountId: meeting.provider_account_id ?? null, joinUrl: null },
      })
    }
    return markCrossCalendarConflicts(events)
  }

  /** The sandbox world's open tasks. A completed sandbox task is not listed by either route. */
  private async sandboxTasks(): Promise<WorkTask[]> {
    const memory = await this.memory()
    this.tasksSource = 'sandbox'
    const row = (id: string, title: string | null | undefined, dueAt: string | null | undefined, priority?: string): WorkTask => ({
      id,
      title: title || '(untitled task)',
      detail: null,
      dueAt: dueAt || null,
      status: 'open',
      priority: toPriority(priority),
      origin: 'extracted',
      sourceEmailId: null,
      createdAt: '',
      completedAt: null,
    })
    if (memory) {
      if (!memory.tasks.ok) throw new Error(`The sandbox tasks could not be read (${memory.tasks.error ?? 'no reason given'}). They are unknown, not empty.`)
      return memory.tasks.items.map(task => row(String(task.id), task.title, task.dueAt))
    }
    const briefing = await fetchDeskBriefing()
    if (briefing.unavailable.includes('tasks')) throw new Error('The sandbox tasks could not be read. They are unknown, not empty.')
    return briefing.open_tasks.map(task => row(String(task.id), task.title, task.due_at, task.effective_priority))
  }

  /** Drops cached reads and tells every screen to load again. */
  refresh(): void {
    this.emit()
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  connections(): Promise<DeskConnections> {
    return fetchDeskConnections()
  }

  async listAccounts(): Promise<ConnectedAccount[]> {
    return toAccounts(await this.connections())
  }

  /** The merged inbox. Shared for a short time so several panels on one screen cause one read. */
  inbox(): Promise<DeskInbox> {
    const cached = this.inboxCache
    if (cached && this.now() - cached.at < INBOX_TTL_MS) return cached.promise
    const promise = fetchDeskInbox({ provider: 'all', limit: 50 }).then(inbox => {
      this.lastInbox = inbox
      return inbox
    })
    this.inboxCache = { at: this.now(), promise }
    // A failed read is not kept: the next caller tries again.
    promise.catch(() => {
      if (this.inboxCache?.promise === promise) this.inboxCache = null
    })
    return promise
  }

  async listEmails(): Promise<InboxEmail[]> {
    return (await this.inbox()).items.map(toInboxEmail)
  }

  submitDraft(): Promise<void> {
    return Promise.reject(new WorkspaceUnavailable('Reply drafts', 'On the live Desk a reply is drafted from the message itself and approved in chat. This control belongs to the mock.'))
  }

  /**
   * This week's events from Google and Outlook. Each provider is read on its own: when one fails
   * and the other answers, the events that were read are shown and the failure is recorded in
   * `lastCalendarErrors` for the screen to state. When every connected calendar fails, the call
   * rejects.
   */
  async listAgenda(week?: { start: string; end: string }): Promise<AgendaEvent[]> {
    if (this.sandbox) return this.sandboxAgenda()
    this.calendarSource = 'scriba'
    const zone = this.desk.info.principal.timezone
    const range = week ?? weekRange(this.now(), zone)
    const connections = await this.connections()
    const connected = (id: 'google_calendar' | 'outlook_calendar') => connections.capabilities.find(c => c.id === id)?.state === 'connected'
    const providers = ([['google', 'google_calendar'], ['outlook', 'outlook_calendar']] as const).filter(([, id]) => connected(id)).map(([provider]) => provider)
    if (providers.length === 0) {
      this.lastCalendarErrors = []
      throw new WorkspaceUnavailable('The unified calendar', 'No calendar is connected. Connect Google Calendar or Outlook Calendar in Scriba to see events here.')
    }
    const results = await Promise.allSettled(providers.map(provider => fetchCalendarEvents(provider, range)))
    const events: AgendaEvent[] = []
    const errors: { provider: 'google' | 'outlook'; message: string }[] = []
    results.forEach((result, index) => {
      const provider = providers[index]
      if (result.status === 'rejected') {
        errors.push({ provider, message: result.reason instanceof Error ? result.reason.message : String(result.reason) })
        return
      }
      this.desk.setTimeZone(result.value.timezone)
      for (const entry of result.value.meetings ?? []) {
        const event = toAgendaEvent(entry, provider)
        if (event) events.push(event)
      }
    })
    this.lastCalendarErrors = errors
    if (errors.length === providers.length) throw new Error(`Could not read ${errors.map(e => (e.provider === 'google' ? 'Google Calendar' : 'Outlook Calendar')).join(' or ')}: ${errors[0].message}`)
    return markCrossCalendarConflicts(events)
  }

  /** No backend prepares a meeting brief yet. Null means "none", which is what the screen shows. */
  getMeetingPrep(): Promise<MeetingPrep | null> {
    return Promise.resolve(null)
  }

  async listTasks(): Promise<WorkTask[]> {
    if (this.sandbox) return this.sandboxTasks()
    this.tasksSource = 'scriba'
    const page = await fetchTasks()
    return page.tasks.map(toWorkTask).filter((task): task is WorkTask => task !== null)
  }

  async setTaskStatus(id: string, status: WorkTask['status']): Promise<void> {
    if (this.sandbox) {
      throw new WorkspaceUnavailable('Changing a sandbox task from this list', 'In the sandbox a task is recorded or completed through an action the secretary proposes in the work queue. The task was left as it is.')
    }
    if (status !== 'done') {
      throw new WorkspaceUnavailable('Reopening a task', 'Scriba has no verified way to reopen a completed task from the Desk yet. The task was left as it is.')
    }
    await completeTask(id)
    this.emit()
  }

  async listReminders(): Promise<Reminder[]> {
    // Scriba's reminder store is not the sandbox world's; the world's reminders have no list route yet.
    if (this.sandbox) return []
    return (await fetchReminders()).map(toReminder).filter((reminder): reminder is Reminder => reminder !== null)
  }

  async setReminderStatus(id: string, status: Reminder['status']): Promise<void> {
    if (this.sandbox) throw new WorkspaceUnavailable('Changing a reminder in the sandbox')
    if (status !== 'dismissed') {
      throw new WorkspaceUnavailable('Marking a reminder done', 'Scriba can cancel a scheduled reminder; it has no "done" for one. Use Dismiss to cancel it.')
    }
    await cancelReminder(id)
    this.emit()
  }

  listFollowUps(): Promise<FollowUp[]> {
    return Promise.reject(new WorkspaceUnavailable('Follow-up tracking', 'Scriba does not yet track sent mail that is waiting for a reply. Nothing is shown rather than something invented.'))
  }

  draftNudge(): Promise<void> {
    return Promise.reject(new WorkspaceUnavailable('Follow-up tracking'))
  }

  /** The live activity screen reads Scriba's action records directly (LiveActivityPage). */
  listActivity(): Promise<ActivityEntry[]> {
    return Promise.reject(new WorkspaceUnavailable('Activity history'))
  }
}
