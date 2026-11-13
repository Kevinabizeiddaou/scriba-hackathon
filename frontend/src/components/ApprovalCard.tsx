import clsx from 'clsx';
import { AlertTriangle, Check, ChevronDown, Info, RotateCcw, X } from 'lucide-react';
import { useId, useState } from 'react';
import { getApi } from '../harness';
import { summaryForChange } from '../harness/changes';
import type { AgentRun, ApprovalRequest } from '../harness/types';
import { STEP_STATE, executionSteps } from '../lib/executionSteps';
import { APPROVAL_STATUS, EXECUTION_STATUS } from '../lib/labels';
import { fmtDayTime } from '../lib/time';
import { ActionTimeline } from './ActionTimeline';
import { ChangePreview } from './ChangePreview';
import { Button, ErrorNote, Pill, SimulatedTag } from './ui';

interface Props {
  approval: ApprovalRequest;
  /** The run this approval belongs to, when the caller has it. Used to show what was executed. */
  run?: AgentRun;
  /** Where the request came from, e.g. the email subject. */
  origin?: { label: string; href: string } | null;
  compact?: boolean;
  highlighted?: boolean;
  /**
   * Starts the work again after a failed execution, when the caller knows how: by asking the
   * secretary to handle the request again, or by sending the chat message again. That produces a
   * new proposal that needs its own approval. Nothing is ever re-run from this card directly.
   */
  onRetry?: () => Promise<unknown>;
}

