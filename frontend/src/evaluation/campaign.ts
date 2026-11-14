/**
 * Reliability campaigns: the same cases run several times, and one run compared with another.
 *
 * One pass over twenty cases says little about an agent that is not deterministic. A campaign
 * repeats the suite and reports, per case, how often it passed, how it failed when it failed,
 * and what it cost. A comparison sets two reports side by side and says which cases were fixed,
 * which regressed, and which checks changed.
 *
 * Two rules, enforced here and not left to the caller:
 *   - reports are only combined or compared when they cover the same case set and come from the
 *     same kind of target. A scripted reference run is never mixed with a real-agent run;
 *   - everything derived from a scripted target is labelled as that. It shows that the harness
 *     and the cases agree with each other, and says nothing about the agent.
 */
import type { DataSource, DeskArea, EvaluationReport, EvaluationResult } from '../harness/types';

// ── how a case failed ───────────────────────────────────────────────────────

export const FAILURE_CLASSES = [
  'unapproved_or_wrong_write',
  'duplicate_operation',
  'double_booking',
  'unknown_recipient',
  'information_leak',
  'left_sandbox',
  'forbidden_action',
  'wrong_outcome',
  'wrong_final_state',
  'missing_or_wrong_tool_call',
  'wrong_order',
  'approval_mismatch',
  'triage',
  'wording',
  'bad_slot_or_time',
  'timeout',
  'error',
  'other',
] as const;
export type FailureClass = (typeof FAILURE_CLASSES)[number];

export const FAILURE_LABEL: Record<FailureClass, string> = {
  unapproved_or_wrong_write: 'Wrote without approval, or not what was approved',
  duplicate_operation: 'Did the same thing twice',
  double_booking: 'Booked over another event',
  unknown_recipient: 'Emailed or invited someone unknown',
  information_leak: 'Named a meeting to an outsider',
  left_sandbox: 'A write left the sandbox',
  forbidden_action: 'Did or proposed something the case forbids',
  wrong_outcome: 'Wrong outcome',
  wrong_final_state: 'Wrong state afterwards',
  missing_or_wrong_tool_call: 'Missing or wrong tool call',
  wrong_order: 'Steps in the wrong order',
  approval_mismatch: 'Asked approval for the wrong things',
  triage: 'Wrong classification, priority or flag',
  wording: 'Wording of the email or reply',
  bad_slot_or_time: 'Bad time: no offset, past, or outside working hours',
  timeout: 'Did not finish in time',
  error: 'Could not be scored',
  other: 'Other',
};

/** Failure classes that mean something was written that should not have been. */
const INCORRECT_WRITE: readonly FailureClass[] = ['unapproved_or_wrong_write', 'double_booking', 'unknown_recipient', 'left_sandbox'];

function classOfCheck(id: string, actual: string): FailureClass {
  if (id === 'approval_gate') return /more than once/.test(actual) ? 'duplicate_operation' : 'unapproved_or_wrong_write';
  if (id === 'idempotency') return 'duplicate_operation';
  if (id === 'no_double_booking') return 'double_booking';
  if (id === 'known_recipients') return 'unknown_recipient';
  if (id === 'no_calendar_leak') return 'information_leak';
  if (id === 'sandbox_only') return 'left_sandbox';
  if (id === 'timestamps_valid' || id === 'proposed_slots') return 'bad_slot_or_time';
  if (id === 'approvals_scoped') return 'approval_mismatch';
  if (id.startsWith('forbidden:')) return 'forbidden_action';
  if (id === 'outcome' || id === 'outcome_consistent' || id === 'run_status') return 'wrong_outcome';
  if (id.startsWith('state:')) return 'wrong_final_state';
  if (id.startsWith('tool:')) return 'missing_or_wrong_tool_call';
  if (id.startsWith('order:')) return 'wrong_order';
  if (id === 'approvals_expected') return 'approval_mismatch';
  if (id === 'classification' || id === 'priority' || id === 'flags') return 'triage';
  if (id.startsWith('email:') || id.startsWith('chat:')) return 'wording';
  return 'other';
}

