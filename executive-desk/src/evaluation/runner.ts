/**
 * The evaluation runner.
 *
 * It drives any EvaluationTarget (the mock today, Role 1's backend later) through a case:
 * start the run, poll it, play the human at approval gates, then score the result.
 * It works in the browser and in Node (scripts/eval.ts) and has no UI dependencies.
 */
import { ApiError, type EvaluationTarget } from '../api/client';
import {
  TERMINAL_RUN_STATUSES,
  type AgentRun,
  type ApprovalRequest,
  type EvaluationCase,
  type EvaluationError,
  type EvaluationReport,
  type EvaluationResult,
} from '../api/types';
import { DEFAULT_PRICE_TABLE, estimateCost, type PriceTable } from './pricing';
import { summarize } from './report';
import { scoreRun } from './scoring';

export const HARNESS_VERSION = '0.1.0';

export interface RunnerOptions {
  /** How often to poll a run that has not finished. */
  pollIntervalMs?: number;
  /** A case that has not reached a final status by then is recorded as an error. */
  timeoutMs?: number;
  /** Fail executed side effects that are not marked `simulated`. Leave on unless you mean it. */
  requireSimulated?: boolean;
  /** Name recorded on approval decisions the harness makes. */
  decidedBy?: string;
  pricing?: PriceTable;
  /** Injectable for tests. */
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
}

export interface EvaluationOptions extends RunnerOptions {
  label?: string;
  /** Case id -> reason. Skipped cases are listed in the report but not executed. */
  skip?: Record<string, string>;
  onProgress?: (progress: { done: number; total: number; current: string | null; last: EvaluationResult | null }) => void;
  signal?: AbortSignal;
}

class HarnessTimeout extends Error {}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function emptyResult(testCase: EvaluationCase, target: EvaluationTarget): EvaluationResult {
  const { expected } = testCase;
  return {
    caseId: testCase.id,
    caseTitle: testCase.title,
    category: testCase.category,
    dataSource: target.info.dataSource,
    verdict: 'skipped',
    checks: [],
    expected: {
      classification: expected.classifications.join(' or '),
      outcomes: expected.outcomes,
      tools: expected.toolCalls.map((t) => (Array.isArray(t.tool) ? t.tool.join(' | ') : t.tool)),
      approvals: expected.approvals.map((a) => (a.optional ? `${a.tool} (optional)` : a.tool)),
    },
    actual: { classification: null, outcome: null, runStatus: null, tools: [], approvals: [] },
    human: { mandatoryApprovals: 0, unexpectedApprovals: 0, rescued: false, interventions: [] },
    errors: [],
    timing: { startedAt: '', finishedAt: '', wallClockMs: 0, agentReportedMs: null },
    usage: null,
    estimatedCostUsd: null,
    costSource: null,
    run: null,
    approvals: [],
    skipReason: null,
  };
}

