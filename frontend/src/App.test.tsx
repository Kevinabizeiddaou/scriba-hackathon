/**
 * The live application, with Scriba's API replaced at the client-function boundary.
 * These tests prove what the Desk does with real response shapes and with failures. They do not
 * prove anything about a running backend or about the agent.
 */
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClientError } from './api/client'
import type { ProviderDescriptor, ProviderStatusPayload } from './api/contract'
import type { DeskBriefing, DeskConnections, DeskHealth, DeskInbox, TriagedEmail } from './api/desk'
import type { ChatConversation, ChatMessage, ChatToolCall } from './live/scribaApi'

vi.mock('./api/scriba', async original => ({
  ...(await original<typeof import('./api/scriba')>()),
  fetchProviderStatus: vi.fn(),
  fetchCalendarEvents: vi.fn(),
  logout: vi.fn(),
}))
vi.mock('./api/desk', async original => ({
  ...(await original<typeof import('./api/desk')>()),
  fetchDeskHealth: vi.fn(),
  fetchDeskConnections: vi.fn(),
  fetchDeskInbox: vi.fn(),
  fetchDeskInboxItem: vi.fn(),
  fetchDeskBriefing: vi.fn(),
  // The shell and the overview read the run queue; without these the tests would call a real backend.
  fetchDeskRuns: vi.fn(),
  fetchDeskRun: vi.fn(),
}))
vi.mock('./live/scribaApi', async original => ({
  ...(await original<typeof import('./live/scribaApi')>()),
  fetchChatConversations: vi.fn(),
  fetchChatMessages: vi.fn(),
  approveChatToolCall: vi.fn(),
  cancelChatToolCall: vi.fn(),
  retryChatToolCall: vi.fn(),
  fetchTasks: vi.fn(),
  fetchReminders: vi.fn(),
  fetchDrafts: vi.fn(),
  completeTask: vi.fn(),
}))

import App from './App'
import { fetchDeskBriefing, fetchDeskConnections, fetchDeskHealth, fetchDeskInbox, fetchDeskRuns } from './api/desk'
import { fetchCalendarEvents, fetchProviderStatus, logout } from './api/scriba'
import { approveChatToolCall, cancelChatToolCall, fetchChatConversations, fetchChatMessages, fetchDrafts, fetchReminders, fetchTasks, retryChatToolCall } from './live/scribaApi'

const row = (overrides: Partial<ProviderDescriptor> = {}): ProviderDescriptor => ({
  active: false, connected: false, available: true, configured: true,
  status: 'disconnected', reason: null, ...overrides,
})

const status = (overrides: Partial<ProviderStatusPayload>): ProviderStatusPayload => ({
  authorized: false, email: null, accountEmail: null, calendarAuthorized: false,
  gmailConnected: false, gmailEmail: null, outlookConnected: false, outlookEmail: null,
  outlookDisplayName: null,
  providers: {
    gmail: row({ loginPath: '/auth/login' }),
    google_calendar: row({ loginPath: '/auth/login' }),
    outlook: row({ loginPath: '/auth/outlook/login' }),
    outlook_calendar: row({ loginPath: '/auth/outlook/login' }),
    slack: row({ connected: true, status: 'connected' }),
  },
  ...overrides,
})

const signedIn = () => status({ authorized: true, email: 'exec@example.test', name: 'Rana Khoury' })

const health = (extra: Record<string, unknown> = {}): DeskHealth =>
  ({ ok: true, service: 'scriba-desk-overlay', version: '0.2.0', scribaCommit: null, capabilities: [], writes: false, ...extra }) as DeskHealth

const connections = (): DeskConnections => ({
  email: 'exec@example.test',
  ready: true,
  mailboxes: [],
  capabilities: [
    { id: 'gmail', vendor: 'google', label: 'Gmail', state: 'connected', email: 'exec@gmail.example', reason: null, loginPath: '/auth/login' },
    { id: 'google_calendar', vendor: 'google', label: 'Google Calendar', state: 'connected', email: 'exec@gmail.example', reason: null, loginPath: '/auth/login' },
    { id: 'outlook_mail', vendor: 'microsoft', label: 'Outlook Mail', state: 'reconnect_required', email: 'exec@contoso.example', reason: 'token_expired', loginPath: '/auth/outlook/login' },
    { id: 'outlook_calendar', vendor: 'microsoft', label: 'Outlook Calendar', state: 'disconnected', email: null, reason: null, loginPath: '/auth/outlook/login' },
  ],
})

