import { describe, expect, it } from 'vitest';
import { ApiError, type EvaluationTarget } from '../api/client';
import { MockExecutiveDesk } from '../api/mock/mockAdapter';
import { MOCK_SCRIPTS } from '../api/mock/scripts';
import type { AgentRun, ApprovalRequest, EvaluationCase } from '../api/types';
import { asLiveTarget, usageOf } from '../test/liveTarget';
import { EVALUATION_CASES, getCase } from './fixtures';
import { costFromPriceTable, estimateCost, parsePriceTable } from './pricing';
import { buildSnapshot, summarize } from './report';
import { runCase, runEvaluation } from './runner';

const fast = { pollIntervalMs: 1, timeoutMs: 2_000 };

/** Wraps a target so a test can change what the runner sees. Marked live to stand in for a real backend. */
function wrap(inner: EvaluationTarget, patch: Partial<EvaluationTarget> & { mapRun?: (run: AgentRun) => AgentRun }): EvaluationTarget {
  const mapRun = patch.mapRun ?? ((run: AgentRun) => run);
  return asLiveTarget(inner, {
    startEvaluationRun: async (input) => mapRun(await inner.startEvaluationRun(input)),
    getRun: async (id) => mapRun(await inner.getRun(id)),
    ...patch,
  });
}

const mock = () => new MockExecutiveDesk({ stepDelayMs: 0, seed: false });
const usage = (cost: number | null = null) => usageOf({}, cost);

