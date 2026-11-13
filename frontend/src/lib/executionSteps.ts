/**
 * Relates each change a human approved to the tool call that carried it out, so the approval
 * card can show, step by step, what ran, what failed and what was never attempted.
 */
import { EXECUTED_ACTION_STATUSES, type AgentRun, type ApprovalRequest, type ProposedChange } from '../harness/types';
import type { Tone } from './labels';

export type StepState = 'proposed' | 'queued' | 'running' | 'done' | 'failed' | 'not_run';

export interface ExecutionStep {
  change: ProposedChange;
  state: StepState;
  /** How many times the tool call went out. More than one means it was retried. */
  attempts: number;
  error: string | null;
  simulated: boolean;
}

export const STEP_STATE: Record<StepState, { label: string; tone: Tone }> = {
  proposed: { label: 'Proposed', tone: 'neutral' },
  queued: { label: 'Up next', tone: 'neutral' },
  running: { label: 'Running', tone: 'info' },
  done: { label: 'Done', tone: 'ok' },
  failed: { label: 'Failed', tone: 'danger' },
  not_run: { label: 'Not run', tone: 'neutral' },
};

export function executionSteps(approval: ApprovalRequest, run: AgentRun | undefined): ExecutionStep[] {
  const mine = run?.actions.filter((a) => a.approvalId === approval.id && a.tool !== 'approval.request') ?? [];

  return approval.changes.map((change, index) => {
    const base = { change, attempts: 0, error: null, simulated: false };
    if (approval.status === 'pending') return { ...base, state: 'proposed' as const };
    if (approval.status !== 'approved') return { ...base, state: 'not_run' as const };

    // One change per tool is the usual case: its latest call is the one that counts, and earlier
    // calls are retries. With several changes for the same tool, they pair up in order.
    const sameTool = mine.filter((a) => a.tool === change.tool);
    const alone = approval.changes.filter((c) => c.tool === change.tool).length === 1;
    const action = alone ? sameTool.at(-1) : sameTool[approval.changes.slice(0, index).filter((c) => c.tool === change.tool).length];
    const attempts = alone ? sameTool.filter((a) => EXECUTED_ACTION_STATUSES.includes(a.status)).length : action && EXECUTED_ACTION_STATUSES.includes(action.status) ? 1 : 0;

    if (!action) {
      // Without the run there is only the approval's own word for it.
      const state: StepState = approval.execution.status === 'executed' ? 'done' : approval.execution.status === 'failed' ? 'not_run' : 'queued';
      return { ...base, state, simulated: approval.execution.simulated };
    }
    const state: StepState =
      action.status === 'succeeded' ? 'done' : action.status === 'failed' ? 'failed' : action.status === 'running' ? 'running' : action.status === 'skipped' || action.status === 'rejected' ? 'not_run' : 'queued';
    return { change, state, attempts, error: action.error?.message ?? null, simulated: action.simulated };
  });
}