const mail = (over: Partial<TriagedEmail> = {}): TriagedEmail => ({
  id: 'm-1', threadId: 't-1', from_addr: '"Dana Haddad" <dana@example.test>', subject: 'Board pack', snippet: 'Could you send the pack by Thursday?',
  timestamp: '2026-11-13T09:00:00Z', provider: 'gmail', is_read: false, reply_supported: true,
  provider_account_id: 'exec@gmail.example', account_email: 'exec@gmail.example', source_item_id: null,
  triage: { category: 'needs_reply', outcome: 'reply', priority: 'high', needs_reply: true, has_deadline: true, reasons: ['direct_request'] },
  ...over,
})

const inbox = (over: Partial<DeskInbox> = {}): DeskInbox => ({
  account: 'exec@example.test',
  items: [mail()],
  sources: [
    { provider: 'gmail', state: 'connected', ok: true, error: null, count: 1, hasMore: false },
    { provider: 'outlook', state: 'reconnect_required', ok: false, error: 'reconnect_required', count: 0, hasMore: false },
  ],
  counts: { meeting_request: 0, needs_reply: 1, action_item: 0, informational: 0, automated: 0 },
  complete: false,
  ...over,
})

const briefing = (): DeskBriefing => ({
  account: 'exec@example.test', generated_at: '2026-11-13T09:05:00Z', headline: '0 meeting requests, 1 message needs a reply, 0 meetings today, 0 tasks due today.',
  counts: { meeting_requests: 0, needs_reply: 1, action_items: 0, meetings_today: 0, open_tasks: 0, tasks_due_today: 0, reminders: 0 },
  needs_attention: [{ id: 'm-1', provider: 'gmail', provider_account_id: 'exec@gmail.example', from_addr: '"Dana Haddad" <dana@example.test>', subject: 'Board pack', timestamp: '2026-11-13T09:00:00Z', category: 'needs_reply', outcome: 'reply', priority: 'high' }],
  meetings_today: [], tasks_due_today: [], open_tasks: [], reminders: [], timezone: 'Asia/Beirut', inbox_complete: false,
  sources: inbox().sources, unavailable: [],
})

const conversation: ChatConversation = { id: 2, title: 'Monday planning', status: 'active', last_message_at: '2026-11-13T09:10:00Z' }
const toolCall = (over: Partial<ChatToolCall>): ChatToolCall => ({ id: 1, message_id: 11, conversation_id: 2, tool_name: 'create_task', status: 'awaiting_approval', input: {}, output: {}, updated_at: '2026-11-13T09:10:00Z', ...over })
const thread = (calls: ChatToolCall[]): { conversation: ChatConversation; messages: ChatMessage[] } => ({
  conversation,
  messages: [
    { id: 10, conversation_id: 2, role: 'user', content: 'Tell Dana Thursday works and note it', status: 'complete' },
    { id: 11, conversation_id: 2, role: 'assistant', content: 'I drafted the reply and a task.', status: 'complete', tool_calls: calls },
  ],
})

const CALLS = {
  email: toolCall({ id: 21, tool_name: 'send_email', input: { to: 'dana@example.test', subject: 'Re: Board pack', body: 'Thursday works.', provider: 'gmail', provider_account_id: 'exec@gmail.example' } }),
  task: toolCall({ id: 22, tool_name: 'create_task', input: { title: 'Send the board pack', due_at: '2026-11-19T15:00:00Z' } }),
  failed: toolCall({ id: 23, tool_name: 'create_task', status: 'failed', error: 'The task store did not answer.', input: { title: 'File expenses' } }),
  slack: toolCall({ id: 24, tool_name: 'send_slack_message', input: { text: 'hi' } }),
}