export function ApprovalCard({ approval, run, origin, compact = false, highlighted = false, onRetry }: Props) {
  const api = getApi();
  const { principal, dataSource } = api.info;
  const noteId = useId();
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [note, setNote] = useState('');
  const [noteOpen, setNoteOpen] = useState(false);

  const pending = approval.status === 'pending';
  const status = APPROVAL_STATUS[approval.status];
  const execution = EXECUTION_STATUS[approval.execution.status];
  const executed = run?.actions.filter((a) => a.approvalId === approval.id && a.tool !== 'approval.request') ?? [];
  const steps = executionSteps(approval, run);
  const multi = steps.length > 1;
  const doneCount = steps.filter((step) => step.state === 'done').length;
  const failedExecution = approval.status === 'approved' && approval.execution.status === 'failed';
  const [retrying, setRetrying] = useState(false);
  const [retried, setRetried] = useState(false);

  async function retry() {
    if (!onRetry) return;
    setRetrying(true);
    setError(null);
    try {
      await onRetry();
      setRetried(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setRetrying(false);
    }
  }

  async function decide(decision: 'approve' | 'reject') {
    setBusy(decision);
    setError(null);
    try {
      await api.decideApproval(approval.id, { decision, decidedBy: principal.name, note: note.trim() || null });
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(null);
    }
  }

  return (
    <article
      id={`approval-${approval.id}`}
      aria-label={`Approval: ${approval.title}`}
      className={clsx('card rise-in', compact ? 'p-4' : 'p-5', highlighted && 'ring-2 ring-accent/60', pending && 'border-warn/25')}
    >
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 className={clsx('font-semibold leading-6 text-ink', compact ? 'text-[15px]' : 'text-[17px]')}>{approval.title}</h2>
          <p className="mt-0.5 text-[12px] text-mute">
            Requested {fmtDayTime(approval.createdAt, principal.timezone)}
            {origin && (
              <>
                {' · from '}
                <a href={origin.href} className="tap inline-flex items-center font-medium text-accent hover:underline">
                  {origin.label}
                </a>
              </>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Pill tone={status.tone}>{status.label}</Pill>
          {approval.status === 'approved' && (
            <Pill tone={execution.tone} spin={approval.execution.status === 'executing'}>
              {execution.label}
            </Pill>
          )}
          {approval.execution.status === 'executed' && approval.execution.simulated && <SimulatedTag />}
        </div>
      </header>

      <div className="mt-3.5 flex gap-2.5 rounded-xl bg-white/[0.04] px-3.5 py-3">
        <Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
        <div className="min-w-0">
          <p className="eyebrow mb-0.5">Why the agent proposes this</p>
          <p className="text-[13.5px] leading-[21px] text-ink">{approval.explanation}</p>
        </div>
      </div>

      {approval.riskNotes.length > 0 && (
        <ul className="mt-2.5 space-y-1.5">
          {approval.riskNotes.map((risk) => (
            <li key={risk} className="flex gap-2.5 rounded-xl border border-warn/25 bg-warn/[0.07] px-3.5 py-2 text-[13px] text-warn">
              <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{risk}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3.5">
        <p className="eyebrow mb-2">
          {pending ? 'If you approve, the agent will' : approval.status === 'approved' ? 'What was approved' : 'What was proposed'}
          {approval.changes.length > 1 && pending && `, in this order`}
        </p>
        {multi && approval.status === 'approved' && (
          <div className="mb-2.5 flex items-center gap-3">
            <div
              role="progressbar"
              aria-label="Execution progress"
              aria-valuemin={0}
              aria-valuemax={steps.length}
              aria-valuenow={doneCount}
              aria-valuetext={`${doneCount} of ${steps.length} steps done`}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.08]"
            >
              <div className={clsx('h-full rounded-full transition-[width] duration-300', failedExecution ? 'bg-danger' : 'bg-ok')} style={{ width: `${(doneCount / steps.length) * 100}%` }} />
            </div>
            <span className="shrink-0 text-[12px] tabular-nums text-soft">
              {doneCount} of {steps.length} steps done
            </span>
          </div>
        )}
        <ol aria-label="Steps" className="space-y-2.5">
          {steps.map((step, i) => {
            const label = STEP_STATE[step.state];
            return (
              <li key={i}>
                {multi && (
                  <p className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-mute">
                    <span className="font-semibold tabular-nums text-soft">
                      Step {i + 1} of {steps.length}
                    </span>
                    {!pending && (
                      <Pill tone={label.tone} spin={step.state === 'running'}>
                        {label.label}
                      </Pill>
                    )}
                    {step.attempts > 1 && <span>{step.state === 'done' ? `Worked on attempt ${step.attempts}` : `${step.attempts} attempts`}</span>}
                  </p>
                )}
                <ChangePreview change={step.change} timeZone={principal.timezone} principalEmail={principal.email} />
              </li>
            );
          })}
        </ol>
      </div>

      {pending ? (
        <footer className="mt-4 border-t border-line pt-3.5">
          {error && (
            <div className="mb-3">
              <ErrorNote error={error} />
            </div>
          )}
          {noteOpen && (
            <div className="mb-3">
              <label htmlFor={noteId} className="mb-1 block text-[12px] font-medium text-soft">
                Note for the record (optional)
              </label>
              <textarea id={noteId} rows={2} value={note} onChange={(e) => setNote(e.target.value)} className="field resize-y text-[13px]" placeholder="For example: push this to next week instead." />
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <button type="button" onClick={() => setNoteOpen((open) => !open)} aria-expanded={noteOpen} className="tap inline-flex cursor-pointer items-center gap-1 rounded-md py-1 text-[12.5px] font-medium text-soft hover:text-ink">
              <ChevronDown aria-hidden className={clsx('h-3.5 w-3.5 transition-transform duration-150', noteOpen && 'rotate-180')} />
              {noteOpen ? 'Hide note' : 'Add a note'}
            </button>
            <div className="flex items-center gap-2">
              <Button variant="danger" icon={X} busy={busy === 'reject'} disabled={busy !== null} onClick={() => decide('reject')}>
                Reject
              </Button>
              <Button variant="primary" icon={Check} busy={busy === 'approve'} disabled={busy !== null} onClick={() => decide('approve')}>
                Approve{approval.changes.length > 1 ? ` all ${approval.changes.length}` : ''}
              </Button>
            </div>
          </div>
          {dataSource === 'simulated' && <p className="mt-2.5 text-right text-[11.5px] text-mute">Mock mode: approving only simulates these steps. Nothing leaves this browser.</p>}
        </footer>
      ) : (
        <footer className="mt-4 space-y-3 border-t border-line pt-3.5">
          <p className="text-[12.5px] text-soft">
            {approval.status === 'approved' ? 'Approved' : approval.status === 'rejected' ? 'Rejected' : 'Expired'}
            {approval.decidedBy && ` by ${approval.decidedBy}`}
            {approval.decidedAt && `, ${fmtDayTime(approval.decidedAt, principal.timezone)}`}
            {approval.status === 'rejected' && '. Nothing was sent and the calendar was not changed.'}
            {approval.decisionNote && <span className="mt-1 block text-mute">Note: {approval.decisionNote}</span>}
          </p>
          {failedExecution && (
            <div role="alert" className="rounded-xl border border-danger/25 bg-danger/[0.07] px-3.5 py-3">
              <p className="text-[13px] font-semibold text-danger">This did not complete{approval.execution.error ? `: ${approval.execution.error.message}` : '.'}</p>
              <ul className="mt-2 space-y-1 text-[12.5px] text-soft">
                {steps.map((step, i) => (
                  <li key={i}>
                    <span className={clsx('font-semibold', step.state === 'done' ? 'text-ok' : step.state === 'failed' ? 'text-danger' : 'text-soft')}>{step.state === 'done' ? 'Done' : step.state === 'failed' ? 'Failed' : 'Not run'}:</span>{' '}
                    {summaryForChange(step.change, step.state === 'done' ? 'past' : 'future')}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[12.5px] text-soft">
                Nothing is repeated automatically, so nothing can be sent or booked twice. {onRetry ? 'Trying again makes a new proposal that you approve before anything runs.' : origin ? 'Open where this came from to pick it up again.' : ''}
              </p>
              {error && (
                <div className="mt-2">
                  <ErrorNote error={error} />
                </div>
              )}
              {(onRetry || origin) && (
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  {onRetry &&
                    (retried ? (
                      <span className="text-[12.5px] font-medium text-ok">Started again. A new proposal will appear for your approval.</span>
                    ) : (
                      <Button variant="secondary" icon={RotateCcw} busy={retrying} onClick={retry}>
                        Try again
                      </Button>
                    ))}
                  {origin && (
                    <a href={origin.href} className="tap inline-flex items-center text-[12.5px] font-medium text-accent hover:underline">
                      Open {origin.label}
                    </a>
                  )}
                </div>
              )}
            </div>
          )}
          {executed.length > 0 && !compact && (
            <div>
              <p className="eyebrow mb-2">Execution</p>
              <ActionTimeline actions={executed} timeZone={principal.timezone} />
            </div>
          )}
        </footer>
      )}
    </article>
  );
}
