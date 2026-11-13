/**
 * The evaluation runner.
 *
 * It drives any EvaluationTarget (the mock today, Role 1's backend later) through a case:
 * start the run, poll it, play the human at approval gates, then score the result.
 * It works in the browser and in Node (scripts/eval.ts) and has no UI dependencies.
 *
 * The runner assumes the target may be wrong or hostile to the contract. It only ever decides
 * approvals that belong to the run it started, it puts a deadline on every call, and it records
 * what it saw and did itself so the scorer does not have to take the backend's word for it.
 */
import { ApiError, type EvaluationTarget } from '../harness/client';
import {
  CONTRACT_VERSION,
  EXECUTED_ACTION_STATUSES,
  REPORT_FORMAT,
  TERMINAL_RUN_STATUSES,
  isSideEffectTool,
  type AgentRun,
  type ApprovalRequest,
  type CaseSetInfo,
  type DataSource,
  type DeskMeta,
  type EvaluationCase,
  type EvaluationError,
  type EvaluationReport,
  type EvaluationResult,
} from '../harness/types';
import { DEFAULT_PRICE_TABLE, estimateCost, type PriceTable } from './pricing';
import { summarize } from './report';
import { scoreRun, type HarnessObservations } from './scoring';

export const HARNESS_VERSION = '1.0.0';

export interface RunnerOptions {
  /** How often to poll a run that has not finished. */
  pollIntervalMs?: number;
  /** Budget for one case, start to final status. Every call to the target is cut off when it runs out. */
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
  /** Identifies the full case set. Defaults to an ad-hoc set made of exactly the cases passed in. */
  caseSet?: CaseSetInfo;
  /** Case id -> reason. Skipped cases are listed in the report but not executed. */
  skip?: Record<string, string>;
  onProgress?: (progress: { done: number; total: number; current: string | null; last: EvaluationResult | null }) => void;
  signal?: AbortSignal;
}

class HarnessTimeout extends Error {}

/** The harness declines to run a case against this target. */
class HarnessRefusal extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

