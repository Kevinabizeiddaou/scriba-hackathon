/**
 * The plan of a run, as the server wrote it when the run was opened: what was understood, what
 * that rests on, and the steps in order. Wording and rules are in runPlan.ts. Nothing here is
 * computed by the Desk: a step that has not been proposed is shown as not proposed, and a step is
 * green only on the server's evidence.
 */
import clsx from 'clsx'
import { ArrowDownRight, Ban, Check, CircleDashed, CircleDot, Clock, HelpCircle, ShieldAlert, X, type LucideIcon } from 'lucide-react'
import type { DeskAction } from '../api/desk'
import { Pill } from '../components/ui'
import { ACTION_LABEL } from './deskRuns'
import { SandboxTag } from './RunParts'
import { MIN_CONFIDENCE, confidenceText, droppedReason, intentLabel, planSummary, plannerLabel, purposeLabel, stepsOf, type RunPlanData, type StepStanding } from './runPlan'

const STEP_ICON: Record<StepStanding, LucideIcon> = {
  waiting: CircleDashed,
  ready: ArrowDownRight,
  blocked: Ban,
  your_decision: CircleDot,
  held: ShieldAlert,
  running: Clock,
  verified: Check,
  ran_unverified: Clock,
  verification_failed: ShieldAlert,
  interrupted: X,
  outcome_unknown: HelpCircle,
  partly: X,
  failed: X,
  cancelled: X,
  unknown: HelpCircle,
}

const RING: Record<string, string> = {
  ok: 'border-ok/50 text-ok',
  warn: 'border-warn/60 text-warn',
  danger: 'border-danger/60 text-danger',
  info: 'border-info/60 text-info',
  accent: 'border-accent/60 text-accent',
  neutral: 'border-line-strong text-mute',
}

function Facts({ title, items, tone, note, label }: { title: string; items: string[]; tone?: 'warn'; note?: string; label: string }) {
  if (items.length === 0) return null
  return (
    <div>
      <p className="eyebrow mb-1">{title}</p>
      <ul aria-label={label} className={clsx('list-disc space-y-1 pl-4 text-[12.5px] leading-[19px]', tone === 'warn' ? 'text-warn' : 'text-soft')}>
        {items.map((item, index) => (
          <li key={index} className="break-words">{item}</li>
        ))}
      </ul>
      {note && <p className="mt-1 text-xs text-mute">{note}</p>}
    </div>
  )
}

