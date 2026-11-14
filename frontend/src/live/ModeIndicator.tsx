/**
 * The execution-mode markers: one banner above every screen, one note in the sidebar and one chip
 * in the phone's top bar. All three say the same thing, from the same reading of GET /desk/health
 * (executionMode.ts), so a screenshot of any screen labels itself.
 */
import clsx from 'clsx'
import { FlaskConical, Radio, ShieldOff, CircleHelp, type LucideIcon } from 'lucide-react'
import { getApi } from '../harness'
import { fmtDayTime, isInstant } from '../lib/time'
import type { DeskMode, ModeTone } from './executionMode'
import { useRequiredLiveSession } from './session'

const ICON: Record<ModeTone, LucideIcon> = { sandbox: FlaskConical, live: Radio, off: ShieldOff, unknown: CircleHelp }

const BANNER: Record<ModeTone, string> = {
  sandbox: 'border-warn/45 bg-warn/[0.12] text-warn',
  live: 'border-danger/45 bg-danger/[0.12] text-danger',
  off: 'border-line-strong bg-white/[0.04] text-soft',
  unknown: 'border-line-strong bg-white/[0.04] text-soft',
}

const BADGE: Record<ModeTone, string> = {
  sandbox: 'bg-warn text-[#1b1400]',
  live: 'bg-danger text-white',
  off: 'bg-white/[0.14] text-ink',
  unknown: 'bg-white/[0.14] text-ink',
}

/** The upper-case marker on its own. */
export function ModeBadge({ mode, className }: { mode: DeskMode; className?: string }) {
  const Icon = ICON[mode.tone]
  return (
    <span data-testid="mode-badge" data-mode={mode.kind} className={clsx('inline-flex h-[22px] shrink-0 items-center gap-1 rounded-md px-1.5 text-[11px] font-extrabold uppercase tracking-[0.08em]', BADGE[mode.tone], className)}>
      <Icon aria-hidden className="h-3 w-3" strokeWidth={2.75} />
      {mode.badge}
    </span>
  )
}

const BANNER_LINE: Record<DeskMode['kind'], string> = {
  sandbox: 'Simulated execution. Synthetic mail and calendars; no real email is sent and no real person is contacted.',
  external: 'External writes are authorized. An approval is carried out on the real mailbox or calendar.',
  disabled: 'External writes are disabled. Mail and calendar actions can be reviewed and cancelled, not carried out.',
  no_overlay: 'No Desk overlay on this backend. External writes stay switched off.',
  unknown: 'The execution mode could not be read. External writes are treated as off.',
  checking: 'Checking how this backend executes actions…',
}

/**
 * The strip above every live screen. In a sandbox it cannot be missed and cannot be dismissed;
 * when writes are simply off it is one quiet line.
 */
export function ModeBanner() {
  const session = useRequiredLiveSession()
  const { mode, sandbox } = session
  const tz = getApi().info.principal.timezone
  if (mode.kind === 'checking') return null
  const clock = sandbox && isInstant(sandbox.now) ? fmtDayTime(sandbox.now, tz) : null
  return (
    <div role="status" aria-label={`Execution mode: ${mode.title}`} data-testid="mode-banner" data-mode={mode.kind} className={clsx('flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b px-4 py-1.5 text-[12.5px] leading-[18px] sm:px-6 lg:px-8', BANNER[mode.tone])}>
      <ModeBadge mode={mode} />
      <span className="min-w-0 font-medium">{BANNER_LINE[mode.kind]}</span>
      {mode.kind === 'sandbox' && (
        <span className="text-mute">
          {mode.world ? `World: ${mode.world}` : ''}
          {mode.world && clock && sandbox?.fixedClock ? ' · ' : ''}
          {clock && sandbox?.fixedClock ? `sandbox clock ${clock} (${tz})` : ''}
        </span>
      )}
    </div>
  )
}

/** The sidebar's note: which backend, which overlay, and what an approval does. */
export function ModeNote() {
  const session = useRequiredLiveSession()
  const { mode, overlay, sandbox } = session
  const { info } = getApi()
  const box = mode.tone === 'sandbox' ? 'border-warn/35 bg-warn/[0.07]' : mode.tone === 'live' ? 'border-danger/35 bg-danger/[0.07]' : 'border-line-strong bg-white/[0.03]'
  return (
    <div className={clsx('rounded-xl border px-3 py-2.5 text-[12px] leading-[17px]', box)} data-testid="data-source" data-mode={mode.kind}>
      <div className="flex flex-wrap items-center gap-1.5">
        <ModeBadge mode={mode} />
        <span className={clsx('font-semibold', mode.tone === 'sandbox' ? 'text-warn' : mode.tone === 'live' ? 'text-danger' : 'text-ink')}>
          {mode.kind === 'sandbox' ? 'Simulated execution' : mode.kind === 'external' ? 'External writes authorized' : mode.kind === 'checking' ? 'Checking…' : mode.kind === 'unknown' ? 'Mode not read' : 'External writes disabled'}
        </span>
      </div>
      <p className="mt-1.5 text-soft">{mode.detail}</p>
      <p className="mt-1.5 flex items-center gap-1.5 text-mute">
        <span aria-hidden className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', mode.connected ? 'bg-ok' : 'bg-mute')} />
        <span className="min-w-0 break-all">
          {mode.connected ? 'Connected to a Scriba backend' : 'Backend not confirmed'}: {info.baseUrl}
        </span>
      </p>
      <p className={clsx('mt-0.5', overlay === 'ok' ? 'text-mute' : 'text-warn')}>
        {overlay === 'ok'
          ? `Desk overlay ${session.health?.version ?? ''}`.trim()
          : overlay === 'missing'
            ? 'No Desk overlay on this backend'
            : overlay === 'error'
              ? 'The Desk overlay could not be checked'
              : 'Checking the Desk overlay…'}
        {mode.kind === 'sandbox' && sandbox ? ` · ${sandbox.operations.length} sandbox operation${sandbox.operations.length === 1 ? '' : 's'} so far` : ''}
      </p>
    </div>
  )
}
