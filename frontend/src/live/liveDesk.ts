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
import { markCrossCalendarConflicts, toAccounts, toAgendaEvent, toInboxEmail, toReminder, toWorkTask } from './mappers'
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

  constructor(status: Pick<ProviderStatusPayload, 'email' | 'name'>, baseUrl: string) {
    const email = status.email ?? ''
    this.state = {
      name: 'Scriba',
      dataSource: 'live',
      baseUrl,
      // Until the backend reports the user's Scriba time zone, times are shown in the browser's.
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

  /** Called when a backend response names the user's Scriba time zone. */
  setTimeZone(zone: string | null | undefined): void {
    if (!zone || zone === this.state.principal.timezone || !isValidTimeZone(zone)) return
    this.state = { ...this.state, principal: { ...this.state.principal, timezone: zone } }
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

  constructor(private readonly desk: LiveDesk, private readonly now: () => number = Date.now) {}

  private emit(): void {
    this.inboxCache = null
    for (const listener of [...this.listeners]) listener()
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
  async listAgenda(): Promise<AgendaEvent[]> {
    const zone = this.desk.info.principal.timezone
    const range = weekRange(this.now(), zone)
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
    const page = await fetchTasks()
    return page.tasks.map(toWorkTask).filter((task): task is WorkTask => task !== null)
  }

  async setTaskStatus(id: string, status: WorkTask['status']): Promise<void> {
    if (status !== 'done') {
      throw new WorkspaceUnavailable('Reopening a task', 'Scriba has no verified way to reopen a completed task from the Desk yet. The task was left as it is.')
    }
    await completeTask(id)
    this.emit()
  }

  async listReminders(): Promise<Reminder[]> {
    return (await fetchReminders()).map(toReminder).filter((reminder): reminder is Reminder => reminder !== null)
  }

  async setReminderStatus(id: string, status: Reminder['status']): Promise<void> {
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