/** Why a result is not a clean pass. Empty for a pass or a skipped case. Each class appears once. */
export function classifyFailure(result: EvaluationResult): FailureClass[] {
  if (result.verdict === 'pass' || result.verdict === 'skipped') return [];
  const classes = new Set<FailureClass>();
  for (const check of result.checks) if (!check.passed) classes.add(classOfCheck(check.id, check.actual));
  if (result.verdict === 'error') classes.add(result.errors.some((error) => error.code === 'timeout') ? 'timeout' : 'error');
  if (classes.size === 0) classes.add('other');
  return FAILURE_CLASSES.filter((name) => classes.has(name));
}

export const hasSafetyViolation = (result: EvaluationResult): boolean => result.checks.some((check) => check.safety && !check.passed);
export const hasIncorrectWrite = (result: EvaluationResult): boolean => classifyFailure(result).some((name) => INCORRECT_WRITE.includes(name));
export const hasDuplicateOperation = (result: EvaluationResult): boolean => classifyFailure(result).includes('duplicate_operation');
const cleanPass = (result: EvaluationResult): boolean => result.verdict === 'pass' && !result.human.rescued;

// ── reports that may be combined ────────────────────────────────────────────

export class CampaignError extends Error {}

function sameKind(reports: EvaluationReport[]): { caseSetId: string; dataSource: DataSource } {
  if (reports.length === 0) throw new CampaignError('No reports were given.');
  const [first] = reports;
  for (const report of reports) {
    if (report.caseSet.id !== first.caseSet.id) {
      throw new CampaignError(`Reports cover different case sets (${first.caseSet.id} and ${report.caseSet.id}). They cannot be combined or compared.`);
    }
    if (report.target.dataSource !== first.target.dataSource) {
      throw new CampaignError('A scripted reference run and a real-agent run cannot be combined or compared: one is a check of the harness, the other a result about the agent.');
    }
  }
  return { caseSetId: first.caseSet.id, dataSource: first.target.dataSource };
}

/** The sentence that goes on top of anything built from these reports. */
export function kindNotice(dataSource: DataSource): string {
  return dataSource === 'live'
    ? 'Real-agent runs. A pass counts only when no person had to rescue the run.'
    : 'Scripted reference runs, not the agent. They show that the cases and the scorer agree with each other. No pass rate is derived from them.';
}

// ── a campaign: the same cases, several runs ────────────────────────────────

export type Stability = 'always_passed' | 'always_failed' | 'flaky' | 'not_run';

export interface CaseCampaign {
  caseId: string;
  title: string;
  area: DeskArea;
  /** Runs in which the case was executed (not skipped). */
  executed: number;
  /** Passed with no rescue. */
  passed: number;
  rescued: number;
  failed: number;
  errored: number;
  skipped: number;
  stability: Stability;
  /** How often each failure class occurred, over the executed runs. */
  failureClasses: Partial<Record<FailureClass, number>>;
  safetyViolations: number;
  incorrectWrites: number;
  duplicateOperations: number;
  mandatoryApprovals: number;
  medianWallClockMs: number | null;
  /** Null when no run of this case reported usage. */
  inputTokens: number | null;
  outputTokens: number | null;
  /** Null unless every executed run of this case was priced. */
  costUsd: number | null;
}

export interface Campaign {
  caseSetId: string;
  dataSource: DataSource;
  runs: number;
  reportIds: string[];
  cases: CaseCampaign[];
  totals: {
    caseRuns: number;
    passed: number;
    rescued: number;
    failed: number;
    errored: number;
    skipped: number;
    safetyViolations: number;
    incorrectWrites: number;
    duplicateOperations: number;
    mandatoryApprovals: number;
    flakyCases: number;
    /** Cases that passed unassisted in every run they were executed in. */
    reliableCases: number;
    /** Sum of the reports' wall-clock time. */
    totalRuntimeMs: number;
    /** Null unless at least one run reported usage. */
    inputTokens: number | null;
    outputTokens: number | null;
    /** Null unless every executed case run was priced. A partial sum would understate the cost. */
    costUsd: number | null;
    costPerCaseRunUsd: number | null;
  };
}

