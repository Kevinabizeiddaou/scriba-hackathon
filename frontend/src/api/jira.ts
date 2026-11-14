/**
 * Typed client for the Desk's Jira routes (`/desk/jira/*`).
 *
 * They exist only on a backend with the Desk overlay, and answer only when it runs with
 * DESK_JIRA on (GET /desk/jira/status always answers, with `enabled: false` otherwise). Shapes
 * mirror backend/desk_overlay/jira/models.py; backend/tests/test_jira.py pins them.
 *
 * Nothing here changes Jira. A change is proposed (`proposeJiraChange`), shown with its preview,
 * and made only when the person approves it, and only on a backend where Jira writes are on.
 */
import { getJson, postJson } from './client'

export type JiraState = 'connected' | 'not_configured' | 'not_connected' | 'reconnect_required'
export type JiraWriteMode = 'held' | 'sandbox' | 'external'
export type StatusCategory = 'todo' | 'in_progress' | 'done'

export interface JiraScopeGroup {
  id: string
  label: string
  product: 'jira' | 'software' | 'servicedesk'
  write: boolean
  optional: boolean
  granted: boolean
  missing: string[]
}

export interface JiraView {
  id: string
  label: string
  description: string
  needs: 'software' | 'servicedesk' | null
  unverified: boolean
  jql: string
}

export interface JiraWrites {
  mode: JiraWriteMode
  enabled: boolean
  simulated: boolean
  reason: string | null
  message: string
  checks: Array<{ id: string; ok: boolean; detail: string }>
}

export interface JiraSetup {
  configured: boolean
  /** Names of the server settings that are not set. Never a value. */
  missingEnv: string[]
  requiredEnv: string[]
  optionalEnv: string[]
  callbackUrl: string | null
  requestedScopes: string[]
  recommendedScopes: string[]
  scopesToAdd: string[]
  console: string
}

export interface JiraStatus {
  enabled: boolean
  version: string
  mode?: 'live' | 'sandbox'
  state?: JiraState
  configured?: boolean
  connected?: boolean
  reason?: string | null
  site?: { name: string | null; url: string | null } | null
  account?: { accountId: string | null; displayName: string | null } | null
  scopes?: JiraScopeGroup[]
  writes?: JiraWrites
  setup?: JiraSetup | null
  loginPath?: string
  views?: JiraView[]
  defaultView?: string
  proposals?: { waiting: number; kind: string; durable: boolean }
}

export interface JiraPerson {
  accountId: string | null
  displayName: string
  avatarUrl: string | null
  active: boolean
}

export interface JiraStatusRef { id?: string | null; name: string; category: StatusCategory }

export interface JiraBrief {
  key: string
  summary: string
  status: JiraStatusRef | null
  type: { name: string }
  url: string | null
}

export interface JiraSprintRef {
  id: number
  name: string
  state: 'active' | 'future' | 'closed' | null
  startDate: string | null
  endDate: string | null
  goal: string | null
}

export interface JiraIssue {
  key: string
  url: string | null
  summary: string
  type: { name: string; subtask: boolean }
  status: JiraStatusRef
  priority: { name: string; rank: number } | null
  project: { key: string | null; name: string | null }
  assignee: JiraPerson | null
  reporter: JiraPerson | null
  labels: string[]
  components: string[]
  fixVersions: string[]
  created: string | null
  updated: string | null
  due: string | null
  parent: JiraBrief | null
  sprint: JiraSprintRef | null
  storyPoints: number | null
  flagged: boolean
  counts: { subtasks: number; subtasksDone: number; comments: number | null; attachments: number | null }
  signals: { overdue: boolean; dueInDays: number | null; blocked: boolean; stale: boolean; unassigned: boolean }
}

export interface JiraComment {
  id: string
  author: JiraPerson | null
  body: string
  created: string | null
  mentionsMe: boolean
  internal: boolean
}

export interface JiraTransition {
  id: string
  name: string
  to: JiraStatusRef
  requiredFields: Array<{ id: string; name: string; allowedValues: string[] }>
}

export interface JiraIssueDetail extends JiraIssue {
  description: string
  resolution: string | null
  subtasks: JiraBrief[]
  links: Array<{ id: string; label: string; issue: JiraBrief; blocksThis: boolean }>
  comments: JiraComment[]
  commentsTruncated: boolean
  attachments: Array<{ id: string; filename: string; size: number | null }>
  watching: boolean
  transitions: JiraTransition[]
  history: Array<{ id: string; author: JiraPerson | null; at: string | null; changes: Array<{ field: string; from: string | null; to: string | null }> }> | null
}

export interface JiraPage { count: number; more: boolean; nextPageToken: string | null; total: number | null }

export interface JiraIssueList {
  issues: JiraIssue[]
  jql: string
  source: string
  simulated: boolean
  page: JiraPage
  approximateCount?: number | null
}

export interface JiraProgress {
  total: number
  todo: number
  inProgress: number
  done: number
  percentDone: number | null
}