function setBackend(calls: ChatToolCall[] = [CALLS.email, CALLS.task]) {
  vi.mocked(fetchProviderStatus).mockResolvedValue(signedIn())
  vi.mocked(fetchDeskHealth).mockResolvedValue(health())
  vi.mocked(fetchDeskConnections).mockResolvedValue(connections())
  vi.mocked(fetchDeskInbox).mockResolvedValue(inbox())
  vi.mocked(fetchDeskBriefing).mockResolvedValue(briefing())
  vi.mocked(fetchDeskRuns).mockResolvedValue({ account: 'exec@example.test', runs: [] })
  vi.mocked(fetchChatConversations).mockResolvedValue([conversation])
  vi.mocked(fetchChatMessages).mockResolvedValue(thread(calls))
  vi.mocked(fetchTasks).mockResolvedValue({ tasks: [] })
  vi.mocked(fetchReminders).mockResolvedValue([])
  vi.mocked(fetchDrafts).mockResolvedValue([])
  vi.mocked(fetchCalendarEvents).mockResolvedValue({ meetings: [], timezone: 'Asia/Beirut' })
}

function renderApp(hash = '') {
  window.location.hash = hash
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

const MOCK_PEOPLE = /Layla|Mansour|Mock data|Simulated/

beforeEach(() => {
  window.localStorage.clear()
  vi.resetAllMocks()
})

afterEach(() => {
  cleanup()
  window.location.hash = ''
})

describe('session gate', () => {
  it('shows sign-in with Google and Microsoft pointing at the Scriba API when anonymous', async () => {
    vi.mocked(fetchProviderStatus).mockResolvedValue(status({}))
    renderApp()

    const google = await screen.findByRole('link', { name: /continue with google/i })
    const microsoft = screen.getByRole('link', { name: /continue with microsoft/i })
    // The test origin is http://localhost:5173, so apiBase resolves to :8000.
    expect(google.getAttribute('href')).toBe('http://localhost:8000/auth/login')
    expect(microsoft.getAttribute('href')).toBe('http://localhost:8000/auth/outlook/login')
    // Nothing behind the gate was requested without a session.
    expect(fetchDeskInbox).not.toHaveBeenCalled()
    expect(fetchChatConversations).not.toHaveBeenCalled()
  })

  it('says the API could not be reached instead of showing a workspace', async () => {
    vi.mocked(fetchProviderStatus).mockRejectedValue(new ApiClientError('Network Error'))
    renderApp()
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be reached: Network Error/)
    expect(document.body.textContent).not.toMatch(MOCK_PEOPLE)
  })

  it('signs out through Scriba and returns to the sign-in screen', async () => {
    setBackend()
    vi.mocked(logout).mockImplementation(async () => {
      vi.mocked(fetchProviderStatus).mockResolvedValue(status({}))
      return { status: 'logged_out' }
    })
    const user = userEvent.setup()
    renderApp()
    await user.click((await screen.findAllByRole('button', { name: 'Sign out' }))[0])
    expect(await screen.findByRole('link', { name: /continue with google/i })).toBeInTheDocument()
    expect(logout).toHaveBeenCalledTimes(1)
  })
})