const median = (values: number[]): number | null => {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};

const tokens = (result: EvaluationResult) =>
  result.usage ? result.usage.models.reduce((sum, model) => ({ input: sum.input + model.inputTokens + (model.cachedInputTokens ?? 0), output: sum.output + model.outputTokens }), { input: 0, output: 0 }) : null;

export function aggregateCampaign(reports: EvaluationReport[]): Campaign {
  const { caseSetId, dataSource } = sameKind(reports);
  const order: string[] = [];
  const byCase = new Map<string, EvaluationResult[]>();
  for (const report of reports) {
    for (const result of report.results) {
      if (!byCase.has(result.caseId)) {
        byCase.set(result.caseId, []);
        order.push(result.caseId);
      }
      byCase.get(result.caseId)!.push(result);
    }
  }

  const cases: CaseCampaign[] = order.map((caseId) => {
    const results = byCase.get(caseId)!;
    const executed = results.filter((result) => result.verdict !== 'skipped');
    const passed = executed.filter(cleanPass).length;
    const failureClasses: Partial<Record<FailureClass, number>> = {};
    for (const result of executed) for (const name of classifyFailure(result)) failureClasses[name] = (failureClasses[name] ?? 0) + 1;
    const used = executed.map(tokens).filter((value): value is { input: number; output: number } => value !== null);
    const priced = executed.filter((result) => typeof result.estimatedCostUsd === 'number');
    return {
      caseId,
      title: results[0].caseTitle,
      area: results[0].area,
      executed: executed.length,
      passed,
      rescued: executed.filter((result) => result.verdict === 'pass' && result.human.rescued).length,
      failed: executed.filter((result) => result.verdict === 'fail').length,
      errored: executed.filter((result) => result.verdict === 'error').length,
      skipped: results.length - executed.length,
      stability: executed.length === 0 ? 'not_run' : passed === executed.length ? 'always_passed' : passed === 0 ? 'always_failed' : 'flaky',
      failureClasses,
      safetyViolations: executed.filter(hasSafetyViolation).length,
      incorrectWrites: executed.filter(hasIncorrectWrite).length,
      duplicateOperations: executed.filter(hasDuplicateOperation).length,
      mandatoryApprovals: executed.reduce((sum, result) => sum + result.human.mandatoryApprovals, 0),
      medianWallClockMs: median(executed.filter((result) => result.verdict !== 'error').map((result) => result.timing.wallClockMs)),
      inputTokens: used.length ? used.reduce((sum, value) => sum + value.input, 0) : null,
      outputTokens: used.length ? used.reduce((sum, value) => sum + value.output, 0) : null,
      costUsd: executed.length > 0 && priced.length === executed.length ? priced.reduce((sum, result) => sum + (result.estimatedCostUsd ?? 0), 0) : null,
    };
  });

  const sum = (pick: (item: CaseCampaign) => number) => cases.reduce((total, item) => total + pick(item), 0);
  const caseRuns = sum((item) => item.executed);
  const allPriced = caseRuns > 0 && cases.every((item) => item.executed === 0 || item.costUsd !== null);
  const costUsd = allPriced ? cases.reduce((total, item) => total + (item.costUsd ?? 0), 0) : null;
  const anyTokens = cases.some((item) => item.inputTokens !== null);
  return {
    caseSetId,
    dataSource,
    runs: reports.length,
    reportIds: reports.map((report) => report.id),
    cases,
    totals: {
      caseRuns,
      passed: sum((item) => item.passed),
      rescued: sum((item) => item.rescued),
      failed: sum((item) => item.failed),
      errored: sum((item) => item.errored),
      skipped: sum((item) => item.skipped),
      safetyViolations: sum((item) => item.safetyViolations),
      incorrectWrites: sum((item) => item.incorrectWrites),
      duplicateOperations: sum((item) => item.duplicateOperations),
      mandatoryApprovals: sum((item) => item.mandatoryApprovals),
      flakyCases: cases.filter((item) => item.stability === 'flaky').length,
      reliableCases: cases.filter((item) => item.stability === 'always_passed').length,
      totalRuntimeMs: reports.reduce((total, report) => total + Math.max(0, Date.parse(report.finishedAt) - Date.parse(report.startedAt)), 0),
      inputTokens: anyTokens ? sum((item) => item.inputTokens ?? 0) : null,
      outputTokens: anyTokens ? sum((item) => item.outputTokens ?? 0) : null,
      costUsd,
      costPerCaseRunUsd: costUsd !== null ? costUsd / caseRuns : null,
    },
  };
}

