/**
 * The approval center and the activity history on live data. Both read Scriba's records of
 * proposed actions (workQueue.ts) and sort them by whose work they are (ownership.ts): the Desk
 * secretary's, opened for a run, or Scriba's own chat. The two are listed and counted apart, so a
 * card the Desk did not open never passes for the secretary's work. The approval center shows
 * what is waiting for the user; activity shows everything, with the status the server reports.
 */
import clsx from 'clsx'
import { FlaskConical, History, RefreshCw, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import type { DeskSandbox } from '../api/desk'
import { Button, EmptyState, ErrorNote, PageHeader, Pill, SkeletonRows } from '../components/ui'
import { getApi } from '../harness'
import { fmtDayTime, isInstant } from '../lib/time'
import { useRunQueue } from './LiveWorkQueuePage'
import { deskIndexOf, deskLinkOf, partitionCards, type DeskIndex, type Ownership } from './ownership'
import { SandboxTag } from './RunParts'
import { useRequiredLiveSession } from './session'
import { ToolCallCard } from './ToolCallCard'
import { RECENT_CONVERSATIONS, WORK_QUEUE_KEY, WORK_STAGES, isWorkItem, loadWorkQueue, needsIntervention, needsUser, stageOf, workQueueRefetchInterval, type ActionCard, type WorkQueue, type WorkStage } from './workQueue'

export function useWorkQueue() {
  return useQuery({ queryKey: WORK_QUEUE_KEY, queryFn: loadWorkQueue, refetchInterval: query => workQueueRefetchInterval(query.state.data) })
}

/**
 * The action cards that change something, sorted by owner. `index` is null while the runs load,
 * and on a backend without the overlay, where no card can be the Desk's.
 */
export function useOwnedWork(): { queue: ReturnType<typeof useWorkQueue>; index: DeskIndex | null; owned: Ownership; runsPending: boolean } {
  const session = useRequiredLiveSession()
  const queue = useWorkQueue()
  const overlay = session.overlay === 'ok'
  const runs = useRunQueue(overlay)
  const index = useMemo(() => deskIndexOf(runs.data), [runs.data])
  const owned = useMemo(() => {
    const work = (queue.data?.cards ?? []).filter(isWorkItem)
    // Without the overlay there are no Desk runs and nothing to set apart: the secretary's chat is
    // the only source of cards, so they are one list, counted as they always were.
    return overlay ? partitionCards(work, index) : { desk: work, scriba: [], known: true }
  }, [queue.data, index, overlay])
  return { queue, index, owned, runsPending: overlay && runs.isPending }
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
  const { policy, mode } = useRequiredLiveSession()
  if (mode.kind === 'external') {
    return (
      <p className="rounded-lg border border-danger/35 bg-danger/[0.07] px-3 py-2 text-[12.5px] leading-[19px] text-soft" data-testid="policy-note">
        <span className="font-semibold text-danger">Live. </span>
        An approval you give here is carried out on the real mailbox or calendar and cannot be taken back.
      </p>
    )
  }
  if (mode.kind === 'sandbox') {
    return (
      <div className="rounded-lg border border-warn/30 bg-warn/[0.06] px-3 py-2 text-[12.5px] leading-[19px] text-soft" data-testid="policy-note">
        <p>
          <span className="font-semibold text-warn">Sandbox. </span>
          Approving an action here applies it to an isolated stand-in for your mailbox, calendar and records. Nothing real is sent or changed, nobody real is contacted, and a result is never a real success.
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
      <span className="font-semibold text-ink">{mode.title}. </span>
      {mode.detail}
    </p>
  )
}

function CardList({ cards, index }: { cards: ActionCard[]; index: DeskIndex | null }) {
  return (
    <ul className="space-y-3">
      {cards.map(card => {
        const link = deskLinkOf(card, index)
        return (
          <li key={card.toolCall.id}>
            <ToolCallCard toolCall={card.toolCall} reason={link?.action?.reason ?? card.assistantText} conversation={card.conversation} run={link ? { runId: link.runId, subject: link.subject } : undefined} action={link?.action ?? undefined} />
          </li>
        )
      })}
    </ul>
  )
}

/** Cards from Scriba's chat: real proposals, but not the Desk secretary's. Kept apart and said so. */
function ScribaCards({ cards, index, title }: { cards: ActionCard[]; index: DeskIndex | null; title: string }) {
  const { mode } = useRequiredLiveSession()
  if (cards.length === 0) return null
  return (
    <details className="rounded-card border border-line px-4 py-3" data-testid="scriba-cards">
      <summary className="tap flex cursor-pointer flex-wrap items-center gap-2 text-[13px] font-semibold text-ink">
        {title} ({cards.length})
        <Pill tone="neutral" icon={null}>Not opened by the Desk</Pill>
      </summary>
      <p className="mb-3 mt-1.5 text-[12.5px] leading-[19px] text-soft">
        These actions are in Scriba's own records: proposed in the secretary chat, or already there before the Desk started. They are not part of a Desk run and are not counted in the secretary's numbers.
        {mode.kind === 'sandbox' && ' In this sandbox they are not part of the simulated office either.'}
      </p>
      <CardList cards={cards} index={index} />
    </details>
  )
}

export function LiveApprovalsPage() {
  const { queue, index, owned, runsPending } = useOwnedWork()
  const waiting = owned.desk.filter(needsUser)
  const attention = owned.desk.filter(needsIntervention)
  const other = owned.scriba.filter(card => needsUser(card) || needsIntervention(card))

  return (
    <div>
      <PageHeader
        title="Approval center"
        subtitle="Everything the secretary wants to send or change, waiting for your decision. Nothing here has happened yet."
        actions={<Button icon={RefreshCw} onClick={() => void queue.refetch()} busy={queue.isFetching}>Refresh</Button>}
      />
      <div className="max-w-3xl space-y-4 px-4 pb-12 sm:px-6 lg:px-8">
        <PolicyNote />
        {(queue.isPending || runsPending) && <SkeletonRows rows={3} />}
        {queue.isError && <ErrorNote error={new Error(`Approvals could not be loaded: ${getErrorMessage(queue.error)}`)} onRetry={() => void queue.refetch()} />}
        {queue.data && !runsPending && (
          <>
            <QueueCoverage queue={queue.data} />
            {!owned.known && (
              <p role="status" className="rounded-lg border border-warn/30 bg-warn/[0.07] px-3 py-2 text-[12.5px] text-warn">The Desk's runs could not be read, so it is not known which of these actions the secretary opened. They are all listed together below.</p>
            )}
            {waiting.length === 0 && attention.length === 0 && (
              <EmptyState icon={ShieldCheck} title="Nothing from the secretary is waiting for you">
                When the secretary proposes to send a message, change a calendar or record a task, the proposal appears here before anything happens.
              </EmptyState>
            )}
            {waiting.length > 0 && (
              <section aria-label="Waiting for your decision" className="space-y-3">
                <h2 className="eyebrow">Proposed by the secretary, waiting for your decision ({waiting.length})</h2>
                <CardList cards={waiting} index={index} />
              </section>
            )}
            {attention.length > 0 && (
              <section aria-label="Needs your attention" className="space-y-3">
                <h2 className="eyebrow">Did not finish cleanly ({attention.length})</h2>
                <CardList cards={attention} index={index} />
              </section>
            )}
            <ScribaCards cards={other} index={index} title={owned.known ? 'Waiting in Scriba chat' : 'Actions waiting'} />
          </>
        )}
      </div>
    </div>
  )
}

const FILTERS: { id: string; label: string; stages: WorkStage[] | null }[] = [
  { id: 'all', label: 'All', stages: null },
  { id: 'open', label: 'Open', stages: ['planning', 'needs_info', 'awaiting_approval', 'executing'] },
  { id: 'completed', label: 'Executed', stages: ['completed'] },
  { id: 'problems', label: 'Failed or partial', stages: ['failed', 'partially_completed'] },
  { id: 'cancelled', label: 'Cancelled', stages: ['cancelled', 'unsupported'] },
]

const OPERATION: Record<string, string> = {
  'calendar.create_event': 'Calendar event created',
  'calendar.update_event': 'Calendar event changed',
  'calendar.cancel_event': 'Calendar event cancelled',
  'email.send': 'Email placed in the sandbox Sent folder',
  'email.draft': 'Draft stored in the sandbox',
  'followup.close': 'Follow-up closed',
  'task.create': 'Task recorded',
  'task.complete': 'Task marked done',
  'reminder.create': 'Reminder set',
}

/** Everything executed against the sandbox world, in order, as the world itself logged it. */
export function SandboxLog({ world }: { world: DeskSandbox }) {
  const tz = getApi().info.principal.timezone
  return (
    <section aria-label="Sandbox operation log" className="card space-y-2 border-warn/30 p-4" data-testid="sandbox-log">
      <div className="flex flex-wrap items-center gap-2">
        <FlaskConical aria-hidden className="h-4 w-4 text-warn" />
        <h2 className="text-[14px] font-semibold text-ink">Executed in the sandbox world</h2>
        <SandboxTag />
      </div>
      <p className="text-[12.5px] leading-[19px] text-soft">
        The sandbox world's own log of what was applied to it: {world.counts.sent} in its Sent folder, {world.counts.events} event{world.counts.events === 1 ? '' : 's'} on its calendars, {world.counts.tasks} task{world.counts.tasks === 1 ? '' : 's'}, {world.counts.reminders} reminder{world.counts.reminders === 1 ? '' : 's'}. None of it left this backend.
      </p>
      {world.operations.length === 0 ? (
        <p className="text-[12.5px] text-mute">Nothing has been executed in the sandbox yet.</p>
      ) : (
        <ol className="space-y-1 text-[12.5px] leading-[19px]">
          {world.operations.map(operation => (
            <li key={operation.seq} className="flex flex-wrap gap-x-2">
              <span className="tabular-nums text-mute">{isInstant(operation.at) ? fmtDayTime(operation.at, tz) : operation.at}</span>
              <span className={clsx('font-medium', operation.status === 'executed' ? 'text-ink' : 'text-danger')}>
                {OPERATION[operation.op] ?? operation.op}
                {operation.status !== 'executed' ? ` (${operation.status === 'unknown' ? 'outcome unknown' : 'failed'}${operation.error ? `: ${operation.error}` : ''})` : ''}
              </span>
              {operation.object_id && <span className="break-all font-mono text-[11.5px] text-mute">{operation.object_id}</span>}
              <span className="text-warn">simulated</span>
            </li>
          ))}
        </ol>
      )}
      {world.isolationViolations.length > 0 && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/[0.08] px-3 py-2 text-[12.5px] text-danger">The sandbox reports {world.isolationViolations.length} isolation violation{world.isolationViolations.length === 1 ? '' : 's'}: a real provider client was reached. Stop and tell the backend owner.</p>
      )}
    </section>
  )
}

export function LiveActivityPage() {
  const session = useRequiredLiveSession()
  const { queue, index, owned, runsPending } = useOwnedWork()
  const [filter, setFilter] = useState('all')
  // The secretary's record is the Desk's own cards. Where ownership is not known, everything is listed.
  const cards = owned.known ? owned.desk : owned.scriba
  const active = FILTERS.find(f => f.id === filter)!
  const matches = (f: (typeof FILTERS)[number], card: ActionCard) => !f.stages || f.stages.includes(stageOf(card.toolCall.status))
  const visible = cards.filter(card => matches(active, card))
  const stages = (Object.keys(WORK_STAGES) as WorkStage[])

  return (
    <div>
      <PageHeader
        title="Activity"
        subtitle={session.mode.kind === 'sandbox' ? 'Every action the secretary proposed or executed in the sandbox, with the status and evidence on record. Nothing here reached a real mailbox or calendar.' : 'Every action the secretary proposed or ran, with the status Scriba has on record for it.'}
        actions={<Button icon={RefreshCw} onClick={() => void queue.refetch()} busy={queue.isFetching}>Refresh</Button>}
      />
      <div className="max-w-3xl space-y-4 px-4 pb-12 sm:px-6 lg:px-8">
        {session.mode.kind === 'sandbox' && session.sandbox && <SandboxLog world={session.sandbox} />}

        <div role="group" aria-label="Filter by stage" className="flex gap-1.5 overflow-x-auto scroll-fade">
          {FILTERS.map(f => (
            <button key={f.id} type="button" aria-pressed={f.id === filter} onClick={() => setFilter(f.id)} className={clsx('tap inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3 text-[12.5px] font-semibold transition-colors duration-150', f.id === filter ? 'bg-brand-500/40 text-ink' : 'text-soft hover:bg-white/[0.06] hover:text-ink')}>
              {f.label}
              <span className={clsx('tabular-nums', f.id === filter ? 'text-accent' : 'text-mute')}>{cards.filter(card => matches(f, card)).length}</span>
            </button>
          ))}
        </div>

        {(queue.isPending || runsPending) && <SkeletonRows rows={4} />}
        {queue.isError && <ErrorNote error={new Error(`Activity could not be loaded: ${getErrorMessage(queue.error)}`)} onRetry={() => void queue.refetch()} />}
        {queue.data && !runsPending && (
          <>
            <QueueCoverage queue={queue.data} />
            {visible.length === 0 ? (
              <EmptyState icon={History} title={cards.length === 0 ? 'No actions yet' : 'Nothing in this view'}>
                {cards.length === 0 ? 'Actions appear here once the secretary proposes one for an incoming message.' : 'No action is at this stage.'}
              </EmptyState>
            ) : (
              <CardList cards={visible} index={index} />
            )}
            {owned.known && <ScribaCards cards={owned.scriba} index={index} title="In Scriba's own records" />}
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
