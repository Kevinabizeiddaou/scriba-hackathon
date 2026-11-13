import clsx from 'clsx';
import {
  AlertTriangle,
  CalendarClock,
  CalendarPlus,
  CalendarSearch,
  CalendarX,
  Check,
  Clock,
  Loader2,
  MailOpen,
  MinusCircle,
  NotebookPen,
  Search,
  Send,
  ShieldQuestion,
  type LucideIcon,
} from 'lucide-react';
import type { AgentAction, ToolName } from '../api/types';
import { ACTION_STATUS, TOOL_LABEL } from '../lib/labels';
import { fmtDuration, fmtTime } from '../lib/time';

const TOOL_ICON: Record<ToolName, LucideIcon> = {
  'email.read_thread': MailOpen,
  'email.search': Search,
  'email.send': Send,
  'calendar.list_events': CalendarSearch,
  'calendar.find_free_slots': CalendarSearch,
  'calendar.create_event': CalendarPlus,
  'calendar.update_event': CalendarClock,
  'calendar.cancel_event': CalendarX,
  'approval.request': ShieldQuestion,
  'audit.record': NotebookPen,
};

const STATUS_STYLE: Record<AgentAction['status'], { ring: string; icon: LucideIcon | null; text: string }> = {
  planned: { ring: 'border-line-strong text-mute', icon: null, text: 'text-mute' },
  awaiting_approval: { ring: 'border-warn/50 text-warn', icon: Clock, text: 'text-warn' },
  running: { ring: 'border-info/60 text-info', icon: Loader2, text: 'text-info' },
  succeeded: { ring: 'border-ok/40 text-ok', icon: Check, text: 'text-ok' },
  failed: { ring: 'border-danger/50 text-danger', icon: AlertTriangle, text: 'text-danger' },
  rejected: { ring: 'border-line-strong text-mute', icon: MinusCircle, text: 'text-mute' },
  skipped: { ring: 'border-line-strong text-mute', icon: MinusCircle, text: 'text-mute' },
};

/**
 * The agent's steps, in order. `detailed` adds timestamps and the raw tool input and output,
 * for the evaluation trace view.
 */
export function ActionTimeline({ actions, timeZone, detailed = false }: { actions: AgentAction[]; timeZone: string; detailed?: boolean }) {
  if (actions.length === 0) return <p className="text-[13px] text-mute">No steps yet.</p>;
  return (
    <ol className="relative space-y-0">
      {actions.map((action, index) => {
        const style = STATUS_STYLE[action.status];
        const ToolIcon = TOOL_ICON[action.tool];
        const StatusIcon = style.icon;
        const muted = action.status === 'rejected' || action.status === 'skipped';
        return (
          <li key={action.id} className="relative flex gap-3 pb-3 last:pb-0">
            {index < actions.length - 1 && <span aria-hidden className="absolute left-[13px] top-7 h-[calc(100%-28px)] w-px bg-line-strong" />}
            <span className={clsx('relative z-10 mt-0.5 flex h-[27px] w-[27px] shrink-0 items-center justify-center rounded-full border bg-surface', style.ring)}>
              <ToolIcon aria-hidden className="h-3.5 w-3.5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <p className={clsx('min-w-0 text-[13.5px]', muted ? 'text-mute line-through decoration-white/20' : 'text-ink')}>{action.summary}</p>
                <span className={clsx('flex shrink-0 items-center gap-1 text-[11.5px] font-medium tabular-nums', style.text)}>
                  {StatusIcon && <StatusIcon aria-hidden className={clsx('h-3 w-3', action.status === 'running' && 'animate-spin')} strokeWidth={2.5} />}
                  {ACTION_STATUS[action.status].label}
                  {action.durationMs !== null && action.durationMs > 0 && <span className="text-mute"> · {fmtDuration(action.durationMs)}</span>}
                </span>
              </div>
              <p className="text-[11.5px] text-mute">
                {TOOL_LABEL[action.tool]}
                {detailed && <span className="font-mono"> · {action.tool}</span>}
                {detailed && action.startedAt && <span className="tabular-nums"> · {fmtTime(action.startedAt, timeZone)}</span>}
                {action.sideEffect && action.status === 'succeeded' && action.simulated && ' · simulated, nothing was sent'}
              </p>
              {action.error && (
                <p className="mt-1 rounded-md border border-danger/25 bg-danger/[0.07] px-2 py-1 text-[12px] text-danger">
                  {action.error.message} <span className="font-mono text-[11px] opacity-80">({action.error.code})</span>
                </p>
              )}
              {detailed && (
                <details className="group mt-1">
                  <summary className="cursor-pointer select-none text-[11.5px] font-medium text-accent hover:underline">Input and output</summary>
                  <pre className="mt-1 max-h-64 overflow-auto rounded-md border border-line bg-sunken p-2.5 font-mono text-[11.5px] leading-[17px] text-soft">
                    {JSON.stringify({ input: action.input, output: action.output }, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
