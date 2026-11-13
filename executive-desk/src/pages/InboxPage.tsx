import clsx from 'clsx';
import { ArrowLeft, Check, Inbox, MinusCircle, Play, ShieldCheck, X } from 'lucide-react';
import { useState } from 'react';
import { getApi } from '../api';
import type { AgentRun, ApprovalRequest, RequestStatus, SecretaryRequest } from '../api/types';
import { RunCard } from '../components/RunCard';
import { Button, EmptyState, ErrorNote, PageHeader, Pill, SkeletonRows } from '../components/ui';
import { CLASSIFICATION, FLAG, OUTCOME, PRIORITY, REQUEST_STATUS } from '../lib/labels';
import { hrefFor } from '../lib/router';
import { fmtDayTime, fmtRange } from '../lib/time';
import { useResource } from '../lib/useResource';

const FILTERS: { id: string; label: string; statuses: RequestStatus[] | null }[] = [
  { id: 'all', label: 'All', statuses: null },
  { id: 'new', label: 'New', statuses: ['received'] },
  { id: 'approval', label: 'Needs approval', statuses: ['awaiting_approval'] },
  { id: 'attention', label: 'Needs you', statuses: ['escalated', 'failed'] },
  { id: 'waiting', label: 'In progress', statuses: ['processing', 'awaiting_reply'] },
  { id: 'done', label: 'Done', statuses: ['completed', 'declined'] },
];

type StepState = 'done' | 'current' | 'todo' | 'skipped' | 'failed';

function steps(request: SecretaryRequest, run: AgentRun | undefined, approvals: ApprovalRequest[]): { label: string; detail: string; state: StepState }[] {
  const triaged = request.classification !== null;
  const approval = approvals[0];
  const finished = run && (run.status === 'completed' || run.status === 'failed');

  let approvalStep: { detail: string; state: StepState };
  if (!approval) approvalStep = finished ? { detail: 'Not needed', state: 'skipped' } : { detail: 'If something is to be sent or changed', state: 'todo' };
  else if (approval.status === 'pending') approvalStep = { detail: 'Waiting for you', state: 'current' };
  else if (approval.status === 'approved') approvalStep = { detail: `Approved by ${approval.decidedBy ?? 'a person'}`, state: 'done' };
  else approvalStep = { detail: 'Rejected', state: 'failed' };

  let outcome: { detail: string; state: StepState };
  if (!finished) outcome = { detail: 'Pending', state: 'todo' };
  else if (run.status === 'failed' || request.status === 'escalated') outcome = { detail: run.outcome ? OUTCOME[run.outcome] : 'Failed', state: 'failed' };
  else outcome = { detail: run.outcome ? OUTCOME[run.outcome] : 'Finished', state: 'done' };

  return [
    { label: 'Received', detail: 'In the inbox', state: 'done' },
    {
      label: 'Understood',
      detail: triaged ? CLASSIFICATION[request.classification!] : request.status === 'processing' ? 'Reading the request' : 'Not started',
      state: triaged ? 'done' : request.status === 'processing' ? 'current' : 'todo',
    },
    { label: 'Approval', ...approvalStep },
    { label: 'Outcome', ...outcome },
  ];
}

const STEP_STYLE: Record<StepState, string> = {
  done: 'border-ok/50 bg-ok/[0.14] text-ok',
  current: 'border-warn/60 bg-warn/[0.14] text-warn',
  todo: 'border-line-strong text-mute',
  skipped: 'border-line-strong text-mute',
  failed: 'border-danger/50 bg-danger/[0.14] text-danger',
};

