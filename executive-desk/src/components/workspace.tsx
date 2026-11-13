/** Small pieces shared by the workspace screens: source badges, due labels, and the "waiting for backend" state. */
import clsx from 'clsx';
import { PlugZap } from 'lucide-react';
import type { ReactNode } from 'react';
import { getApi } from '../api';
import type { CalendarProvider, EmailCategory, EmailWorkStatus, MailProvider } from '../api/workspace';
import { WorkspaceUnavailable } from '../api/workspace';
import type { Tone } from '../lib/labels';
import { fmtDay, fmtDayTime, fmtTime, localParts } from '../lib/time';
import { EmptyState, ErrorNote } from './ui';

const SOURCE: Record<MailProvider | CalendarProvider, { label: string; dot: string; text: string }> = {
  gmail: { label: 'Gmail', dot: 'bg-accent', text: 'text-accent' },
  google: { label: 'Google', dot: 'bg-accent', text: 'text-accent' },
  outlook: { label: 'Outlook', dot: 'bg-info', text: 'text-info' },
};

/** Names the mailbox or calendar an item came from. Text plus a dot, never colour alone. */
export function SourceBadge({ source, className }: { source: MailProvider | CalendarProvider; className?: string }) {
  const s = SOURCE[source];
  return (
    <span className={clsx('inline-flex items-center gap-1.5 whitespace-nowrap text-[11.5px] font-semibold', s.text, className)}>
      <span aria-hidden className={clsx('h-1.5 w-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  );
}

export const EMAIL_CATEGORY: Record<EmailCategory, { label: string; tone: Tone }> = {
  meeting: { label: 'Meeting', tone: 'accent' },
  action_required: { label: 'Action required', tone: 'warn' },
  reply_needed: { label: 'Needs a reply', tone: 'info' },
  follow_up: { label: 'Follow-up', tone: 'info' },
  fyi: { label: 'For information', tone: 'neutral' },
  low_priority: { label: 'Low priority', tone: 'neutral' },
};

export const EMAIL_STATUS: Record<EmailWorkStatus, { label: string; tone: Tone }> = {
  new: { label: 'New', tone: 'accent' },
  in_progress: { label: 'In progress', tone: 'info' },
  needs_approval: { label: 'Needs approval', tone: 'warn' },
  needs_you: { label: 'Needs you', tone: 'danger' },
  waiting: { label: 'Waiting for reply', tone: 'info' },
  done: { label: 'Done', tone: 'ok' },
};

/** The moment the app treats as "now": the mock's fixed clock, or the real time against a backend. */
export function nowMs(): number {
  const simulated = getApi().info.simulatedNow;
  return simulated ? Date.parse(simulated) : Date.now();
}

/** "Overdue since Fri 13 Nov", "Today, 17:00", "Wed 18 Nov, 12:00". */
export function dueLabel(iso: string, timeZone: string): { text: string; overdue: boolean; today: boolean } {
  const now = nowMs();
  const overdue = Date.parse(iso) < now;
  const today = localParts(iso, timeZone).date === localParts(new Date(now).toISOString(), timeZone).date;
  if (overdue) return { text: today ? `Overdue since ${fmtTime(iso, timeZone)}` : `Overdue since ${fmtDay(iso, timeZone)}`, overdue, today };
  return { text: today ? `Today, ${fmtTime(iso, timeZone)}` : fmtDayTime(iso, timeZone), overdue, today };
}

/**
 * Wraps a workspace screen's content. When no backend contract exists for the data, it says so
 * plainly instead of showing an error or an empty list that looks like "nothing to do".
 */
export function WorkspaceState({ error, onRetry, children }: { error: Error | null; onRetry?: () => void; children: ReactNode }) {
  if (error instanceof WorkspaceUnavailable) {
    return (
      <EmptyState icon={PlugZap} title="Waiting for the backend contract">
        <p>{error.message}</p>
        <p className="mt-2">This screen is built and runs on mock data. It will show real data once the backend for it is agreed and connected. See docs/FEATURE_STATUS.md.</p>
      </EmptyState>
    );
  }
  if (error) return <ErrorNote error={error} onRetry={onRetry} />;
  return <>{children}</>;
}

export function Section({ title, action, children, className, label }: { title: string; action?: ReactNode; children: ReactNode; className?: string; label?: string }) {
  return (
    <section aria-label={label ?? title} className={clsx('card p-4 sm:p-5', className)}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-[14.5px] font-semibold text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
