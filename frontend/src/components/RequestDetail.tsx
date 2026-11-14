import clsx from 'clsx';
import { Check, MinusCircle, Play, ShieldCheck, X } from 'lucide-react';
import { useState } from 'react';
import { getApi } from '../harness';
import type { AgentRun, ApprovalRequest, SecretaryRequest } from '../harness/types';
import { CLASSIFICATION, OUTCOME } from '../lib/labels';
import { hrefFor } from '../lib/router';
import { fmtDayTime, fmtRange } from '../lib/time';
import { useResource } from '../lib/useResource';
import { RunCard } from './RunCard';
import { Button, ErrorNote, SkeletonRows } from './ui';

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

/**
 * The scheduling side of a meeting request: where it stands, what was extracted from it,
 * what the secretary did, and its history. Shown inside the inbox for emails that are
 * meeting requests.
 */
export function RequestDetail({ request }: { request: SecretaryRequest }) {
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
    <div className="space-y-4">
      {(request.status === 'received' || pendingApproval) && (
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
      )}
      {error && <ErrorNote error={error} />}

      <section className="card p-4" aria-label="Processing status">
        <h3 className="eyebrow mb-3">Processing status</h3>
        <ol className="grid grid-cols-2 gap-x-3 gap-y-3 sm:grid-cols-4">
          {steps(request, run, approvals).map((step, i) => (
            <li key={step.label} className="flex items-start gap-2.5" aria-current={step.state === 'current' ? 'step' : undefined}>
              <span className={clsx('mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-bold tabular-nums', STEP_STYLE[step.state])}>
                {step.state === 'done' ? <Check aria-hidden className="h-3.5 w-3.5" strokeWidth={3} /> : step.state === 'failed' ? <X aria-hidden className="h-3.5 w-3.5" strokeWidth={3} /> : step.state === 'skipped' ? <MinusCircle aria-hidden className="h-3.5 w-3.5" /> : i + 1}
              </span>
              <span className="min-w-0 leading-tight">
                <span className="block text-[13px] font-semibold text-ink">{step.label}</span>
                <span className="block text-[12px] text-mute">{step.detail}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className="card p-4" aria-label="Extracted meeting details">
        <h3 className="eyebrow mb-2.5">Extracted meeting details</h3>
        {facts.length > 0 ? (
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {facts.map(([term, value]) => (
              <div key={term} className="flex gap-3 text-[13px]">
                <dt className="w-28 shrink-0 text-mute">{term}</dt>
                <dd className="min-w-0 flex-1 break-words text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-[13px] text-mute">{request.status === 'received' ? 'Nothing extracted yet. Process the request to have the secretary read it.' : 'No meeting details were extracted.'}</p>
        )}
      </section>

      <section className="card p-4" aria-label="Agent activity">
        <h3 className="eyebrow mb-2.5">Secretary activity</h3>
        {related.loading ? <SkeletonRows rows={2} /> : run ? <RunCard run={run} timeZone={tz} /> : <p className="text-[13px] text-mute">The secretary has not worked on this request yet.</p>}
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
    </div>
  );
}