function Stepper({ request, run, approvals }: { request: SecretaryRequest; run: AgentRun | undefined; approvals: ApprovalRequest[] }) {
  const list = steps(request, run, approvals);
  return (
    <ol className="grid grid-cols-2 gap-x-3 gap-y-3 sm:grid-cols-4">
      {list.map((step, i) => (
        <li key={step.label} className="flex items-start gap-2.5" aria-current={step.state === 'current' ? 'step' : undefined}>
          <span className={clsx('mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold tabular-nums', STEP_STYLE[step.state])}>
            {step.state === 'done' ? <Check aria-hidden className="h-3.5 w-3.5" strokeWidth={3} /> : step.state === 'failed' ? <X aria-hidden className="h-3.5 w-3.5" strokeWidth={3} /> : step.state === 'skipped' ? <MinusCircle aria-hidden className="h-3.5 w-3.5" /> : i + 1}
          </span>
          <span className="min-w-0 leading-tight">
            <span className="block text-[13px] font-semibold text-ink">{step.label}</span>
            <span className="block text-[12px] text-mute">{step.detail}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function Detail({ request, onBack }: { request: SecretaryRequest; onBack: string }) {
  const api = getApi();
  const tz = api.info.principal.timezone;
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const related = useResource(
    async (a) => {
      const [runs, approvals] = await Promise.all([a.listRuns({ requestId: request.id }), a.listApprovals()]);
      return { run: runs[0] as AgentRun | undefined, approvals: approvals.filter((x) => x.requestId === request.id) };
    },
    [request.id],
  );
  const run = related.data?.run;
  const approvals = related.data?.approvals ?? [];
  const pendingApproval = approvals.find((a) => a.status === 'pending');
  const status = REQUEST_STATUS[request.status];
  const details = request.extracted;

  async function process() {
    setStarting(true);
    setError(null);
    try {
      await api.processRequest(request.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setStarting(false);
    }
  }

  const facts: [string, string][] = details
    ? ([
        ['Meeting', details.title],
        ['With', details.attendees.map((a) => a.name).join(', ') || null],
        ['Length', details.durationMinutes ? `${details.durationMinutes} minutes` : null],
        ['Requested', details.requestedWindows.map((w) => fmtRange(w.start, w.end, tz)).join('; ') || null],
        ['Their time zone', details.requesterTimezone],
        ['Format', details.modality ? details.modality.replace('_', ' ') : null],
        ['Refers to', details.referencedEventId],
        ['Still missing', details.missingFields.join(', ') || null],
        ['Notes', details.notes],
      ].filter(([, value]) => value) as [string, string][])
    : [];

  return (
    <article className="space-y-4 p-4 sm:p-6" aria-label={`Request: ${request.subject}`}>
      <a href={onBack} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-accent hover:underline lg:hidden">
        <ArrowLeft aria-hidden className="h-4 w-4" />
        All requests
      </a>

      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h2 className="text-[19px] font-bold leading-7 text-ink">{request.subject}</h2>
          <p className="mt-0.5 text-[13px] text-soft">
            {request.from.name} <span className="text-mute">&lt;{request.from.email}&gt;</span>
          </p>
          <p className="text-[12px] tabular-nums text-mute">Received {fmtDayTime(request.receivedAt, tz)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {request.status === 'received' && (
            <Button variant="primary" icon={Play} busy={starting} onClick={process}>
              Process request
            </Button>
          )}
          {pendingApproval && (
            <a href={hrefFor('approvals', pendingApproval.id)} className="btn btn-primary">
              <ShieldCheck aria-hidden className="h-4 w-4" />
              Review approval
            </a>
          )}
        </div>
      </header>

      <div className="flex flex-wrap gap-1.5">
        <Pill tone={status.tone} spin={request.status === 'processing'}>
          {status.label}
        </Pill>
        {request.classification && (
          <Pill tone="neutral" icon={null}>
            {CLASSIFICATION[request.classification]}
          </Pill>
        )}
        {request.priority && (
          <Pill tone={PRIORITY[request.priority].tone} icon={null}>
            {PRIORITY[request.priority].label} priority
          </Pill>
        )}
        {request.flags.map((flag) => (
          <Pill key={flag} tone={FLAG[flag].tone}>
            {FLAG[flag].label}
          </Pill>
        ))}
      </div>

      {error && <ErrorNote error={error} />}

      <section className="card p-4" aria-label="Processing status">
        <h3 className="eyebrow mb-3">Processing status</h3>
        <Stepper request={request} run={run} approvals={approvals} />
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="card p-4" aria-label="Incoming email">
          <h3 className="eyebrow mb-2.5">Incoming email</h3>
          <p className="whitespace-pre-wrap text-[13.5px] leading-[21px] text-ink">{request.bodyText}</p>
        </section>

        <section className="card p-4" aria-label="Extracted meeting details">
          <h3 className="eyebrow mb-2.5">Extracted meeting details</h3>
          {facts.length > 0 ? (
            <dl className="space-y-2">
              {facts.map(([term, value]) => (
                <div key={term} className="flex gap-3 text-[13px]">
                  <dt className="w-28 shrink-0 text-mute">{term}</dt>
                  <dd className="min-w-0 flex-1 break-words text-ink">{value}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-[13px] text-mute">{request.status === 'received' ? 'Nothing extracted yet. Process the request to have the agent read it.' : 'The agent extracted no meeting details.'}</p>
          )}
        </section>
      </div>

      <section className="card p-4" aria-label="Agent activity">
        <h3 className="eyebrow mb-2.5">Agent activity</h3>
        {related.loading ? <SkeletonRows rows={2} /> : run ? <RunCard run={run} timeZone={tz} /> : <p className="text-[13px] text-mute">The agent has not worked on this request yet.</p>}
      </section>

      <section className="card p-4" aria-label="History">
        <h3 className="eyebrow mb-2.5">History</h3>
        <ol className="space-y-2">
          {request.history.map((entry, i) => (
            <li key={i} className="flex gap-3 text-[13px]">
              <span className="w-[118px] shrink-0 tabular-nums text-mute">{fmtDayTime(entry.at, tz)}</span>
              <span className="min-w-0 flex-1">
                <span className="font-semibold text-ink">{entry.event}</span>
                <span className="text-mute"> · {entry.actor}</span>
                {entry.detail && <span className="block text-soft">{entry.detail}</span>}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}

export function InboxPage({ requestId }: { requestId: string | null }) {
  const [filter, setFilter] = useState('all');
  const requests = useResource((api) => api.listRequests(), []);
  const tz = getApi().info.principal.timezone;

  const all = requests.data ?? [];
  const active = FILTERS.find((f) => f.id === filter)!;
  const visible = active.statuses ? all.filter((r) => active.statuses!.includes(r.status)) : all;
  const selected = all.find((r) => r.id === requestId) ?? null;
  const count = (statuses: RequestStatus[] | null) => (statuses ? all.filter((r) => statuses.includes(r.status)).length : all.length);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={clsx(selected && 'hidden lg:block')}>
        <PageHeader title="Request Inbox" subtitle="Incoming meeting requests, what the agent made of each one, and where it stands." />
      </div>

      <div className="flex min-h-0 flex-1 border-t border-line">
        <section aria-label="Requests" className={clsx('flex w-full min-w-0 flex-col lg:w-[400px] lg:shrink-0 lg:border-r lg:border-line', selected && 'hidden lg:flex')}>
          <div role="group" aria-label="Filter requests" className="flex gap-1.5 overflow-x-auto border-b border-line px-3 py-2.5">
            {FILTERS.map((f) => {
              const n = count(f.statuses);
              const on = f.id === filter;
              return (
                <button
                  key={f.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setFilter(f.id)}
                  className={clsx(
                    'tap inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3 text-[12.5px] font-semibold transition-colors duration-150',
                    on ? 'bg-brand-500/40 text-ink' : 'text-soft hover:bg-white/[0.06] hover:text-ink',
                  )}
                >
                  {f.label}
                  <span className={clsx('tabular-nums', on ? 'text-accent' : 'text-mute')}>{n}</span>
                </button>
              );
            })}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
            {requests.loading && <SkeletonRows rows={6} />}
            {requests.error && <ErrorNote error={requests.error} onRetry={requests.reload} />}
            {!requests.loading && visible.length === 0 && (
              <EmptyState icon={Inbox} title="Nothing here">
                No requests match this filter.
              </EmptyState>
            )}
            <ul className="space-y-1.5">
              {visible.map((request) => {
                const status = REQUEST_STATUS[request.status];
                const isSelected = request.id === requestId;
                return (
                  <li key={request.id}>
                    <a
                      href={hrefFor('inbox', request.id)}
                      aria-current={isSelected ? 'true' : undefined}
                      className={clsx(
                        'block rounded-xl border px-3.5 py-3 transition-colors duration-150',
                        isSelected ? 'border-accent/40 bg-brand-500/20' : 'border-transparent hover:border-line hover:bg-white/[0.04]',
                      )}
                    >
                      <span className="flex items-baseline justify-between gap-3">
                        <span className={clsx('truncate text-[13.5px] text-ink', request.status === 'received' ? 'font-bold' : 'font-semibold')}>{request.from.name}</span>
                        <span className="shrink-0 text-[11.5px] tabular-nums text-mute">{fmtDayTime(request.receivedAt, tz)}</span>
                      </span>
                      <span className="mt-0.5 block truncate text-[13px] text-soft">{request.subject}</span>
                      <span className="mt-0.5 block truncate text-[12px] text-mute">{request.bodyText.replace(/\s+/g, ' ')}</span>
                      <span className="mt-2 flex flex-wrap items-center gap-1.5">
                        <Pill tone={status.tone} spin={request.status === 'processing'}>
                          {status.label}
                        </Pill>
                        {request.priority && (request.priority === 'urgent' || request.priority === 'high') && (
                          <Pill tone={PRIORITY[request.priority].tone} icon={null}>
                            {PRIORITY[request.priority].label}
                          </Pill>
                        )}
                        {request.flags.slice(0, 1).map((flag) => (
                          <Pill key={flag} tone={FLAG[flag].tone}>
                            {FLAG[flag].label}
                          </Pill>
                        ))}
                      </span>
                    </a>
                  </li>
                );
              })}
            </ul>
          </div>
        </section>

        <section aria-label="Request detail" className={clsx('min-w-0 flex-1 overflow-y-auto', !selected && 'hidden lg:block')}>
          {selected ? (
            <Detail key={selected.id} request={selected} onBack={hrefFor('inbox')} />
          ) : (
            <div className="flex h-full items-center justify-center p-8">
              <EmptyState icon={Inbox} title="Select a request">
                Pick a request on the left to see the email, what the agent extracted, and what it did.
              </EmptyState>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