// ── one run against another ─────────────────────────────────────────────────

export type CaseChange = 'fixed' | 'regressed' | 'still_passing' | 'still_failing' | 'now_needs_rescue' | 'no_longer_needs_rescue' | 'added' | 'removed' | 'not_comparable';

export interface CaseComparison {
  caseId: string;
  title: string;
  area: DeskArea | null;
  change: CaseChange;
  before: string;
  after: string;
  /** Checks that passed before and fail now. */
  newlyFailing: string[];
  /** Checks that failed before and pass now. */
  newlyPassing: string[];
  /** A safety check fails now that did not fail before. */
  newSafetyViolation: boolean;
}

export interface Comparison {
  caseSetId: string;
  dataSource: DataSource;
  base: { id: string; label: string };
  candidate: { id: string; label: string };
  cases: CaseComparison[];
  counts: Record<CaseChange, number>;
  /** Passed unassisted, of executed. Counts, so a scripted target is not given a rate by accident. */
  passed: { before: number; after: number; executedBefore: number; executedAfter: number };
  safetyViolations: { before: number; after: number };
  costPerRunUsd: { before: number | null; after: number | null };
  medianLatencyMs: { before: number | null; after: number | null };
}

const verdictWord = (result: EvaluationResult | undefined): string =>
  !result ? 'absent' : result.verdict === 'pass' ? (result.human.rescued ? 'pass with rescue' : 'pass') : result.verdict;

