/**
 * One Desk run in full: the message it came from, what the secretary made of it, each proposed
 * action with its approval and result, the evidence that an action really happened, and the one
 * thing the user can do next.
 *
 * Every fact is the server's. The action cards are Scriba's own records, read one by one, and are
 * approved through Scriba's routes (ToolCallCard). The two run-level steps call the Desk overlay:
 * "advance" proposes the confirmation reply once the event exists, and "draft reply" asks Scriba
 * to write a draft for review. Neither sends anything.
 */
import clsx from 'clsx'
import { ArrowLeft, Ban, CalendarClock, Check, CircleDashed, CircleDot, FilePen, MailOpen, Minus, RefreshCw, Send, ShieldAlert, ShieldCheck, X, type LucideIcon } from 'lucide-react'
import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiClientError, getErrorMessage } from '../api/client'
import { advanceDeskRun, fetchDeskRun, type CalendarRead, type DeskAction, type DeskRun } from '../api/desk'
import { Button, ErrorNote, PageHeader, Pill, SkeletonRows } from '../components/ui'
import { SourceBadge } from '../components/workspace'
import { getApi } from '../harness'
import { hrefFor } from '../lib/router'
import { fmtDayTime, fmtRange, isInstant } from '../lib/time'
import { providerLabel } from './describeAction'
import {
  ACTION_LABEL,
  QUEUE_GROUPS,
  RUNS_KEY,
  RUN_STATE_LABEL,
  categoryLabel,
  groupOf,
  isKnownState,
  nextStepOf,
  partialBreakdown,
  runKey,
  runToolCallKey,
  timelineOf,
  type StepState,
} from './deskRuns'
import { emailKey, parseSender } from './mappers'
import { createDraftFromRequest, fetchChatToolCall } from './scribaApi'
import { useRequiredLiveSession } from './session'
import { ToolCallCard } from './ToolCallCard'
import { WORK_QUEUE_KEY, WORK_STAGES, stageOf } from './workQueue'

const STEP_STYLE: Record<StepState, { icon: LucideIcon; ring: string; text: string; word: string }> = {
  done: { icon: Check, ring: 'border-ok/50 text-ok', text: 'text-ink', word: 'Done' },
  current: { icon: CircleDot, ring: 'border-warn/60 text-warn', text: 'text-ink', word: 'Now' },
  held: { icon: ShieldAlert, ring: 'border-warn/60 text-warn', text: 'text-ink', word: 'Held' },
  failed: { icon: X, ring: 'border-danger/60 text-danger', text: 'text-ink', word: 'Did not finish' },
  not_needed: { icon: Minus, ring: 'border-line-strong text-mute', text: 'text-soft', word: 'Not needed' },
  upcoming: { icon: CircleDashed, ring: 'border-line-strong text-mute', text: 'text-mute', word: 'Not yet' },
}

/** Why the Desk proposed this action. These are the conditions under which the backend proposes each one. */
const PROPOSAL_REASON: Record<string, string> = {
  create_task: 'The message was classified as an action item: it has a deadline or a direct request and no question to answer.',
  create_calendar_event: 'The message asks for a meeting, and the requested time was checked against every connected calendar before this was proposed.',
  send_email: 'The calendar event exists. This is the confirmation reply to the sender, in the original thread.',
}

