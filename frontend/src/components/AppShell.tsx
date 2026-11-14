import clsx from 'clsx';
import { CalendarDays, ClipboardList, FlaskConical, History, Inbox, LayoutDashboard, ListTodo, LogOut, Menu, MessageSquareText, ShieldCheck, X, type LucideIcon } from 'lucide-react';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { getApi, getWorkspace } from '../harness';
import { hrefFor, type Page } from '../lib/router';
import { fmtDayTime } from '../lib/time';
import { useResource, useWorkspace } from '../lib/useResource';
import { useLiveSession } from '../live/session';
import { nowMs } from './workspace';

interface NavItem {
  page: Page;
  label: string;
  short: string;
  icon: LucideIcon;
  group: 'Desk' | 'Work' | 'Quality';
  /** Shown only on a live backend: the screen has no demo counterpart. */
  liveOnly?: boolean;
}

const NAV: NavItem[] = [
  { page: 'overview', label: 'Overview', short: 'Overview', icon: LayoutDashboard, group: 'Desk' },
  { page: 'inbox', label: 'Inbox', short: 'Inbox', icon: Inbox, group: 'Desk' },
  { page: 'calendar', label: 'Calendar', short: 'Calendar', icon: CalendarDays, group: 'Desk' },
  { page: 'tasks', label: 'Tasks and follow-ups', short: 'Tasks', icon: ListTodo, group: 'Desk' },
  { page: 'work', label: 'Work queue', short: 'Work', icon: ClipboardList, group: 'Work', liveOnly: true },
  { page: 'chat', label: 'Secretary chat', short: 'Chat', icon: MessageSquareText, group: 'Work' },
  { page: 'approvals', label: 'Approval center', short: 'Approvals', icon: ShieldCheck, group: 'Work' },
  { page: 'activity', label: 'Activity', short: 'Activity', icon: History, group: 'Work' },
  { page: 'evaluation', label: 'Evaluation', short: 'Evaluation', icon: FlaskConical, group: 'Quality' },
];
/** The four destinations that fit in the phone's bottom bar. The rest are behind "More". */
const BOTTOM: Page[] = ['overview', 'inbox', 'calendar', 'approvals'];
/** On a live backend the work queue takes the calendar's place: it is where the day's work is. */
const LIVE_BOTTOM: Page[] = ['overview', 'work', 'inbox', 'approvals'];

function Mark() {
  return (
    <span aria-hidden className="flex h-9 w-9 items-center justify-center rounded-[11px] bg-gradient-to-br from-brand-400 to-brand-600 shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_6px_16px_rgba(139,32,64,0.45)]">
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16.5 8c-.7-1.800-2.400-3-4.500-3-2.600 0-4.500 1.500-4.500 3.600 0 4.600 9 2.400 9 7 0 2.100-1.900 3.400-4.500 3.400-2.200 0-3.900-1-4.700-2.700" />
      </svg>
    </span>
  );
}

function Badge({ count, label }: { count: number; label: string }) {
  if (count === 0) return null;
  return (
    <span aria-label={`${count} ${label}`} className="ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent/20 px-1.5 text-xs font-bold tabular-nums text-accent">
      {count}
    </span>
  );
}

/**
 * Badge counts on live data. Supplied by the live session (src/live/LiveApp.tsx), which reads
 * Scriba's action records; null in demo mode, where the mock supplies them.
 */
export interface ShellBadges {
  /** Actions waiting for the user's decision. Null while unknown: no badge, never a zero. */
  approvals: number | null;
  /** Actions that failed or only partly ran. */
  problems: number | null;
  /** Desk runs that need the user: an approval, an input, or a look at a failure. */
  work?: number | null;
}
export const ShellBadgesContext = createContext<ShellBadges | null>(null);

