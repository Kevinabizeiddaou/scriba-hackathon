/**
 * Presentation pieces for a Desk run, shared by the work queue, the run detail, the overview and
 * the follow-up workspace. Each one shows what the server reported and nothing more; the wording
 * and the rules are in runLifecycle.ts.
 */
import clsx from 'clsx'
import { AlertTriangle, Bot, Check, CircleDashed, CircleDot, Clock, FlaskConical, HelpCircle, Minus, Reply, ShieldCheck, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import type { DeskAction, DeskFollowUp, DeskTimelineItem, DeskWorkerStatus } from '../api/desk'
import { Button, Pill } from '../components/ui'
import { hrefFor } from '../lib/router'
import { fmtDayTime, fmtTime, isInstant } from '../lib/time'
import { ACTION_LABEL } from './deskRuns'
import { EVIDENCE_KIND, UNKNOWN_STAGE, followUpInfo, stageInfo, verificationOf, workerView, type ProgressStep } from './runLifecycle'
import { editsOf } from './deskContract'
import { planFieldsOf, type RunTally, type TallyKind } from './runPlan'

const when = (iso: string | null | undefined, tz: string, withDay = true): string | null => (iso && isInstant(iso) ? (withDay ? fmtDayTime(iso, tz) : fmtTime(iso, tz)) : null)

/** The stage a run rests in, as a chip. An unknown stage is shown as such, with the raw value. */
export function RunStatus({ stage, fallback, spin = false }: { stage: string | null; fallback?: ReactNode; spin?: boolean }) {
  const info = stageInfo(stage)
  if (!info) return <>{fallback ?? null}</>
  return (
    <Pill tone={info.tone} spin={spin} icon={info === UNKNOWN_STAGE ? HelpCircle : undefined}>
      {info.label}
    </Pill>
  )
}

/** Marks anything that happened in an isolated provider world: nothing real was read or written. */
export function SandboxTag({ className }: { className?: string }) {
  return (
    <span data-testid="sandbox-tag" className={clsx('pill border border-dashed border-warn/50 bg-warn/[0.08] font-bold uppercase tracking-[0.06em] text-warn', className)} title="Simulated: this is applied to an isolated stand-in for the mailbox and calendar. Nothing real is sent or changed, and nobody real is contacted.">
      <FlaskConical aria-hidden className="h-3 w-3" strokeWidth={2.5} />
      Sandbox
    </span>
  )
}

const PROGRESS_ICON: Record<ProgressStep['state'], LucideIcon> = { reached: Check, current: CircleDot, skipped: Minus, upcoming: CircleDashed }
const PROGRESS_WORD: Record<ProgressStep['state'], string> = { reached: 'done', current: 'now', skipped: 'not recorded', upcoming: 'not yet' }

/**
 * Where a run stands on its path, with the time the server recorded for each stage. A stage the
 * run passed without a recorded event is drawn as passed over, not as done.
 */
export function RunProgress({ steps, timeZone, compact = false }: { steps: ProgressStep[]; timeZone: string; compact?: boolean }) {
  return (
    <ol aria-label="Progress of this run" className={clsx(compact ? 'flex flex-wrap gap-x-1 gap-y-1' : 'flex flex-col gap-0 sm:grid sm:grid-cols-4 sm:gap-x-2 sm:gap-y-4 2xl:grid-cols-8')}>
      {steps.map((step, index) => {
        const Icon = PROGRESS_ICON[step.state]
        const tone = step.state === 'current' ? (step.tone === 'danger' ? 'border-danger/60 text-danger' : step.tone === 'ok' ? 'border-ok/60 text-ok' : step.tone === 'warn' ? 'border-warn/60 text-warn' : 'border-info/60 text-info') : step.state === 'reached' ? 'border-ok/40 text-ok' : 'border-line-strong text-mute'
        const time = when(step.at, timeZone, false)
        if (compact) {
          return (
            <li key={`${step.stage}-${index}`} aria-label={`${step.label}: ${PROGRESS_WORD[step.state]}`} title={`${step.label}${time ? `, ${time}` : ''}`} className={clsx('h-1.5 w-5 rounded-full', step.state === 'current' ? (step.tone === 'danger' ? 'bg-danger' : step.tone === 'ok' ? 'bg-ok' : step.tone === 'warn' ? 'bg-warn' : 'bg-info') : step.state === 'reached' ? 'bg-ok/50' : 'bg-white/[0.1]')} />
          )
        }
        return (
          <li key={`${step.stage}-${index}`} aria-label={`${step.label}: ${PROGRESS_WORD[step.state]}`} aria-current={step.state === 'current' ? 'step' : undefined} className="relative flex min-w-0 items-start gap-2.5 pb-3 last:pb-0 sm:flex-col sm:items-start sm:gap-1.5 sm:pb-0 sm:pr-2">
            {index < steps.length - 1 && <span aria-hidden className={clsx('absolute left-[11px] top-6 h-[calc(100%-22px)] w-px bg-line-strong sm:left-7 sm:top-[11px] sm:h-px sm:w-[calc(100%-28px)]', index % 4 === 3 && 'sm:hidden 2xl:block')} />}
            <span className={clsx('relative z-10 flex h-[23px] w-[23px] shrink-0 items-center justify-center rounded-full border bg-surface', tone)}>
              <Icon aria-hidden className="h-3 w-3" strokeWidth={2.5} />
            </span>
            <span className="min-w-0 max-w-full">
              <span className={clsx('block break-words text-[12.5px] font-semibold leading-[17px]', step.state === 'upcoming' || step.state === 'skipped' ? 'text-mute' : 'text-ink')}>{step.label}</span>
              <span className="block text-xs tabular-nums text-mute">{time ?? (step.state === 'skipped' ? 'not recorded' : step.state === 'upcoming' ? 'not yet' : 'no time recorded')}</span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}

const short = (value: unknown): string | null => {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'string') return value.length > 80 ? `${value.slice(0, 77)}…` : value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.length === 0 ? null : value.every(v => typeof v === 'string' || typeof v === 'number') ? value.join(', ') : `${value.length} items`
  return null
}

/** The facts worth showing beside an event, taken from its `data` as the server wrote them. */
const DETAIL_KEYS: [string, string][] = [
  ['tool', 'Tool'],
  ['count', 'Found'],
  ['category', 'Kind'],
  ['priority', 'Priority'],
  ['planner', 'Planner'],
  ['purpose', 'Purpose'],
  ['status', 'Status'],
  ['method', 'Method'],
  ['by', 'By'],
  ['code', 'Code'],
  ['error', 'Error'],
  ['trigger', 'Started by'],
  ['account', 'Account'],
  ['stepId', 'Plan step'],
  ['fields', 'Fields you changed'],
  ['dependsOn', 'Depends on'],
]

/**
 * The recorded events of a run, oldest first, each with its time and kind. The server writes one
 * kind per event and never puts message text in a summary, so this is safe to show as it is.
 */
export function RunTimeline({ items, timeZone }: { items: DeskTimelineItem[]; timeZone: string }) {
  if (items.length === 0) return <p className="text-[12.5px] text-mute">The server recorded no events for this run.</p>
  return (
    <ol className="space-y-0">
      {items.map((item, index) => {
        const kind = (EVIDENCE_KIND as Record<string, { label: string; tone: string }>)[item.kind] ?? { label: item.kind, tone: 'neutral' }
        const failedRead = item.kind === 'read' && item.data?.ok === false
        const details = DETAIL_KEYS.map(([key, label]) => [label, short(item.data?.[key])] as const).filter(([, value]) => value !== null)
        return (
          <li key={`${item.at}-${index}`} className="relative grid grid-cols-[64px_minmax(0,1fr)] gap-x-3 pb-3 last:pb-0 sm:grid-cols-[72px_112px_minmax(0,1fr)]">
            <span className="pt-0.5 text-xs tabular-nums text-mute">{when(item.at, timeZone, false) ?? 'no time'}</span>
            <span className={clsx('hidden pt-0.5 text-xs font-semibold sm:block', item.kind === 'error' || failedRead ? 'text-danger' : kind.tone === 'ok' ? 'text-ok' : kind.tone === 'warn' ? 'text-warn' : kind.tone === 'accent' ? 'text-accent' : 'text-soft')}>{failedRead ? 'Read failed' : kind.label}</span>
            <div className="min-w-0">
              <p className="text-[13px] leading-[19px] text-ink">
                <span className="font-semibold text-soft sm:hidden">{failedRead ? 'Read failed' : kind.label}: </span>
                {item.summary}
              </p>
              {details.length > 0 && <p className="mt-0.5 break-words text-xs text-mute">{details.map(([label, value]) => `${label}: ${value}`).join(' · ')}</p>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

/** Whether an action took effect, with the evidence. Never green without the server's flag. */
export function VerificationEvidence({ action, timeZone }: { action: DeskAction; timeZone: string }) {
  const view = verificationOf(action)
  const bad = view.state === 'unknown_outcome' || view.state === 'failed'
  const Icon = view.state === 'verified' ? ShieldCheck : bad ? AlertTriangle : view.state === 'pending' ? Clock : CircleDashed
  const colour = view.state === 'verified' ? 'text-ok' : bad ? 'text-danger' : view.state === 'pending' ? 'text-warn' : 'text-mute'
  const at = when(action.verification?.at, timeZone)
  return (
    <p className="flex gap-2 text-[12.5px] leading-[19px]" data-testid={`verification-${action.toolCallId}`} role={bad ? 'alert' : undefined}>
      <Icon aria-hidden className={clsx('mt-0.5 h-3.5 w-3.5 shrink-0', colour)} />
      <span className="min-w-0">
        <span className={clsx('font-semibold', colour)}>{view.label}. </span>
        <span className="text-soft">{view.detail}</span>
        {at && view.state === 'verified' && <span className="text-mute"> Checked {at}.</span>}
      </span>
    </p>
  )
}

const EXECUTION_WORD: Record<string, string> = { executed: 'Executed', partially_executed: 'Partly executed', failed: 'Failed', unknown: 'Outcome unknown', held: 'Held by the execution gate' }
const SANDBOX_EXECUTION_WORD: Record<string, string> = { executed: 'Executed in sandbox', partially_executed: 'Partly executed in sandbox', failed: 'Failed in sandbox', unknown: 'Outcome unknown (sandbox)', held: 'Held by the execution gate' }

const TALLY_BAR: Record<TallyKind, string> = {
  verified: 'bg-ok',
  unverified: 'bg-warn/70',
  problem: 'bg-danger',
  you: 'bg-warn',
  running: 'bg-info',
  later: 'bg-white/[0.12]',
  blocked: 'bg-danger/40',
  cancelled: 'bg-white/[0.2]',
}

/**
 * How far a run has really got: one segment per step, green only for a step that ran AND carries
 * verification evidence, with the count in words. A half-done run reads as half done.
 */
export function StepTally({ tally, compact = false }: { tally: RunTally; compact?: boolean }) {
  if (tally.total === 0) return null
  return (
    <div data-testid="step-tally" className={clsx('flex flex-wrap items-center gap-x-2.5 gap-y-1', compact ? 'text-xs' : 'text-[12.5px]')}>
      <span role="img" aria-label={tally.summary} className="flex gap-0.5">
        {tally.steps.map((step, index) => (
          <span key={index} title={`${step.label}: ${step.standing.replace(/_/g, ' ')}`} className={clsx('h-1.5 rounded-full', compact ? 'w-5' : 'w-8', TALLY_BAR[step.kind])} />
        ))}
      </span>
      <span className={clsx('font-medium', tally.allVerified ? 'text-ok' : tally.counts.problem > 0 ? 'text-danger' : 'text-soft')}>{tally.summary}</span>
    </div>
  )
}

const shown = (value: unknown, tz: string): string => {
  if (value === null || value === undefined || value === '') return 'nothing'
  if (typeof value === 'string') return isInstant(value) ? `${fmtDayTime(value, tz)} (${tz})` : value
  if (Array.isArray(value)) return value.map(item => (typeof item === 'string' ? item : JSON.stringify(item))).join(', ') || 'nothing'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/**
 * What the person changed at approval: the proposal as the secretary wrote it, beside the
 * operation that was approved and ran. The server keeps both (`input` and `effectiveInput`).
 */
export function EditedApproval({ action, timeZone }: { action: DeskAction; timeZone: string }) {
  const edits = editsOf(action)
  const named = (action.decisions ?? []).flatMap(decision => decision.edited ?? [])
  if (edits.length === 0 && named.length === 0) return null
  return (
    <div className="rounded-lg border border-accent/35 bg-accent/[0.06] px-3 py-2.5" data-testid={`edited-${action.toolCallId}`}>
      <p className="text-[12.5px] font-semibold text-ink">You changed this proposal when you approved it</p>
      {edits.length > 0 ? (
        <table className="mt-1.5 w-full text-left text-[12.5px] leading-[19px]">
          <thead>
            <tr className="text-xs text-mute">
              <th scope="col" className="w-[84px] pr-3 font-medium">Field</th>
              <th scope="col" className="pr-3 font-medium">Originally proposed</th>
              <th scope="col" className="font-medium">Approved and {action.execution ? 'executed' : 'to be executed'}</th>
            </tr>
          </thead>
          <tbody>
            {edits.map(edit => (
              <tr key={edit.field} className="align-top">
                <th scope="row" className="pr-3 font-medium text-soft">{edit.field.replace(/_/g, ' ')}</th>
                <td className="break-words pr-3 tabular-nums text-mute line-through decoration-mute/60">{shown(edit.proposed, timeZone)}</td>
                <td className="break-words font-semibold tabular-nums text-ink">{shown(edit.approved, timeZone)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="mt-1 text-[12.5px] leading-[19px] text-warn">Fields changed: {[...new Set(named)].join(', ')}. This backend does not report the approved values, so the card above still shows the original proposal.</p>
      )}
      <p className="mt-1.5 text-xs text-mute">The original proposal is kept on record unchanged. Execution and verification use the approved values.</p>
    </div>
  )
}

/**
 * The record of one action after it was proposed: who decided what and when, what the execution
 * reported, and the verification. Shown under the action card, which carries the action itself.
 */
export function ExecutionStep({ action, timeZone, repeats = 0 }: { action: DeskAction; timeZone: string; repeats?: number }) {
  const decisions = action.decisions ?? []
  const execution = action.execution ?? null
  const proposed = when(action.proposedAt, timeZone)
  const planned = planFieldsOf(action)
  const hasRecord = Boolean(action.purpose || action.reason || proposed || decisions.length || execution || action.verification || action.outcomeUnknown || action.idempotencyKey)
  if (!hasRecord) return null
  return (
    <div className="mt-2 space-y-1.5 rounded-xl border border-line bg-white/[0.02] px-3.5 py-3" data-testid={`execution-${action.toolCallId}`}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="eyebrow">Record of this action</p>
        {action.simulated && <SandboxTag />}
        {repeats > 0 && <span className="text-xs font-semibold text-soft" data-testid={`repeats-${action.toolCallId}`}>One effect, {repeats + 1} cards: a retry reuses the same identity, so it is never carried out twice.</span>}
      </div>
      {action.reason && <p className="text-[12.5px] leading-[19px] text-soft"><span className="font-semibold text-ink">Why: </span>{action.reason}</p>}
      <ul className="space-y-1 text-[12.5px] leading-[19px] text-soft">
        {proposed && <li><span className="tabular-nums text-mute">{proposed}</span> · Proposed{action.purpose ? ` (${action.purpose.replace(/_/g, ' ')})` : ''}</li>}
        {decisions.map((decision, index) => (
          <li key={index}>
            <span className="tabular-nums text-mute">{when(decision.at, timeZone) ?? 'no time'}</span> · {decision.decision === 'approve' ? 'Approved' : 'Rejected'} by {decision.by}
            {decision.result === 'held' && <span className="text-warn"> · held by the execution gate{decision.code ? ` (${decision.code.replace(/_/g, ' ')})` : ''}: nothing ran</span>}
            {decision.edited && decision.edited.length > 0 && <span className="text-warn"> · edited before approval: {decision.edited.join(', ')}</span>}
          </li>
        ))}
        {execution && (
          <li className={clsx(execution.status === 'failed' && 'text-danger', execution.status === 'unknown' && 'text-danger')}>
            <span className="tabular-nums text-mute">{when(execution.at, timeZone) ?? 'no time'}</span> · {((execution.simulated ?? action.simulated) ? SANDBOX_EXECUTION_WORD : EXECUTION_WORD)[execution.status] ?? `Execution reported "${execution.status}"`}
            {typeof execution.durationMs === 'number' && execution.durationMs > 0 && ` in ${execution.durationMs} ms`}
            {(execution.simulated ?? action.simulated) && execution.status === 'executed' && ': simulated, nothing real was sent or changed'}
            {execution.error && `: ${execution.error}`}
          </li>
        )}
      </ul>
      <VerificationEvidence action={action} timeZone={timeZone} />
{(planned.attempts ?? 0) > 1 && (
        <p className="text-xs text-soft" data-testid={`attempts-${action.toolCallId}`}>Execution was attempted {planned.attempts} times. Each attempt carries the same identity, so the effect happens at most once.</p>
      )}
      {action.idempotencyKey && <p className="break-all text-xs text-mute">Identity of this effect: {action.idempotencyKey}</p>}
    </div>
  )
}

/** One awaited reply. A suggested reminder is a proposal: the text says so and links to it. */
export function FollowUpItem({ followUp, timeZone, onClose, closing = false, runSubject }: { followUp: DeskFollowUp; timeZone: string; onClose?: () => void; closing?: boolean; runSubject?: string | null }) {
  const info = followUpInfo(followUp.state)
  const open = followUp.state === 'waiting' || followUp.state === 'overdue'
  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-2 rounded-xl border border-line bg-white/[0.02] px-3.5 py-3" data-testid={`follow-up-${followUp.id}`}>
      <Reply aria-hidden className={clsx('mt-0.5 h-4 w-4 shrink-0', followUp.state === 'overdue' ? 'text-danger' : followUp.state === 'satisfied' ? 'text-ok' : 'text-mute')} />
      <div className="min-w-[min(100%,200px)] flex-1">
        <p className="break-words text-[13.5px] font-semibold text-ink">{followUp.waitingOn || 'Recipient not named on the record'}</p>
        <p className="break-words text-[12.5px] text-soft">{followUp.subject || runSubject || 'No subject on the record'}</p>
        <p className="mt-1 text-xs text-mute">
          {when(followUp.sentAt, timeZone) ? `Sent ${when(followUp.sentAt, timeZone)}` : 'Send time not recorded'}
          {open && when(followUp.dueAt, timeZone) ? ` · reply expected by ${when(followUp.dueAt, timeZone)}` : ''}
          {followUp.state === 'satisfied' && when(followUp.updatedAt, timeZone) ? ` · answered ${when(followUp.updatedAt, timeZone)}` : ''}
        </p>
        <p className="mt-1 text-[12.5px] leading-[19px] text-soft">{info.blurb}</p>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Pill tone={info.tone}>{info.label}</Pill>
        {typeof followUp.runId === 'number' && (
          <a href={hrefFor('work', String(followUp.runId))} className="hit text-[12.5px] font-medium text-accent hover:underline" aria-label={`Open run ${followUp.runId}`}>
            Run {followUp.runId}
          </a>
        )}
        {open && onClose && (
          <Button variant="ghost" className="h-8 px-2.5" onClick={onClose} busy={closing}>
            Stop waiting
          </Button>
        )}
      </div>
    </li>
  )
}

/** What the background intake worker is doing, as the server reports it. */
export function AgentActivity({ worker, timeZone, unavailable }: { worker: DeskWorkerStatus | null; timeZone: string; unavailable?: string | null }) {
  const view = workerView(worker)
  const last = when(worker?.you?.lastAt ?? worker?.lastTickAt, timeZone)
  return (
    <div className="flex gap-3" data-testid="agent-activity">
      <span className={clsx('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border', view.running ? (view.tone === 'ok' ? 'border-ok/40 text-ok' : view.tone === 'danger' ? 'border-danger/50 text-danger' : 'border-warn/50 text-warn') : 'border-line-strong text-mute')}>
        <Bot aria-hidden className="h-4 w-4" />
      </span>
      <div className="min-w-0 text-[12.5px] leading-[19px]">
        <p className="font-semibold text-ink">{unavailable ? 'Background intake status could not be read' : view.headline}</p>
        <p className="text-soft">{unavailable ?? view.detail}</p>
        {!unavailable && worker?.running && (
          <p className="mt-0.5 text-xs text-mute">
            {last ? `Last pass ${last}` : 'No pass recorded yet'}
            {typeof worker.you?.opened === 'number' ? ` · ${worker.you.opened} request${worker.you.opened === 1 ? '' : 's'} opened for you` : ''}
            {worker.claims && !worker.claims.durable ? ' · runs are kept in this process only' : ''}
          </p>
        )}
      </div>
    </div>
  )
}

export const actionName = (action: Pick<DeskAction, 'tool_name'>): string => ACTION_LABEL[action.tool_name] ?? action.tool_name.replace(/_/g, ' ')
