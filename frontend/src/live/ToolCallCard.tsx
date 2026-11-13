import clsx from 'clsx'
import { AlarmClock, AlertTriangle, CalendarCheck, CalendarX, CalendarClock, Check, CircleHelp, ListTodo, Mail, MailOpen, MessageSquareText, RotateCcw, Search, ShieldAlert, ShieldCheck, X, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import { Button, Pill } from '../components/ui'
import { getApi } from '../harness'
import { hrefFor } from '../lib/router'
import { fmtDayTime, fmtRange, isInstant } from '../lib/time'
import { AVAILABILITY_OVERRIDE_FLAG, describeAction, heldByAvailability, providerLabel, type ActionDescription, type ActionKind } from './describeAction'
import { approveChatToolCall, cancelChatToolCall, retryChatToolCall, type ChatToolCall } from './scribaApi'
import { useRequiredLiveSession } from './session'
import { CONFIRMED_RECIPIENTS_FLAG, explainHold, unverifiedRecipients } from './deskHolds'
import { RUNS_KEY } from './deskRuns'
import { WORK_QUEUE_KEY, WORK_STAGES, stageOf } from './workQueue'
import { approvalGate, toolEffect } from './writePolicy'

const ICON: Record<ActionKind, LucideIcon> = {
  email: Mail,
  email_reply: Mail,
  calendar_create: CalendarCheck,
  calendar_update: CalendarClock,
  calendar_cancel: CalendarX,
  task: ListTodo,
  reminder: AlarmClock,
  read: Search,
  other: CircleHelp,
}

export const chatMessagesKey = (conversationId: number) => ['desk', 'chat', 'messages', conversationId] as const

/** A time exactly as the card holds it. A value without an offset is shown as written, with its zone, never converted on a guess. */
function When({ when }: { when: NonNullable<ActionDescription['when']> }) {
  const tz = getApi().info.principal.timezone
  if (isInstant(when.start) && (!when.end || isInstant(when.end))) {
    return <span className="tabular-nums">{when.end ? fmtRange(when.start, when.end, tz) : fmtDayTime(when.start, tz)} <span className="text-mute">({tz})</span></span>
  }
  return (
    <span className="tabular-nums">
      {when.start}{when.end ? ` to ${when.end}` : ''} <span className="text-mute">({when.timezone || 'time zone not stated on the card'})</span>
    </span>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-[92px] shrink-0 text-mute">{label}</dt>
      <dd className="min-w-0 flex-1 break-words text-ink">{children}</dd>
    </div>
  )
}

const OUTCOME_STYLE = {
  ok: { icon: Check, className: 'text-ok' },
  failed: { icon: X, className: 'text-danger' },
  unknown: { icon: CircleHelp, className: 'text-warn' },
  skipped: { icon: CircleHelp, className: 'text-mute' },
} as const

interface Props {
  toolCall: ChatToolCall
  /** The assistant's words when it proposed this. Shown as the reason; it is all the backend records. */
  reason?: string
  /** Shown in the approval center, where the card is away from its conversation. */
  conversation?: { id: number; title: string }
  /** The Desk run this action belongs to, when it came from an incoming message. */
  run?: { runId: number; subject: string | null }
  compact?: boolean
}

/**
 * One action the secretary proposed or ran, straight from Scriba's record of it.
 *
 * The status shown is the server's. Approve, cancel and retry call Scriba's own endpoints and
 * then re-read; the card never moves itself forward. Approvals that reach outside the Desk are
 * gated by the write policy (writePolicy.ts).
 */
export function ToolCallCard({ toolCall, reason, conversation, run, compact = false }: Props) {
  const session = useRequiredLiveSession()
  const queryClient = useQueryClient()
  const description = describeAction(toolCall)
  const effect = toolEffect(toolCall.tool_name)
  const stage = WORK_STAGES[stageOf(toolCall.status)]
  const gate = approvalGate(toolCall.tool_name, session.policy)
  const Icon = ICON[description.kind]
  const [confirmRetry, setConfirmRetry] = useState(false)
  const [override, setOverride] = useState(false)
  const [recipientsConfirmed, setRecipientsConfirmed] = useState(false)

  const afterChange = () => {
    void queryClient.invalidateQueries({ queryKey: WORK_QUEUE_KEY })
    // A card that belongs to a Desk run changes that run's state and its next step.
    void queryClient.invalidateQueries({ queryKey: RUNS_KEY })
    void queryClient.invalidateQueries({ queryKey: chatMessagesKey(toolCall.conversation_id) })
    // A task or reminder created here shows on the Tasks screen and the briefing.
    session.workspace.refresh()
    void queryClient.invalidateQueries({ queryKey: ['desk', 'briefing'] })
  }
  const approve = useMutation({
    mutationFn: () => {
      // Only the overrides the backend honours on an approve request, and only when the user ticked the box for each.
      const overrides: Record<string, unknown> = {}
      if (heldForAvailability && override) overrides[AVAILABILITY_OVERRIDE_FLAG] = true
      if (heldForRecipients && recipientsConfirmed) overrides[CONFIRMED_RECIPIENTS_FLAG] = unverified
      return approveChatToolCall(toolCall.id, Object.keys(overrides).length > 0 ? overrides : undefined)
    },
    onSettled: afterChange,
  })
  const cancel = useMutation({ mutationFn: () => cancelChatToolCall(toolCall.id), onSettled: afterChange })
  const retry = useMutation({ mutationFn: () => retryChatToolCall(toolCall.id), onSettled: () => { setConfirmRetry(false); afterChange() } })
  const busy = approve.isPending || cancel.isPending || retry.isPending
  const error = approve.error ?? cancel.error ?? retry.error

  const status = toolCall.status
  const waiting = status === 'awaiting_approval' || status === 'needs_info'
  const hold = status === 'needs_info' ? explainHold(description.errorCode) : null
  const unverified = unverifiedRecipients(toolCall)
  const heldForAvailability = status === 'needs_info' && heldByAvailability(description)
  const heldForRecipients = hold?.resolution === 'confirm_recipients' && unverified.length > 0
  // needs_info for any other reason cannot be approved as it is: it is completed in chat, looked at in its thread, or waited out.
  const incomplete = status === 'needs_info' && !heldForAvailability && !heldForRecipients
  const canApprove = gate.allowed && !incomplete && (!heldForAvailability || override) && (!heldForRecipients || recipientsConfirmed)
  const completeInChat = incomplete && (hold === null || hold.resolution === 'complete_in_chat')
  const unknownOutcome = description.outcome.some(row => row.state === 'unknown')

  if (effect === 'read') {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-white/[0.025] px-3 py-2 text-[12.5px] text-soft" data-testid="tool-call" data-status={status}>
        <Icon aria-hidden className="h-3.5 w-3.5 shrink-0 text-mute" />
        <span>{description.title}</span>
        {status !== 'executed' && <Pill tone={stage.tone}>{stage.label}</Pill>}
        {toolCall.error && <span className="text-danger">{toolCall.error}</span>}
      </div>
    )
  }

  return (
    <article
      aria-label={`${description.title}${description.headline ? `: ${description.headline}` : ''}`}
      data-testid="tool-call"
      data-status={status}
      className={clsx('card overflow-hidden', waiting && 'border-warn/30', (status === 'failed' || status === 'partially_executed') && 'border-danger/35')}
    >
      <header className="flex flex-wrap items-start gap-3 px-4 pt-4">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/[0.06] text-accent">
          <Icon aria-hidden className="h-[18px] w-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="eyebrow">{description.title}</p>
          <h3 className="mt-0.5 break-words text-[15px] font-semibold leading-[22px] text-ink">{description.headline || 'No title on the card'}</h3>
        </div>
        <Pill tone={stage.tone} spin={status === 'approved' || status === 'executing'}>{stage.label}</Pill>
      </header>

      <dl className="space-y-1.5 px-4 pb-1 pt-3 text-[13px]">
        {description.recipients.length > 0 && (
          <Row label={description.kind.startsWith('calendar') ? 'Invites' : 'To'}>{description.recipients.join(', ')}</Row>
        )}
        {description.when && <Row label={description.kind === 'task' ? 'Due' : 'When'}><When when={description.when} /></Row>}
        {description.location && <Row label="Where">{description.location}</Row>}
        {(description.provider || description.account) && (
          <Row label="Account">
            {[description.provider && providerLabel(description.provider), description.account].filter(Boolean).join(' · ')}
          </Row>
        )}
        {!description.provider && !description.account && effect === 'external_write' && (
          <Row label="Account"><span className="text-warn">The card does not name an account. Scriba will choose one at approval.</span></Row>
        )}
        {description.target && <Row label="Applies to"><span className="break-all font-mono text-[12px]">{description.target}</span></Row>}
        {description.changes.length > 0 && (
          <Row label="Changes">
            <ul className="space-y-0.5">
              {description.changes.map(change => (
                <li key={change.field}><span className="text-soft">{change.field}:</span> {change.value}</li>
              ))}
            </ul>
          </Row>
        )}
      </dl>

      {description.body && !compact && (
        <p className="mx-4 mt-2 max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg border border-line bg-bg/60 px-3 py-2.5 text-[13px] leading-[20px] text-ink">{description.body}</p>
      )}

      {reason && !compact && (
        <p className="mx-4 mt-3 text-[12.5px] text-soft">
          <span className="font-semibold text-ink">Why: </span>
          {reason}
        </p>
      )}

      {description.availability && (
        <div className={clsx('mx-4 mt-3 rounded-lg border px-3 py-2.5 text-[12.5px]', description.availability.free === true ? 'border-ok/25 bg-ok/[0.06] text-ok' : description.availability.free === false ? 'border-danger/30 bg-danger/[0.08] text-danger' : 'border-warn/30 bg-warn/[0.08] text-warn')}>
          <p className="flex items-center gap-1.5 font-semibold">
            {description.availability.free === true ? <ShieldCheck aria-hidden className="h-3.5 w-3.5" /> : <ShieldAlert aria-hidden className="h-3.5 w-3.5" />}
            {description.availability.free === true
              ? 'Checked against every connected calendar: free'
              : description.availability.free === false
                ? 'Conflicts with an existing event'
                : 'Availability unknown: a calendar could not be read'}
            {description.availability.overriddenByUser && ' (booked anyway at your request)'}
          </p>
          {description.availability.conflicts.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-ink">
              {description.availability.conflicts.map((conflict, index) => (
                <li key={index}>
                  {conflict.title ?? 'A busy period'} · {providerLabel(conflict.provider)} ({conflict.account}) · {conflict.start} to {conflict.end}
                </li>
              ))}
            </ul>
          )}
          {description.availability.unreadable.map((calendar, index) => (
            <p key={index} className="mt-1 text-ink">{providerLabel(calendar.provider)} ({calendar.account}): {calendar.error}</p>
          ))}
        </div>
      )}

      {status === 'needs_info' && (hold || description.message) && (
        <div role="status" aria-label="Why this is held" className="mx-4 mt-3 flex gap-2 rounded-lg border border-warn/30 bg-warn/[0.08] px-3 py-2.5 text-[12.5px] text-warn">
          <AlertTriangle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div className="min-w-0">
            {hold && <p className="font-semibold">Held: {hold.title}</p>}
            {hold && <p className="mt-0.5 text-ink">{hold.detail}</p>}
            {unverified.length > 0 && (
              <ul aria-label="Unverified recipients" className="mt-1.5 space-y-0.5">
                {unverified.map(address => (
                  <li key={address} className="break-all font-mono text-[12px] text-ink">{address}</li>
                ))}
              </ul>
            )}
            {description.message && <p className={hold ? 'mt-1.5 text-soft' : undefined}>{hold ? 'The backend says: ' : ''}{description.message}</p>}
            {!hold && description.errorCode && <p className="mt-1 text-soft">Reason code: {description.errorCode}. This version of the Desk does not know it, so it offers no way to approve past it.</p>}
          </div>
        </div>
      )}

      {description.outcome.length > 0 && (
        <div className="mx-4 mt-3">
          <p className="eyebrow mb-1.5">What happened</p>
          <ul className="space-y-1 text-[12.5px]">
            {description.outcome.map((row, index) => {
              const style = OUTCOME_STYLE[row.state]
              return (
                <li key={index} className="flex gap-2">
                  <style.icon aria-hidden className={clsx('mt-0.5 h-3.5 w-3.5 shrink-0', style.className)} />
                  <span className="min-w-0">
                    <span className="font-semibold text-ink">{row.label}</span>
                    {row.detail && <span className="block break-words text-soft">{row.detail}</span>}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {status === 'partially_executed' && (
        <p role="alert" className="mx-4 mt-3 rounded-lg border border-danger/30 bg-danger/[0.08] px-3 py-2.5 text-[12.5px] text-danger">
          Only part of this action ran. Check the parts above before doing anything else: the parts that succeeded are real and are not undone.
        </p>
      )}

      {status === 'failed' && (
        <p role="alert" className="mx-4 mt-3 rounded-lg border border-danger/30 bg-danger/[0.08] px-3 py-2.5 text-[12.5px] text-danger">
          {toolCall.error || description.message || 'This action failed. The backend gave no reason.'}
        </p>
      )}

      {description.otherInput.length > 0 && !compact && (
        <details className="mx-4 mt-3 text-[12px] text-soft">
          <summary className="tap inline-flex cursor-pointer items-center font-medium text-accent">Other details on this card ({description.otherInput.length})</summary>
          <dl className="mt-1.5 space-y-1">
            {description.otherInput.map(item => (
              <div key={item.field} className="flex gap-3">
                <dt className="w-[130px] shrink-0 break-words text-mute">{item.field}</dt>
                <dd className="min-w-0 flex-1 break-words">{item.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}

      {error && (
        <p role="alert" className="mx-4 mt-3 text-[12.5px] text-danger">
          {getErrorMessage(error)}. The card below shows what the server has on record now.
        </p>
      )}

      <footer className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line bg-white/[0.02] px-4 py-3">
        <p className="min-w-0 flex-1 text-[12px] text-mute">
          {run && (
            <a href={hrefFor('work', String(run.runId))} className="tap mr-3 inline-flex items-center gap-1 font-medium text-accent hover:underline">
              <MailOpen aria-hidden className="h-3.5 w-3.5" />
              From the message: {run.subject || `run ${run.runId}`}
            </a>
          )}
          {conversation && !run && (
            <a href={hrefFor('chat', String(conversation.id))} className="tap mr-3 inline-flex items-center gap-1 font-medium text-accent hover:underline">
              <MessageSquareText aria-hidden className="h-3.5 w-3.5" />
              {conversation.title || 'Open the conversation'}
            </a>
          )}
          {toolCall.updated_at && isInstant(toolCall.updated_at) && <span className="tabular-nums">Updated {fmtDayTime(toolCall.updated_at, getApi().info.principal.timezone)}</span>}
        </p>

        {waiting && (
          <>
            {heldForAvailability && gate.allowed && (
              <label className="flex basis-full cursor-pointer items-start gap-2 text-[12.5px] text-warn">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={override} onChange={event => setOverride(event.target.checked)} />
                <span>Book this time anyway. I have read the finding above; the booking will be recorded as made despite it.</span>
              </label>
            )}
            {heldForRecipients && gate.allowed && (
              <label className="flex basis-full cursor-pointer items-start gap-2 text-[12.5px] text-warn">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={recipientsConfirmed} onChange={event => setRecipientsConfirmed(event.target.checked)} />
                <span>I have checked {unverified.length === 1 ? 'this address' : 'these addresses'} and want {unverified.length === 1 ? 'it' : 'them'} to receive this: {unverified.join(', ')}</span>
              </label>
            )}
            {completeInChat && (
              <a href={hrefFor('chat', String(toolCall.conversation_id))} className="btn btn-secondary">
                <MessageSquareText aria-hidden className="h-4 w-4" />
                Answer in chat
              </a>
            )}
            <Button variant="ghost" icon={X} onClick={() => cancel.mutate()} busy={cancel.isPending} disabled={busy}>
              Cancel action
            </Button>
            <Button variant="primary" icon={Check} onClick={() => approve.mutate()} busy={approve.isPending} disabled={busy || !canApprove} title={gate.reason ?? undefined}>
              {effect === 'external_write' ? 'Approve and run' : 'Approve'}
            </Button>
            {!gate.allowed && <p className="basis-full text-[12px] text-warn" data-testid="gate-reason">{gate.reason}</p>}
          </>
        )}

        {(status === 'approved' || status === 'executing') && <span className="text-[12.5px] text-soft">Scriba is running this now. The result appears here when the server reports it.</span>}

        {status === 'failed' && !confirmRetry && (
          <>
            <Button variant="ghost" icon={X} onClick={() => cancel.mutate()} busy={cancel.isPending} disabled={busy}>
              Dismiss
            </Button>
            <Button variant="secondary" icon={RotateCcw} onClick={() => setConfirmRetry(true)} disabled={busy || !gate.allowed} title={gate.reason ?? undefined}>
              Retry…
            </Button>
            {!gate.allowed && <p className="basis-full text-[12px] text-warn" data-testid="gate-reason">{gate.reason}</p>}
          </>
        )}

        {status === 'failed' && confirmRetry && (
          <div role="alertdialog" aria-label="Confirm retry" className="basis-full rounded-lg border border-warn/35 bg-warn/[0.07] p-3 text-[12.5px] text-ink">
            <p className="font-semibold text-warn">Retry runs this action again immediately.</p>
            <p className="mt-1 text-soft">
              Scriba does not ask for a second approval on a retry: it executes as soon as you confirm here.
              {unknownOutcome && ' Part of the first attempt has an unknown outcome, so it may already have happened. Check the provider first: a retry could repeat it.'}
            </p>
            <div className="mt-2.5 flex flex-wrap justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirmRetry(false)} disabled={busy}>Keep as failed</Button>
              <Button variant="danger" icon={RotateCcw} onClick={() => retry.mutate()} busy={retry.isPending} disabled={busy}>
                Run again now
              </Button>
            </div>
          </div>
        )}
      </footer>
    </article>
  )
}
