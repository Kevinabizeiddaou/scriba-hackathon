import clsx from 'clsx'
import { AlertTriangle, ArrowRight, CalendarDays, CheckCircle2, Inbox, ListTodo, PlugZap, RefreshCw, ShieldCheck, type LucideIcon } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { backendUrl, getErrorMessage } from '../api/client'
import { fetchDeskBriefing, fetchDeskFollowUps, type DeskInbox, type MailSource, type TriageCategory } from '../api/desk'
import { Button, ErrorNote, PageHeader, Pill, SkeletonRows } from '../components/ui'
import { Section, SourceBadge } from '../components/workspace'
import { getApi } from '../harness'
import type { ConnectedAccount } from '../harness/workspace'
import { PRIORITY } from '../lib/labels'
import { hrefFor, type Page } from '../lib/router'
import { fmtDayTime, fmtTime, isInstant } from '../lib/time'
import { describeAction } from './describeAction'
import { executedLabel } from './executionMode'
import { useOwnedWork, QueueCoverage } from './LiveWorkPages'
import { deskLinkOf } from './ownership'
import { QUEUE_GROUPS, QUEUE_ORDER, groupOf, nextStepOf, type QueueGroup } from './deskRuns'
import { FOLLOW_UPS_KEY, openFollowUps, tracksFollowUps } from './LiveFollowUps'
import { useDeskWorker, useRunQueue } from './LiveWorkQueuePage'
import { AgentActivity, FollowUpItem } from './RunParts'
import { emailKey, parseSender, toAccounts, toMailProvider, toPriority } from './mappers'
import { useRequiredLiveSession } from './session'
import { WORK_STAGES, needsIntervention, needsUser, stageOf } from './workQueue'

const CATEGORY_LABEL: Record<TriageCategory, string> = {
  meeting_request: 'Meeting requests',
  needs_reply: 'Need a reply',
  action_item: 'Action items',
  informational: 'For information',
  automated: 'Automated',
}

const SOURCE_PROBLEM: Record<string, string> = {
  reconnect_required: 'needs to be reconnected',
  disconnected: 'is not connected',
  unavailable: 'is not available on this server',
  provider_error: 'could not be read',
}

/** Says which mailbox is missing from the numbers, in words. */
export function sourceProblems(sources: MailSource[]): string[] {
  return sources
    .filter(source => !source.ok && source.state !== 'disconnected' && source.state !== 'unavailable')
    .map(source => `${source.provider === 'gmail' ? 'Gmail' : 'Outlook'} ${SOURCE_PROBLEM[source.error ?? source.state] ?? 'could not be read'}`)
}

function Stage({ icon: Icon, label, value, detail, href, tone = 'neutral', unknown = false }: { icon: LucideIcon; label: string; value: number | null; detail: string; href: string; tone?: 'neutral' | 'warn' | 'danger' | 'ok'; unknown?: boolean }) {
  const colour = tone === 'warn' ? 'text-warn' : tone === 'danger' ? 'text-danger' : tone === 'ok' ? 'text-ok' : 'text-ink'
  return (
    <a href={href} className="group flex min-w-0 flex-col gap-0.5 rounded-xl px-2.5 py-2 transition-colors duration-150 hover:bg-white/[0.04]">
      <span className="flex items-center gap-1.5 text-[12px] font-semibold text-soft">
        <Icon aria-hidden className="hidden h-3.5 w-3.5 shrink-0 text-mute sm:block" />
        {label}
      </span>
      <span className={clsx('text-[24px] font-bold leading-8 tabular-nums', value && value > 0 ? colour : 'text-ink')}>
        {unknown || value === null ? '–' : value}
      </span>
      {/* On a phone the explanation is dropped to keep the strip short, except when it reports a failed read. */}
      <span className={clsx('text-[12px] leading-[17px] text-mute', !unknown && 'hidden lg:block')}>{detail}</span>
    </a>
  )
}

