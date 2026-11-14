/** Pieces shared by the Jira screens: query keys, an issue row, sprint health, and the list of proposed changes. */
import clsx from 'clsx'
import { ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '../../api/client'
import { approveJiraProposal, fetchJiraProposals, proposeJiraChange, rejectJiraProposal, type JiraIssue, type JiraProposal, type JiraSprintHealth, type JiraWrites, type StatusCategory } from '../../api/jira'
import { Button, EmptyState, ErrorNote, Pill, SkeletonRows } from '../../components/ui'
import type { Tone } from '../../lib/labels'
import { hrefFor } from '../../lib/router'

export const JIRA_KEYS = {
  all: ['desk', 'jira'] as const,
  status: ['desk', 'jira', 'status'] as const,
  briefing: ['desk', 'jira', 'briefing'] as const,
  features: ['desk', 'jira', 'features'] as const,
  boards: ['desk', 'jira', 'boards'] as const,
  proposals: ['desk', 'jira', 'proposals'] as const,
  board: (id: number | null) => ['desk', 'jira', 'board', id] as const,
  issue: (key: string) => ['desk', 'jira', 'issue', key] as const,
  issues: (params: unknown) => ['desk', 'jira', 'issues', params] as const,
}

/** Marks anything that came from, or was applied to, the synthetic Jira site. */
export function SandboxTag() {
  return <span className="pill border border-dashed border-warn/40 bg-transparent text-warn" title="A synthetic Jira site. Nothing real was read or changed.">Simulated</span>
}

const CATEGORY_TONE: Record<StatusCategory, Tone> = { todo: 'neutral', in_progress: 'info', done: 'ok' }

export function StatusPill({ status }: { status: { name: string; category: StatusCategory } }) {
  return <Pill tone={CATEGORY_TONE[status.category]} icon={null}>{status.name}</Pill>
}

export function dueLabel(issue: JiraIssue): string | null {
  const days = issue.signals.dueInDays
  if (days === null) return null
  if (days < 0) return `${-days} day${days === -1 ? '' : 's'} late`
  if (days === 0) return 'Due today'
  return `Due in ${days} day${days === 1 ? '' : 's'}`
}

export function IssueRow({ issue, selected = false }: { issue: JiraIssue; selected?: boolean }) {
  const due = dueLabel(issue)
  return (
    <a href={hrefFor('jira', issue.key)} aria-current={selected ? 'true' : undefined} className={clsx('card block px-4 py-3', selected && 'ring-1 ring-brand-400')}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
        <span className="font-semibold text-accent">{issue.key}</span>
        <span className="text-mute">{issue.type.name}</span>
        <StatusPill status={issue.status} />
        {issue.signals.overdue && <Pill tone="danger">{due}</Pill>}
        {!issue.signals.overdue && due && <Pill tone="warn">{due}</Pill>}
        {issue.signals.blocked && <Pill tone="danger">Blocked</Pill>}
        {issue.signals.stale && <Pill tone="warn">Stalled</Pill>}
      </div>
      <p className="mt-1 text-[14px] font-medium leading-5 text-ink">{issue.summary}</p>
      <p className="mt-1 text-[12px] text-mute">
        {issue.assignee ? issue.assignee.displayName : 'Unassigned'}
        {issue.priority && ` · ${issue.priority.name}`}
        {issue.sprint && ` · ${issue.sprint.name}`}
        {issue.storyPoints !== null && ` · ${issue.storyPoints} pt`}
      </p>
    </a>
  )
}

/** Work done against time gone. The reasons are the backend's, stated as it gives them. */
export function SprintHealth({ health, title }: { health: JiraSprintHealth; title: string }) {
  const bar = (value: number | null, tone: string, label: string) => (
    <div>
      <div className="flex justify-between text-[11.5px] text-mute"><span>{label}</span><span className="tabular-nums">{value === null ? 'unknown' : `${value}%`}</span></div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/[0.07]" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value ?? undefined}>
        <div className={clsx('h-full rounded-full', tone)} style={{ width: `${value ?? 0}%` }} />
      </div>
    </div>
  )
  return (
    <section aria-label={`Sprint health: ${title}`} className="card space-y-3 p-4" data-testid="sprint-health">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[14px] font-semibold text-ink">{title}</h2>
        <Pill tone={health.atRisk ? 'danger' : 'ok'}>{health.atRisk ? 'At risk' : 'On track'}</Pill>
        {health.daysLeft !== null && <span className="text-[12px] text-mute">{health.daysLeft} day{health.daysLeft === 1 ? '' : 's'} left</span>}
      </div>
      {health.sprint.goal && <p className="text-[12.5px] text-soft">Goal: {health.sprint.goal}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {bar(health.percentDone, 'bg-ok', `Work done (by ${health.measuredIn})`)}
        {bar(health.percentElapsed, 'bg-brand-400', 'Time gone')}
      </div>
      <p className="text-[12px] text-mute">{health.progress.done} done, {health.progress.inProgress} in progress, {health.progress.todo} to do.</p>
      {health.reasons.length > 0 && <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] text-warn">{health.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>}
      {!health.complete && <p role="status" className="text-[12px] text-warn">Only the first 100 issues of this sprint were read.</p>}
    </section>
  )
}

export function useProposals(enabled: boolean) {
  return useQuery({ queryKey: JIRA_KEYS.proposals, queryFn: () => fetchJiraProposals(), enabled, refetchInterval: 30_000 })
}

/**
 * Proposes a change and reports what the backend said. It never approves: approval is a separate,
 * deliberate press on the preview.
 */
export function usePropose() {
  const queryClient = useQueryClient()
  const [state, setState] = useState<{ busy: boolean; error: string | null; proposed: JiraProposal | null }>({ busy: false, error: null, proposed: null })
  const propose = async (action: string, input: Record<string, unknown>): Promise<JiraProposal | null> => {
    setState({ busy: true, error: null, proposed: null })
    try {
      const proposed = await proposeJiraChange(action, input)
      setState({ busy: false, error: null, proposed })
      void queryClient.invalidateQueries({ queryKey: JIRA_KEYS.proposals })
      return proposed
    } catch (cause) {
      const problems = (cause as { details?: { problems?: Array<{ field: string; message: string }> } }).details?.problems
      setState({ busy: false, proposed: null, error: problems?.length ? problems.map(problem => problem.message).join(' ') : getErrorMessage(cause) })
      return null
    }
  }
  return { ...state, propose }
}

export function ProposedNote({ proposed }: { proposed: JiraProposal | null }) {
  if (!proposed) return null
  return (
    <p role="status" className="rounded-lg border border-line bg-white/[0.03] px-3 py-2 text-[12.5px] text-soft">
      <span className="font-semibold text-ink">Prepared, not done. </span>{proposed.summary}{' '}
      <a className="font-medium text-accent" href={hrefFor('jira', 'changes')}>Review and approve it under Changes.</a>
    </p>
  )
}

const PROPOSAL_STATUS: Record<JiraProposal['status'], { label: string; tone: Tone }> = {
  awaiting_approval: { label: 'Waiting for you', tone: 'accent' },
  executing: { label: 'Being made', tone: 'info' },
  executed: { label: 'Done', tone: 'ok' },
  failed: { label: 'Failed', tone: 'danger' },
  rejected: { label: 'Rejected', tone: 'neutral' },
  outcome_unknown: { label: 'Outcome unknown', tone: 'warn' },
}

function ProposalCard({ proposal, writes }: { proposal: JiraProposal; writes: JiraWrites }) {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const open = proposal.status === 'awaiting_approval' || proposal.status === 'outcome_unknown'
  const decide = async (kind: 'approve' | 'reject') => {
    setBusy(kind)
    setError(null)
    try {
      await (kind === 'approve' ? approveJiraProposal(proposal.id, proposal.status === 'outcome_unknown') : rejectJiraProposal(proposal.id))
    } catch (cause) {
      setError(getErrorMessage(cause))
    } finally {
      setBusy(null)
      void queryClient.invalidateQueries({ queryKey: JIRA_KEYS.all })
    }
  }
  const label = PROPOSAL_STATUS[proposal.status]
  // A change Jira accepted but that did not read back as approved is not shown as a success.
  const unverified = proposal.status === 'executed' && proposal.verification?.verified === false
  return (
    <article className="card space-y-2 p-4" aria-label={proposal.summary} data-testid="jira-proposal">
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <Pill tone={unverified ? 'warn' : label.tone}>{unverified ? 'Done, not confirmed' : label.label}</Pill>
        <span className="text-mute">{proposal.label}</span>
        {proposal.risk === 'high' && <Pill tone="warn" icon={null}>Hard to undo</Pill>}
        {proposal.simulated && <SandboxTag />}
      </div>
      <p className="text-[14px] font-medium leading-5 text-ink">{proposal.summary}</p>
      {proposal.reason && <p className="text-[12.5px] text-soft">Why: {proposal.reason}</p>}
      {proposal.held && open && <p role="status" className="text-[12.5px] text-warn">Held: {proposal.held.message}</p>}
      {proposal.verification && <p className="text-[12.5px] text-soft">{proposal.verification.detail}</p>}
      {proposal.error && <p className="text-[12.5px] text-danger">{proposal.error.message}</p>}
      {open && proposal.undo && <p className="text-[12px] text-mute">To undo: {proposal.undo}</p>}
      {error && <ErrorNote error={new Error(error)} />}
      {open && (
        <div className="flex flex-wrap gap-2 pt-1">
          <Button variant="primary" busy={busy === 'approve'} disabled={busy !== null} onClick={() => void decide('approve')}>
            {proposal.status === 'outcome_unknown' ? 'I checked Jira. Try again' : writes.mode === 'sandbox' ? 'Approve in the sandbox' : 'Approve'}
          </Button>
          <Button busy={busy === 'reject'} disabled={busy !== null} onClick={() => void decide('reject')}>Reject</Button>
        </div>
      )}
    </article>
  )
}

export function ProposalList({ writes }: { writes: JiraWrites }) {
  const proposals = useProposals(true)
  if (proposals.isPending) return <SkeletonRows rows={3} />
  if (proposals.isError) return <ErrorNote error={new Error(`Changes could not be loaded: ${getErrorMessage(proposals.error)}`)} onRetry={() => void proposals.refetch()} />
  const rows = proposals.data.proposals
  const waiting = rows.filter(row => row.status === 'awaiting_approval' || row.status === 'outcome_unknown' || row.status === 'executing')
  const settled = rows.filter(row => !waiting.includes(row))
  return (
    <div className="max-w-3xl space-y-4">
      {!proposals.data.store.durable && <p className="text-[12.5px] text-mute">Changes waiting here are kept by the running server only: a restart forgets the ones not yet decided.</p>}
      {rows.length === 0 && <EmptyState icon={ShieldCheck} title="No changes have been prepared">When you prepare a change to an issue, it appears here with exactly what it will do, before anything happens.</EmptyState>}
      {waiting.length > 0 && (
        <section aria-label="Waiting for your decision" className="space-y-3">
          <h2 className="eyebrow">Waiting for your decision ({waiting.length})</h2>
          {waiting.map(row => <ProposalCard key={row.id} proposal={row} writes={writes} />)}
        </section>
      )}
      {settled.length > 0 && (
        <section aria-label="Decided" className="space-y-3">
          <h2 className="eyebrow">Decided ({settled.length})</h2>
          {settled.map(row => <ProposalCard key={row.id} proposal={row} writes={writes} />)}
        </section>
      )}
    </div>
  )
}
