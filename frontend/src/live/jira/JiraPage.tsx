/**
 * The Jira workspace. It reads the Desk's Jira routes (api/jira.ts) and nothing else.
 *
 * One rule shapes every control here: nothing changes Jira from a button press alone. A button
 * PROPOSES a change; the backend answers with a one-sentence preview of exactly what would
 * happen; the change is made only when the person approves that preview under "Changes", and
 * only on a backend where Jira writes are switched on. Until then an approval is held, and says so.
 */
import clsx from 'clsx'
import { ExternalLink, Plug, RefreshCw, SquareKanban } from 'lucide-react'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage, redirectToBackend } from '../../api/client'
import { fetchJiraBoard, fetchJiraBoards, fetchJiraBriefing, fetchJiraFeatures, fetchJiraIssues, fetchJiraStatus, type JiraFeature, type JiraStatus } from '../../api/jira'
import { Button, EmptyState, ErrorNote, PageHeader, Pill, SkeletonRows } from '../../components/ui'
import { navigate } from '../../lib/router'
import { IssuePanel, NewIssueForm } from './IssuePanel'
import { IssueRow, JIRA_KEYS, ProposalList, SandboxTag, SprintHealth, useProposals } from './parts'

const TABS = [
  { id: 'briefing', label: 'Briefing' },
  { id: 'issues', label: 'Issues' },
  { id: 'boards', label: 'Boards' },
  { id: 'changes', label: 'Changes' },
  { id: 'coverage', label: 'Coverage' },
] as const
type Tab = (typeof TABS)[number]['id']
const ISSUE_KEY = /^[A-Za-z][A-Za-z0-9_]*-\d+$/

export function JiraPage({ param }: { param: string | null }) {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: JIRA_KEYS.status, queryFn: fetchJiraStatus, retry: false })
  const issueKey = param && ISSUE_KEY.test(param) ? param.toUpperCase() : null
  const tab: Tab = issueKey ? 'issues' : (TABS.find(t => t.id === param)?.id ?? 'briefing')
  const ready = status.data?.enabled === true && status.data.connected === true
  const proposals = useProposals(ready)
  const waiting = proposals.data?.waiting ?? status.data?.proposals?.waiting ?? 0

  return (
    <div>
      <PageHeader
        title="Jira"
        subtitle={ready ? `${status.data!.site?.name ?? 'Your Jira site'}: what needs you, and changes waiting for your approval.` : 'Issues, sprints and approvals from your Jira site.'}
        actions={
          <>
            {status.data?.mode === 'sandbox' && <SandboxTag />}
            {ready && status.data!.site?.url && (
              <a className="btn btn-ghost" href={status.data!.site.url} target="_blank" rel="noreferrer">
                <ExternalLink aria-hidden className="h-4 w-4" />Open Jira
              </a>
            )}
            <Button icon={RefreshCw} busy={status.isFetching} onClick={() => void queryClient.invalidateQueries({ queryKey: JIRA_KEYS.all })}>Refresh</Button>
          </>
        }
      />
      <div className="space-y-4 px-4 pb-12 sm:px-6 lg:px-8">
        {status.isPending && <SkeletonRows rows={3} />}
        {status.isError && <ErrorNote error={new Error(`Jira could not be checked: ${getErrorMessage(status.error)}`)} onRetry={() => void status.refetch()} />}
        {status.data && !status.data.enabled && (
          <EmptyState icon={SquareKanban} title="Jira is not part of this Desk">This backend runs without Jira (DESK_JIRA is off).</EmptyState>
        )}
        {status.data?.enabled && !ready && <Setup status={status.data} />}
        {ready && (
          <>
            <WritesNote status={status.data!} />
            <div role="tablist" aria-label="Jira sections" className="flex gap-1.5 overflow-x-auto scroll-fade">
              {TABS.map(t => (
                <button key={t.id} type="button" role="tab" aria-selected={t.id === tab} onClick={() => navigate('jira', t.id)} className={clsx('tap inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3 text-[12.5px] font-semibold transition-colors duration-150', t.id === tab ? 'bg-brand-500/40 text-ink' : 'text-soft hover:bg-white/[0.06] hover:text-ink')}>
                  {t.label}
                  {t.id === 'changes' && waiting > 0 && <span className="tabular-nums text-accent" aria-label={`${waiting} waiting for approval`}>{waiting}</span>}
                </button>
              ))}
            </div>
            {tab === 'briefing' && <Briefing />}
            {tab === 'issues' && <Issues status={status.data!} issueKey={issueKey} />}
            {tab === 'boards' && <Boards />}
            {tab === 'changes' && <ProposalList writes={status.data!.writes!} />}
            {tab === 'coverage' && <Coverage status={status.data!} />}
          </>
        )}
      </div>
    </div>
  )
}

