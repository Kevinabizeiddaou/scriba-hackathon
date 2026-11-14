/**
 * The Jira workspace, with the backend replaced at the client-function boundary.
 * The rule under test throughout: a button prepares a change; only an approval makes it.
 */
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { JiraBriefing, JiraIssue, JiraIssueDetail, JiraProposal, JiraStatus } from '../../api/jira'

vi.mock('../../api/jira', async original => ({
  ...(await original<typeof import('../../api/jira')>()),
  fetchJiraStatus: vi.fn(),
  fetchJiraBriefing: vi.fn(),
  fetchJiraIssues: vi.fn(),
  fetchJiraIssue: vi.fn(),
  fetchJiraProposals: vi.fn(),
  fetchJiraFeatures: vi.fn(),
  proposeJiraChange: vi.fn(),
  approveJiraProposal: vi.fn(),
  rejectJiraProposal: vi.fn(),
}))

import { approveJiraProposal, fetchJiraBriefing, fetchJiraFeatures, fetchJiraIssue, fetchJiraIssues, fetchJiraProposals, fetchJiraStatus, proposeJiraChange, rejectJiraProposal } from '../../api/jira'
import { JiraPage } from './JiraPage'

const issue = (over: Partial<JiraIssue> = {}): JiraIssue => ({
  key: 'DESK-4', url: 'https://acme.example/browse/DESK-4', summary: 'Calendar conflict is missed', type: { name: 'Bug', subtask: false },
  status: { name: 'Blocked', category: 'in_progress' }, priority: { name: 'Highest', rank: 1 }, project: { key: 'DESK', name: 'Desk' },
  assignee: { accountId: 'a1', displayName: 'Tomas Lindqvist', avatarUrl: null, active: true }, reporter: null, labels: [], components: [], fixVersions: [],
  created: null, updated: null, due: '2026-11-14', parent: null, sprint: null, storyPoints: 3, flagged: true,
  counts: { subtasks: 0, subtasksDone: 0, comments: 1, attachments: 0 },
  signals: { overdue: true, dueInDays: -2, blocked: true, stale: false, unassigned: false }, ...over,
})

const connected = (over: Partial<JiraStatus> = {}): JiraStatus => ({
  enabled: true, version: '0.1.0', mode: 'live', state: 'connected', configured: true, connected: true, reason: null,
  site: { name: 'Acme', url: 'https://acme.example' }, account: { accountId: 'me', displayName: 'Exec' }, scopes: [],
  writes: { mode: 'held', enabled: false, simulated: false, reason: 'jira_writes_switch', message: 'Changing Jira is switched off on this Desk.', checks: [] },
  setup: null, loginPath: '/auth/jira/login', defaultView: 'my_open',
  views: [{ id: 'my_open', label: 'Assigned to me', description: '', needs: null, unverified: false, jql: '' }],
  proposals: { waiting: 0, kind: 'memory', durable: false }, ...over,
})

const proposal = (over: Partial<JiraProposal> = {}): JiraProposal => ({
  id: 'jp-1', action: 'transition_issue', label: 'Move an issue', risk: 'medium', status: 'awaiting_approval',
  summary: 'Move DESK-4 (Calendar conflict is missed) from Blocked to In Progress.', targets: ['DESK-4'], reason: null, simulated: false,
  createdAt: '2026-11-16T09:00:00Z', decidedAt: null, held: null, result: null, verification: null, error: null, undo: 'Move it back.', ...over,
})

const briefing: JiraBriefing = {
  counts: { open: 13, mine: 5, overdue: 2, blocked: 1, dueSoon: 4, stale: 2, unassigned: 2 },
  sections: [{ id: 'overdue', title: 'Overdue', why: 'Open and past the due date.', count: 1, issues: [issue()], truncated: false }],
  complete: true, simulated: false, site: { name: 'Acme', url: null }, sprints: [], approvals: null, unavailable: [], proposalsWaiting: 0,
}

function show(param: string | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><JiraPage param={param} /></QueryClientProvider>)
}

