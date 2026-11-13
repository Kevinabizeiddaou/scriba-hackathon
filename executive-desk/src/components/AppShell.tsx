import clsx from 'clsx';
import { FlaskConical, Inbox, MessageSquareText, ShieldCheck, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { getApi } from '../api';
import { hrefFor, type Page } from '../lib/router';
import { fmtDayTime } from '../lib/time';
import { useResource } from '../lib/useResource';

const NAV: { page: Page; label: string; short: string; icon: LucideIcon }[] = [
  { page: 'chat', label: 'Secretary Chat', short: 'Chat', icon: MessageSquareText },
  { page: 'inbox', label: 'Request Inbox', short: 'Inbox', icon: Inbox },
  { page: 'approvals', label: 'Approval Center', short: 'Approvals', icon: ShieldCheck },
  { page: 'evaluation', label: 'Evaluation', short: 'Evaluation', icon: FlaskConical },
];

function Mark() {
  return (
    <span aria-hidden className="flex h-9 w-9 items-center justify-center rounded-[11px] bg-gradient-to-br from-brand-400 to-brand-600 shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_6px_16px_rgba(139,32,64,0.45)]">
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16.5 7.5c-.8-1.5-2.4-2.5-4.5-2.5-2.8 0-4.5 1.5-4.5 3.5 0 4.5 9 2.5 9 7 0 2-1.800 3.500-4.500 3.500-2.300 0-4-1-4.800-2.700" />
      </svg>
    </span>
  );
}

function Badge({ count, label }: { count: number; label: string }) {
  if (count === 0) return null;
  return (
    <span aria-label={`${count} ${label}`} className="ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent/20 px-1.5 text-[11px] font-bold tabular-nums text-accent">
      {count}
    </span>
  );
}

function DataSourceNote() {
  const { info } = getApi();
  const simulated = info.dataSource === 'simulated';
  return (
    <div className={clsx('rounded-xl border px-3 py-2.5 text-[12px] leading-[17px]', simulated ? 'border-warn/25 bg-warn/[0.06]' : 'border-ok/25 bg-ok/[0.06]')}>
      <p className={clsx('flex items-center gap-1.5 font-semibold', simulated ? 'text-warn' : 'text-ok')}>
        <span aria-hidden className={clsx('h-1.5 w-1.5 rounded-full', simulated ? 'bg-warn' : 'bg-ok')} />
        {simulated ? 'Mock data' : 'Live backend'}
      </p>
      <p className="mt-1 text-soft">{simulated ? 'Scripted agent. No real email is sent and no calendar is changed.' : `${info.name}. Approvals you give here are carried out for real.`}</p>
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
  const counts = useResource(
    async (api) => {
      const [fresh, pending] = await Promise.all([api.listRequests({ status: ['received'] }), api.listApprovals({ status: ['pending'] })]);
      return { inbox: fresh.length, approvals: pending.length };
    },
    [],
  );
  const badge = (target: Page) => (target === 'inbox' ? (counts.data?.inbox ?? 0) : target === 'approvals' ? (counts.data?.approvals ?? 0) : 0);
  const badgeLabel = (target: Page) => (target === 'inbox' ? 'new requests' : 'approvals waiting');

  return (
    <div className="flex h-full min-h-0">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-btn focus:bg-brand-500 focus:px-3 focus:py-2 focus:text-white">
        Skip to content
      </a>

      {/* Sidebar: large screens */}
      <aside className="hidden w-[248px] shrink-0 flex-col border-r border-line bg-sunken/60 px-3.5 py-5 lg:flex">
        <a href={hrefFor('inbox')} className="mb-7 flex items-center gap-3 rounded-xl px-2 py-1">
          <Mark />
          <span className="leading-tight">
            <span className="block text-[15px] font-bold tracking-[-0.01em] text-ink">Scriba</span>
            <span className="block text-[11.5px] font-medium text-accent">Executive Desk</span>
          </span>
        </a>
        <nav aria-label="Main" className="space-y-1">
          {NAV.map(({ page: target, label, icon: Icon }) => {
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
        </nav>
        <div className="mt-auto space-y-3">
          <DataSourceNote />
          <div className="flex items-center gap-2.5 px-1">
            <span aria-hidden className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-[12px] font-bold text-white">
              {info.principal.name.split(' ').map((part) => part[0]).slice(0, 2).join('')}
            </span>
            <span className="min-w-0 leading-tight">
              <span className="block truncate text-[13px] font-semibold text-ink">{info.principal.name}</span>
              <span className="block truncate text-[11.5px] text-mute">{info.principal.timezone}</span>
            </span>
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
          <span className={clsx('pill', info.dataSource === 'simulated' ? 'bg-warn/[0.14] text-warn' : 'bg-ok/[0.13] text-ok')}>{info.dataSource === 'simulated' ? 'Mock data' : 'Live'}</span>
        </div>

        <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto focus:outline-none">
          {children}
        </main>

        {/* Bottom navigation: small screens */}
        <nav aria-label="Main" className="grid grid-cols-4 border-t border-line bg-sunken/90 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
          {NAV.map(({ page: target, short, icon: Icon }) => {
            const active = target === page;
            const count = badge(target);
            return (
              <a
                key={target}
                href={hrefFor(target)}
                aria-current={active ? 'page' : undefined}
                className={clsx('relative flex min-h-[56px] flex-col items-center justify-center gap-0.5 text-[11px] font-semibold', active ? 'text-accent' : 'text-mute')}
              >
                <span className="relative">
                  <Icon aria-hidden className="h-5 w-5" />
                  {count > 0 && (
                    <span aria-label={`${count} ${badgeLabel(target)}`} className="absolute -right-2.5 -top-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-500 px-1 text-[10px] font-bold text-white">
                      {count}
                    </span>
                  )}
                </span>
                {short}
              </a>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