/** What is missing before Jira can be read, in the order an operator fixes it. Names, never values. */
function Setup({ status }: { status: JiraStatus }) {
  const setup = status.setup
  const notConfigured = status.state === 'not_configured'
  return (
    <section aria-label="Connect Jira" className="card max-w-2xl space-y-3 p-5" data-testid="jira-setup">
      <h2 className="text-[15px] font-semibold text-ink">
        {notConfigured ? 'Jira is not set up on this server yet' : status.state === 'reconnect_required' ? 'Jira needs to be reconnected' : 'Connect your Jira site'}
      </h2>
      {notConfigured ? (
        <>
          <p className="text-[13px] text-soft">The server does not have the Atlassian app's credentials. Whoever runs it sets these, then restarts it:</p>
          <ul className="space-y-1 text-[13px]" aria-label="Missing server settings">
            {(setup?.missingEnv ?? []).map(name => <li key={name}><code className="rounded bg-white/[0.06] px-1.5 py-0.5 text-ink">{name}</code></li>)}
          </ul>
          {setup?.callbackUrl && <p className="text-[13px] text-soft">Callback URL to register in the Atlassian developer console: <code className="break-all rounded bg-white/[0.06] px-1.5 py-0.5 text-ink">{setup.callbackUrl}</code></p>}
        </>
      ) : (
        <>
          <p className="text-[13px] text-soft">{status.reason} You sign in at Atlassian and choose the site; the Desk never sees your password.</p>
          <Button variant="primary" icon={Plug} onClick={() => redirectToBackend(status.loginPath ?? '/auth/jira/login')}>
            {status.state === 'reconnect_required' ? 'Reconnect Jira' : 'Connect Jira'}
          </Button>
        </>
      )}
      {setup && setup.scopesToAdd.length > 0 && (
        <details className="text-[12.5px] text-soft">
          <summary className="tap cursor-pointer font-medium text-accent">Scopes to add for boards and sprints ({setup.scopesToAdd.length})</summary>
          <p className="mt-1.5 break-words">{setup.scopesToAdd.join(' ')}</p>
        </details>
      )}
    </section>
  )
}

function WritesNote({ status }: { status: JiraStatus }) {
  const writes = status.writes
  if (!writes || writes.mode === 'external') return null
  return (
    <p role="status" data-testid="jira-writes-note" className={clsx('rounded-lg border px-3 py-2 text-[12.5px] leading-[19px] text-soft', writes.mode === 'sandbox' ? 'border-warn/30 bg-warn/[0.06]' : 'border-line bg-white/[0.03]')}>
      <span className={clsx('font-semibold', writes.mode === 'sandbox' ? 'text-warn' : 'text-ink')}>{writes.mode === 'sandbox' ? 'Sandbox. ' : 'Changing Jira is switched off. '}</span>
      {writes.message}
    </p>
  )
}

