import { describe, expect, it } from 'vitest';
import { PROBES, runSelfTest } from './selfTest';

describe('harness self-test', () => {
  it('passes all twenty reference scripts and catches every planted defect', async () => {
    const report = await runSelfTest();

    // Reference scripts: every case's expectations are satisfiable and the scorer agrees.
    const notPassing = report.reference.results
      .filter((r) => r.verdict !== 'pass')
      .map((r) => `${r.caseId}: ${r.verdict} ${r.checks.filter((c) => !c.passed).map((c) => `${c.id} (expected ${c.expected}; got ${c.actual})`).join(' | ')} ${r.errors.map((e) => e.message).join(' | ')}`);
    expect(notPassing).toEqual([]);
    expect(report.reference.results).toHaveLength(20);
    expect(report.referenceAsExpected).toBe(20);

    // Probes: each planted defect is caught by the check that is meant to catch it.
    const mismatches = report.probes.filter((p) => !p.asExpected).map((p) => `${p.probe.id}: ${p.mismatch}`);
    expect(mismatches).toEqual([]);
    expect(report.probes).toHaveLength(PROBES.length);
    expect(report.allAsExpected).toBe(true);
  });

  it('labels the reference report as simulated and reports no usage or cost', async () => {
    const { reference } = await runSelfTest();
    expect(reference.target.dataSource).toBe('simulated');
    expect(reference.summary.casesWithUsage).toBe(0);
    expect(reference.summary.totalCostUsd).toBeNull();
    expect(reference.summary.costPerRunUsd).toBeNull();
    for (const result of reference.results) {
      expect(result.dataSource).toBe('simulated');
      expect(result.usage).toBeNull();
      expect(result.estimatedCostUsd).toBeNull();
    }
  });

  it('counts mandatory approvals separately from rescues', async () => {
    const report = await runSelfTest();
    expect(report.reference.summary.rescued).toBe(0);
    expect(report.reference.summary.mandatoryApprovals).toBeGreaterThan(0);
    expect(report.reference.summary.unexpectedApprovals).toBe(0);

    const rescue = report.probes.find((p) => p.probe.id === 'human-rescue')!.result;
    expect(rescue.verdict).toBe('pass');
    expect(rescue.human.rescued).toBe(true);
    expect(rescue.human.mandatoryApprovals).toBe(1);
  });

  it('records a recovered tool failure as an error without failing the case', async () => {
    const report = await runSelfTest();
    const transient = report.reference.results.find((r) => r.caseId === 'EVAL-017')!;
    expect(transient.verdict).toBe('pass');
    expect(transient.errors).toEqual([expect.objectContaining({ source: 'tool', code: 'calendar_unavailable' })]);
  });

  it('reports a timeout and a model failure as errors, not as wrong answers', async () => {
    const report = await runSelfTest();
    const hang = report.probes.find((p) => p.probe.id === 'never-finishes')!.result;
    expect(hang.verdict).toBe('error');
    expect(hang.errors[0]).toMatchObject({ source: 'harness', code: 'timeout' });

    const model = report.probes.find((p) => p.probe.id === 'model-error')!.result;
    expect(model.verdict).toBe('error');
    expect(model.errors).toContainEqual(expect.objectContaining({ source: 'model', code: 'model_overloaded' }));
    expect(model.checks).toEqual([]);
  });
});
