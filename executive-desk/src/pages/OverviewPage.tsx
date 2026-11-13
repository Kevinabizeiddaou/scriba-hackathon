import clsx from 'clsx';
import { AlertTriangle, ArrowRight, CalendarDays, Inbox, ListTodo, Reply, ShieldCheck, type LucideIcon } from 'lucide-react';
import { getApi } from '../api';
import type { RequestPriority } from '../api/types';
import { Pill, SkeletonRows } from '../components/ui';
import { EMAIL_CATEGORY, EMAIL_STATUS, Section, SourceBadge, WorkspaceState, dueLabel, nowMs } from '../components/workspace';
import { FEATURES, STATUS_LABEL, countByStatus, type FeatureStatus } from '../lib/featureStatus';
import { PRIORITY, type Tone } from '../lib/labels';
import { hrefFor, type Page } from '../lib/router';
import { fmtDay, fmtTime, localParts } from '../lib/time';
import { useResource, useWorkspace } from '../lib/useResource';

const PRIORITY_RANK: Record<RequestPriority, number> = { urgent: 0, high: 1, normal: 2, low: 3 };
const STATUS_TONE: Record<FeatureStatus, Tone> = { connected: 'ok', mock: 'warn', waiting: 'info', missing: 'neutral' };

function Stat({ icon: Icon, label, value, hint, page, tone = 'neutral' }: { icon: LucideIcon; label: string; value: number | string; hint: string; page: Page; tone?: 'neutral' | 'attention' }) {
  return (
    <a href={hrefFor(page)} className="card group flex items-start gap-3 px-4 py-3.5 transition-colors duration-150 hover:border-line-strong">
      <span className={clsx('mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px]', tone === 'attention' ? 'bg-brand-500/40 text-accent' : 'bg-white/[0.06] text-soft')}>
        <Icon aria-hidden className="h-[18px] w-[18px]" />
      </span>
      <span className="min-w-0">
        <span className="block text-[24px] font-bold leading-7 tabular-nums tracking-[-0.01em] text-ink">{value}</span>
        <span className="block text-[13px] font-semibold text-ink">{label}</span>
        <span className="block text-[12px] text-mute">{hint}</span>
      </span>
    </a>
  );
}

const More = ({ page, children }: { page: Page; children: string }) => (
  <a href={hrefFor(page)} className="tap inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">
    {children}
    <ArrowRight aria-hidden className="h-3.5 w-3.5" />
  </a>
);