function Briefing() {
  const briefing = useQuery({ queryKey: JIRA_KEYS.briefing, queryFn: fetchJiraBriefing })
  if (briefing.isPending) return <SkeletonRows rows={4} />
  if (briefing.isError) return <ErrorNote error={new Error(`The briefing could not be loaded: ${getErrorMessage(briefing.error)}`)} onRetry={() => void briefing.refetch()} />
  const data = briefing.data
  const stats: Array<[string, number]> = [['Open', data.counts.open], ['Yours', data.counts.mine], ['Overdue', data.counts.overdue], ['Blocked', data.counts.blocked], ['Due this week', data.counts.dueSoon], ['Stalled', data.counts.stale]]
  return (
    <div className="max-w-3xl space-y-5">
      {data.unavailable.length > 0 && (
        <p role="status" className="rounded-lg border border-warn/30 bg-warn/[0.07] px-3 py-2 text-[12.5px] text-warn">
          Part of this briefing could not be read, so it is incomplete: {data.unavailable.map(item => item.message).join(' ')}
        </p>
      )}
      {!data.complete && <p role="status" className="text-[12.5px] text-warn">Only the 100 most pressing issues were read. The counts cover those, not every issue.</p>}
      <dl className="grid grid-cols-3 gap-2 sm:grid-cols-6" aria-label="Jira counts">
        {stats.map(([label, value]) => (
          <div key={label} className="card px-3 py-2.5">
            <dt className="text-[11.5px] font-medium text-mute">{label}</dt>
            <dd className="text-[20px] font-bold tabular-nums text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      {data.approvals && data.approvals.length > 0 && (
        <section aria-label="Waiting for your approval" className="space-y-2">
          <h2 className="eyebrow">Service requests waiting for your approval ({data.approvals.length})</h2>
          <ul className="space-y-2">
            {data.approvals.map(item => (
              <li key={`${item.issue}-${item.approvalId}`} className="card flex flex-wrap items-center gap-2 px-4 py-3 text-[13px]">
                <a className="font-semibold text-accent" href={`#/jira/${item.issue}`}>{item.issue}</a>
                <span className="min-w-0 flex-1 text-ink">{item.summary}</span>
                <span className="text-mute">{item.approvalName}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {data.sprints.map(sprint => <SprintHealth key={sprint.sprint.id} health={sprint} title={`${sprint.board.name}: ${sprint.sprint.name}`} />)}
      {data.sections.length === 0 && <EmptyState icon={SquareKanban} title="Nothing in Jira needs you right now">Nothing is late, blocked, stalled or unowned among the open issues you can see.</EmptyState>}
      {data.sections.map(section => (
        <section key={section.id} aria-label={section.title} className="space-y-2">
          <h2 className="eyebrow">{section.title} ({section.count})</h2>
          <p className="text-[12.5px] text-mute">{section.why}{section.truncated && ' The most pressing are shown.'}</p>
          <ul className="space-y-2">{section.issues.map(issue => <li key={issue.key}><IssueRow issue={issue} /></li>)}</ul>
        </section>
      ))}
    </div>
  )
}

function Issues({ status, issueKey }: { status: JiraStatus; issueKey: string | null }) {
  const [view, setView] = useState(status.defaultView ?? 'my_open')
  const [text, setText] = useState('')
  const [query, setQuery] = useState<{ view: string; text: string; jql: string }>({ view, text: '', jql: '' })
  const [jql, setJql] = useState('')
  const [creating, setCreating] = useState(false)
  const params = query.jql ? { jql: query.jql } : { view: query.view, text: query.text || undefined }
  const list = useQuery({ queryKey: JIRA_KEYS.issues(params), queryFn: () => fetchJiraIssues({ ...params, limit: 50 }) })
  const submit = (next: Partial<typeof query>) => setQuery(current => ({ ...current, jql: '', ...next }))

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="min-w-0 space-y-3">
        <div role="group" aria-label="Views" className="flex flex-wrap gap-1.5">
          {(status.views ?? []).map(item => (
            <button key={item.id} type="button" aria-pressed={!query.jql && item.id === query.view} title={item.description} onClick={() => { setView(item.id); submit({ view: item.id }) }} className={clsx('tap inline-flex h-7 cursor-pointer items-center rounded-full px-2.5 text-[12px] font-semibold', !query.jql && item.id === query.view ? 'bg-brand-500/40 text-ink' : 'bg-white/[0.04] text-soft hover:text-ink')}>
              {item.label}
            </button>
          ))}
        </div>
        <form className="flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); submit({ view, text: text.trim() }) }}>
          <input aria-label="Search issues" value={text} onChange={event => setText(event.target.value)} placeholder="Search text, or an issue key" className="h-9 min-w-0 flex-1 rounded-btn border border-line bg-sunken px-3 text-[13px] text-ink placeholder:text-mute" />
          <Button type="submit">Search</Button>
          <Button variant="primary" onClick={() => setCreating(value => !value)}>{creating ? 'Close' : 'New issue'}</Button>
        </form>
        <details className="text-[12.5px] text-soft">
          <summary className="tap cursor-pointer font-medium text-accent">Write JQL</summary>
          <form className="mt-2 flex gap-2" onSubmit={event => { event.preventDefault(); if (jql.trim()) setQuery(current => ({ ...current, jql: jql.trim() })) }}>
            <input aria-label="JQL" value={jql} onChange={event => setJql(event.target.value)} placeholder='project = "DESK" AND statusCategory != Done' className="h-9 min-w-0 flex-1 rounded-btn border border-line bg-sunken px-3 font-mono text-[12.5px] text-ink placeholder:text-mute" />
            <Button type="submit">Run</Button>
          </form>
        </details>
        {creating && <NewIssueForm onDone={() => setCreating(false)} />}
        {list.isPending && <SkeletonRows rows={5} />}
        {list.isError && <ErrorNote error={new Error(`Issues could not be loaded: ${getErrorMessage(list.error)}`)} onRetry={() => void list.refetch()} />}
        {list.data && (
          <>
            {list.data.issues.length === 0 && <EmptyState icon={SquareKanban} title="No issues in this view" />}
            <ul className="space-y-2" aria-label="Issues">{list.data.issues.map(issue => <li key={issue.key}><IssueRow issue={issue} selected={issue.key === issueKey} /></li>)}</ul>
            {list.data.page.more && <p role="status" className="text-[12.5px] text-mute">The first {list.data.issues.length} are shown. Narrow the view to see the rest.</p>}
          </>
        )}
      </div>
      <div className="min-w-0">
        {issueKey ? <IssuePanel issueKey={issueKey} /> : <p className="hidden rounded-card border border-dashed border-line-strong px-6 py-10 text-center text-[13px] text-soft xl:block">Choose an issue to read it and prepare a change.</p>}
      </div>
    </div>
  )
}

function Boards() {
  const boards = useQuery({ queryKey: JIRA_KEYS.boards, queryFn: fetchJiraBoards, retry: false })
  const [chosen, setChosen] = useState<number | null>(null)
  const boardId = chosen ?? boards.data?.boards[0]?.id ?? null
  const board = useQuery({ queryKey: JIRA_KEYS.board(boardId), queryFn: () => fetchJiraBoard(boardId!), enabled: boardId !== null })
  if (boards.isPending) return <SkeletonRows rows={3} />
  if (boards.isError) return <ErrorNote error={new Error(`Boards could not be loaded: ${getErrorMessage(boards.error)}`)} onRetry={() => void boards.refetch()} />
  if (boards.data.boards.length === 0) return <EmptyState icon={SquareKanban} title="No boards">This Jira site has no board you can see.</EmptyState>
  return (
    <div className="max-w-3xl space-y-4">
      <div role="group" aria-label="Boards" className="flex flex-wrap gap-1.5">
        {boards.data.boards.map(item => (
          <button key={item.id} type="button" aria-pressed={item.id === boardId} onClick={() => setChosen(item.id)} className={clsx('tap inline-flex h-7 cursor-pointer items-center rounded-full px-2.5 text-[12px] font-semibold', item.id === boardId ? 'bg-brand-500/40 text-ink' : 'bg-white/[0.04] text-soft hover:text-ink')}>
            {item.name}{item.type ? ` (${item.type})` : ''}
          </button>
        ))}
      </div>
      {board.isPending && <SkeletonRows rows={4} />}
      {board.isError && <ErrorNote error={new Error(`The board could not be loaded: ${getErrorMessage(board.error)}`)} onRetry={() => void board.refetch()} />}
      {board.data && (
        <>
          {board.data.activeSprint && <SprintHealth health={board.data.activeSprint} title={board.data.activeSprint.sprint.name} />}
          {!board.data.activeSprint && board.data.board.type !== 'kanban' && <p className="text-[13px] text-soft">No sprint is running on this board.</p>}
          {board.data.sprints.filter(sprint => sprint.state === 'future').length > 0 && (
            <p className="text-[12.5px] text-mute">Planned next: {board.data.sprints.filter(sprint => sprint.state === 'future').map(sprint => sprint.name).join(', ')}.</p>
          )}
          <ul className="space-y-2" aria-label="Issues on this board">
            {(board.data.activeSprint?.issues ?? board.data.issues ?? []).map(issue => <li key={issue.key}><IssueRow issue={issue} /></li>)}
          </ul>
        </>
      )}
    </div>
  )
}

const STATE_TONE: Record<JiraFeature['state'], 'ok' | 'info' | 'neutral' | 'warn'> = { ready: 'ok', api: 'info', planned: 'neutral', excluded: 'warn' }
const STATE_LABEL: Record<JiraFeature['state'], string> = { ready: 'Ready', api: 'API only', planned: 'Planned', excluded: 'Left out' }

/** The honest map: every Jira feature, how far this Desk covers it, and what this connection allows. */
function Coverage({ status }: { status: JiraStatus }) {
  const features = useQuery({ queryKey: JIRA_KEYS.features, queryFn: fetchJiraFeatures })
  if (features.isPending) return <SkeletonRows rows={5} />
  if (features.isError) return <ErrorNote error={new Error(`Coverage could not be loaded: ${getErrorMessage(features.error)}`)} onRetry={() => void features.refetch()} />
  const areas = [...new Set(features.data.features.map(feature => feature.area))]
  const ungranted = (status.scopes ?? []).filter(group => !group.granted)
  return (
    <div className="max-w-3xl space-y-5">
      <p className="text-[13px] text-soft">
        {features.data.summary.ready} ready, {features.data.summary.api} served without a screen yet, {features.data.summary.planned} planned, {features.data.summary.excluded} left out on purpose.
      </p>
      {ungranted.length > 0 && (
        <div className="card space-y-1.5 p-4 text-[12.5px] text-soft">
          <p className="font-semibold text-ink">This connection was not granted everything</p>
          <ul className="space-y-1">{ungranted.map(group => <li key={group.id}>{group.label}: <span className="break-words text-mute">{group.missing.join(' ')}</span></li>)}</ul>
          <p>Add the scopes to the Atlassian app, set them on the server, then reconnect Jira.</p>
        </div>
      )}
      {areas.map(area => (
        <section key={area} aria-label={area} className="space-y-1.5">
          <h2 className="eyebrow">{area}</h2>
          <ul className="divide-y divide-line rounded-card border border-line">
            {features.data.features.filter(feature => feature.area === area).map(feature => (
              <li key={feature.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3.5 py-2.5 text-[13px]">
                <span className="min-w-0 flex-1 text-ink">{feature.label}</span>
                {!feature.granted && feature.state !== 'excluded' && <Pill tone="warn" icon={null}>Scope missing</Pill>}
                <Pill tone={STATE_TONE[feature.state]} icon={null}>{STATE_LABEL[feature.state]}</Pill>
                {feature.note && <span className="basis-full text-[12px] text-mute">{feature.note}</span>}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
