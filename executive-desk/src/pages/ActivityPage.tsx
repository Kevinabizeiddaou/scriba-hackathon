import clsx from 'clsx';
import { CalendarDays, History, ListTodo, Mail, Reply, Settings2, ShieldCheck, Sparkles, type LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { getApi } from '../api';
import type { ActivityEntry } from '../api/workspace';
import { EmptyState, PageHeader, Pill, SimulatedTag, SkeletonRows } from '../components/ui';
import { WorkspaceState } from '../components/workspace';
import type { Tone } from '../lib/labels';
import { hrefFor } from '../lib/router';
import { fmtDay, fmtTime, localParts } from '../lib/time';
import { useWorkspace } from '../lib/useResource';

const KIND: Record<ActivityEntry['kind'], { label: string; icon: LucideIcon }> = {
  email: { label: 'Email', icon: Mail },
  calendar: { label: 'Calendar', icon: CalendarDays },
  task: { label: 'Tasks', icon: ListTodo },
  approval: { label: 'Approvals', icon: ShieldCheck },
  triage: { label: 'Triage', icon: Sparkles },
  follow_up: { label: 'Follow-ups', icon: Reply },
  system: { label: 'Handed to you', icon: Settings2 },
};

const OUTCOME: Record<ActivityEntry['outcome'], { label: string; tone: Tone }> = {
  done: { label: 'Done', tone: 'ok' },
  failed: { label: 'Failed', tone: 'danger' },
  pending: { label: 'Waiting', tone: 'warn' },
  rejected: { label: 'Rejected', tone: 'neutral' },
};

const ACTOR = { agent: 'Secretary', human: 'You', system: 'System' } as const;

export function ActivityPage() {
  const tz = getApi().info.principal.timezone;
  const [kind, setKind] = useState<ActivityEntry['kind'] | 'all'>('all');
  const activity = useWorkspace((w) => w.listActivity(), []);
  const all = activity.data ?? [];
  const shown = kind === 'all' ? all : all.filter((entry) => entry.kind === kind);

  const days: { date: string; label: string; entries: ActivityEntry[] }[] = [];
  for (const entry of shown) {
    const date = localParts(entry.at, tz).date;
    const last = days.at(-1);
    if (last?.date === date) last.entries.push(entry);
    else days.push({ date, label: fmtDay(entry.at, tz), entries: [entry] });
  }

  return (
    <div>
      <PageHeader title="Activity" subtitle="Everything the secretary read, proposed, sent or changed, and every decision you made, newest first." />
      <div className="px-4 pb-12 sm:px-6 lg:px-8">
        <div role="group" aria-label="Filter activity" className="mb-4 flex gap-1.5 overflow-x-auto">
          {(['all', ...Object.keys(KIND)] as (ActivityEntry['kind'] | 'all')[]).map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={kind === k}
              onClick={() => setKind(k)}
              className={clsx('tap inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3 text-[12.5px] font-semibold transition-colors duration-150', kind === k ? 'bg-brand-500/40 text-ink' : 'text-soft hover:bg-white/[0.06] hover:text-ink')}
            >
              {k === 'all' ? 'All' : KIND[k].label}
              <span className={clsx('tabular-nums', kind === k ? 'text-accent' : 'text-mute')}>{k === 'all' ? all.length : all.filter((e) => e.kind === k).length}</span>
            </button>
          ))}
        </div>

        <WorkspaceState error={activity.error} onRetry={activity.reload}>
          {activity.loading ? (
            <SkeletonRows rows={6} />
          ) : shown.length === 0 ? (
            <EmptyState icon={History} title="Nothing recorded">
              No activity of this kind yet.
            </EmptyState>
          ) : (
            <div className="max-w-3xl space-y-6">
              {days.map((day) => (
                <section key={day.date} aria-label={day.label}>
                  <h2 className="eyebrow mb-2.5">{day.label}</h2>
                  <ol className="relative space-y-0">
                    {day.entries.map((entry, index) => {
                      const Icon = KIND[entry.kind].icon;
                      const outcome = OUTCOME[entry.outcome];
                      return (
                        <li key={entry.id} className="relative flex gap-3 pb-4 last:pb-0">
                          {index < day.entries.length - 1 && <span aria-hidden className="absolute left-[15px] top-8 h-[calc(100%-32px)] w-px bg-line-strong" />}
                          <span className={clsx('relative z-10 flex h-[31px] w-[31px] shrink-0 items-center justify-center rounded-full border bg-surface', entry.outcome === 'failed' ? 'border-danger/50 text-danger' : entry.outcome === 'pending' ? 'border-warn/50 text-warn' : 'border-line-strong text-soft')}>
                            <Icon aria-hidden className="h-4 w-4" />
                          </span>
                          <div className="min-w-0 flex-1 pt-0.5">
                            <p className="text-[13.5px] text-ink">{entry.title}</p>
                            {entry.detail && <p className="mt-0.5 text-[12.5px] text-soft">{entry.detail}</p>}
                            <p className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12px] text-mute">
                              <span className="tabular-nums">{fmtTime(entry.at, tz)}</span>
                              <span>{ACTOR[entry.actor]}</span>
                              <Pill tone={outcome.tone} icon={null}>
                                {outcome.label}
                              </Pill>
                              {entry.simulated && (entry.kind === 'email' || entry.kind === 'calendar') && entry.outcome === 'done' && <SimulatedTag />}
                              {entry.link && (
                                <a href={hrefFor(entry.link.page, entry.link.param)} className="tap inline-flex items-center font-medium text-accent hover:underline">
                                  View
                                </a>
                              )}
                            </p>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                </section>
              ))}
            </div>
          )}
        </WorkspaceState>
      </div>
    </div>
  );
}
