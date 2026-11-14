/**
 * The workflow of one run, drawn as a chain of stages with depth.
 *
 * Nothing here is decoration. Every node is a stage of `progressOf(run)` (runLifecycle.ts): the
 * server's stage, the time the server recorded for it, and whether the run reached it, rests in
 * it, passed over it or has not got there. The notes under a node are counts and names read from
 * the same run: the tools it read with, the steps of its plan, the actions waiting for a
 * decision, the files it made, what was verified. A run with no lifecycle draws no graph.
 *
 * Motion is one thing only: the connector into the stage the run is in moves while the secretary
 * holds the next move, and stands still when the next move is the user's or nobody's. With
 * `prefers-reduced-motion` nothing moves.
 */
import clsx from 'clsx'
import { Ban, Check, CircleDashed, Clock, FileText, Globe, Hand, ListChecks, Loader, Minus, ShieldCheck, TriangleAlert, Wrench, type LucideIcon } from 'lucide-react'
import type { DeskRun } from '../api/desk'
import { fmtDayTime, isInstant } from '../lib/time'
import { LIFECYCLE, isKnownStage, type ProgressState, type ProgressStep } from './runLifecycle'

type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'accent'

export interface StageNote {
  icon: LucideIcon
  text: string
  tone?: Tone
}

const WORD: Record<ProgressState, string> = { reached: 'done', current: 'now', skipped: 'not recorded', upcoming: 'not yet' }

const TOOL_NAME: Record<string, string> = {
  'email.read_thread': 'mail thread',
  'calendar.find_free_slots': 'calendars',
  'file.read_attachment': 'attached files',
  send_email: 'email',
  draft_email_reply: 'reply draft',
  create_calendar_event: 'calendar event',
  update_calendar_event: 'calendar change',
  cancel_calendar_event: 'cancellation',
  create_task: 'task',
  create_reminder: 'reminder',
  create_document: 'document',
  create_spreadsheet: 'workbook',
}
const toolName = (tool: string) => TOOL_NAME[tool] ?? tool.replace(/[._]/g, ' ')
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** What the run's own record says happened at each stage. Counts and names only. */
export function stageNotes(run: DeskRun): Record<string, StageNote[]> {
  const notes: Record<string, StageNote[]> = {}
  const add = (stage: string, note: StageNote) => (notes[stage] ??= []).push(note)
  const actions = run.actions ?? []
  const plan = run.plan
  const extra = run as DeskRun & { browser?: { state?: string; site?: string; stepsDone?: number; stepsTotal?: number } }

  const read = [...new Set((plan?.tools ?? []).map(toolName))]
  if (read.length > 0) add('INVESTIGATING', { icon: Wrench, text: `Read: ${read.join(', ')}` })
  const attachments = run.attachments ?? []
  if (attachments.length > 0) add('INVESTIGATING', { icon: FileText, text: plural(attachments.length, 'file') + ' with the message' })
  if (extra.browser?.site) {
    const done = extra.browser.state === 'VERIFIED' || extra.browser.state === 'COMPLETED'
    add('INVESTIGATING', { icon: Globe, text: `${extra.browser.site}: ${extra.browser.stepsDone ?? 0} of ${extra.browser.stepsTotal ?? 0} steps`, tone: done ? 'ok' : extra.browser.state === 'RUNNING' || extra.browser.state === 'PLANNED' ? 'info' : 'danger' })
  }

  if (plan?.steps?.length) add('PLANNING', { icon: ListChecks, text: `${plural(plan.steps.length, 'step')}, ${plan.approvals} to approve` })

  const waiting = actions.filter(a => ['pending', 'awaiting_approval', 'needs_info', 'draft', 'proposed'].includes(a.status))
  if (waiting.length > 0) add('AWAITING_APPROVAL', { icon: Hand, text: `${plural(waiting.length, 'action')} waiting for you: ${[...new Set(waiting.map(a => toolName(a.tool_name)))].join(', ')}`, tone: 'warn' })
  const changes = (run.fileChanges ?? []).filter(c => c.state === 'suggested')
  if (changes.length > 0) add('AWAITING_APPROVAL', { icon: Hand, text: `${plural(changes.length, 'workbook change')} for you to apply`, tone: 'warn' })

  const ran = actions.filter(a => a.status === 'executed' || a.status === 'partially_executed')
  if (ran.length > 0) add('EXECUTING', { icon: Wrench, text: `Ran: ${[...new Set(ran.map(a => toolName(a.tool_name)))].join(', ')}` })
  const failed = actions.filter(a => a.status === 'failed')
  if (failed.length > 0) add('EXECUTING', { icon: TriangleAlert, text: `${plural(failed.length, 'action')} failed`, tone: 'danger' })
  const files = run.files ?? []
  if (files.length > 0) add('EXECUTING', { icon: FileText, text: `${plural(files.length, 'file')} made or retrieved` })

  const verified = ran.filter(a => a.verified === true)
  if (ran.length > 0) add('VERIFYING', { icon: ShieldCheck, text: `${verified.length} of ${ran.length} verified`, tone: verified.length === ran.length ? 'ok' : 'warn' })

  const awaited = (run.followUps ?? []).filter(f => f.state === 'waiting' || f.state === 'overdue')
  if (awaited.length > 0) add('WAITING_FOR_RESPONSE', { icon: Clock, text: `${plural(awaited.length, 'reply', 'replies')} awaited` })
  return notes
}