beforeEach(() => {
  vi.mocked(fetchJiraStatus).mockResolvedValue(connected())
  vi.mocked(fetchJiraBriefing).mockResolvedValue(briefing)
  vi.mocked(fetchJiraProposals).mockResolvedValue({ proposals: [], waiting: 0, store: { kind: 'memory', durable: false } })
  vi.mocked(fetchJiraIssues).mockResolvedValue({ issues: [issue()], jql: '', source: 'view:my_open', simulated: false, page: { count: 1, more: false, nextPageToken: null, total: null } })
  vi.mocked(fetchJiraFeatures).mockResolvedValue({ features: [], summary: { ready: 0, api: 0, planned: 0, excluded: 0 }, connected: true })
})
afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('before Jira is usable', () => {
  it('says so when the backend runs without Jira, and asks for nothing else', async () => {
    vi.mocked(fetchJiraStatus).mockResolvedValue({ enabled: false, version: '0.1.0' })
    show(null)
    expect(await screen.findByText('Jira is not part of this Desk')).toBeInTheDocument()
    expect(fetchJiraBriefing).not.toHaveBeenCalled()
    expect(fetchJiraProposals).not.toHaveBeenCalled()
  })

  it('names the missing server settings and the callback URL, and offers no connect button', async () => {
    vi.mocked(fetchJiraStatus).mockResolvedValue(connected({
      state: 'not_configured', configured: false, connected: false, reason: 'Jira is not set up on this server yet.',
      setup: { configured: false, missingEnv: ['JIRA_CLIENT_ID', 'JIRA_CLIENT_SECRET'], requiredEnv: [], optionalEnv: [], callbackUrl: 'https://desk.example/api/auth/jira/callback', requestedScopes: [], recommendedScopes: [], scopesToAdd: [], console: '' },
    }))
    show(null)
    const setup = await screen.findByTestId('jira-setup')
    expect(within(setup).getByText('JIRA_CLIENT_ID')).toBeInTheDocument()
    expect(within(setup).getByText('https://desk.example/api/auth/jira/callback')).toBeInTheDocument()
    expect(within(setup).queryByRole('button', { name: /connect/i })).toBeNull()
    expect(fetchJiraBriefing).not.toHaveBeenCalled()
  })

  it('offers to connect when the server is set up and the person is not connected', async () => {
    vi.mocked(fetchJiraStatus).mockResolvedValue(connected({ state: 'not_connected', connected: false, reason: 'Jira is not connected.' }))
    show(null)
    expect(await screen.findByRole('button', { name: 'Connect Jira' })).toBeInTheDocument()
  })
})

