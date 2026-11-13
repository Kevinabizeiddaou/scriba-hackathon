/**
 * The work queue: every incoming message the Desk has picked up, where it stands, and what it
 * needs from the user.
 *
 * It reads the Desk's runs (deskRuns.ts) and shows them as the server reports them. Runs start
 * when a signed-in client asks: there is no background worker on this backend, and the screen
 * says so instead of animating one. "Check for new work" calls POST /desk/intake/sweep, which is
 * bounded and safe to repeat; it proposes actions for approval and sends or writes nothing.
 */
import clsx from 'clsx'
import { ArrowRight, CircleAlert, ClipboardList, Inbox, MailPlus, PlugZap, RefreshCw, ScanSearch } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import { startDeskIntake, sweepDeskInbox, type DeskInbox, type DeskSweep, type TriagedEmail } from '../api/desk'
import { Button, EmptyState, ErrorNote, PageHeader, Pill, SkeletonRows } from '../components/ui'
import { SourceBadge } from '../components/workspace'
import { getApi } from '../harness'
import { hrefFor, navigate } from '../lib/router'
import { fmtDayTime, fmtTime, isInstant } from '../lib/time'
import {
  QUEUE_GROUPS,
  QUEUE_ORDER,
  RUNS_KEY,
  RUN_DETAIL_LIMIT,
  categoryLabel,
  groupOf,
  loadRunQueue,
  nextStepOf,
  runHeadline,
  runQueueRefetchInterval,
  sweepGaps,
  sweepLines,
  unstartedMail,
  type QueueGroup,
  type RunEntry,
  type RunQueue,
} from './deskRuns'
import { LiveRunDetail } from './LiveRunDetail'
import { parseSender, toMailProvider } from './mappers'
import { useRequiredLiveSession } from './session'

export function useRunQueue(enabled = true) {
  return useQuery({ queryKey: RUNS_KEY, queryFn: loadRunQueue, enabled, refetchInterval: query => runQueueRefetchInterval(query.state.data) })
}

/** Runs that need the user: an approval, an input, a failure to look at, or an unrecognised state. */
export function runsNeedingUser(queue: RunQueue | undefined): number | null {
  if (!queue) return null
  return queue.entries.filter(entry => entry.run && ['decision', 'input', 'problem', 'unknown'].includes(groupOf(entry.run))).length
}

/** How often the opt-in automatic check runs, and when it gives up. */
export const AUTO_CHECK_MS = 5 * 60_000
export const AUTO_CHECK_MAX_FAILURES = 3

interface SweepRecord {
  result: DeskSweep | null
  error: string | null
  at: number
  automatic: boolean
}