export async function runCase(target: EvaluationTarget, testCase: EvaluationCase, options: RunnerOptions = {}): Promise<EvaluationResult> {
  const now = options.now ?? Date.now;
  const sleep = options.sleep ?? defaultSleep;
  const pollIntervalMs = options.pollIntervalMs ?? 500;
  const timeoutMs = options.timeoutMs ?? 120_000;
  const decidedBy = options.decidedBy ?? 'evaluation-harness';

  const result = emptyResult(testCase, target);
  const startedMs = now();
  result.timing.startedAt = new Date(startedMs).toISOString();

  const expectedTools = new Set<string>(testCase.expected.approvals.map((a) => a.tool));
  const decided = new Set<string>();
  let run: AgentRun | null = null;
  let approvals: ApprovalRequest[] = [];
  const errors: EvaluationError[] = [];

  try {
    run = await target.startEvaluationRun({ caseId: testCase.id, input: testCase.input, context: testCase.context, mode: 'sandbox' });

    while (!TERMINAL_RUN_STATUSES.includes(run.status)) {
      if (run.status === 'awaiting_approval') {
        const pending = (await target.listApprovals({ runId: run.id, status: ['pending'] })).filter((a) => !decided.has(a.id));
        for (const approval of pending) {
          // The harness plays the human. An approval is mandatory when the case calls for every
          // side effect it covers; anything else is unexpected and gets rejected.
          const isExpected = approval.changes.every((change) => expectedTools.has(change.tool));
          await target.decideApproval(approval.id, {
            decision: isExpected ? testCase.expected.harnessDecision : 'reject',
            decidedBy,
            note: isExpected ? null : 'Rejected by the evaluation harness: this case does not call for this side effect.',
          });
          decided.add(approval.id);
          if (isExpected) result.human.mandatoryApprovals += 1;
          else result.human.unexpectedApprovals += 1;
        }
      }
      if (now() - startedMs > timeoutMs) throw new HarnessTimeout(`No final status after ${timeoutMs} ms (last status: ${run.status}).`);
      await sleep(pollIntervalMs);
      run = await target.getRun(run.id);
    }

    approvals = await target.listApprovals({ runId: run.id });
  } catch (cause) {
    if (cause instanceof HarnessTimeout) errors.push({ source: 'harness', code: 'timeout', message: cause.message });
    else if (cause instanceof ApiError) errors.push({ source: 'backend', code: cause.code, message: cause.message });
    else errors.push({ source: 'harness', code: 'exception', message: cause instanceof Error ? cause.message : String(cause) });
    result.verdict = 'error';
  }

  const finishedMs = now();
  result.timing.finishedAt = new Date(finishedMs).toISOString();
  result.timing.wallClockMs = finishedMs - startedMs;
  result.run = run;
  result.approvals = approvals;

  if (run) {
    result.timing.agentReportedMs = run.durationMs;
    result.usage = run.usage;
    const cost = estimateCost(run.usage, options.pricing ?? DEFAULT_PRICE_TABLE);
    result.estimatedCostUsd = cost.usd;
    result.costSource = cost.source;
    result.human.interventions = run.humanInterventions;
    result.human.rescued = run.humanInterventions.some((i) => i.kind !== 'approval');
    result.actual = {
      classification: run.triage?.classification ?? null,
      outcome: run.outcome,
      runStatus: run.status,
      tools: run.actions.filter((a) => a.status === 'succeeded' || a.status === 'failed').map((a) => (a.status === 'failed' ? `${a.tool} (failed)` : a.tool)),
      approvals: approvals.flatMap((a) => a.changes.map((c) => `${c.tool} (${a.status})`)),
    };
    // Tool and model errors are recorded even when the agent recovered from them.
    for (const action of run.actions) {
      if (action.error) errors.push({ source: action.error.source === 'model' ? 'model' : 'tool', code: action.error.code, message: `${action.tool}: ${action.error.message}` });
    }
    if (run.error) errors.push({ source: run.error.source === 'tool' ? 'tool' : run.error.source, code: run.error.code, message: run.error.message });
  }
  result.errors = errors;

  if (result.verdict !== 'error' && run) {
    if (run.status !== 'completed' && !testCase.expected.runStatuses.includes(run.status)) {
      // The run died where the case expects it to finish: an execution error, not a wrong answer.
      result.verdict = 'error';
      if (!run.error) errors.push({ source: 'backend', code: `run_${run.status}`, message: `The run ended as ${run.status} without an error object.` });
    } else {
      result.checks = scoreRun({ testCase, run, approvals, requireSimulated: options.requireSimulated ?? true });
      result.verdict = result.checks.every((c) => c.passed) ? 'pass' : 'fail';
    }
  }
  return result;
}

export async function runEvaluation(target: EvaluationTarget, cases: EvaluationCase[], options: EvaluationOptions = {}): Promise<EvaluationReport> {
  const now = options.now ?? Date.now;
  const startedAt = new Date(now()).toISOString();
  const results: EvaluationResult[] = [];

  for (const testCase of cases) {
    options.onProgress?.({ done: results.length, total: cases.length, current: testCase.id, last: results.at(-1) ?? null });
    const skipReason = options.signal?.aborted ? 'The evaluation was stopped before this case ran.' : options.skip?.[testCase.id];
    if (skipReason) {
      results.push({ ...emptyResult(testCase, target), skipReason });
      continue;
    }
    results.push(await runCase(target, testCase, options));
  }
  options.onProgress?.({ done: results.length, total: cases.length, current: null, last: results.at(-1) ?? null });

  return {
    id: `report-${startedAt.replace(/[^0-9]/g, '').slice(0, 14)}`,
    label: options.label ?? (target.info.dataSource === 'live' ? 'Evaluation run' : 'Harness self-test'),
    harnessVersion: HARNESS_VERSION,
    target: { name: target.info.name, dataSource: target.info.dataSource, baseUrl: target.info.baseUrl },
    startedAt,
    finishedAt: new Date(now()).toISOString(),
    results,
    summary: summarize(results),
  };
}
