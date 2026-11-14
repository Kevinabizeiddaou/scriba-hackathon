/**
 * The work queue and the run detail, with the backend replaced at the client-function boundary.
 * These tests prove what the Desk does with the run contract's shapes and with failures. They
 * prove nothing about a running backend or about the agent.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClientError } from '../api/client'
import type { ProviderDescriptor, ProviderStatusPayload } from '../api/contract'
import type { DeskBriefing, DeskConnections, DeskHealth, DeskInbox, DeskRun, DeskSweep, TriagedEmail } from '../api/desk'
import type { ChatToolCall } from './scribaApi'

vi.mock('../api/scriba', async original => ({
  ...(await original<typeof import('../api/scriba')>()),
  fetchProviderStatus: vi.fn(),
  fetchCalendarEvents: vi.fn(),
  logout: vi.fn(),
}))
vi.mock('../api/desk', async original => ({
  ...(await original<typeof import('../api/desk')>()),
  fetchDeskHealth: vi.fn(),
  fetchDeskConnections: vi.fn(),
  fetchDeskInbox: vi.fn(),
  fetchDeskInboxItem: vi.fn(),
  fetchDeskBriefing: vi.fn(),
  fetchDeskRuns: vi.fn(),
  fetchDeskRun: vi.fn(),
  sweepDeskInbox: vi.fn(),
  startDeskIntake: vi.fn(),
  advanceDeskRun: vi.fn(),
}))
vi.mock('./scribaApi', async original => ({
  ...(await original<typeof import('./scribaApi')>()),
  fetchChatConversations: vi.fn(),
  fetchChatMessages: vi.fn(),
  fetchChatToolCall: vi.fn(),
  approveChatToolCall: vi.fn(),
  cancelChatToolCall: vi.fn(),
  retryChatToolCall: vi.fn(),
  fetchTasks: vi.fn(),
  fetchReminders: vi.fn(),
  fetchDrafts: vi.fn(),
  createDraftFromRequest: vi.fn(),
}))

import App from '../App'
import { advanceDeskRun, fetchDeskBriefing, fetchDeskConnections, fetchDeskHealth, fetchDeskInbox, fetchDeskRun, fetchDeskRuns, startDeskIntake, sweepDeskInbox } from '../api/desk'
import { fetchCalendarEvents, fetchProviderStatus } from '../api/scriba'
import { deskAction, deskRun, executedAction } from '../test/deskFixtures'
import { HOLD_CODES, explainHold, unverifiedRecipients } from './deskHolds'
import { AUTO_CHECK_MS } from './LiveWorkQueuePage'
import { approveChatToolCall, createDraftFromRequest, fetchChatConversations, fetchChatMessages, fetchChatToolCall, fetchDrafts, fetchReminders, fetchTasks } from './scribaApi'

const provider = (over: Partial<ProviderDescriptor> = {}): ProviderDescriptor => ({ active: false, connected: false, available: true, configured: true, status: 'disconnected', reason: null, ...over })
const signedIn = (): ProviderStatusPayload =>
  ({
    authorized: true, email: 'exec@example.test', name: 'Rana Khoury', accountEmail: null, calendarAuthorized: false,
    gmailConnected: true, gmailEmail: null, outlookConnected: false, outlookEmail: null, outlookDisplayName: null,
    providers: { gmail: provider(), google_calendar: provider(), outlook: provider(), outlook_calendar: provider() },
  }) as ProviderStatusPayload

const health = (extra: Record<string, unknown> = {}): DeskHealth => ({ ok: true, service: 'scriba-desk-overlay', version: '0.2.0', scribaCommit: null, capabilities: [], writes: false, ...extra }) as DeskHealth
const connections = (): DeskConnections => ({
  email: 'exec@example.test',
  ready: true,
  capabilities: [],
  mailboxes: [{ provider: 'gmail', email: 'exec@gmail.example', label: 'Work', providerAccountId: 'acct-1', isPrimary: true }],
})
const mail = (over: Partial<TriagedEmail> = {}): TriagedEmail => ({
  id: 'm-new', threadId: 't-new', from_addr: '"Omar Saab" <omar@example.test>', subject: 'Contract renewal: decision by Friday', snippet: 'Please decide by Friday.',
  timestamp: '2026-11-14T07:00:00Z', provider: 'gmail', is_read: false, reply_supported: true,
  provider_account_id: 'acct-1', account_email: 'exec@gmail.example', source_item_id: null,
  triage: { category: 'action_item', outcome: 'task', priority: 'high', needs_reply: false, has_deadline: true, reasons: ['deadline'] },
  ...over,
})
const inbox = (items: TriagedEmail[] = []): DeskInbox => ({
  account: 'exec@example.test', items,
  sources: [{ provider: 'gmail', state: 'connected', ok: true, error: null, count: items.length, hasMore: false }],
  counts: { meeting_request: 0, needs_reply: 0, action_item: items.length, informational: 0, automated: 0 },
  complete: true,
})
const briefing = (): DeskBriefing =>
  ({ account: 'exec@example.test', generated_at: '2026-11-14T08:00:00Z', headline: 'Nothing urgent.', counts: { meeting_requests: 0, needs_reply: 0, action_items: 0, meetings_today: 0, open_tasks: 0, tasks_due_today: 0, reminders: 0 }, needs_attention: [], meetings_today: [], tasks_due_today: [], open_tasks: [], reminders: [], timezone: 'Asia/Beirut', inbox_complete: true, sources: [], unavailable: [] }) as DeskBriefing

const card = (over: Partial<ChatToolCall> = {}): ChatToolCall => ({ id: 31, message_id: 5, conversation_id: 7, tool_name: 'create_task', status: 'awaiting_approval', input: { title: 'Send the board pack' }, output: {}, ...over })

const sweepResult = (over: Partial<DeskSweep> = {}): DeskSweep => ({
  account: 'exec@example.test', status: 'completed', examined: 12,
  opened: [{ provider: 'gmail', id: 'm-new', subject: 'Contract renewal: decision by Friday', category: 'action_item', runId: 12, state: 'awaiting_approval' }],
  existing: 3, skipped: 8, deferred: [], failed: [],
  sources: [{ provider: 'gmail', state: 'connected', ok: true, error: null, count: 12, hasMore: false }],
  complete: true,
  ...over,
})

/** The backend holds these runs; the list and each detail read come from the same place, as on a server. */
let runs: DeskRun[] = []
function serveRuns(next: DeskRun[]) {
  runs = next
  vi.mocked(fetchDeskRuns).mockImplementation(async () => ({
    account: 'exec@example.test',
    runs: runs.map(run => ({ runId: run.runId, provider: run.email.provider, email_id: run.email.email_id, subject: run.email.subject, from_addr: run.email.from_addr, category: run.category, created_at: run.createdAt })),
  }) as never)
  vi.mocked(fetchDeskRun).mockImplementation(async runId => {
    const found = runs.find(run => run.runId === runId)
    if (!found) throw new ApiClientError('Run not found.', { status: 404 })
    return found
  })
}