describe('connected', () => {
  it('shows the briefing and says that changing Jira is switched off', async () => {
    show(null)
    expect(await screen.findByRole('region', { name: 'Overdue' })).toHaveTextContent('Calendar conflict is missed')
    expect(screen.getByTestId('jira-writes-note')).toHaveTextContent('Changing Jira is switched off.')
    expect(screen.getByText('2 days late')).toBeInTheDocument()
  })

  it('says when part of the briefing could not be read', async () => {
    vi.mocked(fetchJiraBriefing).mockResolvedValue({ ...briefing, unavailable: [{ part: 'team', code: 'jira_unavailable', message: 'Jira did not answer.' }] })
    show(null)
    expect(await screen.findByText(/it is incomplete: Jira did not answer\./)).toBeInTheDocument()
  })

  it('a workflow button prepares a change and approves nothing', async () => {
    const detail: JiraIssueDetail = {
      ...issue(), description: 'Checked an hour off.', resolution: null, subtasks: [], links: [], comments: [], commentsTruncated: false, attachments: [], watching: false, history: null,
      transitions: [{ id: '21', name: 'Start progress', to: { name: 'In Progress', category: 'in_progress' }, requiredFields: [] }],
    }
    vi.mocked(fetchJiraIssue).mockResolvedValue({ issue: detail, simulated: false, canWrite: true })
    vi.mocked(proposeJiraChange).mockResolvedValue(proposal())
    show('DESK-4')
    await userEvent.click(await screen.findByRole('button', { name: 'Start progress' }))
    expect(proposeJiraChange).toHaveBeenCalledWith('transition_issue', { issue: 'DESK-4', transition: '21' })
    expect(await screen.findByText(/Prepared, not done\./)).toBeInTheDocument()
    expect(approveJiraProposal).not.toHaveBeenCalled()
  })

  it('a connection without the write scope cannot prepare a change', async () => {
    const detail = { ...issue(), description: '', resolution: null, subtasks: [], links: [], comments: [], commentsTruncated: false, attachments: [], watching: false, history: null, transitions: [{ id: '21', name: 'Start progress', to: { name: 'In Progress', category: 'in_progress' as const }, requiredFields: [] }] }
    vi.mocked(fetchJiraIssue).mockResolvedValue({ issue: detail, simulated: false, canWrite: false })
    show('DESK-4')
    expect(await screen.findByRole('button', { name: 'Start progress' })).toBeDisabled()
  })

  it('approving and rejecting are separate, deliberate presses on the preview', async () => {
    vi.mocked(fetchJiraProposals).mockResolvedValue({ proposals: [proposal()], waiting: 1, store: { kind: 'memory', durable: false } })
    vi.mocked(approveJiraProposal).mockResolvedValue(proposal({ held: { code: 'jira_writes_disabled', message: 'off', at: '' } }))
    show('changes')
    const card = await screen.findByTestId('jira-proposal')
    expect(card).toHaveTextContent('from Blocked to In Progress')
    expect(approveJiraProposal).not.toHaveBeenCalled()
    await userEvent.click(within(card).getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(approveJiraProposal).toHaveBeenCalledWith('jp-1', false))
    expect(rejectJiraProposal).not.toHaveBeenCalled()
  })

  it('coverage says when project reads lack the project scope, and names it', async () => {
    vi.mocked(fetchJiraStatus).mockResolvedValue(connected({
      scopes: [{ id: 'projects_read', label: 'Read projects: the list, details, issue types and components', product: 'jira', write: false, optional: false, granted: false, missing: ['read:project:jira'] }],
    }))
    vi.mocked(fetchJiraFeatures).mockResolvedValue({
      features: [
        { id: 'projects', area: 'Projects', label: 'Projects I can see', state: 'ready', needs: 'projects_read', write: false, route: 'GET /desk/jira/projects', jira: 'GET /project/search', note: null, granted: false, missingScopes: ['read:project:jira'] },
        { id: 'my_open', area: 'My work', label: 'Assigned to me', state: 'ready', needs: 'core_read', write: false, route: null, jira: null, note: null, granted: true, missingScopes: [] },
      ],
      summary: { ready: 2, api: 0, planned: 0, excluded: 0 }, connected: true,
    })
    show('coverage')
    const projects = await screen.findByRole('region', { name: 'Projects' })
    expect(within(projects).getByText('Projects I can see')).toBeInTheDocument()
    expect(within(projects).getByText('Scope missing')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'My work' })).queryByText('Scope missing')).toBeNull()
    expect(screen.getByText('read:project:jira')).toBeInTheDocument()
  })

  it('a held change says it is held, and an unconfirmed one is not shown as done', async () => {
    vi.mocked(fetchJiraProposals).mockResolvedValue({
      proposals: [
        proposal({ held: { code: 'jira_writes_disabled', message: 'Changing Jira is switched off on this Desk.', at: '' } }),
        proposal({ id: 'jp-2', status: 'executed', verification: { verified: false, detail: 'DESK-4 is Blocked, not In Progress.' } }),
        proposal({ id: 'jp-3', status: 'outcome_unknown', error: { code: 'outcome_unknown', message: 'The request to Jira did not complete.' } }),
      ], waiting: 2, store: { kind: 'memory', durable: false },
    })
    show('changes')
    expect(await screen.findByText(/Held: Changing Jira is switched off/)).toBeInTheDocument()
    expect(screen.getByText('Done, not confirmed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'I checked Jira. Try again' })).toBeInTheDocument()
    expect(screen.getByText(/a restart forgets the ones not yet decided/)).toBeInTheDocument()
  })
})