export function compareReports(base: EvaluationReport, candidate: EvaluationReport): Comparison {
  const { caseSetId, dataSource } = sameKind([base, candidate]);
  const before = new Map(base.results.map((result) => [result.caseId, result]));
  const after = new Map(candidate.results.map((result) => [result.caseId, result]));
  const ids = [...new Set([...before.keys(), ...after.keys()])];

  const cases: CaseComparison[] = ids.map((caseId) => {
    const b = before.get(caseId);
    const a = after.get(caseId);
    const failedBefore = new Set((b?.checks ?? []).filter((check) => !check.passed).map((check) => check.id));
    const failedAfter = new Set((a?.checks ?? []).filter((check) => !check.passed).map((check) => check.id));
    let change: CaseChange;
    if (!b) change = 'added';
    else if (!a) change = 'removed';
    else if (b.verdict === 'skipped' || a.verdict === 'skipped') change = 'not_comparable';
    else if (b.verdict === 'pass' && a.verdict === 'pass') change = b.human.rescued === a.human.rescued ? 'still_passing' : a.human.rescued ? 'now_needs_rescue' : 'no_longer_needs_rescue';
    else if (b.verdict === 'pass') change = 'regressed';
    else if (a.verdict === 'pass') change = 'fixed';
    else change = 'still_failing';
    return {
      caseId,
      title: (a ?? b)!.caseTitle,
      area: (a ?? b)!.area ?? null,
      change,
      before: verdictWord(b),
      after: verdictWord(a),
      newlyFailing: b && a ? [...failedAfter].filter((id) => !failedBefore.has(id)) : [],
      newlyPassing: b && a ? [...failedBefore].filter((id) => !failedAfter.has(id)) : [],
      newSafetyViolation: !!a && a.checks.some((check) => check.safety && !check.passed && !failedBefore.has(check.id)),
    };
  });

  const counts = { fixed: 0, regressed: 0, still_passing: 0, still_failing: 0, now_needs_rescue: 0, no_longer_needs_rescue: 0, added: 0, removed: 0, not_comparable: 0 } as Record<CaseChange, number>;
  for (const item of cases) counts[item.change] += 1;
  const executed = (report: EvaluationReport) => report.results.filter((result) => result.verdict !== 'skipped');
  return {
    caseSetId,
    dataSource,
    base: { id: base.id, label: base.label },
    candidate: { id: candidate.id, label: candidate.label },
    cases,
    counts,
    passed: { before: executed(base).filter(cleanPass).length, after: executed(candidate).filter(cleanPass).length, executedBefore: executed(base).length, executedAfter: executed(candidate).length },
    safetyViolations: { before: executed(base).filter(hasSafetyViolation).length, after: executed(candidate).filter(hasSafetyViolation).length },
    costPerRunUsd: { before: base.summary.costPerRunUsd, after: candidate.summary.costPerRunUsd },
    medianLatencyMs: { before: base.summary.latency?.medianMs ?? null, after: candidate.summary.latency?.medianMs ?? null },
  };
}

// ── readable output ─────────────────────────────────────────────────────────

const usd = (value: number | null) => (value === null ? 'n/a' : `$${value.toFixed(4)}`);
const seconds = (ms: number | null) => (ms === null ? 'n/a' : `${(ms / 1000).toFixed(1)} s`);
const STABILITY_WORD: Record<Stability, string> = { always_passed: 'every run', always_failed: 'never', flaky: 'FLAKY', not_run: 'not run' };

export function renderCampaignMarkdown(campaign: Campaign): string {
  const live = campaign.dataSource === 'live';
  const t = campaign.totals;
  const lines = [
    `# Reliability campaign: ${campaign.caseSetId}, ${campaign.runs} run${campaign.runs === 1 ? '' : 's'}`,
    '',
    `> ${kindNotice(campaign.dataSource)}`,
    '',
    '| | |',
    '| --- | --- |',
    `| Case runs executed | ${t.caseRuns} (${t.skipped} skipped) |`,
    live
      ? `| Passed unassisted | ${t.passed} of ${t.caseRuns} (${t.caseRuns ? ((t.passed / t.caseRuns) * 100).toFixed(1) : '0.0'}%) |`
      : `| Scripted runs scored as expected | ${t.passed} of ${t.caseRuns} |`,
    `| Passed only with a human rescue | ${t.rescued} |`,
    `| Failed / could not be scored | ${t.failed} / ${t.errored} |`,
    `| Cases that passed in every run | ${t.reliableCases} of ${campaign.cases.length} |`,
    `| Flaky cases (passed in some runs only) | ${t.flakyCases} |`,
    `| Runs with a safety violation | ${t.safetyViolations} |`,
    `| Runs with an incorrect write | ${t.incorrectWrites} |`,
    `| Runs with a duplicate operation | ${t.duplicateOperations} |`,
    `| Mandatory approvals granted | ${t.mandatoryApprovals} |`,
    `| Total runtime | ${seconds(t.totalRuntimeMs)}${live ? '' : ' (scripted; not a latency measurement)'} |`,
    `| Model usage | ${t.inputTokens === null ? 'not reported' : `${t.inputTokens} input, ${t.outputTokens} output tokens`} |`,
    `| Cost | ${usd(t.costUsd)} total, ${usd(t.costPerCaseRunUsd)} per case run |`,
    '',
    '## Per case',
    '',
    `| Case | Area | ${live ? 'Passed unassisted' : 'As expected'} | Stable | Rescued | Failure classes | Safety | Bad writes | Duplicates | Median time | Cost |`,
    '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ...campaign.cases.map((item) => {
      const classes = Object.entries(item.failureClasses).map(([name, count]) => `${FAILURE_LABEL[name as FailureClass]} (${count})`).join('; ') || 'none';
      return `| ${item.caseId} ${item.title} | ${item.area} | ${item.passed} of ${item.executed} | ${STABILITY_WORD[item.stability]} | ${item.rescued} | ${classes} | ${item.safetyViolations} | ${item.incorrectWrites} | ${item.duplicateOperations} | ${live ? seconds(item.medianWallClockMs) : 'n/a'} | ${usd(item.costUsd)} |`;
    }),
    '',
  ];
  return lines.join('\n');
}

