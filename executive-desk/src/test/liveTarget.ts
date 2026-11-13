/**
 * Test helper: presents a scripted mock as if a real agent were behind it.
 *
 * Reports and results are labelled "live" only when GET /meta says the agent is real, so
 * tests that need a live-labelled report (snapshots, headline tiles, cost) wrap the mock with
 * this. It must never be used outside tests: it is exactly the mislabelling the product forbids.
 */
import type { EvaluationTarget } from '../api/client';
import type { ModelUsage, TokenUsage } from '../api/types';

export function asLiveTarget(inner: EvaluationTarget, patch: Partial<EvaluationTarget> = {}): EvaluationTarget {
  return {
    info: { ...inner.info, name: 'Test backend', dataSource: 'live', baseUrl: 'http://backend.test' },
    getMeta: async () => ({ ...(await inner.getMeta()), agent: 'real', service: 'Test backend' }),
    startEvaluationRun: (input) => inner.startEvaluationRun(input),
    getRun: (id) => inner.getRun(id),
    listApprovals: (filter) => inner.listApprovals(filter),
    decideApproval: (id, input) => inner.decideApproval(id, input),
    ...patch,
  };
}

export function usageOf(over: Partial<ModelUsage> = {}, estimatedCostUsd: number | null = null): TokenUsage {
  return { models: [{ model: 'test-model', calls: 3, inputTokens: 12_000, outputTokens: 800, cachedInputTokens: 4_000, ...over }], estimatedCostUsd };
}