describe('runCase', () => {
  it('sends the case input and context to the target in sandbox mode', async () => {
    const seen: unknown[] = [];
    const inner = mock();
    const target = wrap(inner, {
      startEvaluationRun: async (input) => {
        seen.push(input);
        return inner.startEvaluationRun(input);
      },
    });
    const testCase = getCase('EVAL-001');
    await runCase(target, testCase, fast);
    expect(seen).toEqual([{ caseId: 'EVAL-001', input: testCase.input, context: testCase.context, mode: 'sandbox' }]);
  });

  it('approves expected approvals in the harness name and records them as mandatory', async () => {
    const inner = mock();
    const result = await runCase(wrap(inner, {}), getCase('EVAL-001'), { ...fast, decidedBy: 'harness-bot' });
    expect(result.verdict).toBe('pass');
    expect(result.human).toMatchObject({ mandatoryApprovals: 1, unexpectedApprovals: 0, rescued: false });
    expect(result.approvals).toHaveLength(1);
    expect(result.approvals[0]).toMatchObject({ status: 'approved', decidedBy: 'harness-bot' });
    expect(result.dataSource).toBe('live');
  });

  it('rejects an approval the case does not call for, and the side effect never runs', async () => {
    // EVAL-012 expects no approvals at all. Feed it the EVAL-011 script, which asks to move an event.
    const inner = new MockExecutiveDesk({ stepDelayMs: 0, seed: false, scriptFor: () => MOCK_SCRIPTS['EVAL-011'] });
    const result = await runCase(inner, getCase('EVAL-012'), fast);
    expect(result.human).toMatchObject({ mandatoryApprovals: 0, unexpectedApprovals: 1 });
    expect(result.approvals[0].status).toBe('rejected');
    expect(result.run!.actions.filter((a) => a.sideEffect).map((a) => a.status)).toEqual(['rejected', 'rejected']);
    expect(result.verdict).toBe('fail');
    expect(result.checks.find((c) => c.id === 'approvals_expected')!.passed).toBe(false);
  });

  it('applies a reject decision when the case scripts one, and nothing is executed', async () => {
    const base = getCase('EVAL-001');
    const rejecting: EvaluationCase = {
      ...base,
      expected: { ...base.expected, harnessDecision: 'reject', outcomes: ['declined'], toolCalls: [], order: [], outboundEmail: null },
    };
    const result = await runCase(mock(), rejecting, fast);
    expect(result.approvals[0].status).toBe('rejected');
    expect(result.run!.outcome).toBe('declined');
    expect(result.run!.actions.some((a) => a.sideEffect && a.status === 'succeeded')).toBe(false);
    expect(result.verdict).toBe('pass');
  });

  it('turns a backend failure into an error result instead of throwing', async () => {
    const target = wrap(mock(), {
      startEvaluationRun: async () => {
        throw new ApiError('Service unavailable', 503, 'http_503');
      },
    });
    const result = await runCase(target, getCase('EVAL-001'), fast);
    expect(result.verdict).toBe('error');
    expect(result.errors).toEqual([{ source: 'backend', code: 'http_503', message: 'Service unavailable' }]);
    expect(result.run).toBeNull();
    expect(result.checks).toEqual([]);
  });

  it('measures wall-clock time itself and keeps the duration the backend reported', async () => {
    let clock = 1_000;
    const result = await runCase(mock(), getCase('EVAL-012'), {
      ...fast,
      now: () => clock,
      sleep: async (ms) => {
        clock += 250;
        await new Promise((resolve) => setTimeout(resolve, ms));
      },
    });
    expect(result.timing.wallClockMs).toBeGreaterThanOrEqual(250);
    expect(result.timing.wallClockMs % 250).toBe(0);
    expect(result.timing.agentReportedMs).toBe(result.run!.durationMs);
  });

  it('takes the cost from the backend when it reports one', async () => {
    const target = wrap(mock(), { mapRun: (run) => ({ ...run, usage: usage(0.0421) }) });
    const result = await runCase(target, getCase('EVAL-012'), fast);
    expect(result.usage!.models).toEqual([{ model: 'test-model', calls: 3, inputTokens: 12_000, outputTokens: 800, cachedInputTokens: 4_000 }]);
    expect(result.estimatedCostUsd).toBe(0.0421);
    expect(result.costSource).toBe('backend');
  });

  it('prices usage from the table when the backend reports tokens only', async () => {
    const target = wrap(mock(), { mapRun: (run) => ({ ...run, usage: usage() }) });
    const pricing = { 'test-model': { inputPerMTokUsd: 2, outputPerMTokUsd: 10, cachedInputPerMTokUsd: 0.5 } };
    const result = await runCase(target, getCase('EVAL-012'), { ...fast, pricing });
    // 12,000 x 2 + 800 x 10 + 4,000 x 0.5 = 34,000 micro-dollars
    expect(result.estimatedCostUsd).toBeCloseTo(0.034, 10);
    expect(result.costSource).toBe('price_table');
  });

  it('leaves the cost empty when usage is reported but the model has no price', async () => {
    const target = wrap(mock(), { mapRun: (run) => ({ ...run, usage: usage() }) });
    const result = await runCase(target, getCase('EVAL-012'), fast);
    expect(result.usage).not.toBeNull();
    expect(result.estimatedCostUsd).toBeNull();
    expect(result.costSource).toBeNull();
  });

  it('fails a real (unsimulated) side effect by default and allows it only when asked', async () => {
    const real = (run: AgentRun): AgentRun => ({ ...run, actions: run.actions.map((a) => (a.sideEffect ? { ...a, simulated: false } : a)) });
    const strict = await runCase(wrap(mock(), { mapRun: real }), getCase('EVAL-001'), fast);
    expect(strict.verdict).toBe('fail');
    expect(strict.checks.find((c) => c.id === 'sandbox_only')!.passed).toBe(false);

    const relaxed = await runCase(wrap(mock(), { mapRun: real }), getCase('EVAL-001'), { ...fast, requireSimulated: false });
    expect(relaxed.verdict).toBe('pass');
    expect(relaxed.checks.some((c) => c.id === 'sandbox_only')).toBe(false);
  });

  it('does not decide the same approval twice while the backend is slow to update', async () => {
    const inner = mock();
    const decisions: string[] = [];
    let stale: ApprovalRequest[] | null = null;
    const target = wrap(inner, {
      // Keep reporting the first pending list, as a lagging backend would.
      listApprovals: async (filter) => {
        const fresh = await inner.listApprovals(filter);
        if (filter?.status?.includes('pending')) {
          stale ??= fresh;
          return stale;
        }
        return fresh;
      },
      decideApproval: async (id, input) => {
        decisions.push(id);
        return inner.decideApproval(id, input);
      },
    });
    const result = await runCase(target, getCase('EVAL-001'), fast);
    expect(decisions).toHaveLength(1);
    expect(result.human.mandatoryApprovals).toBe(1);
  });
});

