import clsx from 'clsx';
import { ChevronDown } from 'lucide-react';
import { useState } from 'react';
import type { AgentRun } from '../api/types';
import { OUTCOME, RUN_STATUS } from '../lib/labels';
import { fmtDuration } from '../lib/time';
import { ActionTimeline } from './ActionTimeline';
import { Pill } from './ui';

/** One agent run: status, what it concluded, and the steps it took. */
export function RunCard({ run, timeZone, defaultOpen = true, className }: { run: AgentRun; timeZone: string; defaultOpen?: boolean; className?: string }) {
  const [open, setOpen] = useState(defaultOpen);
  const status = RUN_STATUS[run.status];
  const active = run.status === 'running' || run.status === 'queued';
  const current = run.actions.find((a) => a.status === 'running');
  const steps = run.actions.filter((a) => a.status !== 'planned').length;

  return (
    <section aria-label="Agent run" className={clsx('rounded-xl border border-line bg-white/[0.025]', className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="tap flex w-full cursor-pointer flex-wrap items-center gap-x-2.5 gap-y-1.5 rounded-xl px-3.5 py-2.5 text-left hover:bg-white/[0.03]"
      >
        <Pill tone={status.tone} spin={active}>
          {status.label}
        </Pill>
        <span className="min-w-0 flex-1 truncate text-[13px] text-soft" aria-live="polite">
          {active ? (current?.summary ?? 'Reading the request') : run.outcome ? OUTCOME[run.outcome] : run.status === 'awaiting_approval' ? 'A proposal is ready for your review' : ''}
        </span>
        <span className="tabular-nums text-[11.5px] text-mute">
          {steps} {steps === 1 ? 'step' : 'steps'}
          {run.durationMs !== null && ` · ${fmtDuration(run.durationMs)}`}
        </span>
        <ChevronDown aria-hidden className={clsx('h-4 w-4 text-mute transition-transform duration-150', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="border-t border-line px-3.5 py-3">
          {run.summary && <p className="mb-3 text-[13.5px] text-ink">{run.summary}</p>}
          {run.error && (
            <p role="alert" className="mb-3 rounded-lg border border-danger/25 bg-danger/[0.07] px-3 py-2 text-[12.5px] text-danger">
              {run.error.message} <span className="font-mono text-[11px] opacity-80">({run.error.code})</span>
            </p>
          )}
          <ActionTimeline actions={run.actions} timeZone={timeZone} />
        </div>
      )}
    </section>
  );
}