describe('live overview', () => {
  it('shows the signed-in user, live data and the four connections, with no excluded integration and no mock data', async () => {
    setBackend()
    renderApp()

    expect(await screen.findByRole('heading', { level: 1, name: /Rana/ })).toBeInTheDocument()
    expect(screen.getAllByTestId('data-source')[0]).toHaveTextContent('Live: Scriba')
    expect(await screen.findByTestId('connection-gmail')).toHaveTextContent('Connected')
    expect(screen.getByTestId('connection-google_calendar')).toHaveTextContent('Connected')
    const outlook = screen.getByTestId('connection-outlook_mail')
    expect(within(outlook).getByRole('link', { name: 'Reconnect' }).getAttribute('href')).toBe('http://localhost:8000/auth/outlook/login')
    expect(within(screen.getByTestId('connection-outlook_calendar')).getByRole('link', { name: 'Connect' })).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/slack|teams|jira|drive/i)
    expect(document.body.textContent).not.toMatch(MOCK_PEOPLE)
  })

  it('answers the dashboard questions from server data: arrived, classified, awaiting approval, failed', async () => {
    setBackend([CALLS.email, CALLS.task, CALLS.failed])
    renderApp()

    const queue = await screen.findByRole('region', { name: 'Where the work stands' })
    await waitFor(() => expect(within(queue).getByText('Awaiting approval').closest('a')).toHaveTextContent('2'))
    expect(within(queue).getByText('Arrived').closest('a')).toHaveTextContent('1')
    expect(within(queue).getByText('Need action').closest('a')).toHaveTextContent('1')
    expect(within(queue).getByText('Failed or partial').closest('a')).toHaveTextContent('1')
    expect(within(queue).getByText('Completed').closest('a')).toHaveTextContent('0')
    expect(screen.getByTestId('classified')).toHaveTextContent('1 need a reply')
    expect(screen.getByRole('region', { name: 'Mail that needs you' })).toHaveTextContent('Dana Haddad')
  })

  it('separates what is waiting on the user from what the secretary has in hand, and lists finished work only when the server says it ran', async () => {
    setBackend([CALLS.email, { ...CALLS.task, status: 'executed' }, { ...CALLS.task, id: 25, status: 'executed', input: { title: 'Book the room' } }, CALLS.failed])
    renderApp()

    const strip = await screen.findByRole('region', { name: 'Where the work stands' })
    const yours = within(strip).getByRole('group', { name: 'Waiting on you' })
    const theirs = within(strip).getByRole('group', { name: 'With the secretary' })
    await waitFor(() => expect(within(yours).getByText('Awaiting approval').closest('a')).toHaveTextContent('1'))
    expect(within(yours).getByText('Failed or partial').closest('a')).toHaveTextContent('1')
    expect(within(yours).getByText('Need action')).toBeInTheDocument()
    expect(within(theirs).getByText('Completed').closest('a')).toHaveTextContent('2')
    expect(within(theirs).getByText('Arrived')).toBeInTheDocument()
    expect(within(theirs).queryByText('Awaiting approval')).toBeNull()

    const handled = screen.getByRole('region', { name: 'Handled by the secretary' })
    await waitFor(() => expect(within(handled).getByText('Send the board pack')).toBeInTheDocument())
    expect(within(handled).getByText('Book the room')).toBeInTheDocument()
    expect(within(handled).getAllByRole('listitem')).toHaveLength(2)
    // A proposal that is still waiting and an action that failed are not finished work.
    expect(handled).not.toHaveTextContent('Re: Board pack')
    expect(handled).not.toHaveTextContent('File expenses')
  })

  it('says nothing has been finished when the server reports no completed action', async () => {
    setBackend([CALLS.email, CALLS.failed])
    renderApp()
    const handled = await screen.findByRole('region', { name: 'Handled by the secretary' })
    await waitFor(() => expect(handled).toHaveTextContent('Nothing has been finished yet'))
    expect(within(handled).queryAllByRole('listitem')).toHaveLength(0)
  })

  it('labels who is speaking in chat and sums up a reply that carries several actions', async () => {
    setBackend([CALLS.email, { ...CALLS.task, status: 'executed' }, CALLS.failed])
    renderApp('#/chat/2')
    const summary = await screen.findByTestId('steps-summary')
    expect(summary).toHaveTextContent('3 actions in this reply: 1 awaiting approval, 1 failed, 1 completed.')
    expect(screen.getByText('Action 1 of 3')).toBeInTheDocument()
    expect(screen.getByText('Action 3 of 3')).toBeInTheDocument()
    expect(screen.getByText('Secretary')).toBeInTheDocument()
    expect(screen.getByText('You said:')).toBeInTheDocument()
  })

  it('says which mailbox is missing when one could not be read, instead of presenting a partial count as the total', async () => {
    setBackend()
    renderApp()
    expect(await screen.findByTestId('mail-incomplete')).toHaveTextContent(/Outlook needs to be reconnected.*minimum, not a total/)
  })

  it('shows a failed inbox as a failure and never fills it with mock data', async () => {
    setBackend()
    vi.mocked(fetchDeskInbox).mockRejectedValue(new ApiClientError('Gmail did not answer', { status: 502 }))
    vi.mocked(fetchDeskBriefing).mockRejectedValue(new ApiClientError('Gmail did not answer', { status: 502 }))
    renderApp()

    expect(await screen.findByText(/The briefing could not be loaded: Gmail did not answer/)).toBeInTheDocument()
    const queue = screen.getByRole('region', { name: 'Where the work stands' })
    await waitFor(() => expect(within(queue).getByText('Arrived').closest('a')).toHaveTextContent('Could not be read'))
    // An unknown count is a dash, never a zero.
    expect(within(queue).getByText('Arrived').closest('a')).toHaveTextContent('–')
    expect(document.body.textContent).not.toMatch(MOCK_PEOPLE)
  })

  it('says the Desk overlay is missing when the backend is plain Scriba', async () => {
    setBackend()
    vi.mocked(fetchDeskHealth).mockRejectedValue(new ApiClientError('Not Found', { status: 404 }))
    renderApp()
    expect(await screen.findByText(/running without the Desk overlay/)).toBeInTheDocument()
    expect(screen.getAllByTestId('data-source')[0]).toHaveTextContent('No Desk overlay on this backend')
  })
})