export interface JiraSprintHealth {
  sprint: JiraSprintRef
  progress: JiraProgress
  measuredIn: 'points' | 'issues'
  percentDone: number | null
  percentElapsed: number | null
  daysLeft: number | null
  blocked: string[]
  atRisk: boolean
  reasons: string[]
  complete: boolean
  issues?: JiraIssue[]
}

export interface JiraApproval {
  issue: string
  summary: string
  approvalId: string
  approvalName: string | null
  url: string | null
  requestType: string | null
  reporter: JiraPerson | null
}

export interface JiraBriefing {
  counts: { open: number; mine: number; overdue: number; blocked: number; dueSoon: number; stale: number; unassigned: number }
  sections: Array<{ id: string; title: string; why: string; count: number; issues: JiraIssue[]; truncated: boolean }>
  complete: boolean
  simulated: boolean
  site: { name: string | null; url: string | null }
  sprints: Array<JiraSprintHealth & { board: JiraBoard }>
  approvals: JiraApproval[] | null
  unavailable: Array<{ part: string; code: string; message: string }>
  proposalsWaiting: number
}

export interface JiraBoard { id: number; name: string; type: 'scrum' | 'kanban' | 'simple' | null; projectKey: string | null }

export interface JiraBoardDetail {
  board: JiraBoard
  sprints: JiraSprintRef[]
  columns: Array<{ name: string; statusIds: string[] }> | null
  activeSprint: JiraSprintHealth | null
  issues?: JiraIssue[]
  simulated: boolean
}

export interface JiraProject { key: string; name: string; kind: string | null; url: string | null }

export type JiraProposalStatus = 'awaiting_approval' | 'executing' | 'executed' | 'failed' | 'rejected' | 'outcome_unknown'

export interface JiraProposal {
  id: string
  action: string
  label: string
  risk: 'low' | 'medium' | 'high'
  status: JiraProposalStatus
  /** One sentence: exactly what approving does. */
  summary: string
  targets: string[]
  reason: string | null
  simulated: boolean
  createdAt: string
  decidedAt: string | null
  held: { code: string; message: string; at: string } | null
  result: Record<string, unknown> | null
  verification: { verified: boolean | null; detail: string } | null
  error: { code: string; message: string } | null
  undo: string | null
}

export interface JiraProposalList {
  proposals: JiraProposal[]
  waiting: number
  store: { kind: string; durable: boolean }
}

export interface JiraFeature {
  id: string
  area: string
  label: string
  state: 'ready' | 'api' | 'planned' | 'excluded'
  note: string | null
  granted: boolean
  missingScopes: string[]
}

export interface JiraFeatureList {
  features: JiraFeature[]
  summary: Record<JiraFeature['state'], number>
  connected: boolean
}

const BASE = '/desk/jira'
const key = (value: string) => encodeURIComponent(value)

export const fetchJiraStatus = () => getJson<JiraStatus>(`${BASE}/status`)
export const fetchJiraFeatures = () => getJson<JiraFeatureList>(`${BASE}/features`)
export const fetchJiraBriefing = () => getJson<JiraBriefing>(`${BASE}/briefing`, { timeout: 60_000 })
export const fetchJiraIssues = (params: Record<string, string | number | boolean | undefined>) =>
  getJson<JiraIssueList>(`${BASE}/issues`, { params })
export const fetchJiraIssue = (issue: string) =>
  getJson<{ issue: JiraIssueDetail; simulated: boolean; canWrite: boolean }>(`${BASE}/issues/${key(issue)}`)
export const fetchJiraProjects = () => getJson<{ projects: JiraProject[] }>(`${BASE}/projects`)
export const fetchJiraProject = (project: string) =>
  getJson<{ project: JiraProject; issueTypes: Array<{ name: string; subtask: boolean }> }>(`${BASE}/projects/${key(project)}`)
export const fetchJiraBoards = () => getJson<{ boards: JiraBoard[] }>(`${BASE}/boards`)
export const fetchJiraBoard = (id: number) => getJson<JiraBoardDetail>(`${BASE}/boards/${id}`)
export const fetchJiraPeople = (params: { issue?: string; project?: string; query?: string; purpose?: 'assign' | 'mention' }) =>
  getJson<{ people: JiraPerson[]; me: string | null }>(`${BASE}/people`, { params })
export const fetchJiraProposals = (status?: string) =>
  getJson<JiraProposalList>(`${BASE}/proposals`, { params: status ? { status } : undefined })

/** Records a change for approval. The backend reads Jira to build the preview; it changes nothing. */
export const proposeJiraChange = (action: string, input: Record<string, unknown>, reason?: string) =>
  postJson<JiraProposal>(`${BASE}/proposals`, { action, input, reason })
export const approveJiraProposal = (id: string, confirmChecked = false) =>
  postJson<JiraProposal>(`${BASE}/proposals/${key(id)}/approve`, { confirmChecked })
export const rejectJiraProposal = (id: string) => postJson<JiraProposal>(`${BASE}/proposals/${key(id)}/reject`)