/** One half of the status strip: either what is waiting on the user, or what the secretary has in hand. */
function StageGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={title} className="min-w-0 p-3 sm:p-4">
      <p className="eyebrow mb-1 px-2.5">{title}</p>
      <div className="grid grid-cols-3 gap-1">{children}</div>
    </div>
  )
}

const STATE_LABEL = { connected: 'Connected', reconnect_required: 'Reconnect needed', disconnected: 'Not connected', unavailable: 'Not available on this server' } as const

export function ConnectionsCard({ accounts, ready }: { accounts: ConnectedAccount[]; ready: boolean }) {
  return (
    <Section title="Connected accounts" action={<Pill tone={ready ? 'ok' : 'warn'}>{ready ? 'Ready: mail and calendar' : 'Connect a mailbox and a calendar'}</Pill>}>
      <ul className="grid gap-2 sm:grid-cols-2">
        {accounts.map(account => (
          <li key={account.id} className="flex items-center gap-3 rounded-xl border border-line bg-white/[0.02] px-3 py-2.5" data-testid={`connection-${account.id}`}>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-ink">{account.label}</p>
              <p className="truncate text-[12px] text-mute">{account.address || (account.status === 'unavailable' ? 'This server is not set up for it' : 'No account connected')}</p>
            </div>
            {account.status === 'connected' ? (
              <Pill tone="ok">Connected</Pill>
            ) : account.status === 'unavailable' ? (
              <Pill tone="neutral" icon={null}>{STATE_LABEL.unavailable}</Pill>
            ) : (
              // A navigation to Scriba's own OAuth start, chosen by the user. Never a fetch, never automatic.
              <a href={backendUrl(account.loginPath ?? '/')} className="btn btn-secondary h-8 px-2.5">
                {account.status === 'reconnect_required' ? 'Reconnect' : 'Connect'}
              </a>
            )}
            {account.status !== 'connected' && account.status !== 'unavailable' && <span className="sr-only">{STATE_LABEL[account.status]}</span>}
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-[12px] text-mute">Connections are the ones already authorised in Scriba. Connecting opens Scriba's sign-in for that provider; afterwards, return to this page.</p>
    </Section>
  )
}

export function LiveOverviewPage() {
  const session = useRequiredLiveSession()
  const { principal } = getApi().info
  const tz = principal.timezone

  const briefing = useQuery({ queryKey: ['desk', 'briefing'], queryFn: fetchDeskBriefing, staleTime: 30_000 })
  const inbox = useQuery<DeskInbox>({ queryKey: ['desk', 'inbox'], queryFn: () => session.workspace.inbox() })
  const connections = useQuery({ queryKey: ['desk', 'connections'], queryFn: () => session.workspace.connections() })
  // The secretary's numbers are the Desk's own action cards; Scriba chat cards are counted apart.
  const { queue, index, owned, runsPending } = useOwnedWork()
  const runs = useRunQueue(session.overlay === 'ok')
  const sandbox = session.mode.kind === 'sandbox'
  const worker = useDeskWorker()
  const followUpsTracked = tracksFollowUps(session)
  const followUps = useQuery({ queryKey: FOLLOW_UPS_KEY, queryFn: () => fetchDeskFollowUps({ refresh: true }), enabled: followUpsTracked })
  // How many picked-up requests sit in each list of the work queue. Only runs that were read count.
  const byGroup = new Map<QueueGroup, number>()
  for (const entry of runs.data?.entries ?? []) if (entry.run) byGroup.set(groupOf(entry.run), (byGroup.get(groupOf(entry.run)) ?? 0) + 1)
  const runsForUser = (runs.data?.entries ?? []).filter(entry => entry.run && ['decision', 'input', 'problem', 'unverified', 'unknown'].includes(groupOf(entry.run)))

  useEffect(() => {
    session.desk.setTimeZone(briefing.data?.timezone)
  }, [briefing.data?.timezone, session.desk])

  const refresh = () => {
    session.workspace.refresh()
    void briefing.refetch()
    void inbox.refetch()
    void connections.refetch()
    void queue.refetch()
    void runs.refetch()
  }

  const link = (page: Page, param?: string) => hrefFor(page, param)
  // While the runs load it is not known whose a card is: nothing is counted as the secretary's yet.
  const work = owned.known ? owned.desk : runsPending ? [] : owned.scriba
  const counted = Boolean(queue.data) && !runsPending
  const waiting = work.filter(needsUser)
  const problems = work.filter(needsIntervention)
  const executing = work.filter(card => stageOf(card.toolCall.status) === 'executing')
  const completed = work.filter(card => stageOf(card.toolCall.status) === 'completed')
  // "Verified" is the Desk's evidence flag on the action, or, for a card the Desk does not own, Scriba's action record.
  const isVerified = (card: (typeof work)[number]) => {
    const action = deskLinkOf(card, index)?.action
    return action ? action.verified === true : card.toolCall.assistant_action_id != null
  }
  const verifiedCount = completed.filter(isVerified).length
  const unverifiedCount = completed.length - verifiedCount
  const scribaWaiting = owned.known ? owned.scriba.filter(card => needsUser(card) || needsIntervention(card)).length : 0
  const finishedRuns = (runs.data?.entries ?? []).filter(entry => entry.run && ['done', 'unverified', 'no_action'].includes(groupOf(entry.run)))
  const finishedRunActions = new Set(finishedRuns.flatMap(entry => entry.run!.actions.map(action => action.toolCallId)))
  // Finished work, only as the server reports it: actions that ran, and picked-up requests the run closed.
  // Green is for work with verification evidence; "ran" alone is listed as not verified.
  const handled: { key: string; kind: 'verified' | 'unverified' | 'closed'; title: string; detail: string; href: string }[] = [
    // A run's actions are chat tool calls (the ids match), so an action whose run is listed below is
    // not listed a second time on its own.
    ...completed.filter(card => !finishedRunActions.has(card.toolCall.id)).map(card => {
      const description = describeAction(card.toolCall)
      const run = deskLinkOf(card, index)
      const simulated = run?.action?.simulated === true
      const verified = isVerified(card)
      return { key: `action-${card.toolCall.id}`, kind: verified ? ('verified' as const) : ('unverified' as const), title: description.headline || description.title, detail: `${description.title}: ${verified ? executedLabel(simulated, true).toLowerCase() : `${executedLabel(simulated).toLowerCase()}, not verified`}`, href: run ? link('work', String(run.runId)) : link('activity') }
    }),
    ...finishedRuns.map(({ row, run }) => {
      const group = groupOf(run!)
      return { key: `run-${row.runId}`, kind: group === 'done' ? ('verified' as const) : group === 'unverified' ? ('unverified' as const) : ('closed' as const), title: run!.email.subject || 'No subject', detail: group === 'done' && run!.simulated ? 'Completed in the sandbox, verified by read-back' : QUEUE_GROUPS[group].label, href: link('work', String(row.runId)) }
    }),
  ]
  const arrived = inbox.data?.items.length ?? null
  const classified = inbox.data?.counts
  const needsAttention = briefing.data?.needs_attention ?? []
  const missingMail = [...sourceProblems(inbox.data?.sources ?? briefing.data?.sources ?? [])]
  const hour = Number(fmtTime(new Date().toISOString(), tz).slice(0, 2))
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const firstName = principal.name.includes('@') ? '' : principal.name.split(' ')[0]

  return (
    <div>
      <PageHeader
        title={firstName ? `${greeting}, ${firstName}` : greeting}
        subtitle={briefing.data?.headline ?? 'What arrived, what the secretary made of it, and what is waiting for you.'}
        actions={<Button icon={RefreshCw} onClick={refresh} busy={briefing.isFetching || inbox.isFetching || queue.isFetching}>Refresh</Button>}
      />

      <div className="space-y-5 px-4 pb-12 sm:px-6 lg:px-8">
        {session.overlay === 'missing' && (
          <p role="alert" className="flex gap-2.5 rounded-xl border border-warn/30 bg-warn/[0.08] px-3.5 py-3 text-[13px] text-warn">
            <PlugZap aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
            <span>This Scriba backend is running without the Desk overlay, so the unified inbox, triage, availability and briefing are not available. Start the backend with the overlay (backend/README.md). Chat, tasks and the calendar still work.</span>
          </p>
        )}

        {missingMail.length > 0 && (
          <p role="alert" className="flex gap-2.5 rounded-xl border border-warn/30 bg-warn/[0.08] px-3.5 py-3 text-[13px] text-warn" data-testid="mail-incomplete">
            <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{missingMail.join('; ')}. Mail from it is missing below, so the numbers are a minimum, not a total.</span>
          </p>
        )}

        {/* Two halves: what cannot move without the user, and what the secretary has in hand or has finished. */}
        <section aria-label="Where the work stands" className="card grid divide-y divide-line lg:grid-cols-2 lg:divide-x lg:divide-y-0">
          <StageGroup title="Waiting on you">
            <Stage icon={ShieldCheck} label="Awaiting approval" value={counted ? waiting.length : null} unknown={queue.isError} tone="warn" href={link('approvals')} detail={queue.isError ? 'Could not be read' : scribaWaiting > 0 ? `Proposed by the secretary; nothing has happened yet. ${scribaWaiting} more in Scriba chat, counted apart` : 'Proposed by the secretary; nothing has happened yet'} />
            <Stage icon={AlertTriangle} label="Failed or partial" value={counted ? problems.length : null} unknown={queue.isError} tone="danger" href={link('activity')} detail={queue.isError ? 'Could not be read' : 'Did not finish cleanly; needs a person'} />
            <Stage icon={ListTodo} label="Need action" value={classified ? classified.meeting_request + classified.needs_reply + classified.action_item : null} unknown={inbox.isError} href={link('inbox')} detail={inbox.isError ? 'Could not be read' : 'Mail classified as a meeting request, a reply or an action'} />
          </StageGroup>
          <StageGroup title="With the secretary">
            <Stage icon={Inbox} label="Arrived" value={arrived} unknown={inbox.isError} href={link('inbox')} detail={inbox.isError ? 'Could not be read' : 'Recent messages across Gmail and Outlook'} />
            <Stage icon={RefreshCw} label="Executing" value={counted ? executing.length : null} unknown={queue.isError} href={link('activity')} detail={queue.isError ? 'Could not be read' : sandbox ? 'Approved and running in the sandbox now' : 'Approved and running now'} />
            <Stage icon={CheckCircle2} label="Verified" value={counted ? verifiedCount : null} unknown={queue.isError} tone="ok" href={link('activity')} detail={queue.isError ? 'Could not be read' : `${sandbox ? 'Executed in the sandbox and read back there; nothing real was sent' : 'Executed, with verification evidence on record'}${unverifiedCount > 0 ? `. ${unverifiedCount} more ran without verification and ${unverifiedCount === 1 ? 'is' : 'are'} not counted` : ''}`} />
          </StageGroup>
        </section>
        {queue.data && <QueueCoverage queue={queue.data} />}

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-5">
            {session.overlay === 'ok' && (
              <Section title="Requests the secretary picked up" action={<a href={link('work')} className="tap inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">Work queue <ArrowRight aria-hidden className="h-3.5 w-3.5" /></a>}>
                {worker.supported && worker.query.data && (
                  <div className="mb-3 border-b border-line pb-3">
                    <AgentActivity worker={worker.query.data.worker} timeZone={tz} />
                  </div>
                )}
                {runs.data && byGroup.size > 0 && (
                  <ul aria-label="Picked-up requests by where they stand" className="mb-3 flex flex-wrap gap-1.5">
                    {QUEUE_ORDER.filter(group => byGroup.has(group)).map(group => (
                      <li key={group}>
                        <Pill tone={QUEUE_GROUPS[group].tone} icon={null}>
                          <span className="tabular-nums">{byGroup.get(group)}</span> {QUEUE_GROUPS[group].label.toLowerCase()}
                        </Pill>
                      </li>
                    ))}
                  </ul>
                )}
                {runs.isPending && <SkeletonRows rows={2} />}
                {runs.isError && <ErrorNote error={new Error(`The work queue could not be loaded: ${getErrorMessage(runs.error)}`)} onRetry={() => void runs.refetch()} />}
                {runs.data && runsForUser.length === 0 && (
                  <p className="text-[13px] text-soft">
                    {runs.data.entries.length === 0 ? 'Nothing has been picked up yet. New mail is picked up when you check for new work in the work queue.' : 'No picked-up request needs you right now.'}
                  </p>
                )}
                <ul className="space-y-2">
                  {runsForUser.slice(0, 5).map(({ row, run }) => (
                    <li key={row.runId}>
                      <a href={link('work', String(row.runId))} className="lift flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-white/[0.02] px-3.5 py-2.5 hover:border-line-strong">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13.5px] font-semibold text-ink">{run!.email.subject || 'No subject'}</span>
                          <span className="block truncate text-[12px] text-soft">{nextStepOf(run!).label}</span>
                        </span>
                        <Pill tone={QUEUE_GROUPS[groupOf(run!)].tone}>{QUEUE_GROUPS[groupOf(run!)].label}</Pill>
                      </a>
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            <Section title="Waiting for you" action={<a href={link('approvals')} className="tap inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">Approval center <ArrowRight aria-hidden className="h-3.5 w-3.5" /></a>}>
              {queue.isPending && <SkeletonRows rows={2} />}
              {queue.isError && <ErrorNote error={new Error(`The secretary's actions could not be loaded: ${getErrorMessage(queue.error)}`)} onRetry={() => void queue.refetch()} />}
              {counted && waiting.length === 0 && problems.length === 0 && <p className="text-[13px] text-soft">No proposal from the secretary is waiting for a decision, and nothing has failed.</p>}
              {scribaWaiting > 0 && <p className="mb-2 text-[12px] text-mute" data-testid="scriba-waiting">{scribaWaiting} more action{scribaWaiting === 1 ? ' is' : 's are'} waiting in Scriba chat. {scribaWaiting === 1 ? 'It was' : 'They were'} not opened by the Desk and {scribaWaiting === 1 ? 'is' : 'are'} listed apart in the approval center.</p>}
              <ul className="space-y-2">
                {[...waiting, ...problems].slice(0, 6).map(card => {
                  const description = describeAction(card.toolCall)
                  const stage = WORK_STAGES[stageOf(card.toolCall.status)]
                  return (
                    <li key={card.toolCall.id}>
                      <a href={link('approvals')} className="lift flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-white/[0.02] px-3.5 py-2.5 hover:border-line-strong">
                        <span className="min-w-0 flex-1">
                          <span className="block text-[12px] text-mute">{description.title}</span>
                          <span className="block truncate text-[13.5px] font-semibold text-ink">{description.headline || 'No title on the card'}</span>
                          {description.recipients.length > 0 && <span className="block truncate text-[12px] text-soft">To {description.recipients.join(', ')}</span>}
                        </span>
                        <Pill tone={stage.tone}>{stage.label}</Pill>
                      </a>
                    </li>
                  )
                })}
              </ul>
            </Section>

            <Section title="Mail that needs you" action={<a href={link('inbox')} className="tap inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">Inbox <ArrowRight aria-hidden className="h-3.5 w-3.5" /></a>}>
              {briefing.isPending && <SkeletonRows rows={3} />}
              {briefing.isError && <ErrorNote error={new Error(`The briefing could not be loaded: ${getErrorMessage(briefing.error)}`)} onRetry={() => void briefing.refetch()} />}
              {briefing.data && needsAttention.length === 0 && <p className="text-[13px] text-soft">{briefing.data.inbox_complete ? 'No recent message needs a reply or an action.' : 'No message that could be read needs a reply or an action.'}</p>}
              <ul className="space-y-1.5">
                {needsAttention.slice(0, 7).map(line => {
                  const priority = toPriority(line.priority)
                  return (
                    <li key={`${line.provider}:${line.id}`}>
                      <a href={link('inbox', emailKey(line.provider, line.id))} className="lift flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-transparent px-3 py-2 hover:border-line hover:bg-white/[0.04]">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13.5px] font-semibold text-ink">{parseSender(line.from_addr).name}</span>
                          <span className="block truncate text-[12.5px] text-soft">{line.subject || '(no subject)'}</span>
                        </span>
                        <Pill tone={line.category === 'meeting_request' ? 'accent' : line.category === 'action_item' ? 'warn' : 'info'} icon={null}>{CATEGORY_LABEL[line.category].replace(/s$/, '')}</Pill>
                        {(priority === 'urgent' || priority === 'high') && <Pill tone={PRIORITY[priority].tone} icon={null}>{PRIORITY[priority].label}</Pill>}
                        <SourceBadge source={toMailProvider(line.provider)} />
                      </a>
                    </li>
                  )
                })}
              </ul>
              {classified && (
                <p className="mt-3 border-t border-line pt-3 text-[12px] text-mute" data-testid="classified">
                  Classified by rules, without a model: {(Object.keys(CATEGORY_LABEL) as TriageCategory[]).map(category => `${classified[category] ?? 0} ${CATEGORY_LABEL[category].toLowerCase()}`).join(' · ')}.
                </p>
              )}
            </Section>
          </div>

          <div className="min-w-0 space-y-5">
            <Section title="Today" action={<a href={link('calendar')} className="tap inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">Calendar <ArrowRight aria-hidden className="h-3.5 w-3.5" /></a>}>
              {briefing.isPending && <SkeletonRows rows={3} />}
              {briefing.data && (
                <div className="space-y-4 text-[13px]">
                  {briefing.data.unavailable.length > 0 && (
                    <p role="alert" className="rounded-lg border border-warn/30 bg-warn/[0.07] px-3 py-2 text-[12.5px] text-warn">
                      Could not be loaded: {briefing.data.unavailable.join(', ')}. Those parts are missing below, not empty.
                    </p>
                  )}
                  <div>
                    <h3 className="eyebrow mb-1.5 flex items-center gap-1.5"><CalendarDays aria-hidden className="h-3.5 w-3.5" /> Meetings ({briefing.data.meetings_today.length})</h3>
                    {briefing.data.unavailable.includes('agenda') ? null : briefing.data.meetings_today.length === 0 ? (
                      <p className="text-soft">No meetings today.</p>
                    ) : (
                      <ul className="space-y-1">
                        {briefing.data.meetings_today.map((meeting, index) => (
                          <li key={meeting.event_id ?? index} className="flex items-baseline gap-3">
                            <span className="w-[92px] shrink-0 tabular-nums text-soft">
                              {meeting.start_time && isInstant(meeting.start_time) ? `${fmtTime(meeting.start_time, tz)}${meeting.end_time && isInstant(meeting.end_time) ? `–${fmtTime(meeting.end_time, tz)}` : ''}` : 'All day'}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-ink">{meeting.title || '(no title)'}</span>
                            <SourceBadge source={(meeting.calendar_provider ?? meeting.provider ?? '').includes('outlook') ? 'outlook' : 'google'} />
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div>
                    <h3 className="eyebrow mb-1.5 flex items-center gap-1.5"><ListTodo aria-hidden className="h-3.5 w-3.5" /> Tasks due today ({briefing.data.tasks_due_today.length})</h3>
                    {briefing.data.unavailable.includes('tasks') ? null : briefing.data.tasks_due_today.length === 0 ? (
                      <p className="text-soft">Nothing is due today. {briefing.data.counts.open_tasks} open in total.</p>
                    ) : (
                      <ul className="space-y-1">
                        {briefing.data.tasks_due_today.map(task => (
                          <li key={task.id} className="flex items-baseline gap-3">
                            <span className="min-w-0 flex-1 truncate text-ink">{task.title}</span>
                            {task.due_at && isInstant(task.due_at) && <span className="tabular-nums text-soft">{fmtDayTime(task.due_at, tz)}</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <p className="text-[12px] text-mute">
                    {briefing.data.counts.reminders} reminder{briefing.data.counts.reminders === 1 ? '' : 's'} scheduled. <a href={link('tasks', 'reminders')} className="font-medium text-accent hover:underline">Open</a>
                  </p>
                </div>
              )}
            </Section>

            <Section title="Handled by the secretary" action={<a href={link('activity')} className="tap inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">Activity <ArrowRight aria-hidden className="h-3.5 w-3.5" /></a>}>
              {(queue.isPending || (session.overlay === 'ok' && runs.isPending)) && <SkeletonRows rows={2} />}
              {!queue.isPending && !(session.overlay === 'ok' && runs.isPending) && handled.length === 0 && (
                <p className="text-[13px] text-soft">{queue.isError ? 'The record of finished work could not be read.' : sandbox ? 'Nothing has been executed in the sandbox yet. Actions the secretary executed and verified, and requests closed without action, are listed here.' : 'Nothing has been finished yet. Verified actions and requests closed without action are listed here once the server reports them.'}</p>
              )}
              <ul className="divide-y divide-line">
                {handled.slice(0, 5).map(item => (
                  <li key={item.key}>
                    <a href={item.href} className="flex items-center gap-3 py-2 hover:bg-white/[0.02]">
                      {item.kind === 'unverified' ? <AlertTriangle aria-hidden className="h-4 w-4 shrink-0 text-warn" /> : <CheckCircle2 aria-hidden className={clsx('h-4 w-4 shrink-0', item.kind === 'verified' ? 'text-ok' : 'text-mute')} />}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13.5px] font-medium text-ink">{item.title}</span>
                        <span className="block truncate text-[12px] text-soft">{item.detail}</span>
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
              {handled.length > 5 && <p className="mt-2 text-[12px] text-mute">And {handled.length - 5} more in the activity record.</p>}
            </Section>

            {followUpsTracked ? (
              <Section title="Replies awaited" action={<a href={link('tasks', 'followups')} className="tap inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">Follow-ups <ArrowRight aria-hidden className="h-3.5 w-3.5" /></a>}>
                {followUps.isPending && <SkeletonRows rows={2} />}
                {followUps.isError && <ErrorNote error={new Error(`The follow-ups could not be read: ${getErrorMessage(followUps.error)}`)} onRetry={() => void followUps.refetch()} />}
                {followUps.data && openFollowUps(followUps.data.followUps) === 0 && (
                  <p className="text-[13px] text-soft">No reply is being waited for. A follow-up opens when a reply the secretary sent expects an answer.</p>
                )}
                {followUps.data && openFollowUps(followUps.data.followUps) > 0 && (
                  <ul className="space-y-2">
                    {followUps.data.followUps.filter(followUp => followUp.state === 'overdue' || followUp.state === 'waiting').sort((a, b) => Number(b.state === 'overdue') - Number(a.state === 'overdue')).slice(0, 3).map(followUp => (
                      <FollowUpItem key={`${followUp.runId}-${followUp.id}`} followUp={followUp} timeZone={tz} />
                    ))}
                  </ul>
                )}
              </Section>
            ) : (
              <Section title="Follow-ups">
                <p className="text-[13px] text-soft">
                  Scriba does not yet track sent mail that is waiting for a reply, so the Desk cannot tell you who owes you an answer. Nothing is shown here rather than something invented.
                </p>
              </Section>
            )}

            {connections.isPending && <SkeletonRows rows={2} />}
            {connections.isError && <ErrorNote error={new Error(`Connections could not be loaded: ${getErrorMessage(connections.error)}`)} onRetry={() => void connections.refetch()} />}
            {connections.data && <ConnectionsCard accounts={toAccounts(connections.data)} ready={connections.data.ready} />}
          </div>
        </div>
      </div>
    </div>
  )
}