function setBackend() {
  vi.mocked(fetchProviderStatus).mockResolvedValue(signedIn())
  vi.mocked(fetchDeskHealth).mockResolvedValue(health())
  vi.mocked(fetchDeskConnections).mockResolvedValue(connections())
  vi.mocked(fetchDeskInbox).mockResolvedValue(inbox())
  vi.mocked(fetchDeskBriefing).mockResolvedValue(briefing())
  vi.mocked(fetchChatConversations).mockResolvedValue([])
  vi.mocked(fetchChatMessages).mockResolvedValue({ conversation: { id: 7, title: 'Desk', status: 'active' }, messages: [] })
  vi.mocked(fetchChatToolCall).mockImplementation(async id => card({ id }))
  vi.mocked(fetchTasks).mockResolvedValue({ tasks: [] })
  vi.mocked(fetchReminders).mockResolvedValue([])
  vi.mocked(fetchDrafts).mockResolvedValue([])
  vi.mocked(fetchCalendarEvents).mockResolvedValue({ meetings: [], timezone: 'Asia/Beirut' } as never)
  serveRuns([])
}

function renderApp(hash: string) {
  window.location.hash = hash
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

const TASK_RUN = deskRun({ runId: 7 })
const HELD_RUN = deskRun({
  runId: 8,
  state: 'no_action_proposed',
  category: 'meeting_request',
  outcome: 'schedule',
  email: { provider: 'outlook', email_id: 'm-8', thread_id: 't-8', provider_account_id: 'acct-o', from_addr: 'Maya Okafor <maya@example.test>', subject: 'Can we meet Tuesday at 14:00?' },
  actions: [],
  held: {
    reason: 'availability_unknown',
    message: 'A calendar could not be read, so the requested time is not verified. No event is proposed. Offer verified free times in a reply.',
    slots: [],
    requested: { start: '2026-11-17T14:00:00+02:00', end: '2026-11-17T14:30:00+02:00' },
    conflicts: [],
    calendars: [
      { provider: 'google', account: 'exec@gmail.example', ok: true, error: null, busy_count: 4 },
      { provider: 'outlook', account: 'exec@contoso.example', ok: false, error: 'reconnect_required', busy_count: 0 },
    ],
  },
})
const DONE_RUN = deskRun({ runId: 9, state: 'completed', email: { ...TASK_RUN.email, email_id: 'm-9', subject: 'Expense report due' }, actions: [executedAction({ toolCallId: 41, assistantActionId: 412 })] })
const INFO_RUN = deskRun({ runId: 10, state: 'no_action_proposed', category: 'informational', outcome: 'none', email: { ...TASK_RUN.email, email_id: 'm-10', subject: 'Weekly digest' }, actions: [] })

beforeEach(() => {
  window.localStorage.clear()
  vi.resetAllMocks()
  setBackend()
})

afterEach(() => {
  vi.useRealTimers()
  cleanup()
  window.location.hash = ''
})

describe('work queue', () => {
  it('lists runs by what they need, with what needs the user first, and counts them in the navigation', async () => {
    serveRuns([INFO_RUN, DONE_RUN, HELD_RUN, TASK_RUN])
    renderApp('#/work')
    await screen.findByRole('heading', { level: 1, name: 'Work queue' })
    const sections = await waitFor(() => {
      const found = ['Awaiting your approval', 'Needs your input', 'Completed', 'No action needed'].map(name => screen.getByRole('region', { name }))
      return found
    })
    // Document order is the order of urgency.
    expect(sections[0].compareDocumentPosition(sections[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(sections[1].compareDocumentPosition(sections[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    const approval = within(sections[0]).getByRole('link', { name: 'Run 7: Board pack by Thursday' })
    expect(approval).toHaveAttribute('href', '#/work/7')
    expect(approval).toHaveTextContent('Dana Haddad')
    expect(approval).toHaveTextContent('Proposed: Record a task')
    expect(approval).toHaveTextContent('Review the proposed action and decide')

    const held = within(sections[1]).getByRole('link', { name: /Run 8/ })
    expect(held).toHaveTextContent('A calendar could not be read, so the requested time is not verified')
    expect(within(sections[2]).getByRole('link', { name: /Run 9/ })).toHaveTextContent('Nothing needed from you')

    // Two runs need the user: the approval and the held meeting request. Finished work is not counted.
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0]
    expect(within(within(nav).getByRole('link', { name: /Work queue/ })).getByLabelText('2 runs that need you')).toBeInTheDocument()
  })

  it('filters by group and never claims a background worker', async () => {
    const user = userEvent.setup()
    serveRuns([DONE_RUN, TASK_RUN])
    renderApp('#/work')
    const filters = await screen.findByRole('group', { name: 'Filter runs' })
    expect(within(filters).getAllByRole('button').map(button => button.textContent)).toEqual(['All runs2', 'Awaiting your approval1', 'Completed1'])
    await user.click(within(filters).getByRole('button', { name: /Completed/ }))
    expect(screen.queryByRole('region', { name: 'Awaiting your approval' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Completed' })).toBeInTheDocument()

    const intake = screen.getByRole('region', { name: 'Intake' })
    expect(intake).toHaveTextContent('This backend has no background worker: nothing is picked up while the Desk is closed.')
    expect(within(intake).getByRole('checkbox', { name: /Check every 5 minutes while this tab is open/ })).not.toBeChecked()
    expect(sweepDeskInbox).not.toHaveBeenCalled() // opening the page never starts intake
  })

  it('says so when the queue is empty, when a run could not be read, and when the list is cut off', async () => {
    renderApp('#/work')
    expect(await screen.findByText('No work has been picked up yet')).toBeInTheDocument()
    cleanup()

    serveRuns([TASK_RUN, DONE_RUN])
    vi.mocked(fetchDeskRun).mockImplementation(async runId => {
      if (runId === 9) throw new ApiClientError('Request timed out')
      return TASK_RUN
    })
    renderApp('#/work')
    expect(await screen.findByText(/1 run could not be read, so its state is unknown/)).toBeInTheDocument()
    const unread = screen.getByRole('region', { name: 'State not read' })
    expect(within(unread).getByRole('link', { name: /Run 9/ })).toHaveTextContent('Could not be read')
    expect(screen.queryByRole('region', { name: 'Completed' })).not.toBeInTheDocument() // unknown is not shown as done
  })

  it('shows a failure to load as a failure, not as an empty queue', async () => {
    vi.mocked(fetchDeskRuns).mockRejectedValue(new ApiClientError('Backend unreachable'))
    renderApp('#/work')
    expect(await screen.findByText(/The work queue could not be loaded: Backend unreachable/)).toBeInTheDocument()
    expect(screen.queryByText('No work has been picked up yet')).not.toBeInTheDocument()
  })

  it('explains itself on a backend without the Desk overlay, and asks it for nothing', async () => {
    vi.mocked(fetchDeskHealth).mockRejectedValue(new ApiClientError('Not Found', { status: 404 }))
    renderApp('#/work')
    expect(await screen.findByText('This backend has no Desk overlay')).toBeInTheDocument()
    expect(fetchDeskRuns).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Check for new work' })).not.toBeInTheDocument()
  })
})

describe('overview', () => {
  it('lists the picked-up requests that need the user and links each to its run', async () => {
    serveRuns([INFO_RUN, DONE_RUN, HELD_RUN, TASK_RUN])
    renderApp('#/overview')
    const section = await screen.findByRole('region', { name: 'Requests the secretary picked up' })
    const links = await within(section).findAllByRole('link', { name: /Board pack|Can we meet/ })
    expect(links.map(a => a.getAttribute('href'))).toEqual(['#/work/8', '#/work/7'])
    expect(links[1]).toHaveTextContent('Review the proposed action and decide')
    expect(section).not.toHaveTextContent('Weekly digest') // finished and no-action runs are not pushed at the user
    expect(within(section).getByRole('link', { name: /Work queue/ })).toHaveAttribute('href', '#/work')
  })

  it('says that mail is picked up on request when nothing has been picked up yet', async () => {
    renderApp('#/overview')
    const section = await screen.findByRole('region', { name: 'Requests the secretary picked up' })
    expect(await within(section).findByText(/Nothing has been picked up yet\. New mail is picked up when you check for new work/)).toBeInTheDocument()
  })
})

describe('checking for new work', () => {
  it('runs one bounded check per click, reports every message it examined, and reads the queue again', async () => {
    const user = userEvent.setup()
    let finish: (value: DeskSweep) => void = () => {}
    vi.mocked(sweepDeskInbox).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    renderApp('#/work')
    const button = await screen.findByRole('button', { name: 'Check for new work' })
    await user.click(button)
    expect(button).toBeDisabled() // a second click cannot start a second check
    await user.click(button)
    expect(sweepDeskInbox).toHaveBeenCalledTimes(1)
    expect(sweepDeskInbox).toHaveBeenCalledWith({ provider: 'all', limit: 25, max_new: 5 })
    expect(screen.getByText(/Checking the inbox.*nothing is sent/)).toBeInTheDocument()

    serveRuns([deskRun({ runId: 12, email: { ...TASK_RUN.email, email_id: 'm-new', subject: 'Contract renewal: decision by Friday' } })])
    finish(sweepResult())
    const report = await screen.findByRole('status', { name: 'Result of the last check' })
    expect(report).toHaveTextContent('It proposed actions only: nothing was sent and no calendar was changed.')
    const numbers = Object.fromEntries(within(report).getAllByRole('term').map(term => [term.textContent, term.nextElementSibling!.textContent]))
    expect(numbers).toEqual({ 'Messages examined': '12', 'New runs opened': '1', 'Already had a run': '3', 'Need no run': '8', 'Left for the next check': '0', 'Could not be processed': '0' })
    expect(within(report).getByRole('link', { name: 'Run 12: Contract renewal: decision by Friday' })).toHaveAttribute('href', '#/work/12')
    // The new run is in the queue without a manual refresh: once in the report, once as a queue row.
    await waitFor(() => expect(screen.getAllByRole('link', { name: 'Run 12: Contract renewal: decision by Friday' })).toHaveLength(2))
  })

  it('offers to take deferred messages, names a mailbox it could not read and lists what failed', async () => {
    const user = userEvent.setup()
    vi.mocked(sweepDeskInbox).mockResolvedValue(
      sweepResult({
        opened: [],
        deferred: [{ provider: 'gmail', id: 'd1', subject: 'Later 1', category: 'needs_reply' }, { provider: 'gmail', id: 'd2', subject: 'Later 2', category: 'meeting_request' }],
        failed: [{ provider: 'gmail', id: 'f1', subject: 'Offsite dates', category: 'meeting_request', error: 'TimeoutError' }],
        complete: false,
        sources: [{ provider: 'gmail', state: 'connected', ok: true, error: null, count: 12, hasMore: false }, { provider: 'outlook', state: 'connected', ok: false, error: 'provider_error', count: 0, hasMore: false }],
      }),
    )
    renderApp('#/work')
    await user.click(await screen.findByRole('button', { name: 'Check for new work' }))
    const report = await screen.findByRole('status', { name: 'Result of the last check' })
    expect(within(report).getByRole('alert')).toHaveTextContent('Outlook could not be read (provider_error), so its mail was not examined.')
    expect(within(report).getByRole('list', { name: 'Messages that could not be processed' })).toHaveTextContent('Offsite dates (TimeoutError). The next check tries it again.')
    expect(report).toHaveTextContent('2 more messages need a run.')
    await user.click(within(report).getByRole('button', { name: 'Take the next ones' }))
    await waitFor(() => expect(sweepDeskInbox).toHaveBeenCalledTimes(2))
  })

  it('reports a failed check and a check that was already running without pretending anything was opened', async () => {
    const user = userEvent.setup()
    vi.mocked(sweepDeskInbox).mockRejectedValueOnce(new ApiClientError('Gateway timeout', { status: 504 }))
    renderApp('#/work')
    const button = await screen.findByRole('button', { name: 'Check for new work' })
    await user.click(button)
    expect(await screen.findByRole('alert')).toHaveTextContent(/failed: Gateway timeout\. Nothing was opened by it\. It is safe to check again\./)
    expect(sweepDeskInbox).toHaveBeenCalledTimes(1) // not retried on its own

    vi.mocked(sweepDeskInbox).mockResolvedValueOnce(sweepResult({ status: 'already_running', examined: 0, opened: [], existing: 0, skipped: 0, complete: false, sources: [] }))
    await user.click(button)
    expect(await screen.findByText(/Another check for this account was already running/)).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Result of the last check' })).not.toBeInTheDocument()
  })

  it('checks on a timer only when asked to, only while the tab is visible, and stops after repeated failures', async () => {
    const user = userEvent.setup()
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    vi.mocked(sweepDeskInbox).mockResolvedValue(sweepResult({ opened: [] }))
    renderApp('#/work')
    const toggle = await screen.findByRole('checkbox', { name: /Check every 5 minutes/ })
    vi.advanceTimersByTime(AUTO_CHECK_MS * 3)
    expect(sweepDeskInbox).not.toHaveBeenCalled() // off by default

    await user.click(toggle)
    vi.advanceTimersByTime(AUTO_CHECK_MS)
    await waitFor(() => expect(sweepDeskInbox).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/\(automatic\)/)).toBeInTheDocument()

    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    vi.advanceTimersByTime(AUTO_CHECK_MS)
    expect(sweepDeskInbox).toHaveBeenCalledTimes(1) // a hidden tab does not check
    visibility.mockRestore()

    vi.mocked(sweepDeskInbox).mockRejectedValue(new ApiClientError('Backend unreachable'))
    for (let i = 0; i < 3; i += 1) {
      vi.advanceTimersByTime(AUTO_CHECK_MS)
      await waitFor(() => expect(sweepDeskInbox).toHaveBeenCalledTimes(2 + i))
    }
    await waitFor(() => expect(toggle).not.toBeChecked()) // three failures in a row: it turns itself off
    vi.advanceTimersByTime(AUTO_CHECK_MS * 2)
    expect(sweepDeskInbox).toHaveBeenCalledTimes(4)
  })

  it('lists mail that needs work and has no run, and starts one run for one message', async () => {
    const user = userEvent.setup()
    serveRuns([TASK_RUN])
    vi.mocked(fetchDeskInbox).mockResolvedValue(inbox([mail(), mail({ id: 'm-7', subject: 'Board pack by Thursday' }), mail({ id: 'm-info', subject: 'Newsletter', triage: { category: 'informational', outcome: 'none', priority: 'low', needs_reply: false, has_deadline: false, reasons: [] } })]))
    const started = deskRun({ runId: 13, email: { ...TASK_RUN.email, email_id: 'm-new', subject: 'Contract renewal: decision by Friday' } })
    vi.mocked(startDeskIntake).mockImplementation(async () => {
      serveRuns([started, TASK_RUN])
      return started
    })
    renderApp('#/work')
    const waiting = await screen.findByRole('region', { name: 'Arrived, not picked up yet' })
    // m-7 already has run 7, and the newsletter needs no run.
    expect(within(waiting).getAllByRole('listitem')).toHaveLength(1)
    await user.click(within(waiting).getByRole('button', { name: 'Start a run for: Contract renewal: decision by Friday' }))
    expect(startDeskIntake).toHaveBeenCalledWith({ provider: 'gmail', id: 'm-new', mailbox: 'exec@gmail.example' })
    expect(await screen.findByRole('heading', { level: 1, name: 'Contract renewal: decision by Friday' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/work/13')
  })
})

describe('actions held by a safety check', () => {
  const HELD_EMAIL = (output: Record<string, unknown>) =>
    card({ id: 52, tool_name: 'send_email', status: 'needs_info', input: { to: 'maya@example.test, billing@payments.example', subject: 'Re: Invoice', body: 'Please see attached.', provider: 'gmail', provider_account_id: 'acct-1' }, output })
  const runWithHeldEmail = () => deskRun({ runId: 7, actions: [deskAction({ toolCallId: 52, tool_name: 'send_email', status: 'needs_info' })] })
  const UNVERIFIED = { blocked: true, error_code: 'unverified_recipient', unverified_recipients: ['billing@payments.example'], message: 'One recipient could not be verified.' }

  it('names the unverified address and why it is held, and cannot be approved while sending is switched off', async () => {
    serveRuns([runWithHeldEmail()])
    vi.mocked(fetchChatToolCall).mockResolvedValue(HELD_EMAIL(UNVERIFIED))
    renderApp('#/work/7')
    const why = await screen.findByRole('status', { name: 'Why this is held' })
    expect(why).toHaveTextContent('Held: A recipient has not been verified')
    expect(why).toHaveTextContent('It may have come from the text of an email, which is untrusted.')
    expect(within(why).getByRole('list', { name: 'Unverified recipients' })).toHaveTextContent('billing@payments.example')
    expect(screen.getByRole('button', { name: 'Approve and run' })).toBeDisabled()
    expect(screen.queryByRole('checkbox', { name: /I have checked this address/ })).not.toBeInTheDocument() // no way to confirm what cannot be sent
    expect(screen.queryByRole('link', { name: 'Answer in chat' })).not.toBeInTheDocument()
  })

  it('sends the confirmation the backend honours, and only after the user ticks it', async () => {
    const user = userEvent.setup()
    vi.mocked(fetchDeskHealth).mockResolvedValue(health({ externalWrites: { enabled: true, revision: 'test' } }))
    serveRuns([runWithHeldEmail()])
    vi.mocked(fetchChatToolCall).mockResolvedValue(HELD_EMAIL(UNVERIFIED))
    vi.mocked(approveChatToolCall).mockResolvedValue({ tool_call: HELD_EMAIL({}) })
    renderApp('#/work/7')
    const approve = await screen.findByRole('button', { name: 'Approve and run' })
    expect(approve).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /I have checked this address and want it to receive this: billing@payments.example/ }))
    expect(approve).toBeEnabled()
    await user.click(approve)
    expect(approveChatToolCall).toHaveBeenCalledWith(52, { desk_confirmed_recipients: ['billing@payments.example'] })
  })

  it('does not offer an approval when the thread has moved on, even with sending switched on', async () => {
    vi.mocked(fetchDeskHealth).mockResolvedValue(health({ externalWrites: { enabled: true, revision: 'test' } }))
    serveRuns([runWithHeldEmail()])
    vi.mocked(fetchChatToolCall).mockResolvedValue(HELD_EMAIL({ blocked: true, error_code: 'reply_target_changed', message: 'A newer message arrived in this thread.' }))
    renderApp('#/work/7')
    const why = await screen.findByRole('status', { name: 'Why this is held' })
    expect(why).toHaveTextContent('Held: The thread has moved on')
    expect(why).toHaveTextContent('It cannot be approved as it is.')
    expect(screen.getByRole('button', { name: 'Approve and run' })).toBeDisabled()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Answer in chat' })).not.toBeInTheDocument() // the fix is in the thread, not in chat
    expect(screen.getByRole('button', { name: 'Cancel action' })).toBeEnabled()
  })

  it('offers no way past a hold it does not recognise', async () => {
    vi.mocked(fetchDeskHealth).mockResolvedValue(health({ externalWrites: { enabled: true, revision: 'test' } }))
    serveRuns([runWithHeldEmail()])
    vi.mocked(fetchChatToolCall).mockResolvedValue(HELD_EMAIL({ blocked: true, error_code: 'policy_review_required', message: 'Held for review.' }))
    renderApp('#/work/7')
    const why = await screen.findByRole('status', { name: 'Why this is held' })
    expect(why).toHaveTextContent('Reason code: policy_review_required. This version of the Desk does not know it, so it offers no way to approve past it.')
    expect(screen.getByRole('button', { name: 'Approve and run' })).toBeDisabled()
  })

  it('explains every hold code the backend can emit, each with one way forward', () => {
    const read = (name: string) => readFileSync(resolve(__dirname, '../../../backend/desk_overlay', name), 'utf8')
    const codes = new Set<string>([
      ...[...read('safeguards.py').matchAll(/return \(?"([a-z_]+)",/g)].map(match => match[1]),
      ...[...read('chat_scope.py').matchAll(/"error_code": "([a-z_]+)"/g)].map(match => match[1]),
      ...[...read('chat_scope.py').matchAll(/output, "([a-z_]+)"/g)].map(match => match[1]),
    ])
    codes.delete('needs_info') // a card status that shares a call signature with the codes, not a hold code
    expect(codes.size).toBeGreaterThanOrEqual(10)
    for (const code of codes) expect(explainHold(code), code).not.toBeNull()
    // Only two holds are passed by an approval, and each needs its own explicit override.
    const approvable = HOLD_CODES.filter(code => ['confirm_recipients', 'book_anyway'].includes(explainHold(code)!.resolution))
    expect(approvable.sort()).toEqual(['availability_unknown', 'calendar_conflict', 'unverified_recipient'])
    expect(explainHold('something_else')).toBeNull()
    expect(unverifiedRecipients({ output: { unverified_recipients: ['a@example.test', ''] } })).toEqual(['a@example.test'])
    expect(unverifiedRecipients({ output: {} })).toEqual([])
  })
})

describe('approval center', () => {
  it('says which incoming message an action came from and links to its run', async () => {
    serveRuns([TASK_RUN])
    vi.mocked(fetchChatConversations).mockResolvedValue([{ id: 7, title: 'Desk: Board pack by Thursday', status: 'active' }])
    vi.mocked(fetchChatMessages).mockResolvedValue({
      conversation: { id: 7, title: 'Desk: Board pack by Thursday', status: 'active' },
      messages: [{ id: 5, conversation_id: 7, role: 'assistant', content: 'Classified as action_item. Proposed for your approval: create_task.', status: 'complete', tool_calls: [card({ id: 31 })] }],
    })
    renderApp('#/approvals')
    const waiting = await screen.findByRole('region', { name: 'Waiting for your decision' })
    const link = await within(waiting).findByRole('link', { name: 'From the message: Board pack by Thursday' })
    expect(link).toHaveAttribute('href', '#/work/7')
  })
})

describe('run detail', () => {
  it('shows the source message, the timeline, and the one thing the run needs', async () => {
    serveRuns([TASK_RUN])
    renderApp('#/work/7')
    expect(await screen.findByRole('heading', { level: 1, name: 'Board pack by Thursday' })).toBeInTheDocument()
    const next = screen.getByRole('region', { name: 'Next step' })
    expect(within(next).getByRole('heading', { level: 2 })).toHaveTextContent('Review the proposed action and decide')
    expect(next).toHaveTextContent('Server state: Awaiting approval')

    const source = screen.getByRole('complementary', { name: 'Source message' })
    expect(source).toHaveTextContent('Dana Haddad')
    expect(source).toHaveTextContent('dana@example.test')
    await waitFor(() => expect(source).toHaveTextContent('exec@gmail.example')) // the mailbox, resolved from the account on the run
    expect(within(source).getByRole('link', { name: 'Open the message' })).toHaveAttribute('href', '#/inbox/gmail%3Am-7')

    const timeline = screen.getByRole('region', { name: 'Timeline' })
    expect(within(timeline).getAllByRole('listitem').map(li => li.getAttribute('aria-label'))).toEqual([
      'Picked up: Done',
      'Classified: Done',
      'Actions proposed: Done',
      'Approval: Now',
      'Execution: Not yet',
      'Verified: Not yet',
    ])
    expect(timeline).toHaveTextContent('Only stages this backend reports')
  })

  it('approves an action through Scriba, then shows the state and the evidence the server reports', async () => {
    const user = userEvent.setup()
    serveRuns([TASK_RUN])
    vi.mocked(approveChatToolCall).mockImplementation(async id => {
      // The server executes, records the action, and the run moves on.
      serveRuns([deskRun({ runId: 7, state: 'completed', actions: [executedAction({ toolCallId: 31, assistantActionId: 412 })] })])
      vi.mocked(fetchChatToolCall).mockImplementation(async toolCallId => card({ id: toolCallId, status: 'executed', assistant_action_id: 412 }))
      return { tool_call: card({ id, status: 'executed' }) }
    })
    renderApp('#/work/7')
    const actions = await screen.findByRole('region', { name: 'Proposed actions' })
    const slot = within(actions).getByRole('listitem', { name: 'Action 1 of 1: Record a task' })
    expect(slot).not.toHaveTextContent('Verified') // nothing has run, so nothing is verified
    await user.click(await within(slot).findByRole('button', { name: 'Approve' }))
    expect(approveChatToolCall).toHaveBeenCalledTimes(1)
    expect(vi.mocked(approveChatToolCall).mock.calls[0][0]).toBe(31)

    await waitFor(() => expect(screen.getByRole('region', { name: 'Next step' })).toHaveTextContent('Server state: Completed'))
    expect(screen.getByRole('listitem', { name: 'Action 1 of 1: Record a task' })).toHaveTextContent('Verified: Scriba recorded it as action #412')
    expect(within(screen.getByRole('region', { name: 'Timeline' })).getByRole('listitem', { name: 'Verified: Done' })).toHaveTextContent('Scriba recorded the action (#412).')
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('does not call an executed action verified when Scriba has no record of it', async () => {
    serveRuns([deskRun({ runId: 7, state: 'completed', actions: [executedAction({ toolCallId: 31, assistantActionId: null, verified: false })] })])
    vi.mocked(fetchChatToolCall).mockResolvedValue(card({ status: 'executed' }))
    renderApp('#/work/7')
    expect(await screen.findByText('Not verified: Scriba has no action record for it')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Next step' })).toHaveTextContent('Check the result yourself')
    expect(within(screen.getByRole('region', { name: 'Timeline' })).getByRole('listitem', { name: 'Verified: Held' })).toBeInTheDocument()
  })

  it('explains a held meeting request: unknown availability is not free, and nothing can be approved', async () => {
    serveRuns([HELD_RUN])
    renderApp('#/work/8')
    const held = await screen.findByRole('region', { name: 'Why nothing was proposed' })
    expect(held).toHaveTextContent('A calendar could not be read, so the requested time is not verified.')
    const calendars = within(held).getByRole('list', { name: 'Calendars read' })
    expect(within(calendars).getAllByRole('listitem')[0]).toHaveTextContent('exec@gmail.example read, 4 busy periods')
    expect(within(calendars).getAllByRole('listitem')[1]).toHaveTextContent('exec@contoso.example could not be read (reconnect required): availability unknown')
    expect(held).toHaveTextContent('None. No time is offered unless every connected calendar was read.')
    expect(screen.getByRole('region', { name: 'Next step' })).toHaveTextContent('An unread calendar is never treated as free')
    expect(screen.queryByRole('region', { name: 'Proposed actions' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Timeline' })).getByRole('listitem', { name: 'Calendars read: Held' })).toBeInTheDocument()
  })

  it('offers verified free times only when the backend supplied them', async () => {
    serveRuns([deskRun({ ...HELD_RUN, held: { ...HELD_RUN.held!, reason: 'calendar_conflict', message: 'The requested time conflicts with an existing commitment.', calendars: [HELD_RUN.held!.calendars[0]], conflicts: [{ start: '2026-11-17T13:30:00+02:00', end: '2026-11-17T14:30:00+02:00', provider: 'google', account: 'exec@gmail.example', title: null }], slots: [{ start: '2026-11-17T15:00:00+02:00', end: '2026-11-17T15:30:00+02:00' }] } })])
    renderApp('#/work/8')
    const held = await screen.findByRole('region', { name: 'Why nothing was proposed' })
    expect(within(held).getByRole('list', { name: 'Verified free times' })).toHaveTextContent('15:00')
    expect(held).toHaveTextContent('A busy period · Google Calendar (exec@gmail.example) · Tue 17 Nov, 13:30 to 14:30')
  })

  it('proposes the confirmation reply only when the server says the event exists, and keeps sending switched off', async () => {
    const user = userEvent.setup()
    const event = executedAction({ toolCallId: 51, tool_name: 'create_calendar_event', assistantActionId: 500, input: { title: 'Intro call', start: '2026-11-17T15:00:00+02:00', end: '2026-11-17T15:30:00+02:00' } })
    const booked = deskRun({ ...HELD_RUN, runId: 8, state: 'completed', held: null, actions: [event], next: ['advance'] })
    serveRuns([booked])
    vi.mocked(fetchChatToolCall).mockImplementation(async id =>
      id === 51
        ? card({ id, tool_name: 'create_calendar_event', status: 'executed', assistant_action_id: 500, input: event.input })
        : card({ id, tool_name: 'send_email', status: 'awaiting_approval', input: { to: 'maya@example.test', subject: 'Re: Can we meet Tuesday at 14:00?', body: 'Thank you for your message. I have scheduled "Intro call".', provider: 'outlook', provider_account_id: 'acct-o' } }),
    )
    const withReply = { ...booked, state: 'awaiting_approval' as const, next: [], actions: [event, deskAction({ toolCallId: 52, tool_name: 'send_email', approve: { method: 'POST' as const, path: '/chat/tool-calls/52/approve' } })] }
    vi.mocked(advanceDeskRun).mockImplementation(async () => {
      serveRuns([withReply])
      return withReply
    })
    renderApp('#/work/8')
    const next = await screen.findByRole('region', { name: 'Next step' })
    expect(next).toHaveTextContent('The calendar event exists. The reply to the sender has not been proposed yet')
    await user.click(within(next).getByRole('button', { name: 'Propose the confirmation reply' }))
    expect(advanceDeskRun).toHaveBeenCalledWith(8)

    const reply = await screen.findByRole('listitem', { name: 'Action 2 of 2: Send an email' })
    expect(reply).toHaveTextContent('maya@example.test')
    expect(reply).toHaveTextContent('I have scheduled "Intro call"')
    // No backend has reported that external writes are safe, so the reply can be read and cancelled, not sent.
    expect(await within(reply).findByRole('button', { name: 'Approve and run' })).toBeDisabled()
    expect(within(reply).getByTestId('gate-reason')).toHaveTextContent('Sending mail and changing calendars are switched off')
    expect(within(reply).getByRole('button', { name: 'Cancel action' })).toBeEnabled()
  })

  it('writes a reply draft through Scriba and says it was not sent', async () => {
    const user = userEvent.setup()
    const draftRequest = { method: 'POST' as const, path: '/drafts/create' as const, body: { provider: 'gmail' as const, email_id: 'm-7', thread_id: 't-7', provider_account_id: 'acct-1', user_context: 'Answer the question.' } }
    serveRuns([deskRun({ runId: 7, state: 'no_action_proposed', category: 'needs_reply', outcome: 'reply', actions: [], draftRequest, next: ['draft_reply'] })])
    vi.mocked(createDraftFromRequest).mockResolvedValue({ id: 3, subject: 'Re: Board pack by Thursday', from_addr: 'exec@gmail.example', draft_text: 'Dear Dana, Thursday works.' })
    renderApp('#/work/7')
    await user.click(await screen.findByRole('button', { name: 'Write a reply draft' }))
    expect(createDraftFromRequest).toHaveBeenCalledWith(draftRequest)
    const stored = await screen.findByText('A draft is stored in Scriba. It has not been sent.')
    expect(stored.parentElement).toHaveTextContent('Dear Dana, Thursday works.')
    expect(screen.getByRole('button', { name: 'Write a reply draft' })).toBeDisabled() // one draft per click, not one per impatient click

    cleanup()
    vi.mocked(createDraftFromRequest).mockRejectedValue(new ApiClientError('AI service is failing', { status: 502 }))
    renderApp('#/work/7')
    await user.click(await screen.findByRole('button', { name: 'Write a reply draft' }))
    expect(await screen.findByText(/The draft could not be written: AI service is failing\. Nothing was sent\./)).toBeInTheDocument()
  })

  it('separates what ran, what failed and what was never attempted in a partial run', async () => {
    serveRuns([
      deskRun({
        runId: 7,
        state: 'partial',
        category: 'meeting_request',
        actions: [
          executedAction({ toolCallId: 61, tool_name: 'create_calendar_event', assistantActionId: 700 }),
          deskAction({ toolCallId: 62, tool_name: 'send_email', status: 'failed', approve: null, error: 'provider_error' }),
          deskAction({ toolCallId: 63, tool_name: 'create_task', status: 'cancelled', approve: null }),
        ],
      }),
    ])
    vi.mocked(fetchChatToolCall).mockImplementation(async id => card({ id, tool_name: id === 61 ? 'create_calendar_event' : id === 62 ? 'send_email' : 'create_task', status: id === 61 ? 'executed' : id === 62 ? 'failed' : 'cancelled', error: id === 62 ? 'provider_error' : null }))
    renderApp('#/work/7')
    const breakdown = await screen.findByRole('alert', { name: 'What ran and what did not' })
    expect(within(breakdown).getAllByRole('listitem').map(li => li.textContent)).toEqual([
      'Ran: Create a calendar event (recorded as action #700)',
      'Failed: Send an email (provider_error)',
      'Not run: Record a task (cancelled)',
    ])
    expect(breakdown).toHaveTextContent('Nothing is repeated automatically.')
    expect(screen.getByRole('region', { name: 'Next step' })).toHaveTextContent('A retry on an action card runs immediately, without a second approval.')
  })

  it('shows an unrecognised state as unrecognised, with the raw value', async () => {
    serveRuns([deskRun({ runId: 7, state: 'awaiting_reply' as DeskRun['state'] })])
    renderApp('#/work/7')
    const next = await screen.findByRole('region', { name: 'Next step' })
    expect(next).toHaveTextContent('The backend reports "awaiting_reply"')
    expect(next).toHaveTextContent('State not recognised')
    expect(next).not.toHaveTextContent('Completed')
  })

  it('still shows the action when its full record cannot be read, without a way to approve it blind', async () => {
    serveRuns([TASK_RUN])
    vi.mocked(fetchChatToolCall).mockRejectedValue(new ApiClientError('Request timed out'))
    renderApp('#/work/7')
    const fallback = await screen.findByTestId('action-fallback')
    await waitFor(() => expect(fallback).toHaveTextContent('The full action could not be read (Request timed out), so it cannot be approved or cancelled from here yet.'))
    expect(within(fallback).queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
    expect(within(fallback).getByRole('button', { name: 'Read again' })).toBeInTheDocument()
  })

  it('says a run does not exist instead of offering to retry forever', async () => {
    renderApp('#/work/999')
    expect(await screen.findByText('Run 999 does not exist for this account.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Try again|Retry/ })).not.toBeInTheDocument()
    expect(within(screen.getByRole('main')).getByRole('link', { name: 'Work queue' })).toHaveAttribute('href', '#/work')
  })
})
