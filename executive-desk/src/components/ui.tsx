import clsx from 'clsx';
import {
  AlertTriangle,
  Ban,
  Check,
  CircleDashed,
  Clock,
  Info,
  Loader2,
  type LucideIcon,
} from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { TONE_CLASS, type Tone } from '../lib/labels';

const TONE_ICON: Record<Tone, LucideIcon> = {
  neutral: CircleDashed,
  ok: Check,
  warn: Clock,
  danger: AlertTriangle,
  info: Info,
  accent: CircleDashed,
};

/** Status chip: always an icon plus a text label, so colour is never the only signal. */
export function Pill({ tone, children, icon, spin = false, className }: { tone: Tone; children: ReactNode; icon?: LucideIcon | null; spin?: boolean; className?: string }) {
  const Icon = spin ? Loader2 : icon === null ? null : (icon ?? TONE_ICON[tone]);
  return (
    <span className={clsx('pill', TONE_CLASS[tone], className)}>
      {Icon && <Icon aria-hidden className={clsx('h-3 w-3 shrink-0', spin && 'animate-spin')} strokeWidth={2.5} />}
      {children}
    </span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 aria-hidden className={clsx('h-4 w-4 animate-spin', className)} />;
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  busy?: boolean;
  icon?: LucideIcon;
}

export function Button({ variant = 'secondary', busy = false, icon: Icon, children, className, disabled, ...rest }: ButtonProps) {
  return (
    <button type="button" {...rest} disabled={disabled || busy} aria-busy={busy || undefined} className={clsx('btn', `btn-${variant}`, className)}>
      {busy ? <Spinner /> : Icon ? <Icon aria-hidden className="h-4 w-4" /> : null}
      {children}
    </button>
  );
}

export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-card border border-dashed border-line-strong px-6 py-10 text-center">
      <span className="mb-1 flex h-10 w-10 items-center justify-center rounded-full bg-white/[0.06] text-soft">
        <Icon aria-hidden className="h-5 w-5" />
      </span>
      <p className="text-[15px] font-semibold text-ink">{title}</p>
      {children && <div className="max-w-md text-[13px] text-soft">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-btn border border-danger/30 bg-danger/[0.08] px-3.5 py-2.5 text-[13px] text-danger">
      <AlertTriangle aria-hidden className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1">{error.message}</span>
      {onRetry && (
        <Button variant="ghost" className="h-7 px-2 text-danger" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div aria-hidden className="space-y-2.5">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-16 animate-pulse rounded-btn bg-white/[0.05]" />
      ))}
    </div>
  );
}

/** Small "nothing real happened" marker used wherever the mock adapter produced the data. */
export function SimulatedTag({ className }: { className?: string }) {
  return (
    <span className={clsx('pill border border-dashed border-warn/40 bg-transparent text-warn', className)} title="Produced by the mock adapter. No email was sent and no calendar was changed.">
      <Ban aria-hidden className="h-3 w-3" strokeWidth={2.5} />
      Simulated
    </span>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle: string; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 px-4 pb-4 pt-5 sm:px-6 lg:px-8 lg:pt-7">
      <div className="min-w-0">
        <h1 className="text-[22px] font-bold leading-7 tracking-[-0.01em] text-ink">{title}</h1>
        <p className="mt-1 max-w-2xl text-[13.5px] text-soft">{subtitle}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
