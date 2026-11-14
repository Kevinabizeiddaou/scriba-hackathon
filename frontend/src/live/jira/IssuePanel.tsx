/** One issue, and the forms that prepare a change to it. Every form proposes; none of them changes Jira. */
import { ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getErrorMessage } from '../../api/client'
import { fetchJiraIssue, fetchJiraProject, fetchJiraProjects } from '../../api/jira'
import { Button, ErrorNote, SkeletonRows } from '../../components/ui'
import { hrefFor } from '../../lib/router'
import { JIRA_KEYS, ProposedNote, StatusPill, dueLabel, usePropose } from './parts'

const FIELD = 'w-full rounded-btn border border-line bg-sunken px-3 py-2 text-[13px] text-ink placeholder:text-mute'

export function IssuePanel({ issueKey }: { issueKey: string }) {
  const detail = useQuery({ queryKey: JIRA_KEYS.issue(issueKey), queryFn: () => fetchJiraIssue(issueKey) })
  const change = usePropose()
  const [comment, setComment] = useState('')
  if (detail.isPending) return <SkeletonRows rows={4} />
  if (detail.isError) return <ErrorNote error={new Error(`${issueKey} could not be loaded: ${getErrorMessage(detail.error)}`)} onRetry={() => void detail.refetch()} />
  const { issue, canWrite } = detail.data
  const due = dueLabel(issue)
  const facts: Array<[string, string | null]> = [
    ['Assignee', issue.assignee?.displayName ?? 'Unassigned'], ['Reporter', issue.reporter?.displayName ?? null],
    ['Priority', issue.priority?.name ?? null], ['Due', issue.due ? `${issue.due}${due ? ` (${due.toLowerCase()})` : ''}` : null],
    ['Sprint', issue.sprint?.name ?? null], ['Story points', issue.storyPoints === null ? null : String(issue.storyPoints)],
    ['Parent', issue.parent ? `${issue.parent.key} ${issue.parent.summary}` : null], ['Labels', issue.labels.join(', ') || null],
    ['Fix versions', issue.fixVersions.join(', ') || null],
  ]
  return (
    <article aria-label={`${issue.key}: ${issue.summary}`} className="card space-y-4 p-5" data-testid="jira-issue">
      <header className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2 text-[12px]">
          <span className="font-semibold text-accent">{issue.key}</span>
          <span className="text-mute">{issue.type.name}</span>
          <StatusPill status={issue.status} />
          {issue.url && <a className="ml-auto inline-flex items-center gap-1 text-accent" href={issue.url} target="_blank" rel="noreferrer"><ExternalLink aria-hidden className="h-3.5 w-3.5" />Open in Jira</a>}
        </div>
        <h2 className="text-[17px] font-semibold leading-6 text-ink">{issue.summary}</h2>
      </header>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[12.5px]">
        {facts.filter(([, value]) => value).map(([label, value]) => (
          <div key={label} className="contents"><dt className="text-mute">{label}</dt><dd className="min-w-0 text-ink">{value}</dd></div>
        ))}
      </dl>
      {/* Written by other people: shown as text, never interpreted. */}
      {issue.description && <p className="whitespace-pre-wrap break-words text-[13px] leading-5 text-soft">{issue.description}</p>}
      {issue.links.length + issue.subtasks.length > 0 && (
        <ul className="space-y-1 text-[12.5px]" aria-label="Related issues">
          {issue.links.map(link => <li key={link.id}><span className="text-mute">{link.label}</span> <a className="text-accent" href={hrefFor('jira', link.issue.key)}>{link.issue.key}</a> {link.issue.summary}</li>)}
          {issue.subtasks.map(task => <li key={task.key}><span className="text-mute">sub-task</span> <a className="text-accent" href={hrefFor('jira', task.key)}>{task.key}</a> {task.summary}</li>)}
        </ul>
      )}

      <section aria-label="Prepare a change" className="space-y-2.5 border-t border-line pt-4">
        <h3 className="eyebrow">Prepare a change</h3>
        {!canWrite && <p className="text-[12.5px] text-warn">This connection can read Jira but was not granted the scope to change it.</p>}
        <div className="flex flex-wrap gap-2" role="group" aria-label="Move this issue">
          {issue.transitions.map(transition => (
            <Button key={transition.id} disabled={!canWrite || change.busy} onClick={() => void change.propose('transition_issue', { issue: issue.key, transition: transition.id })}>
              {transition.name}
            </Button>
          ))}
          <Button disabled={!canWrite || change.busy} onClick={() => void change.propose('assign_issue', { issue: issue.key, assignee: 'me' })}>Assign to me</Button>
          <Button disabled={!canWrite || change.busy} onClick={() => void change.propose(issue.watching ? 'unwatch_issue' : 'watch_issue', { issue: issue.key })}>{issue.watching ? 'Stop watching' : 'Watch'}</Button>
        </div>
        <form className="space-y-2" onSubmit={event => { event.preventDefault(); void change.propose('add_comment', { issue: issue.key, body: comment }).then(done => { if (done) setComment('') }) }}>
          <textarea aria-label="Comment" value={comment} onChange={event => setComment(event.target.value)} rows={3} placeholder="Write a comment" className={FIELD} />
          <Button type="submit" disabled={!canWrite || !comment.trim()} busy={change.busy}>Prepare comment</Button>
        </form>
        {change.error && <ErrorNote error={new Error(change.error)} />}
        <ProposedNote proposed={change.proposed} />
      </section>

      <section aria-label="Comments" className="space-y-2 border-t border-line pt-4">
        <h3 className="eyebrow">Comments ({issue.counts.comments ?? issue.comments.length})</h3>
        {issue.comments.length === 0 && <p className="text-[12.5px] text-mute">No comments.</p>}
        <ul className="space-y-2.5">
          {issue.comments.map(item => (
            <li key={item.id} className="text-[13px]">
              <p className="text-[12px] text-mute">{item.author?.displayName ?? 'Unknown'}{item.created && ` · ${item.created.slice(0, 10)}`}{item.mentionsMe && ' · mentions you'}{item.internal && ' · internal note'}</p>
              <p className="whitespace-pre-wrap break-words text-soft">{item.body}</p>
            </li>
          ))}
        </ul>
        {issue.commentsTruncated && <p className="text-[12px] text-mute">Older comments are in Jira.</p>}
      </section>
    </article>
  )
}

