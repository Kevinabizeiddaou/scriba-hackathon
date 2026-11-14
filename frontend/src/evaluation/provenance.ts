/**
 * Where an evaluation report's results came from. Three kinds, never mixed:
 *
 *   mock      the in-memory scripted mock answered. It proves the harness, nothing else.
 *   scripted  a backend ran its real workflow in a sandbox, but no model took part: its planner
 *             was rules alone (or another stand-in), and it said so in GET /meta. These are real
 *             runs of real code and a fair picture of the rules. They are not the product's agent.
 *   real      a backend ran with a model-driven agent, in a sandbox.
 *
 * The kind is read from what the target reported and what the runner recorded, never from a
 * label a person typed. A report that cannot be placed is `unknown` and is shown as no result.
 */
import type { EvaluationReport, EvaluationResult } from '../harness/types';
import { hasSafetyViolation } from './campaign';

export type Provenance = 'mock' | 'scripted' | 'real' | 'unknown';

export function provenanceOf(report: Pick<EvaluationReport, 'target'>): Provenance {
  const target = report.target;
  if (!target || typeof target !== 'object') return 'unknown';
  if (target.dataSource === 'live') return 'real';
  if (target.dataSource !== 'simulated') return 'unknown';
  // A simulated report with no base URL never left this process: it is the scripted mock.
  return target.baseUrl ? 'scripted' : 'mock';
}

export const PROVENANCE: Record<Provenance, { label: string; short: string; means: string; tone: 'neutral' | 'info' | 'warn' | 'ok' }> = {
  mock: { label: 'Mock evaluation', short: 'Mock', means: 'The scripted mock answered. This checks the scorer and the runner. It says nothing about the secretary.', tone: 'neutral' },
  scripted: { label: 'Scripted-model evaluation', short: 'Scripted', means: 'The backend ran its real workflow, safeguards and execution gate in a sandbox, with no model: its planner was rules alone. Real runs of real code, but not the product\'s agent.', tone: 'warn' },
  real: { label: 'Real-model evaluation', short: 'Real model', means: 'The backend ran with a model-driven agent, in a sandbox. This is the secretary\'s result.', tone: 'ok' },
  unknown: { label: 'Origin not recorded', short: 'Unknown', means: 'The report does not say what produced it, so it is not shown as a result.', tone: 'neutral' },
};

export interface ProvenanceMetrics {
  executed: number;
  passed: number;
  failed: number;
  errored: number;
  skipped: number;
  /** passed / executed. Null when nothing was executed. Never shown for a mock report. */
  passRate: number | null;
  /** Cases in which a safety check failed. */
  safetyViolations: number;
  medianLatencyMs: number | null;
  /** Null when no priced model call was recorded. Null is not zero. */
  totalCostUsd: number | null;
  casesWithUsage: number;
}

export function metricsOf(report: Pick<EvaluationReport, 'results' | 'summary'>): ProvenanceMetrics {
  const executed: EvaluationResult[] = report.results.filter((result) => result.verdict !== 'skipped');
  const count = (verdict: EvaluationResult['verdict']) => report.results.filter((result) => result.verdict === verdict).length;
  return {
    executed: executed.length,
    passed: count('pass'),
    failed: count('fail'),
    errored: count('error'),
    skipped: count('skipped'),
    passRate: executed.length > 0 ? count('pass') / executed.length : null,
    safetyViolations: executed.filter(hasSafetyViolation).length,
    medianLatencyMs: report.summary.latency?.medianMs ?? null,
    totalCostUsd: report.summary.totalCostUsd,
    casesWithUsage: report.summary.casesWithUsage,
  };
}
