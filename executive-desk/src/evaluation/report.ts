/** Aggregates case results into a report summary and day snapshots. */
import type {
  EvaluationReport,
  EvaluationResult,
  EvaluationSnapshot,
  EvaluationSummary,
  SnapshotDay,
  Verdict,
} from '../api/types';

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 1) return sorted[0];
  const rank = (sorted.length - 1) * p;
  const low = Math.floor(rank);
  const high = Math.ceil(rank);
  return sorted[low] + (sorted[high] - sorted[low]) * (rank - low);
}

export function summarize(results: EvaluationResult[]): EvaluationSummary {
  const executed = results.filter((r) => r.verdict !== 'skipped');
  const passed = executed.filter((r) => r.verdict === 'pass');
  const passedUnassisted = passed.filter((r) => !r.human.rescued);
  const durations = executed.filter((r) => r.verdict !== 'error').map((r) => r.timing.wallClockMs).sort((a, b) => a - b);
  const withUsage = executed.filter((r) => r.usage !== null);
  const withCost = executed.filter((r) => r.estimatedCostUsd !== null);
  const totalCost = withCost.reduce((sum, r) => sum + (r.estimatedCostUsd ?? 0), 0);

  return {
    total: results.length,
    executed: executed.length,
    passed: passed.length,
    passedUnassisted: passedUnassisted.length,
    failed: executed.filter((r) => r.verdict === 'fail').length,
    errored: executed.filter((r) => r.verdict === 'error').length,
    skipped: results.length - executed.length,
    rescued: executed.filter((r) => r.human.rescued).length,
    mandatoryApprovals: executed.reduce((sum, r) => sum + r.human.mandatoryApprovals, 0),
    unexpectedApprovals: executed.reduce((sum, r) => sum + r.human.unexpectedApprovals, 0),
    passRate: executed.length > 0 ? passedUnassisted.length / executed.length : null,
    latency:
      durations.length > 0
        ? {
            medianMs: percentile(durations, 0.5),
            p95Ms: percentile(durations, 0.95),
            meanMs: durations.reduce((sum, d) => sum + d, 0) / durations.length,
          }
        : null,
    casesWithUsage: withUsage.length,
    totalInputTokens: withUsage.length > 0 ? withUsage.reduce((sum, r) => sum + r.usage!.inputTokens + (r.usage!.cachedInputTokens ?? 0), 0) : null,
    totalOutputTokens: withUsage.length > 0 ? withUsage.reduce((sum, r) => sum + r.usage!.outputTokens, 0) : null,
    casesWithCost: withCost.length,
    totalCostUsd: withCost.length > 0 ? totalCost : null,
    costPerRunUsd: withCost.length > 0 ? totalCost / withCost.length : null,
  };
}

export const SNAPSHOT_DAYS: { day: SnapshotDay; label: string; date: string }[] = [
  { day: 'friday', label: 'Friday', date: '13 Nov' },
  { day: 'saturday', label: 'Saturday', date: '14 Nov' },
  { day: 'sunday', label: 'Sunday', date: '15 Nov' },
];

/**
 * Freezes a report as a day's snapshot. Refuses simulated reports: a snapshot is a record
 * of how the real agent did, and scripted mock output must never end up in one.
 */
export function buildSnapshot(report: EvaluationReport, day: SnapshotDay, savedAt: string): EvaluationSnapshot {
  if (report.target.dataSource !== 'live') {
    throw new Error('Only a report from a live backend can be saved as a snapshot. This report is simulated.');
  }
  const verdicts: Record<string, Verdict> = {};
  for (const result of report.results) verdicts[result.caseId] = result.verdict;
  return { day, savedAt, reportId: report.id, label: report.label, target: report.target, summary: report.summary, verdicts };
}

export function isSnapshot(value: unknown): value is EvaluationSnapshot {
  const v = value as Partial<EvaluationSnapshot> | null;
  return (
    !!v &&
    typeof v === 'object' &&
    (v.day === 'friday' || v.day === 'saturday' || v.day === 'sunday') &&
    typeof v.savedAt === 'string' &&
    !!v.summary &&
    typeof v.summary.total === 'number' &&
    v.target?.dataSource === 'live'
  );
}

export function isReport(value: unknown): value is EvaluationReport {
  const v = value as Partial<EvaluationReport> | null;
  return (
    !!v &&
    typeof v === 'object' &&
    typeof v.id === 'string' &&
    Array.isArray(v.results) &&
    !!v.summary &&
    (v.target?.dataSource === 'live' || v.target?.dataSource === 'simulated')
  );
}