export function RunPlan({ plan, actions, simulated = false }: { plan: RunPlanData; actions: DeskAction[]; simulated?: boolean }) {
  const steps = stepsOf(plan, actions)
  const position = (id: string) => steps.findIndex(step => step.id === id) + 1
  return (
    <section aria-label="Plan of this run" className="card space-y-4 p-4 sm:p-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[14.5px] font-semibold text-ink">The plan</h2>
          {simulated && <SandboxTag />}
        </div>
        <p className="mt-1 text-[12.5px] leading-[19px] text-soft">
          Written once, when the request was picked up. {planSummary(plan)}
        </p>
        <p className="mt-0.5 text-xs text-mute">Planner: {plannerLabel(plan.planner)}</p>
      </div>

      {plan.intents.length > 0 && (
        <div>
          <p className="eyebrow mb-1">What the message asks for</p>
          <ul aria-label="What the message asks for" className="space-y-1.5">
            {plan.intents.map((intent, index) => (
              <li key={index} className="text-[12.5px] leading-[19px]">
                <span className="font-semibold text-ink">{intentLabel(intent.type)}</span>
                <span className={clsx('text-soft', intent.confidence !== null && intent.confidence < MIN_CONFIDENCE && 'text-warn')}> · {confidenceText(intent)}</span>
                {intent.evidence.length > 0 && (
                  <span className="block break-words text-xs text-mute">
                    {intent.source === 'rules' ? `Rules matched: ${intent.evidence.map(name => name.replace(/_/g, ' ')).join(', ')}` : `Quoted from the message: ${intent.evidence.map(quote => `“${quote}”`).join(' ')}`}
                  </span>
                )}
                {intent.missing.length > 0 && <span className="block text-xs text-warn">Not stated: {intent.missing.join(', ')}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan.unsupported.length > 0 && (
        <div>
          <p className="eyebrow mb-1">Left out</p>
          <ul aria-label="Readings that were left out" className="space-y-1 text-[12.5px] leading-[19px] text-soft">
            {plan.unsupported.map((intent, index) => (
              <li key={index}>
                <span className="text-ink">{intentLabel(intent.type)}</span>: {droppedReason(intent.why)}. Nothing was proposed from it.
              </li>
            ))}
          </ul>
        </div>
      )}

      {(plan.facts.length > 0 || plan.assumptions.length > 0 || plan.missing.length > 0) && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Facts title="Verified by reading" label="Facts verified by reading" items={plan.facts} />
          <Facts title="Assumed" label="Assumptions" items={plan.assumptions} note="Filled in because the message did not say. Check these before you approve." />
          <Facts title="Missing" label="Missing details" items={plan.missing} tone="warn" note="A missing detail leads to a question or a hand-over to you. It is never made up." />
        </div>
      )}

      {steps.length > 0 && (
        <div>
          <p className="eyebrow mb-2">Steps, in order</p>
          <ol aria-label="Steps of the plan" className="space-y-0">
            {steps.map((step, index) => {
              const Icon = STEP_ICON[step.standing]
              const after = step.dependsOn.map(id => (position(id) > 0 ? `step ${position(id)}` : id))
              return (
                <li key={step.id} data-testid={`plan-step-${step.id}`} aria-label={`Step ${index + 1}: ${purposeLabel(step)}. ${step.label}`} className="relative flex gap-3 pb-4 last:pb-0">
                  {index < steps.length - 1 && <span aria-hidden className="absolute left-[13px] top-7 h-[calc(100%-28px)] w-px bg-line-strong" />}
                  <span className={clsx('relative z-10 flex h-[27px] w-[27px] shrink-0 items-center justify-center rounded-full border bg-surface', RING[step.tone])}>
                    <Icon aria-hidden className="h-3.5 w-3.5" strokeWidth={2.5} />
                  </span>
                  <div className="min-w-0 flex-1 pt-0.5">
                    <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="text-[13.5px] font-semibold text-ink">{index + 1}. {purposeLabel(step)}</span>
                      <Pill tone={step.tone} icon={null}>{step.label}</Pill>
                    </p>
                    <p className="mt-0.5 text-xs text-mute">
                      {ACTION_LABEL[step.tool] ?? step.tool.replace(/_/g, ' ')}
                      {' · '}
                      {step.external ? 'reaches a mailbox or calendar' : 'your own records only'}
                      {' · '}
                      {step.requiresApproval ? 'needs your approval' : 'the server reports no approval is needed'}
                      {after.length > 0 ? ` · only after ${after.join(' and ')}` : ''}
                    </p>
                    <p className="mt-1 text-[12.5px] leading-[19px] text-soft">{step.blurb}</p>
                    {step.expected && <p className="mt-0.5 text-[12.5px] leading-[19px] text-soft"><span className="text-mute">Done when: </span>{step.expected}</p>}
                    {(step.standing === 'failed' || step.standing === 'partly' || step.standing === 'verification_failed' || step.standing === 'interrupted') && step.onFailure && <p className="mt-0.5 text-[12.5px] leading-[19px] text-danger">{step.onFailure}</p>}
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      )}

      {(plan.escalation.length > 0 || plan.tools.length > 0) && (
        <details className="rounded-lg border border-line px-3 py-1">
          <summary className="tap flex cursor-pointer items-center text-[12.5px] font-medium text-accent">When the secretary stops, and what it read</summary>
          <div className="space-y-3 pb-2 pt-1">
            <Facts title="It stops and hands over to you when" label="Conditions for handing over" items={plan.escalation} />
            {plan.tools.length > 0 && (
              <div>
                <p className="eyebrow mb-1">Reads made for this plan</p>
                <p className="break-words text-[12.5px] text-soft">{plan.tools.join(', ')}</p>
                <p className="mt-1 text-xs text-mute">Each read and its result is in the record of this run below.</p>
              </div>
            )}
          </div>
        </details>
      )}
    </section>
  )
}