function LiveSourceNote() {
  const session = useLiveSession()!;
  const { info } = getApi();
  const overlay = session.overlay;
  return (
    <div className="rounded-xl border border-ok/25 bg-ok/[0.06] px-3 py-2.5 text-[12px] leading-[17px]" data-testid="data-source">
      <p className="flex items-center gap-1.5 font-semibold text-ok">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-ok" />
        Live: Scriba
      </p>
      <p className="mt-1 break-all text-mute">{info.baseUrl}</p>
      <p className={clsx('mt-1', overlay === 'ok' ? 'text-soft' : 'text-warn')}>
        {overlay === 'ok'
          ? `Desk overlay ${session.health?.version ?? ''}`.trim()
          : overlay === 'missing'
            ? 'No Desk overlay on this backend'
            : overlay === 'error'
              ? 'The Desk overlay could not be checked'
              : 'Checking the Desk overlay…'}
      </p>
      <p className="mt-1 text-soft">
        {session.policy.externalWritesEnabled ? 'Approvals you give are carried out for real.' : 'Sending and calendar changes are switched off. Tasks and reminders can be approved.'}
      </p>
    </div>
  );
}

function DataSourceNote() {
  const live = useLiveSession() !== null;
  return live ? <LiveSourceNote /> : <MockSourceNote />;
}

function MockSourceNote() {
  const { info } = getApi();
  const simulated = info.dataSource === 'simulated';
  return (
    <div className={clsx('rounded-xl border px-3 py-2.5 text-[12px] leading-[17px]', simulated ? 'border-warn/25 bg-warn/[0.06]' : 'border-ok/25 bg-ok/[0.06]')}>
      <p className={clsx('flex items-center gap-1.5 font-semibold', simulated ? 'text-warn' : 'text-ok')}>
        <span aria-hidden className={clsx('h-1.5 w-1.5 rounded-full', simulated ? 'bg-warn' : 'bg-ok')} />
        {simulated ? 'Mock data' : 'Live backend'}
      </p>
      <p className="mt-1 text-soft">{simulated ? 'Scripted agent and fictional people. No real email is sent and no calendar is changed.' : `${info.name}. Approvals you give here are carried out for real.`}</p>
      {info.baseUrl && (
        <p className="mt-1 break-all text-mute">
          {info.baseUrl}
          {info.contractVersion && ` · contract ${info.contractVersion}`}
        </p>
      )}
      {info.simulatedNow && <p className="mt-1 text-mute">Simulated clock: {fmtDayTime(info.simulatedNow, info.principal.timezone)}</p>}
    </div>
  );
}