describe('runEvaluation and summarize', () => {
  it('reports no pass rate, latency or cost before anything has run', () => {
    const summary = summarize([]);
    expect(summary).toMatchObject({ total: 0, executed: 0, passRate: null, latency: null, totalCostUsd: null, costPerRunUsd: null, totalInputTokens: null });
  });

  it('lists skipped cases without executing them and keeps them out of the pass rate', async () => {
    const cases = EVALUATION_CASES.slice(0, 3);
    const report = await runEvaluation(mock(), cases, { ...fast, skip: { 'EVAL-002': 'Chat endpoint not ready.' } });
    expect(report.results.map((r) => r.verdict)).toEqual(['pass', 'skipped', 'pass']);
    expect(report.results[1]).toMatchObject({ skipReason: 'Chat endpoint not ready.', run: null });
    expect(report.summary).toMatchObject({ total: 3, executed: 2, skipped: 1, passed: 2, passRate: 1 });
  });

  it('builds the pass rate on unassisted passes and averages cost over priced runs only', async () => {
    const inner = mock();
    // EVAL-001: rescued by a person. EVAL-002: clean, with usage. EVAL-003: wrong outcome.
    const target = wrap(inner, {
      mapRun: (run) => {
        const caseTitle = run.triage?.extracted?.title ?? '';
        if (caseTitle.startsWith('Intro call') && run.status === 'completed') {
          return { ...run, humanInterventions: [...run.humanInterventions, { at: run.finishedAt!, kind: 'rescue', by: 'Operator', note: null }] };
        }
        if (caseTitle.startsWith('Q1 hiring')) return { ...run, usage: usage(0.05) };
        if (caseTitle.startsWith('Revised contract') && run.status === 'completed') return { ...run, outcome: 'scheduled' };
        return run;
      },
    });
    const progress: number[] = [];
    const report = await runEvaluation(target, EVALUATION_CASES.slice(0, 3), { ...fast, onProgress: (p) => progress.push(p.done) });

    expect(report.target).toEqual({ name: 'Test backend', dataSource: 'live', baseUrl: 'http://backend.test', contractVersion: '1.0.0', sandbox: true });
    expect(report).toMatchObject({ format: 'executive-desk.evaluation-report/1', contractVersion: '1.0.0', caseSet: { id: 'ad-hoc', provenance: 'synthetic', caseCount: 3 } });
    expect(report.results.every((r) => r.provenance === 'synthetic' && r.dataSource === 'live')).toBe(true);
    expect(report.results.map((r) => [r.caseId, r.verdict, r.human.rescued])).toEqual([
      ['EVAL-001', 'pass', true],
      ['EVAL-002', 'pass', false],
      ['EVAL-003', 'fail', false],
    ]);
    expect(report.summary).toMatchObject({ executed: 3, passed: 2, passedUnassisted: 1, failed: 1, rescued: 1, mandatoryApprovals: 3, casesWithCost: 1, casesWithUsage: 1 });
    expect(report.summary.passRate).toBeCloseTo(1 / 3, 10);
    expect(report.summary.costPerRunUsd).toBe(0.05);
    expect(report.summary.totalInputTokens).toBe(16_000);
    expect(report.summary.latency).not.toBeNull();
    expect(progress).toEqual([0, 1, 2, 3]);

    const failed = report.results[2].checks.find((c) => c.id === 'outcome')!;
    expect(failed).toMatchObject({ passed: false, expected: 'alternatives_proposed', actual: 'scheduled' });
  });

  it('labels results from what the backend says it is, not from how it was reached', async () => {
    // The plain mock says agent: scripted, so everything is simulated.
    const scripted = await runEvaluation(mock(), EVALUATION_CASES.slice(0, 1), fast);
    expect(scripted.target).toMatchObject({ dataSource: 'simulated', sandbox: true });
    expect(scripted.results[0].dataSource).toBe('simulated');
  });

  it('refuses to run against a backend that says it is not a sandbox', async () => {
    const inner = mock();
    let started = 0;
    const production = asLiveTarget(inner, {
      getMeta: async () => ({ ...(await inner.getMeta()), agent: 'real', sandbox: false }),
      startEvaluationRun: (input) => {
        started += 1;
        return inner.startEvaluationRun(input);
      },
    });
    const result = await runCase(production, getCase('EVAL-001'), fast);
    expect(started).toBe(0);
    expect(result.verdict).toBe('error');
    expect(result.errors).toEqual([expect.objectContaining({ source: 'harness', code: 'not_sandbox' })]);
  });

  it('skips fault-injection cases when the backend cannot inject faults, and runs the rest', async () => {
    const inner = mock();
    const limited = asLiveTarget(inner, {
      getMeta: async () => {
        const meta = await inner.getMeta();
        return { ...meta, agent: 'real', capabilities: { ...meta.capabilities, faultInjection: false } };
      },
    });
    const cases = EVALUATION_CASES.filter((c) => ['EVAL-016', 'EVAL-017', 'EVAL-018'].includes(c.id));
    const report = await runEvaluation(limited, cases, fast);
    expect(report.results.map((r) => [r.caseId, r.verdict])).toEqual([['EVAL-016', 'pass'], ['EVAL-017', 'skipped'], ['EVAL-018', 'skipped']]);
    expect(report.results[1].skipReason).toMatch(/fault injection/);
    expect(report.summary).toMatchObject({ executed: 1, skipped: 2 });
  });

  it('refuses a case set that mixes synthetic and real-world cases', async () => {
    const real: EvaluationCase = { ...getCase('EVAL-001'), id: 'REAL-001', provenance: { kind: 'real_world', source: 'pilot user, week 46', anonymized: true, consentReference: 'consent-0001' } };
    await expect(runEvaluation(mock(), [getCase('EVAL-001'), real], fast)).rejects.toThrow(/must not mix/);
    const report = await runEvaluation(mock(), [real], fast);
    expect(report.caseSet).toMatchObject({ provenance: 'real_world', caseCount: 1 });
    expect(report.results[0].provenance).toBe('real_world');
  });

  it('refuses to save a simulated report as a snapshot and accepts a live one', async () => {
    const simulated = await runEvaluation(mock(), EVALUATION_CASES.slice(0, 1), fast);
    expect(() => buildSnapshot(simulated, 'friday', '2026-11-13T20:00:00+02:00')).toThrow(/simulated/i);

    const live = await runEvaluation(wrap(mock(), {}), EVALUATION_CASES.slice(0, 1), { ...fast, label: 'Friday evening' });
    const snapshot = buildSnapshot(live, 'friday', '2026-11-13T20:00:00+02:00');
    expect(snapshot).toMatchObject({ day: 'friday', label: 'Friday evening', verdicts: { 'EVAL-001': 'pass' }, summary: { executed: 1, passed: 1 } });
  });
});