function RunRow({ entry }: { entry: RunEntry }) {
  const tz = getApi().info.principal.timezone
  const { row, run } = entry
  const sender = parseSender(run?.email.from_addr ?? row.fromAddr)
  const subject = run?.email.subject ?? row.subject ?? 'No subject'
  const when = run?.createdAt ?? row.createdAt
  const group = run ? groupOf(run) : null
  const next = run ? nextStepOf(run) : null

  return (
    <li>
      <a
        href={hrefFor('work', String(row.runId))}
        aria-label={`Run ${row.runId}: ${subject}`}
        className="card group block px-4 py-3.5 transition-colors duration-150 hover:border-line-strong hover:bg-white/[0.035] focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      >
        <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[14.5px] font-semibold text-ink">{subject}</p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-soft">
              <span className="truncate">{sender.name || sender.email || 'Unknown sender'}</span>{' '}
              {(run?.email.provider ?? row.provider) && <SourceBadge source={(run?.email.provider ?? row.provider)!} />}{' '}
              <span className="text-mute">{categoryLabel(run?.category ?? row.category)}</span>{' '}
              {when && isInstant(when) && <span className="tabular-nums text-mute">picked up {fmtDayTime(when, tz)}</span>}
            </p>
          </div>
          {group ? (
            <Pill tone={QUEUE_GROUPS[group].tone} spin={group === 'in_progress'}>{QUEUE_GROUPS[group].label}</Pill>
          ) : (
            <Pill tone="neutral" icon={null}>{entry.error ? 'Could not be read' : 'Not read'}</Pill>
          )}
        </div>
        {run && next ? (
          <div className="mt-2.5 flex flex-wrap items-end justify-between gap-x-4 gap-y-1.5 border-t border-line pt-2.5 text-[12.5px]">
            <p className="min-w-0 flex-1 text-soft">
              <span className="text-mute">Proposed: </span>
              {runHeadline(run)}
            </p>
            <p className={clsx('flex items-center gap-1.5 font-semibold', next.kind === 'none' || next.kind === 'wait' ? 'text-mute' : 'text-accent')}>
              {next.kind === 'none' ? 'Nothing needed from you' : next.label}
              <ArrowRight aria-hidden className="h-3.5 w-3.5 transition-transform duration-150 group-hover:translate-x-0.5" />
            </p>
          </div>
        ) : (
          <p className="mt-2 text-[12.5px] text-mute">
            {entry.error ? `Its state could not be read (${entry.error}). Open it to try again.` : `Only the ${RUN_DETAIL_LIMIT} newest runs are read in full. Open this one to see where it stands.`}
          </p>
        )}
      </a>
    </li>
  )
}

function SweepReport({ record, onAgain, busy }: { record: SweepRecord; onAgain: () => void; busy: boolean }) {
  const tz = getApi().info.principal.timezone
  const at = fmtTime(new Date(record.at).toISOString(), tz)
  if (record.error || !record.result) {
    return (
      <div role="alert" className="rounded-lg border border-danger/30 bg-danger/[0.07] px-3 py-2.5 text-[12.5px] text-danger">
        The check at {at} failed: {record.error}. Nothing was opened by it. It is safe to check again.
      </div>
    )
  }
  const sweep = record.result
  if (sweep.status === 'already_running') {
    return (
      <p role="status" className="rounded-lg border border-line bg-white/[0.03] px-3 py-2.5 text-[12.5px] text-soft">
        Another check for this account was already running at {at}, so this one did nothing. Wait for it to finish, then refresh.
      </p>
    )
  }
  const gaps = sweepGaps(sweep)
  return (
    <div className="space-y-3" role="status" aria-label="Result of the last check">
      <p className="text-[12.5px] text-soft">
        Last check at <span className="tabular-nums text-ink">{at}</span>
        {record.automatic && ' (automatic)'}. It proposed actions only: nothing was sent and no calendar was changed.
      </p>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {sweepLines(sweep).map(line => (
          <div key={line.id} className={clsx('rounded-xl px-3 py-2', line.id === 'failed' && line.count > 0 ? 'bg-danger/[0.09]' : line.id === 'opened' && line.count > 0 ? 'bg-ok/[0.08]' : 'bg-white/[0.04]')} title={line.note}>
            <dt className="text-[11.5px] text-mute">{line.label}</dt>
            <dd className="text-[18px] font-bold tabular-nums text-ink">{line.count}</dd>
          </div>
        ))}
      </dl>
      {gaps.map(gap => (
        <p key={gap} role="alert" className="flex gap-2 rounded-lg border border-warn/30 bg-warn/[0.08] px-3 py-2 text-[12.5px] text-warn">
          <CircleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{gap}</span>
        </p>
      ))}
      {sweep.opened.length > 0 && (
        <ul aria-label="Runs opened by the last check" className="space-y-1 text-[12.5px]">
          {sweep.opened.map(item => (
            <li key={`${item.provider}:${item.id}`}>
              <a href={hrefFor('work', String(item.runId))} className="tap inline-flex items-center gap-1.5 font-medium text-accent hover:underline">
                Run {item.runId}: {item.subject ?? 'No subject'}
              </a>
              <span className="text-mute"> · {categoryLabel(item.category)}</span>
            </li>
          ))}
        </ul>
      )}
      {sweep.failed.length > 0 && (
        <ul aria-label="Messages that could not be processed" className="space-y-1 text-[12.5px] text-soft">
          {sweep.failed.map(item => (
            <li key={`${item.provider}:${item.id}`}>
              <span className="font-semibold text-danger">Not processed: </span>
              {item.subject ?? 'No subject'} <span className="text-mute">({item.error}). The next check tries it again.</span>
            </li>
          ))}
        </ul>
      )}
      {sweep.deferred.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-[12.5px] text-soft">
          <span>
            {sweep.deferred.length} more message{sweep.deferred.length === 1 ? ' needs' : 's need'} a run. A check opens a few at a time, because each meeting request costs a model call and calendar reads.
          </span>
          <Button icon={ScanSearch} onClick={onAgain} busy={busy}>Take the next ones</Button>
        </div>
      )}
    </div>
  )
}