export function AppShell({ page, children }: { page: Page; children: ReactNode }) {
  const { info } = getApi();
  const session = useLiveSession();
  const liveBadges = useContext(ShellBadgesContext);
  const [moreOpen, setMoreOpen] = useState(false);
  useEffect(() => setMoreOpen(false), [page]);

  const desk = useResource(
    async (api) => {
      // On live data the counts come from Scriba's action records (ShellBadgesContext), not from here.
      if (getWorkspace().availability === 'live') return { inbox: 0, approvals: 0 };
      const [fresh, pending] = await Promise.all([api.listRequests({ status: ['received'] }), api.listApprovals({ status: ['pending'] })]);
      return { inbox: fresh.length, approvals: pending.length };
    },
    [],
  );
  // Overdue work, when the workspace has data. Against a backend without a contract for it, no badge.
  const work = useWorkspace(async (workspace) => {
    if (workspace.availability !== 'mock') return 0;
    const [tasks, followUps] = await Promise.all([workspace.listTasks(), workspace.listFollowUps()]);
    return tasks.filter((t) => t.status === 'open' && t.dueAt && Date.parse(t.dueAt) < nowMs()).length + followUps.filter((f) => f.status === 'overdue').length;
  }, []);

  const badge = (target: Page) =>
    liveBadges
      ? target === 'approvals'
        ? (liveBadges.approvals ?? 0)
        : target === 'work'
          ? (liveBadges.work ?? 0)
          : target === 'activity'
          ? (liveBadges.problems ?? 0)
          : 0
      : target === 'inbox'
        ? (desk.data?.inbox ?? 0)
        : target === 'approvals'
          ? (desk.data?.approvals ?? 0)
          : target === 'tasks'
            ? (work.data ?? 0)
            : 0;
  const badgeLabel = (target: Page) => (target === 'work' ? 'runs that need you' : target === 'inbox' ? 'new requests' : target === 'approvals' ? 'approvals waiting' : target === 'activity' ? 'actions that failed or only partly ran' : 'overdue items');
  const groups = ['Desk', 'Work', 'Quality'] as const;
  const nav = NAV.filter((item) => !item.liveOnly || session !== null);
  const bottom = session !== null ? LIVE_BOTTOM : BOTTOM;
  const inMore = nav.filter((item) => !bottom.includes(item.page));
  const moreActive = inMore.some((item) => item.page === page);
  const moreCount = inMore.reduce((sum, item) => sum + badge(item.page), 0);

  return (
    <div className="flex h-full min-h-0">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-btn focus:bg-brand-500 focus:px-3 focus:py-2 focus:text-white">
        Skip to content
      </a>

      {/* Sidebar: large screens */}
      <aside className="hidden w-[256px] shrink-0 flex-col border-r border-line bg-sunken/60 px-3.5 py-5 lg:flex">
        <a href={hrefFor('overview')} className="mb-6 flex items-center gap-3 rounded-xl px-2 py-1">
          <Mark />
          <span className="leading-tight">
            <span className="block text-[15px] font-bold tracking-[-0.01em] text-ink">Scriba</span>
            <span className="block text-xs font-medium text-accent">Executive Desk</span>
          </span>
        </a>
        <nav aria-label="Main" className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          {groups.map((group) => (
            <div key={group}>
              <p className="eyebrow mb-1.5 px-3">{group}</p>
              <div className="space-y-0.5">
                {nav.filter((item) => item.group === group).map(({ page: target, label, icon: Icon }) => {
                  const active = target === page;
                  return (
                    <a
                      key={target}
                      href={hrefFor(target)}
                      aria-current={active ? 'page' : undefined}
                      className={clsx(
                        'flex h-10 items-center gap-3 rounded-btn px-3 text-[13.5px] font-medium transition-colors duration-150',
                        active ? 'bg-brand-500/30 text-ink shadow-[inset_2px_0_0_var(--accent)]' : 'text-soft hover:bg-white/[0.06] hover:text-ink',
                      )}
                    >
                      <Icon aria-hidden className={clsx('h-[18px] w-[18px]', active ? 'text-accent' : 'text-mute')} />
                      {label}
                      <Badge count={badge(target)} label={badgeLabel(target)} />
                    </a>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <div className="mt-4 space-y-3">
          <DataSourceNote />
          <div className="flex items-center gap-2.5 px-1">
            <span aria-hidden className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-[12px] font-bold text-white">
              {info.principal.name.split(' ').map((part) => part[0]).slice(0, 2).join('')}
            </span>
            <span className="min-w-0 leading-tight">
              <span className="block truncate text-[13px] font-semibold text-ink">{info.principal.name}</span>
              <span className="block truncate text-xs text-mute">{info.principal.timezone}</span>
            </span>
            {session && (
              <button type="button" onClick={() => void session.signOut()} aria-label="Sign out" title="Sign out" className="tap ml-auto inline-flex cursor-pointer items-center justify-center rounded-md p-1.5 text-mute hover:bg-white/[0.08] hover:text-ink">
                <LogOut aria-hidden className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar: small screens */}
        <div className="flex items-center justify-between gap-3 border-b border-line bg-sunken/60 px-4 py-2.5 lg:hidden">
          <span className="flex items-center gap-2.5">
            <Mark />
            <span className="text-[14px] font-bold text-ink">
              Scriba <span className="font-medium text-accent">Executive Desk</span>
            </span>
          </span>
          <span className={clsx('pill', info.dataSource === 'simulated' ? 'bg-warn/[0.14] text-warn' : 'bg-ok/[0.13] text-ok')}>{info.dataSource === 'simulated' ? 'Mock data' : session ? 'Live: Scriba' : 'Live'}</span>
        </div>

        <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto focus:outline-none">
          {children}
        </main>

        {/* "More" sheet: small screens */}
        {moreOpen && (
          <div className="lg:hidden">
            <button type="button" aria-label="Close menu" className="fixed inset-0 z-30 cursor-default bg-black/55" onClick={() => setMoreOpen(false)} />
            <div id="more-menu" role="dialog" aria-label="More destinations" className="rise-in fixed inset-x-0 bottom-[calc(56px+env(safe-area-inset-bottom))] z-40 rounded-t-2xl border-t border-line-strong bg-surface p-3 shadow-pop">
              <div className="mb-1 flex items-center justify-between px-2">
                <p className="eyebrow">More</p>
                <button type="button" aria-label="Close menu" onClick={() => setMoreOpen(false)} className="tap inline-flex cursor-pointer items-center justify-center rounded-md p-1 text-mute hover:text-ink">
                  <X aria-hidden className="h-4 w-4" />
                </button>
              </div>
              {inMore.map(({ page: target, label, icon: Icon }) => (
                <a key={target} href={hrefFor(target)} aria-current={target === page ? 'page' : undefined} className={clsx('flex min-h-[48px] items-center gap-3 rounded-btn px-3 text-[14px] font-medium', target === page ? 'bg-brand-500/30 text-ink' : 'text-soft')}>
                  <Icon aria-hidden className={clsx('h-5 w-5', target === page ? 'text-accent' : 'text-mute')} />
                  {label}
                  <Badge count={badge(target)} label={badgeLabel(target)} />
                </a>
              ))}
              <div className="mt-2 space-y-2">
                <DataSourceNote />
                {session && (
                  <button type="button" onClick={() => void session.signOut()} className="btn btn-secondary w-full">
                    <LogOut aria-hidden className="h-4 w-4" />
                    Sign out {info.principal.email && `(${info.principal.email})`}
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Bottom navigation: small screens */}
        <nav aria-label="Main" className="relative z-40 grid grid-cols-5 border-t border-line bg-sunken/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
          {bottom.map((target) => nav.find((item) => item.page === target)!).map(({ page: target, short, icon: Icon }) => {
            const active = target === page && !moreOpen;
            const count = badge(target);
            return (
              <a key={target} href={hrefFor(target)} aria-current={active ? 'page' : undefined} className={clsx('relative flex min-h-[56px] flex-col items-center justify-center gap-0.5 text-xs font-semibold', active ? 'text-accent' : 'text-mute')}>
                <span className="relative">
                  <Icon aria-hidden className="h-5 w-5" />
                  {count > 0 && (
                    <span aria-label={`${count} ${badgeLabel(target)}`} className="absolute -right-2.5 -top-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-500 px-1 text-xs font-bold text-white">
                      {count}
                    </span>
                  )}
                </span>
                {short}
              </a>
            );
          })}
          <button
            type="button"
            onClick={() => setMoreOpen((open) => !open)}
            aria-expanded={moreOpen}
            aria-controls="more-menu"
            className={clsx('relative flex min-h-[56px] cursor-pointer flex-col items-center justify-center gap-0.5 text-xs font-semibold', moreActive || moreOpen ? 'text-accent' : 'text-mute')}
          >
            <span className="relative">
              <Menu aria-hidden className="h-5 w-5" />
              {moreCount > 0 && (
                <span aria-label={`${moreCount} items in More`} className="absolute -right-2.5 -top-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-500 px-1 text-xs font-bold text-white">
                  {moreCount}
                </span>
              )}
            </span>
            More
          </button>
        </nav>
      </div>
    </div>
  );
}

/** Whether the workspace has data to show, for screens that want to say so in their header. */
export function workspaceIsMock(): boolean {
  return getWorkspace().availability === 'mock';
}