export function NewIssueForm({ onDone }: { onDone: () => void }) {
  const projects = useQuery({ queryKey: [...JIRA_KEYS.all, 'projects'], queryFn: fetchJiraProjects })
  const [project, setProject] = useState('')
  const chosen = project || projects.data?.projects[0]?.key || ''
  const meta = useQuery({ queryKey: [...JIRA_KEYS.all, 'project', chosen], queryFn: () => fetchJiraProject(chosen), enabled: Boolean(chosen) })
  const [issueType, setIssueType] = useState('Task')
  const [summary, setSummary] = useState('')
  const [description, setDescription] = useState('')
  const change = usePropose()
  const types = (meta.data?.issueTypes ?? []).filter(kind => !kind.subtask)
  return (
    <form aria-label="New issue" className="card space-y-2.5 p-4" onSubmit={event => {
      event.preventDefault()
      void change.propose('create_issue', { project: chosen, issueType, summary, description }).then(done => { if (done) { setSummary(''); setDescription('') } })
    }}>
      <div className="grid gap-2 sm:grid-cols-2">
        <select aria-label="Project" value={chosen} onChange={event => setProject(event.target.value)} className={FIELD}>
          {(projects.data?.projects ?? []).map(item => <option key={item.key} value={item.key}>{item.name} ({item.key})</option>)}
        </select>
        <select aria-label="Issue type" value={issueType} onChange={event => setIssueType(event.target.value)} className={FIELD}>
          {(types.length ? types : [{ name: 'Task' }]).map(kind => <option key={kind.name} value={kind.name}>{kind.name}</option>)}
        </select>
      </div>
      <input aria-label="Summary" value={summary} onChange={event => setSummary(event.target.value)} maxLength={255} placeholder="Summary" className={FIELD} />
      <textarea aria-label="Description" value={description} onChange={event => setDescription(event.target.value)} rows={3} placeholder="Description (optional)" className={FIELD} />
      {projects.isError && <ErrorNote error={new Error(`Projects could not be loaded: ${getErrorMessage(projects.error)}`)} />}
      {change.error && <ErrorNote error={new Error(change.error)} />}
      <ProposedNote proposed={change.proposed} />
      <div className="flex gap-2">
        <Button type="submit" variant="primary" busy={change.busy} disabled={!chosen || !summary.trim()}>Prepare issue</Button>
        <Button onClick={onDone}>Close</Button>
      </div>
    </form>
  )
}