describe('live inbox', () => {
  it('lists mail with its mailbox and triage, and states the mailbox that could not be read', async () => {
    setBackend()
    renderApp('#/inbox')
    const list = await screen.findByRole('region', { name: 'Messages' })
    expect(await within(list).findByText('Dana Haddad')).toBeInTheDocument()
    expect(within(list).getByText('Needs a reply')).toBeInTheDocument()
    expect(within(list).queryByText('Not tracked')).not.toBeInTheDocument()
    expect(await screen.findByTestId('inbox-incomplete')).toHaveTextContent('Outlook needs to be reconnected')
  })

  it('shows an inbox failure with a way to try again', async () => {
    setBackend()
    vi.mocked(fetchDeskInbox).mockRejectedValue(new ApiClientError('Request failed with status code 500', { status: 500 }))
    renderApp('#/inbox')
    expect(await screen.findByRole('alert')).toHaveTextContent('Request failed with status code 500')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(MOCK_PEOPLE)
  })
})

describe('live calendar and tasks', () => {
  it('shows one calendar and names the other when it could not be read', async () => {
    setBackend()
    const both = connections()
    both.capabilities[3] = { ...both.capabilities[3], state: 'connected', email: 'exec@contoso.example' }
    vi.mocked(fetchDeskConnections).mockResolvedValue(both)
    vi.mocked(fetchCalendarEvents).mockImplementation(async provider => {
      if (provider === 'outlook') throw new ApiClientError('Graph timed out', { status: 504 })
      return { timezone: 'Asia/Beirut', meetings: [] }
    })
    renderApp('#/calendar')
    expect(await screen.findByTestId('calendar-incomplete')).toHaveTextContent(/Outlook Calendar could not be read \(Graph timed out\).*not known to be free/)
  })

  it('says follow-up tracking does not exist yet, while tasks still load', async () => {
    setBackend()
    vi.mocked(fetchTasks).mockResolvedValue({ tasks: [{ id: 5, title: 'Prepare board slides', status: 'active' }] })
    renderApp('#/tasks')
    expect(await screen.findByText('Prepare board slides')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /Follow-ups/ }))
    expect(await screen.findByText('Follow-up tracking is not available yet')).toBeInTheDocument()
  })
})