const dataSourceOf = (meta: DeskMeta): DataSource => (meta.agent === 'real' ? 'live' : 'simulated');

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Rejects if `promise` has not settled within `ms`. The underlying call is abandoned, not cancelled. */
function withDeadline<T>(promise: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new HarnessTimeout(`${what} did not answer within the case time budget.`)), Math.max(ms, 0));
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function emptyResult(testCase: EvaluationCase, dataSource: DataSource): EvaluationResult {
  const { expected } = testCase;
  return {
    caseId: testCase.id,
    caseTitle: testCase.title,
    category: testCase.category,
    area: testCase.area,
    provenance: testCase.provenance.kind,
    dataSource,
    verdict: 'skipped',
    checks: [],
    expected: {
      classification: expected.classifications.join(' or '),
      outcomes: expected.outcomes,
      tools: expected.toolCalls.map((t) => (Array.isArray(t.tool) ? t.tool.join(' | ') : t.tool)),
      approvals: expected.approvals.map((a) => (a.optional ? `${a.tool} (optional)` : a.tool)),
    },
    actual: { classification: null, outcome: null, runStatus: null, tools: [], approvals: [] },
    human: { mandatoryApprovals: 0, unexpectedApprovals: 0, foreignApprovals: 0, rescued: false, interventions: [] },
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

  const result = emptyResult(testCase, target.info.dataSource);
  const startedMs = now();
  result.timing.startedAt = new Date(startedMs).toISOString();

  const expectedTools = new Set<string>(testCase.expected.approvals.map((a) => a.tool));
  const observed: HarnessObservations = { decisions: {}, foreignApprovals: [], earlyExecutions: [] };
  const errors: EvaluationError[] = [];
  let run: AgentRun | null = null;
  let approvals: ApprovalRequest[] | null = null;
  let harnessFailed = false;

  /** Calls the target with whatever is left of the case budget as its deadline. */
  const call = <T>(what: string, start: () => Promise<T>): Promise<T> => {
    const left = timeoutMs - (now() - startedMs);
    if (left <= 0) throw new HarnessTimeout(`No final status after ${timeoutMs} ms (last status: ${run?.status ?? 'not started'}).`);
    return withDeadline(start(), left, what);
  };

  /** Keeps only this run's approvals. Anything else the backend returned is recorded and left untouched. */
  const own = (list: ApprovalRequest[], runId: string): ApprovalRequest[] => {
    for (const approval of list) {
      if (approval.runId !== runId && !observed.foreignApprovals.includes(approval.id)) observed.foreignApprovals.push(approval.id);
    }
    return list.filter((approval) => approval.runId === runId);
  };

  try {
    // The handshake decides how the result is labelled and whether the case may run at all.
    const meta = await call('Reading the backend description', () => target.getMeta());
    result.dataSource = dataSourceOf(meta);
    if (!meta.capabilities.evaluation) throw new HarnessRefusal('evaluation_unsupported', 'The backend reports that it has no evaluation endpoint.');
    if ((options.requireSimulated ?? true) && !meta.sandbox) {
      throw new HarnessRefusal('not_sandbox', 'The backend reports sandbox: false. Evaluation cases are not run against a service that can reach real mailboxes or calendars.');
    }
    if (testCase.context.faults.length > 0 && !meta.capabilities.faultInjection) {
      result.timing.finishedAt = result.timing.startedAt;
      result.skipReason = 'The backend does not support fault injection, which this case needs.';
      return result;
    }

    run = await call('Starting the run', () => target.startEvaluationRun({ caseId: testCase.id, input: testCase.input, context: testCase.context, mode: 'sandbox' }));
    const runId = run.id;

    while (!TERMINAL_RUN_STATUSES.includes(run.status)) {
      if (run.status === 'awaiting_approval') {
        const pending = own(await call('Listing approvals', () => target.listApprovals({ runId, status: ['pending'] })), runId).filter(
          (approval) => approval.status === 'pending' && !(approval.id in observed.decisions),
        );
        for (const approval of pending) {
          // Anything this approval gates must not have run yet. Checked here, at the moment of
          // decision, because it does not depend on comparing two clocks.
          for (const action of run.actions ?? []) {
            if (action.approvalId === approval.id && isSideEffectTool(action.tool) && EXECUTED_ACTION_STATUSES.includes(action.status)) {
              observed.earlyExecutions.push(`${action.tool} (${action.id}) had already run while approval ${approval.id} was still pending`);
            }
          }
          // The harness plays the human. An approval is mandatory when the case calls for every
          // side effect it covers; anything else is unexpected and gets rejected.
          const isExpected = (approval.changes ?? []).length > 0 && approval.changes.every((change) => expectedTools.has(change.tool));
          const decision = isExpected ? testCase.expected.harnessDecision : 'reject';
          await call('Deciding an approval', () =>
            target.decideApproval(approval.id, {
              decision,
              decidedBy,
              note: isExpected ? null : 'Rejected by the evaluation harness: this case does not call for this side effect.',
            }),
          );
          observed.decisions[approval.id] = decision;
          if (isExpected) result.human.mandatoryApprovals += 1;
          else result.human.unexpectedApprovals += 1;
        }
      }
      if (now() - startedMs > timeoutMs) throw new HarnessTimeout(`No final status after ${timeoutMs} ms (last status: ${run.status}).`);
      await sleep(pollIntervalMs);
      run = await call('Reading the run', () => target.getRun(runId));
    }
  } catch (cause) {
    harnessFailed = true;
    if (cause instanceof HarnessTimeout) errors.push({ source: 'harness', code: 'timeout', message: cause.message });
    else if (cause instanceof HarnessRefusal) errors.push({ source: 'harness', code: cause.code, message: cause.message });
    else if (cause instanceof ApiError) errors.push({ source: 'backend', code: cause.code, message: cause.message });
    else errors.push({ source: 'harness', code: 'exception', message: cause instanceof Error ? cause.message : String(cause) });
  }

  if (run) {
    // Needed for scoring even after a timeout, so this one call gets a short budget of its own.
    const runId = run.id;
    try {
      approvals = own(await withDeadline(target.listApprovals({ runId }), Math.min(timeoutMs, 10_000), 'Listing approvals'), runId);
    } catch (cause) {
      errors.push({ source: 'backend', code: cause instanceof ApiError ? cause.code : 'approvals_unavailable', message: `Could not load the run's approvals, so it was not scored: ${cause instanceof Error ? cause.message : String(cause)}` });
    }
  }

  const finishedMs = now();
  result.timing.finishedAt = new Date(finishedMs).toISOString();
  result.timing.wallClockMs = finishedMs - startedMs;
  result.run = run;
  result.approvals = approvals ?? [];
  result.human.foreignApprovals = observed.foreignApprovals.length;

  if (run) {
    const interventions = Array.isArray(run.humanInterventions) ? run.humanInterventions : [];
    result.timing.agentReportedMs = typeof run.durationMs === 'number' ? run.durationMs : null;
    result.usage = run.usage ?? null;
    const cost = estimateCost(result.usage, options.pricing ?? DEFAULT_PRICE_TABLE);
    result.estimatedCostUsd = cost.usd;
    result.costSource = cost.source;
    result.human.interventions = interventions;
    result.human.rescued = interventions.some((i) => i.kind !== 'approval');
    result.actual = {
      classification: run.triage?.classification ?? null,
      outcome: run.outcome ?? null,
      runStatus: run.status,
      tools: (run.actions ?? []).filter((a) => a.status === 'succeeded' || a.status === 'failed').map((a) => (a.status === 'failed' ? `${a.tool} (failed)` : a.tool)),
      approvals: (approvals ?? []).flatMap((a) => (a.changes ?? []).map((c) => `${c.tool} (${a.status})`)),
    };
    // Tool and model errors are recorded even when the agent recovered from them.
    for (const action of run.actions ?? []) {
      if (action.error) errors.push({ source: action.error.source === 'model' ? 'model' : 'tool', code: action.error.code, message: `${action.tool}: ${action.error.message}` });
    }
    if (run.error) errors.push({ source: run.error.source, code: run.error.code, message: run.error.message });
  }

  // "Could not be scored" means the run did not end the way the case allows: it died, hung,
  // or the harness lost contact with the backend.
  const endedWrong = harnessFailed || !run || !TERMINAL_RUN_STATUSES.includes(run.status) || (run.status !== 'completed' && !testCase.expected.runStatuses.includes(run.status));
  if (run && endedWrong && !harnessFailed && !run.error) {
    errors.push({ source: 'backend', code: `run_${run.status}`, message: `The run ended as ${run.status} without an error object.` });
  }

  if (run && approvals) {
    try {
      result.checks = scoreRun({ testCase, run, approvals, harness: observed, requireSimulated: options.requireSimulated ?? true });
    } catch (cause) {
      // A malformed trace must cost one case, not the whole evaluation.
      harnessFailed = true;
      errors.push({ source: 'harness', code: 'scoring_exception', message: `The run could not be scored: ${cause instanceof Error ? cause.message : String(cause)}` });
    }
  }
  result.errors = errors;

  // A safety violation is a failure whatever else happened: an unapproved email followed by a
  // crash is not merely "an error".
  const safetyFailed = result.checks.some((c) => c.safety && !c.passed);
  if (safetyFailed) result.verdict = 'fail';
  else if (endedWrong || harnessFailed || !approvals) result.verdict = 'error';
  else result.verdict = result.checks.every((c) => c.passed) ? 'pass' : 'fail';
  return result;
}

export async function runEvaluation(target: EvaluationTarget, cases: EvaluationCase[], options: EvaluationOptions = {}): Promise<EvaluationReport> {
  const now = options.now ?? Date.now;
  const startedAt = new Date(now()).toISOString();
  const results: EvaluationResult[] = [];

  // Synthetic fixtures and real-world cases are reported separately, never as one number.
  const kinds = new Set(cases.map((c) => c.provenance.kind));
  if (kinds.size > 1) throw new Error('A case set must not mix synthetic and real-world cases. Run them as two evaluations.');
  const provenance = cases[0]?.provenance.kind ?? 'synthetic';
  if (options.caseSet && options.caseSet.provenance !== provenance) {
    throw new Error(`The case set is declared as ${options.caseSet.provenance}, but its cases are ${provenance}.`);
  }

  let meta: DeskMeta | null = null;
  try {
    meta = await withDeadline(target.getMeta(), options.timeoutMs ?? 120_000, 'Reading the backend description');
  } catch {
    // Every case will report the failure itself; the report is then labelled from what is known locally.
  }
  const dataSource = meta ? dataSourceOf(meta) : target.info.dataSource;

  for (const testCase of cases) {
    options.onProgress?.({ done: results.length, total: cases.length, current: testCase.id, last: results.at(-1) ?? null });
    const skipReason = options.signal?.aborted ? 'The evaluation was stopped before this case ran.' : options.skip?.[testCase.id];
    if (skipReason) {
      results.push({ ...emptyResult(testCase, dataSource), skipReason });
      continue;
    }
    results.push(await runCase(target, testCase, options));
  }
  options.onProgress?.({ done: results.length, total: cases.length, current: null, last: results.at(-1) ?? null });

  return {
    format: REPORT_FORMAT,
    id: `report-${startedAt.replace(/[^0-9]/g, '').slice(0, 14)}`,
    label: options.label ?? (dataSource === 'live' ? 'Evaluation run' : 'Scripted run (simulated)'),
    harnessVersion: HARNESS_VERSION,
    contractVersion: CONTRACT_VERSION,
    caseSet: options.caseSet ?? { id: 'ad-hoc', provenance, caseCount: cases.length },
    target: {
      name: meta?.service ?? target.info.name,
      dataSource,
      baseUrl: target.info.baseUrl,
      contractVersion: meta?.contractVersion ?? null,
      sandbox: meta?.sandbox ?? null,
    },
    startedAt,
    finishedAt: new Date(now()).toISOString(),
    results,
    summary: summarize(results),
  };
}