const CHANGE_WORD: Record<CaseChange, string> = {
  fixed: 'Fixed',
  regressed: 'REGRESSED',
  still_passing: 'Still passing',
  still_failing: 'Still failing',
  now_needs_rescue: 'Now needs a rescue',
  no_longer_needs_rescue: 'No longer needs a rescue',
  added: 'New case',
  removed: 'No longer run',
  not_comparable: 'Skipped in one run',
};

/** The order a reader wants: what got worse, then what got better, then the rest. */
const CHANGE_ORDER: CaseChange[] = ['regressed', 'now_needs_rescue', 'fixed', 'no_longer_needs_rescue', 'still_failing', 'not_comparable', 'added', 'removed', 'still_passing'];

export function renderComparisonMarkdown(comparison: Comparison): string {
  const live = comparison.dataSource === 'live';
  const c = comparison.counts;
  const sorted = [...comparison.cases].sort((x, y) => CHANGE_ORDER.indexOf(x.change) - CHANGE_ORDER.indexOf(y.change) || x.caseId.localeCompare(y.caseId));
  const lines = [
    `# Comparison: ${comparison.caseSetId}`,
    '',
    `> ${kindNotice(comparison.dataSource)}`,
    '',
    `Before: ${comparison.base.label} (\`${comparison.base.id}\`). After: ${comparison.candidate.label} (\`${comparison.candidate.id}\`).`,
    '',
    '| | Before | After |',
    '| --- | --- | --- |',
    `| ${live ? 'Passed unassisted' : 'Scripted runs as expected'} | ${comparison.passed.before} of ${comparison.passed.executedBefore} | ${comparison.passed.after} of ${comparison.passed.executedAfter} |`,
    `| Runs with a safety violation | ${comparison.safetyViolations.before} | ${comparison.safetyViolations.after} |`,
    `| Cost per run | ${usd(comparison.costPerRunUsd.before)} | ${usd(comparison.costPerRunUsd.after)} |`,
    `| Median latency | ${live ? seconds(comparison.medianLatencyMs.before) : 'n/a'} | ${live ? seconds(comparison.medianLatencyMs.after) : 'n/a'} |`,
    '',
    `Regressed: ${c.regressed}. Fixed: ${c.fixed}. Still failing: ${c.still_failing}. Still passing: ${c.still_passing}. Now needs a rescue: ${c.now_needs_rescue}. No longer needs a rescue: ${c.no_longer_needs_rescue}.`,
    '',
    '| Case | Change | Before | After | Checks now failing | Checks now passing |',
    '| --- | --- | --- | --- | --- | --- |',
    ...sorted.map((item) => `| ${item.caseId} ${item.title} | ${CHANGE_WORD[item.change]}${item.newSafetyViolation ? ' (new safety violation)' : ''} | ${item.before} | ${item.after} | ${item.newlyFailing.join(', ') || 'none'} | ${item.newlyPassing.join(', ') || 'none'} |`),
    '',
  ];
  return lines.join('\n');
}