describe('approval center on live data', () => {
  it('shows what will happen, to whom and from which account, and keeps sending disabled until the backend reports its safety fixes', async () => {
    setBackend()
    renderApp('#/approvals')

    const email = await screen.findByRole('article', { name: /Send an email: Re: Board pack/ })
    expect(email).toHaveTextContent('dana@example.test')
    expect(email).toHaveTextContent('Gmail · exec@gmail.example')
    expect(email).toHaveTextContent('Thursday works.')
    expect(email).toHaveTextContent('Why: I drafted the reply and a task.')
    expect(within(email).getByRole('button', { name: 'Approve and run' })).toBeDisabled()
    expect(within(email).getByTestId('gate-reason')).toHaveTextContent(/switched off/)
    expect(within(email).getByRole('button', { name: 'Cancel action' })).toBeEnabled()
    expect(screen.getByTestId('policy-note')).toBeInTheDocument()
  })

  it('enables sending only when the backend health says external writes are verified', async () => {
    setBackend()
    vi.mocked(fetchDeskHealth).mockResolvedValue(health({ externalWrites: { enabled: true } }))
    renderApp('#/approvals')
    const email = await screen.findByRole('article', { name: /Send an email/ })
    await waitFor(() => expect(within(email).getByRole('button', { name: 'Approve and run' })).toBeEnabled())
    expect(screen.queryByTestId('policy-note')).not.toBeInTheDocument()
  })

  it('approves a task once, then shows the status the server returns, not one of its own', async () => {
    setBackend()
    vi.mocked(approveChatToolCall).mockImplementation(async () => {
      vi.mocked(fetchChatMessages).mockResolvedValue(thread([CALLS.email, { ...CALLS.task, status: 'executed' }]))
      return { tool_call: { ...CALLS.task, status: 'executed' } }
    })
    const user = userEvent.setup()
    renderApp('#/approvals')

    const task = await screen.findByRole('article', { name: /Create a task: Send the board pack/ })
    await user.click(within(task).getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(screen.queryByRole('article', { name: /Create a task: Send the board pack/ })).not.toBeInTheDocument())
    expect(approveChatToolCall).toHaveBeenCalledTimes(1)
    expect(approveChatToolCall).toHaveBeenCalledWith(22, undefined)
  })

  it('keeps the server status when an approval is refused', async () => {
    setBackend()
    vi.mocked(approveChatToolCall).mockRejectedValue(new ApiClientError('This action was already decided.', { status: 409 }))
    const user = userEvent.setup()
    renderApp('#/approvals')
    const task = await screen.findByRole('article', { name: /Create a task: Send the board pack/ })
    await user.click(within(task).getByRole('button', { name: 'Approve' }))
    expect(await within(task).findByText(/This action was already decided/)).toBeInTheDocument()
    expect(task).toHaveAttribute('data-status', 'awaiting_approval')
  })

  it('never offers approval for an integration outside the Desk', async () => {
    setBackend([CALLS.slack])
    vi.mocked(fetchDeskHealth).mockResolvedValue(health({ externalWrites: { enabled: true } }))
    renderApp('#/approvals')
    const card = await screen.findByTestId('tool-call')
    expect(within(card).getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(within(card).getByTestId('gate-reason')).toHaveTextContent(/not part of the Executive Desk/)
  })

  it('says a retry runs immediately, and only retries after that is confirmed', async () => {
    setBackend([CALLS.failed])
    vi.mocked(retryChatToolCall).mockResolvedValue({ tool_call: { ...CALLS.failed, status: 'executed' } })
    const user = userEvent.setup()
    renderApp('#/approvals')

    const failed = await screen.findByRole('article', { name: /Create a task: File expenses/ })
    expect(failed).toHaveTextContent('The task store did not answer.')
    await user.click(within(failed).getByRole('button', { name: 'Retry…' }))
    expect(retryChatToolCall).not.toHaveBeenCalled()
    const confirm = within(failed).getByRole('alertdialog', { name: 'Confirm retry' })
    expect(confirm).toHaveTextContent(/runs this action again immediately/)
    expect(confirm).toHaveTextContent(/does not ask for a second approval/)

    await user.click(within(confirm).getByRole('button', { name: 'Keep as failed' }))
    expect(retryChatToolCall).not.toHaveBeenCalled()

    await user.click(within(failed).getByRole('button', { name: 'Retry…' }))
    await user.click(within(failed).getByRole('button', { name: 'Run again now' }))
    await waitFor(() => expect(retryChatToolCall).toHaveBeenCalledTimes(1))
    expect(cancelChatToolCall).not.toHaveBeenCalled()
  })

  it('shows a failure to load approvals as a failure, not as an empty list', async () => {
    setBackend()
    vi.mocked(fetchChatConversations).mockRejectedValue(new ApiClientError('Request failed with status code 503', { status: 503 }))
    renderApp('#/approvals')
    expect(await screen.findByText(/Approvals could not be loaded/)).toBeInTheDocument()
    expect(screen.queryByText('Nothing is waiting for you')).not.toBeInTheDocument()
  })
})

describe('evaluation on a live session', () => {
  it('offers only the harness self-test and says no result describes the real agent', async () => {
    setBackend()
    renderApp('#/evaluation')
    const kinds = await screen.findByTestId('result-kinds')
    expect(kinds).toHaveTextContent(/nothing on this page describes how the real agent performs/)
    expect(within(kinds).getAllByText('No result')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Run harness self-test' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run evaluation' })).not.toBeInTheDocument()
  })
})