export function LiveWorkQueuePage({ runId }: { runId: string | null }) {
  const id = runId !== null && /^\d+$/.test(runId) ? Number(runId) : null
  if (id !== null) return <LiveRunDetail runId={id} />
  return <WorkQueue />
}

function WorkQueue() {
  const session = useRequiredLiveSession()
  const queryClient = useQueryClient()
  const overlayMissing = session.overlay === 'missing'
  const queue = useRunQueue(session.overlay === 'ok')
  const inbox = useQuery<DeskInbox>({ queryKey: ['desk', 'inbox'], queryFn: () => session.workspace.inbox(), enabled: !overlayMissing })
  const [filter, setFilter] = useState<QueueGroup | 'all'>('all')
  const [record, setRecord] = useState<SweepRecord | null>(null)
  const [auto, setAuto] = useState(false)
  const failures = useRef(0)

  const sweep = useMutation({
    mutationFn: (_automatic: boolean) => sweepDeskInbox({ provider: 'all', limit: 25, max_new: 5 }),
    onSuccess: (result, automatic) => {
      failures.current = 0
      setRecord({ result, error: null, at: Date.now(), automatic })
      void queryClient.invalidateQueries({ queryKey: RUNS_KEY })
    },
    onError: (error, automatic) => {
      failures.current += 1
      setRecord({ result: null, error: getErrorMessage(error), at: Date.now(), automatic })
      // An automatic check that keeps failing stops itself instead of hammering the backend.
      if (automatic && failures.current >= AUTO_CHECK_MAX_FAILURES) setAuto(false)
    },
  })
  const sweeping = sweep.isPending
  const check = sweep.mutate

  // Opt-in, and only while this tab is open and visible. It is a client calling the same bounded
  // endpoint on a timer, not a background worker, and the screen says so.
  useEffect(() => {
    if (!auto || overlayMissing) return
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible' && !sweep.isPending) check(true)
    }, AUTO_CHECK_MS)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, overlayMissing])

  const intake = useMutation({
    mutationFn: (item: TriagedEmail) => startDeskIntake({ provider: toMailProvider(item.provider), id: item.id, mailbox: item.account_email ?? undefined }),
    onSuccess: run => {
      void queryClient.invalidateQueries({ queryKey: RUNS_KEY })
      navigate('work', String(run.runId))
    },
  })

  if (overlayMissing) {
    return (
      <div>
        <PageHeader title="Work queue" subtitle="Every request the secretary has picked up, where it stands, and what it needs from you." />
        <div className="max-w-3xl px-4 pb-12 sm:px-6 lg:px-8">
          <EmptyState icon={PlugZap} title="This backend has no Desk overlay">
            The work queue reads the Desk's runs, which exist only when Scriba is started with the Desk overlay. Chat, approvals and tasks still work.
          </EmptyState>
        </div>
      </div>
    )
  }

  const entries = queue.data?.entries ?? []
  const grouped = (group: QueueGroup) => entries.filter(entry => entry.run && groupOf(entry.run) === group)
  const unread = entries.filter(entry => !entry.run)
  // Only once the runs are known: before that, every message would look as if it had no run.
  const waiting = queue.data ? unstartedMail(inbox.data, entries.map(entry => entry.row)) : []
  const visibleGroups = QUEUE_ORDER.filter(group => (filter === 'all' || filter === group) && grouped(group).length > 0)
  const refresh = () => {
    session.workspace.refresh()
    void queue.refetch()
    void inbox.refetch()
  }

  return (
    <div>
      <PageHeader
        title="Work queue"
        subtitle="Every request the secretary has picked up, where it stands, and what it needs from you."
        actions={
          <>
            <Button icon={RefreshCw} onClick={refresh} busy={queue.isFetching && !sweeping}>Refresh</Button>
            <Button variant="primary" icon={ScanSearch} onClick={() => check(false)} busy={sweeping}>Check for new work</Button>
          </>
        }
      />

      <div className="max-w-4xl space-y-5 px-4 pb-12 sm:px-6 lg:px-8">
        <section aria-label="Intake" className="card space-y-3 p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h2 className="text-[14.5px] font-semibold text-ink">Intake</h2>
              <p className="mt-1 text-[12.5px] leading-[19px] text-soft">
                The secretary picks up new mail when you ask it to. This backend has no background worker: nothing is picked up while the Desk is closed.
              </p>
            </div>
            <label className="tap flex cursor-pointer items-center gap-2 text-[12.5px] font-medium text-soft">
              <input type="checkbox" checked={auto} onChange={event => { failures.current = 0; setAuto(event.target.checked) }} className="h-4 w-4 cursor-pointer accent-[var(--accent)]" />
              Check every 5 minutes while this tab is open
            </label>
          </div>
          {sweeping && (
            <p role="status" className="rounded-lg border border-line bg-white/[0.03] px-3 py-2.5 text-[12.5px] text-soft">
              Checking the inbox. This reads recent mail and, for meeting requests, the calendars. It can take a while on a slow backend; nothing is sent.
            </p>
          )}
          {record && !sweeping && <SweepReport record={record} onAgain={() => check(false)} busy={sweeping} />}
          {!record && !sweeping && <p className="text-[12.5px] text-mute">No check has been run in this session.</p>}
        </section>

        {waiting.length > 0 && (
          <section aria-label="Arrived, not picked up yet" className="space-y-2.5">
            <div>
              <h2 className="eyebrow">Arrived, not picked up yet ({waiting.length})</h2>
              <p className="mt-1 text-[12.5px] text-soft">Mail that needs work and has no run. Start one here, or check for new work to take several.</p>
            </div>
            {intake.isError && <ErrorNote error={new Error(`The run could not be started: ${getErrorMessage(intake.error)}`)} />}
            <ul className="space-y-2">
              {waiting.slice(0, 8).map(item => {
                const sender = parseSender(item.from_addr)
                const pending = intake.isPending && intake.variables?.id === item.id && intake.variables.provider === item.provider
                return (
                  <li key={`${item.provider}:${item.id}`} className="card flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                    <MailPlus aria-hidden className="h-4 w-4 shrink-0 text-mute" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13.5px] font-semibold text-ink">{item.subject || 'No subject'}</p>
                      <p className="flex flex-wrap items-center gap-x-2 text-[12px] text-soft">
                        <span className="truncate">{sender.name || sender.email}</span>{' '}
                        <SourceBadge source={toMailProvider(item.provider)} />{' '}
                        <span className="text-mute">{categoryLabel(item.triage.category)}</span>
                      </p>
                    </div>
                    <Button onClick={() => intake.mutate(item)} busy={pending} disabled={intake.isPending || sweeping} aria-label={`Start a run for: ${item.subject || 'No subject'}`}>
                      Start
                    </Button>
                  </li>
                )
              })}
            </ul>
            {waiting.length > 8 && <p className="text-[12.5px] text-mute">{waiting.length - 8} more. Check for new work to take them a few at a time.</p>}
          </section>
        )}

        {queue.isPending && <SkeletonRows rows={4} />}
        {queue.isError && <ErrorNote error={new Error(`The work queue could not be loaded: ${getErrorMessage(queue.error)}`)} onRetry={() => void queue.refetch()} />}

        {queue.data && (
          <>
            <div role="group" aria-label="Filter runs" className="flex gap-1.5 overflow-x-auto">
              {(['all', ...QUEUE_ORDER] as const).map(group => {
                const count = group === 'all' ? entries.length : grouped(group).length
                if (group !== 'all' && count === 0) return null
                return (
                  <button
                    key={group}
                    type="button"
                    aria-pressed={filter === group}
                    onClick={() => setFilter(group)}
                    className={clsx('tap inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3 text-[12.5px] font-semibold transition-colors duration-150', filter === group ? 'bg-brand-500/40 text-ink' : 'text-soft hover:bg-white/[0.06] hover:text-ink')}
                  >
                    {group === 'all' ? 'All runs' : QUEUE_GROUPS[group].label}
                    <span className={clsx('tabular-nums', filter === group ? 'text-accent' : 'text-mute')}>{count}</span>
                  </button>
                )
              })}
            </div>

            {(queue.data.failedReads > 0 || queue.data.notRead > 0) && (
              <p role="status" className="rounded-lg border border-warn/30 bg-warn/[0.07] px-3 py-2 text-[12.5px] text-warn">
                {queue.data.failedReads > 0 && `${queue.data.failedReads} run${queue.data.failedReads === 1 ? '' : 's'} could not be read, so ${queue.data.failedReads === 1 ? 'its state is' : 'their states are'} unknown. `}
                {queue.data.notRead > 0 && `Only the ${RUN_DETAIL_LIMIT} newest runs are read in full; ${queue.data.notRead} older ${queue.data.notRead === 1 ? 'run is' : 'runs are'} listed without a state.`}
              </p>
            )}

            {entries.length === 0 && (
              <EmptyState icon={ClipboardList} title="No work has been picked up yet">
                Check for new work to have the secretary read the recent inbox and open a run for each message that needs one.
              </EmptyState>
            )}

            {visibleGroups.map(group => (
              <section key={group} aria-label={QUEUE_GROUPS[group].label} className="space-y-2.5">
                <div>
                  <h2 className="eyebrow">{QUEUE_GROUPS[group].label} ({grouped(group).length})</h2>
                  <p className="mt-1 text-[12.5px] text-soft">{QUEUE_GROUPS[group].blurb}</p>
                </div>
                <ul className="space-y-2">
                  {grouped(group).map(entry => <RunRow key={entry.row.runId} entry={entry} />)}
                </ul>
              </section>
            ))}

            {filter === 'all' && unread.length > 0 && (
              <section aria-label="State not read" className="space-y-2.5">
                <h2 className="eyebrow">State not read ({unread.length})</h2>
                <ul className="space-y-2">
                  {unread.map(entry => <RunRow key={entry.row.runId} entry={entry} />)}
                </ul>
              </section>
            )}

            {filter !== 'all' && visibleGroups.length === 0 && (
              <EmptyState icon={Inbox} title="Nothing in this view">No run is in this state right now.</EmptyState>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/** Demo mode has no backend, so it has no runs. Said plainly instead of filling the screen with invented ones. */
export function WorkQueueDemoNotice() {
  return (
    <div>
      <PageHeader title="Work queue" subtitle="Every request the secretary has picked up, where it stands, and what it needs from you." />
      <div className="max-w-3xl px-4 pb-12 sm:px-6 lg:px-8">
        <EmptyState icon={ClipboardList} title="The work queue needs a live backend">
          It shows the Desk's runs from Scriba. Demo mode has no backend, so there is nothing to list here. The inbox and the approval center show the demo's scripted requests.
        </EmptyState>
      </div>
    </div>
  )
}
