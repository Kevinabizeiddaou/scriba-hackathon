/**
 * The approval center and the activity history on live data. Both read the same thing: Scriba's
 * records of the actions the agent proposed (workQueue.ts). The approval center shows what is
 * waiting for the user; activity shows everything, with the stage the server reports.
 */
import clsx from 'clsx'
import { History, RefreshCw, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import { Button, EmptyState, ErrorNote, PageHeader, Pill, SkeletonRows } from '../components/ui'
import { useRunQueue } from './LiveWorkQueuePage'
import { useRequiredLiveSession } from './session'
import { ToolCallCard } from './ToolCallCard'
import { RECENT_CONVERSATIONS, WORK_QUEUE_KEY, WORK_STAGES, isWorkItem, loadWorkQueue, needsIntervention, needsUser, stageOf, workQueueRefetchInterval, type ActionCard, type WorkQueue, type WorkStage } from './workQueue'

export function useWorkQueue() {
  return useQuery({ queryKey: WORK_QUEUE_KEY, queryFn: loadWorkQueue, refetchInterval: query => workQueueRefetchInterval(query.state.data) })
}

/** States what the list does not cover, so a short list is never mistaken for a complete one. */
export function QueueCoverage({ queue }: { queue: WorkQueue }) {
  if (!queue.truncated && queue.failedConversations === 0) return null
  return (
    <p role="status" className="rounded-lg border border-warn/30 bg-warn/[0.07] px-3 py-2 text-[12.5px] text-warn">
      {queue.failedConversations > 0 && `${queue.failedConversations} conversation${queue.failedConversations === 1 ? '' : 's'} could not be read, so their actions are missing here. `}
      {queue.truncated && `Only the ${RECENT_CONVERSATIONS} most recent conversations are read. Actions in older conversations are not listed.`}
    </p>
  )
}

function PolicyNote() {
  const { policy, overlay } = useRequiredLiveSession()
  if (policy.externalWritesEnabled) return null
  if (policy.executionMode === 'sandbox') {
    return (
      <div className="rounded-lg border border-warn/30 bg-warn/[0.06] px-3 py-2 text-[12.5px] leading-[19px] text-soft" data-testid="policy-note">
        <p>
          <span className="font-semibold text-warn">Sandbox. </span>
          Approving a mail or calendar action here applies it to an isolated stand-in for your mailbox and calendar. Nothing real is sent or changed, and a result is never a real success.
        </p>
        {policy.readinessChecks.length > 0 && (
          <details className="mt-1.5">
            <summary className="tap cursor-pointer font-medium text-accent">Why real sending is off ({policy.readinessChecks.filter(check => !check.ok).length} of {policy.readinessChecks.length} checks not passed)</summary>
            <ul className="mt-1.5 space-y-1" aria-label="Readiness checks for real sending">
              {policy.readinessChecks.map(check => (
                <li key={check.id} className="flex gap-2">
                  <span className={check.ok ? 'font-semibold text-ok' : 'font-semibold text-warn'}>{check.ok ? 'Passed' : 'Not passed'}</span>
                  <span className="min-w-0">{check.detail}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    )
  }
  return (
    <p className="rounded-lg border border-line bg-white/[0.03] px-3 py-2 text-[12.5px] text-soft" data-testid="policy-note">
      <span className="font-semibold text-ink">Sending and calendar changes are switched off. </span>
      {overlay === 'missing'
        ? 'This backend does not have the Desk overlay, so it cannot report whether its safety fixes are in place.'
        : 'This backend has not reported that its send and calendar safety fixes are in place.'}{' '}
      You can review and cancel those actions. Tasks and reminders, which stay inside Scriba, can be approved.
    </p>
  )
}

/** Which Desk run each action card belongs to, from the run queue. Empty while it loads or without the overlay. */
function useRunOfCard(): Map<number, { runId: number; subject: string | null }> {
  const session = useRequiredLiveSession()
  const runs = useRunQueue(session.overlay === 'ok')
  const map = new Map<number, { runId: number; subject: string | null }>()
  for (const entry of runs.data?.entries ?? []) {
    for (const action of entry.run?.actions ?? []) map.set(action.toolCallId, { runId: entry.row.runId, subject: entry.run!.email.subject ?? entry.row.subject })
  }
  return map
}

function CardList({ cards }: { cards: ActionCard[] }) {
  const runOf = useRunOfCard()
  return (
    <ul className="space-y-3">
      {cards.map(card => (
        <li key={card.toolCall.id}>
          <ToolCallCard toolCall={card.toolCall} reason={card.assistantText} conversation={card.conversation} run={runOf.get(card.toolCall.id)} />
        </li>
      ))}
    </ul>
  )
}

export function LiveApprovalsPage() {
  const queue = useWorkQueue()
  const cards = (queue.data?.cards ?? []).filter(isWorkItem)
  const waiting = cards.filter(needsUser)
  const attention = cards.filter(needsIntervention)

  return (
    <div>
      <PageHeader
        title="Approval center"
        subtitle="Everything the secretary wants to send or change, waiting for your decision. Nothing here has happened yet."
        actions={<Button icon={RefreshCw} onClick={() => void queue.refetch()} busy={queue.isFetching}>Refresh</Button>}
      />
      <div className="max-w-3xl space-y-4 px-4 pb-12 sm:px-6 lg:px-8">
        <PolicyNote />
        {queue.isPending && <SkeletonRows rows={3} />}
        {queue.isError && <ErrorNote error={new Error(`Approvals could not be loaded: ${getErrorMessage(queue.error)}`)} onRetry={() => void queue.refetch()} />}
        {queue.data && (
          <>
            <QueueCoverage queue={queue.data} />
            {waiting.length === 0 && attention.length === 0 && (
              <EmptyState icon={ShieldCheck} title="Nothing is waiting for you">
                When the secretary proposes to send a message, change a calendar or record a task, the proposal appears here before anything happens.
              </EmptyState>
            )}
            {waiting.length > 0 && (
              <section aria-label="Waiting for your decision" className="space-y-3">
                <h2 className="eyebrow">Waiting for your decision ({waiting.length})</h2>
                <CardList cards={waiting} />
              </section>
            )}
            {attention.length > 0 && (
              <section aria-label="Needs your attention" className="space-y-3">
                <h2 className="eyebrow">Did not finish cleanly ({attention.length})</h2>
                <CardList cards={attention} />
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}

const FILTERS: { id: string; label: string; stages: WorkStage[] | null }[] = [
  { id: 'all', label: 'All', stages: null },
  { id: 'open', label: 'Open', stages: ['planning', 'needs_info', 'awaiting_approval', 'executing'] },
  { id: 'completed', label: 'Completed', stages: ['completed'] },
  { id: 'problems', label: 'Failed or partial', stages: ['failed', 'partially_completed'] },
  { id: 'cancelled', label: 'Cancelled', stages: ['cancelled', 'unsupported'] },
]

export function LiveActivityPage() {
  const queue = useWorkQueue()
  const [filter, setFilter] = useState('all')
  const cards = (queue.data?.cards ?? []).filter(isWorkItem)
  const active = FILTERS.find(f => f.id === filter)!
  const matches = (f: (typeof FILTERS)[number], card: ActionCard) => !f.stages || f.stages.includes(stageOf(card.toolCall.status))
  const visible = cards.filter(card => matches(active, card))
  const stages = (Object.keys(WORK_STAGES) as WorkStage[])

  return (
    <div>
      <PageHeader
        title="Activity"
        subtitle="Every action the secretary proposed or ran, with the status Scriba has on record for it."
        actions={<Button icon={RefreshCw} onClick={() => void queue.refetch()} busy={queue.isFetching}>Refresh</Button>}
      />
      <div className="max-w-3xl space-y-4 px-4 pb-12 sm:px-6 lg:px-8">
        <div role="group" aria-label="Filter by stage" className="flex gap-1.5 overflow-x-auto scroll-fade">
          {FILTERS.map(f => (
            <button key={f.id} type="button" aria-pressed={f.id === filter} onClick={() => setFilter(f.id)} className={clsx('tap inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3 text-[12.5px] font-semibold transition-colors duration-150', f.id === filter ? 'bg-brand-500/40 text-ink' : 'text-soft hover:bg-white/[0.06] hover:text-ink')}>
              {f.label}
              <span className={clsx('tabular-nums', f.id === filter ? 'text-accent' : 'text-mute')}>{cards.filter(card => matches(f, card)).length}</span>
            </button>
          ))}
        </div>

        {queue.isPending && <SkeletonRows rows={4} />}
        {queue.isError && <ErrorNote error={new Error(`Activity could not be loaded: ${getErrorMessage(queue.error)}`)} onRetry={() => void queue.refetch()} />}
        {queue.data && (
          <>
            <QueueCoverage queue={queue.data} />
            {visible.length === 0 ? (
              <EmptyState icon={History} title={cards.length === 0 ? 'No actions yet' : 'Nothing in this view'}>
                {cards.length === 0 ? 'Actions appear here once the secretary proposes one in chat.' : 'No action is at this stage.'}
              </EmptyState>
            ) : (
              <CardList cards={visible} />
            )}
          </>
        )}

        <details className="rounded-card border border-line px-4 py-3 text-[12.5px] text-soft">
          <summary className="tap inline-flex cursor-pointer items-center font-semibold text-ink">Which work stages this backend reports</summary>
          <ul className="mt-2 space-y-1.5">
            {stages.map(stage => (
              <li key={stage} className="flex flex-wrap items-baseline gap-2">
                <Pill tone={WORK_STAGES[stage].supported ? WORK_STAGES[stage].tone : 'neutral'} icon={null}>{WORK_STAGES[stage].label}</Pill>
                <span className={clsx(!WORK_STAGES[stage].supported && 'text-mute')}>
                  {WORK_STAGES[stage].supported ? '' : 'Not reported yet. '}
                  {WORK_STAGES[stage].source}
                </span>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  )
}