function CalendarReads({ calendars }: { calendars: CalendarRead[] }) {
  if (calendars.length === 0) return <p className="text-[12.5px] text-mute">No calendar read is recorded.</p>
  return (
    <ul className="space-y-1 text-[12.5px]" aria-label="Calendars read">
      {calendars.map(calendar => (
        <li key={`${calendar.provider}:${calendar.account}`} className="flex flex-wrap items-center gap-x-2">
          <SourceBadge source={calendar.provider} />{' '}
          <span className="break-all text-soft">{calendar.account}</span>{' '}
          {calendar.ok ? (
            <span className="text-ok">read, {calendar.busy_count} busy period{calendar.busy_count === 1 ? '' : 's'}</span>
          ) : (
            <span className="font-semibold text-warn">could not be read ({(calendar.error ?? 'provider_error').replace(/_/g, ' ')}): availability unknown</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function Held({ run }: { run: DeskRun }) {
  const tz = getApi().info.principal.timezone
  const held = run.held!
  const range = (slot: { start: string; end: string }) => (isInstant(slot.start) && isInstant(slot.end) ? fmtRange(slot.start, slot.end, tz) : `${slot.start} to ${slot.end}`)
  return (
    <section aria-label="Why nothing was proposed" className="card space-y-3 border-warn/30 p-4 sm:p-5">
      <h2 className="text-[14.5px] font-semibold text-ink">Why no meeting was proposed</h2>
      <p className="text-[13px] leading-[20px] text-soft">{held.message}</p>
      {held.requested && (
        <p className="text-[12.5px] text-soft">
          <span className="text-mute">Requested time: </span>
          <span className="tabular-nums text-ink">{range(held.requested)}</span> <span className="text-mute">({tz})</span>
        </p>
      )}
      {(held.conflicts?.length ?? 0) > 0 && (
        <div>
          <p className="eyebrow mb-1">In the way</p>
          <ul className="space-y-1 text-[12.5px] text-soft">
            {held.conflicts!.map((conflict, index) => (
              <li key={index}>
                <span className="text-ink">{conflict.title ?? 'A busy period'}</span> · {providerLabel(conflict.provider)} ({conflict.account}) · <span className="tabular-nums">{range(conflict)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <p className="eyebrow mb-1">Calendars</p>
        <CalendarReads calendars={held.calendars ?? []} />
      </div>
      <div>
        <p className="eyebrow mb-1">Times verified free on every calendar</p>
        {held.slots.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5" aria-label="Verified free times">
            {held.slots.map(slot => (
              <li key={slot.start} className="rounded-full border border-ok/30 bg-ok/[0.07] px-2.5 py-1 text-[12px] tabular-nums text-ok">{range(slot)}</li>
            ))}
          </ul>
        ) : (
          <p className="text-[12.5px] text-mute">None. No time is offered unless every connected calendar was read.</p>
        )}
      </div>
    </section>
  )
}

function ActionSlot({ action, index, total }: { action: DeskAction; index: number; total: number }) {
  const card = useQuery({ queryKey: runToolCallKey(action.toolCallId), queryFn: () => fetchChatToolCall(action.toolCallId) })
  const stage = WORK_STAGES[stageOf(action.status)]
  const label = ACTION_LABEL[action.tool_name] ?? action.tool_name.replace(/_/g, ' ')
  const executed = stageOf(action.status) === 'completed' || stageOf(action.status) === 'partially_completed'

  return (
    <li aria-label={`Action ${index + 1} of ${total}: ${label}`}>
      <p className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-mute">
        <span className="font-semibold tabular-nums text-soft">Action {index + 1} of {total}</span>
        {executed &&
          (action.verified ? (
            <span className="inline-flex items-center gap-1 text-ok">
              <ShieldCheck aria-hidden className="h-3.5 w-3.5" />
              Verified: Scriba recorded it as action #{action.assistantActionId}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-warn">
              <ShieldAlert aria-hidden className="h-3.5 w-3.5" />
              Not verified: Scriba has no action record for it
            </span>
          ))}
      </p>
      {card.data ? (
        <ToolCallCard toolCall={card.data} reason={PROPOSAL_REASON[action.tool_name]} />
      ) : (
        <div className="card space-y-2 px-4 py-3.5" data-testid="action-fallback">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[14px] font-semibold text-ink">{label}</p>
            <Pill tone={stage.tone}>{stage.label}</Pill>
          </div>
          {action.message && <p className="text-[12.5px] text-soft">{action.message}</p>}
          {action.error && <p className="text-[12.5px] text-danger">{action.error}</p>}
          {card.isPending ? (
            <p role="status" className="text-[12.5px] text-mute">Reading the full action from Scriba…</p>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2.5">
              <p className="min-w-0 flex-1 text-[12.5px] text-warn">The full action could not be read ({getErrorMessage(card.error)}), so it cannot be approved or cancelled from here yet.</p>
              <Button icon={RefreshCw} onClick={() => void card.refetch()} busy={card.isFetching}>Read again</Button>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

export function LiveRunDetail({ runId }: { runId: number }) {
  const session = useRequiredLiveSession()
  const queryClient = useQueryClient()
  const tz = getApi().info.principal.timezone
  const run = useQuery({
    queryKey: runKey(runId),
    queryFn: () => fetchDeskRun(runId),
    // Read again while an approved action is running; otherwise the page changes only when the user acts.
    refetchInterval: query => (query.state.data?.state === 'executing' ? 3_000 : false),
  })
  const connections = useQuery({ queryKey: ['desk', 'connections'], queryFn: () => session.workspace.connections() })

  const afterStep = (next: DeskRun) => {
    queryClient.setQueryData(runKey(runId), next)
    void queryClient.invalidateQueries({ queryKey: RUNS_KEY })
    void queryClient.invalidateQueries({ queryKey: WORK_QUEUE_KEY })
  }
  const advance = useMutation({ mutationFn: () => advanceDeskRun(runId), onSuccess: afterStep })
  const draft = useMutation({ mutationFn: () => createDraftFromRequest(run.data!.draftRequest!) })

  // A different run is a different page: drop the result of a step taken on the previous one.
  useEffect(() => {
    advance.reset()
    draft.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const back = (
    <a href={hrefFor('work')} className="tap inline-flex items-center gap-1.5 text-[13px] font-medium text-accent hover:underline">
      <ArrowLeft aria-hidden className="h-4 w-4" />
      Work queue
    </a>
  )

  if (run.isPending) {
    return (
      <div className="max-w-4xl space-y-4 px-4 py-6 sm:px-6 lg:px-8">
        {back}
        <SkeletonRows rows={5} />
      </div>
    )
  }
  if (run.isError) {
    const missing = run.error instanceof ApiClientError && run.error.status === 404
    return (
      <div className="max-w-3xl space-y-4 px-4 py-6 sm:px-6 lg:px-8">
        {back}
        <ErrorNote
          error={new Error(missing ? `Run ${runId} does not exist for this account.` : `Run ${runId} could not be loaded: ${getErrorMessage(run.error)}`)}
          onRetry={missing ? undefined : () => void run.refetch()}
        />
      </div>
    )
  }

  const data = run.data
  const group = groupOf(data)
  const next = nextStepOf(data)
  const steps = timelineOf(data)
  const sender = parseSender(data.email.from_addr)
  const mailbox = connections.data?.mailboxes.find(box => box.providerAccountId === data.email.provider_account_id && box.provider === data.email.provider)
  const breakdown = group === 'problem' ? partialBreakdown(data) : null
  const name = (action: DeskAction) => ACTION_LABEL[action.tool_name] ?? action.tool_name.replace(/_/g, ' ')

  return (
    <div>
      <div className="px-4 pt-5 sm:px-6 lg:px-8">{back}</div>
      <PageHeader
        title={data.email.subject || 'No subject'}
        subtitle={`Run ${data.runId}. ${categoryLabel(data.category)} from ${sender.name || sender.email || 'an unknown sender'}.`}
        actions={<Button icon={RefreshCw} onClick={() => void run.refetch()} busy={run.isFetching}>Refresh</Button>}
      />

      <div className="grid gap-5 px-4 pb-12 sm:px-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:px-8">
        <div className="min-w-0 space-y-5">
          <section aria-label="Next step" className={clsx('card p-4 sm:p-5', next.kind !== 'none' && next.kind !== 'wait' && 'border-accent/40')}>
            <div className="flex flex-wrap items-center gap-2">
              <p className="eyebrow">What this needs from you</p>
              <Pill tone={QUEUE_GROUPS[group].tone} spin={group === 'in_progress'}>{QUEUE_GROUPS[group].label}</Pill>
              <span className="text-[12px] text-mute">Server state: {isKnownState(data.state) ? RUN_STATE_LABEL[data.state] : data.state}</span>
            </div>
            <h2 className="mt-2 text-[17px] font-semibold leading-6 text-ink">{next.label}</h2>
            <p className="mt-1 text-[13px] leading-[20px] text-soft">{next.detail}</p>

            {next.kind === 'advance' && (
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button variant="primary" icon={Send} onClick={() => advance.mutate()} busy={advance.isPending}>Propose the confirmation reply</Button>
                <span className="text-[12px] text-mute">Creates an action card for your approval. It sends nothing.</span>
              </div>
            )}
            {next.kind === 'draft_reply' && data.draftRequest && (
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button variant="primary" icon={FilePen} onClick={() => draft.mutate()} busy={draft.isPending} disabled={draft.isSuccess}>Write a reply draft</Button>
                <span className="text-[12px] text-mute">Scriba writes it with its model and stores it for review. It sends nothing.</span>
              </div>
            )}
            {next.kind === 'held' && data.held?.reason === 'change_request' && (
              <a href={hrefFor('chat')} className="btn btn-secondary mt-3">
                <CalendarClock aria-hidden className="h-4 w-4" />
                Open the secretary chat
              </a>
            )}
            {advance.isError && <p role="alert" className="mt-3 text-[12.5px] text-danger">The reply could not be proposed: {getErrorMessage(advance.error)}. Nothing was sent. It is safe to try again.</p>}
            {draft.isError && <p role="alert" className="mt-3 text-[12.5px] text-danger">The draft could not be written: {getErrorMessage(draft.error)}. Nothing was sent. Writing a draft needs a model on the backend.</p>}
            {draft.isSuccess && (
              <div role="status" className="mt-3 rounded-lg border border-ok/25 bg-ok/[0.06] px-3 py-2.5">
                <p className="text-[12.5px] font-semibold text-ok">A draft is stored in Scriba. It has not been sent.</p>
                {(draft.data.final_text || draft.data.draft_text) && <p className="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap text-[13px] leading-[20px] text-ink">{draft.data.final_text || draft.data.draft_text}</p>}
                <a href={hrefFor('inbox', emailKey(data.email.provider, data.email.email_id))} className="tap mt-1 inline-flex items-center text-[12.5px] font-medium text-accent hover:underline">Review it with the message</a>
              </div>
            )}
          </section>

          {breakdown && (
            <section aria-label="What ran and what did not" role="alert" className="card space-y-2 border-danger/35 p-4 sm:p-5">
              <h2 className="text-[14.5px] font-semibold text-danger">This run did not finish cleanly</h2>
              <ul className="space-y-1 text-[13px] text-soft">
                {breakdown.ran.map(action => (
                  <li key={action.toolCallId}><span className="font-semibold text-ok">Ran: </span>{name(action)}{action.verified ? ` (recorded as action #${action.assistantActionId})` : ' (no record in Scriba)'}</li>
                ))}
                {breakdown.failed.map(action => (
                  <li key={action.toolCallId}><span className="font-semibold text-danger">{stageOf(action.status) === 'partially_completed' ? 'Partly ran: ' : 'Failed: '}</span>{name(action)}{action.error ? ` (${action.error})` : ''}</li>
                ))}
                {breakdown.notRun.map(action => (
                  <li key={action.toolCallId}><span className="font-semibold text-soft">Not run: </span>{name(action)} ({WORK_STAGES[stageOf(action.status)].label.toLowerCase()})</li>
                ))}
              </ul>
              <p className="text-[12.5px] text-soft">What ran is real and is not undone. Nothing is repeated automatically. Before retrying an action whose outcome is uncertain, check the mailbox or calendar: a retry runs at once.</p>
            </section>
          )}

          {data.held && <Held run={data} />}

          {data.actions.length > 0 && (
            <section aria-label="Proposed actions" className="space-y-3">
              <h2 className="eyebrow">Proposed actions ({data.actions.length})</h2>
              <ol className="space-y-4">
                {data.actions.map((action, index) => <ActionSlot key={action.toolCallId} action={action} index={index} total={data.actions.length} />)}
              </ol>
            </section>
          )}

          <section aria-label="Timeline" className="card p-4 sm:p-5">
            <h2 className="text-[14.5px] font-semibold text-ink">Timeline</h2>
            <p className="mt-1 text-[12.5px] text-mute">Only stages this backend reports. A stage is marked done when the server says so, never before.</p>
            <ol className="mt-4">
              {steps.map((step, index) => {
                const style = STEP_STYLE[step.state]
                return (
                  <li key={step.id} className="relative flex gap-3 pb-4 last:pb-0" aria-label={`${step.label}: ${style.word}`}>
                    {index < steps.length - 1 && <span aria-hidden className="absolute left-[13px] top-7 h-[calc(100%-28px)] w-px bg-line-strong" />}
                    <span className={clsx('relative z-10 flex h-[27px] w-[27px] shrink-0 items-center justify-center rounded-full border bg-surface', style.ring)}>
                      <style.icon aria-hidden className="h-3.5 w-3.5" strokeWidth={2.5} />
                    </span>
                    <div className="min-w-0 flex-1 pt-0.5">
                      <p className={clsx('flex flex-wrap items-baseline gap-x-2 text-[13.5px] font-semibold', style.text)}>
                        {step.label}
                        <span className="text-[11.5px] font-medium text-mute">{style.word}</span>
                      </p>
                      <p className="mt-0.5 text-[12.5px] leading-[19px] text-soft">{step.detail}</p>
                      <p className="mt-0.5 text-[11.5px] text-mute">Source: {step.source}</p>
                    </div>
                  </li>
                )
              })}
            </ol>
          </section>
        </div>

        <aside aria-label="Source message" className="space-y-4">
          <section className="card space-y-2.5 p-4">
            <h2 className="eyebrow">Source message</h2>
            <dl className="space-y-2 text-[12.5px]">
              <div>
                <dt className="text-mute">From</dt>
                <dd className="break-words text-ink">{sender.name || sender.email || 'Unknown sender'}{sender.name && sender.email ? <span className="block break-all text-soft">{sender.email}</span> : null}</dd>
              </div>
              <div>
                <dt className="text-mute">Arrived in</dt>
                <dd className="flex flex-wrap items-center gap-x-2 text-ink">
                  <SourceBadge source={data.email.provider} />{' '}
                  <span className="break-all">{mailbox?.email ?? data.email.provider_account_id ?? 'mailbox not named on the run'}</span>
                </dd>
              </div>
              <div>
                <dt className="text-mute">Subject</dt>
                <dd className="break-words text-ink">{data.email.subject || 'No subject'}</dd>
              </div>
              <div>
                <dt className="text-mute">Picked up</dt>
                <dd className="tabular-nums text-ink">{isInstant(data.createdAt) ? `${fmtDayTime(data.createdAt, tz)} (${tz})` : data.createdAt}</dd>
              </div>
              <div>
                <dt className="text-mute">Classified as</dt>
                <dd className="text-ink">{categoryLabel(data.category)}</dd>
              </div>
            </dl>
            <a href={hrefFor('inbox', emailKey(data.email.provider, data.email.email_id))} className="btn btn-secondary w-full">
              <MailOpen aria-hidden className="h-4 w-4" />
              Open the message
            </a>
          </section>
          <section className="card space-y-1.5 p-4 text-[12.5px] text-soft">
            <h2 className="eyebrow">Safety</h2>
            <p className="flex gap-2"><Ban aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mute" />The message is untrusted input. Only its sender, taken from the From header, can become a recipient or attendee.</p>
            <p className="flex gap-2"><ShieldCheck aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mute" />Nothing runs without your approval, and {session.policy.externalWritesEnabled ? 'each approval is carried out for real.' : 'sending mail and changing calendars are switched off on this backend.'}</p>
          </section>
        </aside>
      </div>
    </div>
  )
}