const ICON: Record<ProgressState, LucideIcon> = { reached: Check, current: Loader, skipped: Minus, upcoming: CircleDashed }

function nodeLook(step: ProgressStep): { ring: string; icon: LucideIcon; spin: boolean; live: boolean } {
  if (step.state !== 'current') {
    return { ring: step.state === 'reached' ? 'flow-node-done' : 'flow-node-idle', icon: ICON[step.state], spin: false, live: false }
  }
  const info = isKnownStage(step.stage) ? LIFECYCLE[step.stage] : null
  const working = info?.holder === 'secretary'
  if (step.tone === 'danger') return { ring: 'flow-node-danger', icon: TriangleAlert, spin: false, live: false }
  if (step.tone === 'ok') return { ring: 'flow-node-ok', icon: Check, spin: false, live: false }
  if (step.tone === 'warn') return { ring: 'flow-node-warn', icon: Hand, spin: false, live: false }
  if (step.stage === 'CANCELLED') return { ring: 'flow-node-idle', icon: Ban, spin: false, live: false }
  return { ring: 'flow-node-live', icon: working ? Loader : Clock, spin: working, live: working }
}

const NOTE_TONE: Record<Tone, string> = { neutral: 'text-mute', ok: 'text-ok', warn: 'text-warn', danger: 'text-danger', info: 'text-info', accent: 'text-accent' }

export function WorkflowGraph({ steps, timeZone, notes = {} }: { steps: ProgressStep[]; timeZone: string; notes?: Record<string, StageNote[]> }) {
  return (
    <div className="flow" data-testid="workflow-graph">
      <ol aria-label="Progress of this run" className="flow-track">
        {steps.map((step, index) => {
          const look = nodeLook(step)
          const Icon = look.icon
          const time = step.at && isInstant(step.at) ? fmtDayTime(step.at, timeZone) : null
          const own = notes[step.stage] ?? []
          return (
            <li
              key={`${step.stage}-${index}`}
              aria-label={`${step.label}: ${WORD[step.state]}`}
              aria-current={step.state === 'current' ? 'step' : undefined}
              data-state={step.state}
              className={clsx('flow-step', step.state === 'upcoming' && 'flow-step-ahead')}
            >
              {index > 0 && <span aria-hidden className={clsx('flow-link', step.state === 'reached' || step.state === 'current' ? 'flow-link-on' : step.state === 'skipped' ? 'flow-link-skip' : '', look.live && 'flow-link-live')} />}
              <span className={clsx('flow-node', look.ring)}>
                <Icon aria-hidden className={clsx('h-[18px] w-[18px]', look.spin && 'flow-spin')} strokeWidth={2.25} />
              </span>
              <span className="flow-text">
                <span className={clsx('block text-[13px] font-semibold leading-[18px]', step.state === 'upcoming' || step.state === 'skipped' ? 'text-mute' : 'text-ink')}>{step.label}</span>
                <span className="block text-[11.5px] tabular-nums leading-4 text-mute">{time ?? (step.state === 'skipped' ? 'not recorded' : step.state === 'upcoming' ? 'not yet' : 'no time recorded')}</span>
                {own.length > 0 && (
                  <span className="mt-1.5 block space-y-1">
                    {own.map((note, i) => {
                      const NoteIcon = note.icon
                      return (
                        <span key={i} className={clsx('flex items-start gap-1.5 text-[11.5px] leading-4', NOTE_TONE[note.tone ?? 'neutral'])}>
                          <NoteIcon aria-hidden className="mt-px h-3 w-3 shrink-0" />
                          <span className="min-w-0 break-words text-soft">{note.text}</span>
                        </span>
                      )
                    })}
                  </span>
                )}
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