export function OverviewPage() {
  const { principal } = getApi().info;
  const tz = principal.timezone;
  const approvals = useResource((api) => api.listApprovals({ status: ['pending'] }), []);
  const work = useWorkspace(async (w) => {
    const [emails, agenda, tasks, followUps, activity] = await Promise.all([w.listEmails(), w.listAgenda(), w.listTasks(), w.listFollowUps(), w.listActivity()]);
    return { emails, agenda, tasks, followUps, activity };
  }, []);

  const now = nowMs();
  const nowIso = new Date(now).toISOString();
  const today = localParts(nowIso, tz).date;
  const hour = Number(localParts(nowIso, tz).time.slice(0, 2));
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const data = work.data;

  const todayEvents = (data?.agenda ?? []).filter((e) => e.kind === 'event' && localParts(e.start, tz).date === today);
  const openMail = (data?.emails ?? []).filter((e) => e.status !== 'done');
  const priorityMail = [...openMail].sort((a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority] || Date.parse(b.receivedAt) - Date.parse(a.receivedAt)).slice(0, 5);
  const openTasks = (data?.tasks ?? []).filter((t) => t.status === 'open');
  const dueTasks = [...openTasks].filter((t) => t.dueAt).sort((a, b) => Date.parse(a.dueAt!) - Date.parse(b.dueAt!)).slice(0, 4);
  const overdueTasks = openTasks.filter((t) => t.dueAt && Date.parse(t.dueAt) < now).length;
  const overdueFollowUps = (data?.followUps ?? []).filter((f) => f.status === 'overdue');
  const waitingFollowUps = (data?.followUps ?? []).filter((f) => f.status === 'waiting' || f.status === 'overdue');
  const conflicts = todayEvents.filter((e) => e.conflictsWith.length > 0).length;
  const counts = countByStatus();

  return (
    <div className="px-4 pb-12 pt-5 sm:px-6 lg:px-8 lg:pt-7">
      <header className="mb-5">
        <p className="eyebrow">{fmtDay(nowIso, tz)}</p>
        <h1 className="mt-1 text-[24px] font-bold leading-8 tracking-[-0.01em] text-ink">
          {greeting}, {principal.name.split(' ')[0]}
        </h1>
        <p className="mt-1 max-w-2xl text-[13.5px] text-soft">Here is what came in, what is waiting for your decision, and what the secretary has already done.</p>
      </header>

      <WorkspaceState error={work.error} onRetry={work.reload}>
        {work.loading ? (
          <SkeletonRows rows={5} />
        ) : (
          <div className="space-y-5">
            <section aria-label="At a glance" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <Stat icon={ShieldCheck} label="Waiting for your approval" value={approvals.data?.length ?? 0} hint="Nothing is sent until you decide" page="approvals" tone={(approvals.data?.length ?? 0) > 0 ? 'attention' : 'neutral'} />
              <Stat icon={Inbox} label="Open in the inbox" value={openMail.length} hint={`${openMail.filter((e) => e.status === 'new').length} not yet read by the secretary`} page="inbox" />
              <Stat icon={CalendarDays} label="Meetings today" value={todayEvents.length} hint={conflicts > 0 ? `${conflicts} in conflict` : 'No conflicts'} page="calendar" tone={conflicts > 0 ? 'attention' : 'neutral'} />
              <Stat icon={ListTodo} label="Open tasks" value={openTasks.length} hint={overdueTasks > 0 ? `${overdueTasks} overdue` : 'None overdue'} page="tasks" tone={overdueTasks > 0 ? 'attention' : 'neutral'} />
              <Stat icon={Reply} label="Replies awaited" value={waitingFollowUps.length} hint={overdueFollowUps.length > 0 ? `${overdueFollowUps.length} overdue` : 'None overdue'} page="tasks" tone={overdueFollowUps.length > 0 ? 'attention' : 'neutral'} />
            </section>

            <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
              <div className="min-w-0 space-y-5">
                <Section title="Waiting for your decision" action={<More page="approvals">Approval center</More>}>
                  {(approvals.data?.length ?? 0) === 0 ? (
                    <p className="text-[13px] text-mute">Nothing is waiting for you.</p>
                  ) : (
                    <ul className="divide-y divide-line">
                      {approvals.data!.map((item) => (
                        <li key={item.id}>
                          <a href={hrefFor('approvals', item.id)} className="flex items-start gap-3 py-2.5 hover:bg-white/[0.02]">
                            <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
                            <span className="min-w-0 flex-1">
                              <span className="block text-[13.5px] font-semibold text-ink">{item.title}</span>
                              <span className="block truncate text-[12.5px] text-soft">{item.changes.map((c) => (c.type === 'email' ? 'Send an email' : c.type === 'calendar_create' ? 'Create an event' : c.type === 'calendar_update' ? 'Move an event' : 'Cancel an event')).join(', then ')}</span>
                            </span>
                            <ArrowRight aria-hidden className="mt-1 h-4 w-4 shrink-0 text-mute" />
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </Section>

                <Section title="Priority inbox" action={<More page="inbox">Inbox</More>}>
                  <ul className="divide-y divide-line">
                    {priorityMail.map((email) => (
                      <li key={email.id}>
                        <a href={hrefFor('inbox', email.id)} className="block py-2.5 hover:bg-white/[0.02]">
                          <span className="flex items-baseline justify-between gap-3">
                            <span className="truncate text-[13.5px] font-semibold text-ink">{email.from.name}</span>
                            <SourceBadge source={email.provider} />
                          </span>
                          <span className="block truncate text-[13px] text-soft">{email.subject}</span>
                          <span className="mt-1.5 flex flex-wrap gap-1.5">
                            <Pill tone={EMAIL_STATUS[email.status].tone}>{EMAIL_STATUS[email.status].label}</Pill>
                            <Pill tone={EMAIL_CATEGORY[email.category].tone} icon={null}>
                              {EMAIL_CATEGORY[email.category].label}
                            </Pill>
                            {(email.priority === 'urgent' || email.priority === 'high') && (
                              <Pill tone={PRIORITY[email.priority].tone} icon={null}>
                                {PRIORITY[email.priority].label}
                              </Pill>
                            )}
                          </span>
                        </a>
                      </li>
                    ))}
                  </ul>
                </Section>

                <Section title="Recent activity" action={<More page="activity">All activity</More>}>
                  <ul className="space-y-2.5">
                    {(data?.activity ?? []).slice(0, 6).map((entry) => (
                      <li key={entry.id} className="flex gap-3 text-[13px]">
                        <span className="w-[92px] shrink-0 tabular-nums text-mute">
                          {fmtDay(entry.at, tz).split(' ')[0]} {fmtTime(entry.at, tz)}
                        </span>
                        <span className="min-w-0 flex-1 text-ink">{entry.title}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              </div>

              <div className="min-w-0 space-y-5">
                <Section title="Today" action={<More page="calendar">Calendar</More>}>
                  {todayEvents.length === 0 ? (
                    <p className="text-[13px] text-mute">No meetings today.</p>
                  ) : (
                    <ol className="space-y-2">
                      {todayEvents.map((event) => (
                        <li key={event.id}>
                          <a href={hrefFor('calendar', event.id)} className={clsx('flex items-start gap-3 rounded-xl border px-3 py-2.5 hover:bg-white/[0.03]', event.conflictsWith.length ? 'border-danger/40' : 'border-line')}>
                            <span className="w-[88px] shrink-0 tabular-nums text-[12.5px] text-soft">
                              {fmtTime(event.start, tz)} to {fmtTime(event.end, tz)}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block text-[13.5px] font-semibold text-ink">{event.title}</span>
                              <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">
                                <SourceBadge source={event.provider} />
                                {event.conflictsWith.length > 0 && (
                                  <span className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-danger">
                                    <AlertTriangle aria-hidden className="h-3 w-3" />
                                    Conflict
                                  </span>
                                )}
                              </span>
                            </span>
                          </a>
                        </li>
                      ))}
                    </ol>
                  )}
                </Section>

                <Section title="Due and overdue" action={<More page="tasks">Tasks and follow-ups</More>}>
                  <ul className="space-y-2">
                    {dueTasks.map((task) => {
                      const due = dueLabel(task.dueAt!, tz);
                      return (
                        <li key={task.id} className="flex items-start justify-between gap-3 text-[13px]">
                          <span className="min-w-0 text-ink">{task.title}</span>
                          <span className={clsx('shrink-0 text-[12px] font-medium tabular-nums', due.overdue ? 'text-danger' : due.today ? 'text-warn' : 'text-mute')}>{due.text}</span>
                        </li>
                      );
                    })}
                    {overdueFollowUps.map((followUp) => (
                      <li key={followUp.id} className="flex items-start justify-between gap-3 text-[13px]">
                        <span className="min-w-0 text-ink">
                          No reply from {followUp.waitingOn.name}: {followUp.subject}
                        </span>
                        <span className="shrink-0 text-[12px] font-medium text-danger">{dueLabel(followUp.expectedBy, tz).text}</span>
                      </li>
                    ))}
                  </ul>
                </Section>

                <Section title="Integration status" label="Integration status">
                  <p className="mb-3 text-[12.5px] text-soft">What is connected to the real Scriba backend and what still runs on mock data.</p>
                  <dl className="grid grid-cols-2 gap-2">
                    {(Object.keys(counts) as FeatureStatus[]).map((status) => (
                      <div key={status} className="rounded-xl bg-white/[0.04] px-3 py-2">
                        <dt className="text-[11.5px] text-mute">{STATUS_LABEL[status]}</dt>
                        <dd className="text-[18px] font-bold tabular-nums text-ink">{counts[status]}</dd>
                      </div>
                    ))}
                  </dl>
                  <details className="mt-3">
                    <summary className="tap inline-flex cursor-pointer select-none items-center text-[12.5px] font-medium text-accent hover:underline">Show every feature</summary>
                    <ul className="mt-2 space-y-2">
                      {FEATURES.map((feature) => (
                        <li key={feature.name} className="text-[12.5px]">
                          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="font-semibold text-ink">{feature.name}</span>
                            <Pill tone={STATUS_TONE[feature.status]} icon={null}>
                              {STATUS_LABEL[feature.status]}
                            </Pill>
                          </span>
                          <span className="block text-mute">Backend today: {feature.backend}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                </Section>
              </div>
            </div>
          </div>
        )}
      </WorkspaceState>
    </div>
  );
}