describe('pricing', () => {
  it('ships with an empty price table so no cost is invented', () => {
    expect(estimateCost(usage(), {})).toEqual({ usd: null, source: null });
    expect(estimateCost(null, {})).toEqual({ usd: null, source: null });
  });

  it('bills cached tokens at the input price when no cached price is given', () => {
    expect(costFromPriceTable(usage(), { 'test-model': { inputPerMTokUsd: 2, outputPerMTokUsd: 10 } })).toBeCloseTo(0.04, 10);
  });

  it('prices each model at its own rate and refuses a partial sum', () => {
    const twoModels = {
      models: [
        { model: 'small', calls: 4, inputTokens: 1_000_000, outputTokens: 0, cachedInputTokens: null },
        { model: 'large', calls: 1, inputTokens: 0, outputTokens: 1_000_000, cachedInputTokens: null },
      ],
      estimatedCostUsd: null,
    };
    const table = { small: { inputPerMTokUsd: 1, outputPerMTokUsd: 5 }, large: { inputPerMTokUsd: 3, outputPerMTokUsd: 15 } };
    expect(costFromPriceTable(twoModels, table)).toBe(16);
    // One model without a price: no cost at all, rather than the cost of the other one alone.
    expect(costFromPriceTable(twoModels, { small: table.small })).toBeNull();
    expect(estimateCost(twoModels, { small: table.small })).toEqual({ usd: null, source: null });
    expect(costFromPriceTable({ models: [], estimatedCostUsd: null }, table)).toBeNull();
  });

  it('validates a price table loaded from JSON', () => {
    expect(parsePriceTable({ m: { inputPerMTokUsd: 1, outputPerMTokUsd: 2 } })).toEqual({ m: { inputPerMTokUsd: 1, outputPerMTokUsd: 2 } });
    expect(() => parsePriceTable({ m: { inputPerMTokUsd: '1' } })).toThrow(/numeric/);
    expect(() => parsePriceTable([])).toThrow(/JSON object/);
  });
});
