// @vitest-environment node
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import { MockExecutiveDesk } from '../api/mock/mockAdapter';
import { REPORT_FORMAT, type EvaluationCase, type EvaluationReport } from '../api/types';
import { asLiveTarget } from '../test/liveTarget';
import { CASE_SET_FORMAT, buildCaseSetFile, caseSetProblems, loadCaseSet, type CaseSetFile } from './caseSets';
import { EVALUATION_CASES, SYNTHETIC_CASE_SET, getCase } from './fixtures';
import { toJUnit } from './junit';
import { isReport } from './report';
import { runEvaluation } from './runner';

const root = resolve(__dirname, '../..');
const shipped = () => JSON.parse(readFileSync(resolve(root, 'fixtures/evaluation-cases.json'), 'utf8')) as CaseSetFile;
const clone = <T>(value: T): T => structuredClone(value);

const realCase = (over: Partial<EvaluationCase> = {}): EvaluationCase => ({
  ...clone(getCase('EVAL-001')),
  id: 'REAL-001',
  title: 'Intro call request from a pilot user',
  provenance: { kind: 'real_world', source: 'Pilot user 3, week 46', anonymized: true, consentReference: 'consent/2026-11-pilot-3' },
  ...over,
});
const realSet = (cases: EvaluationCase[]) => buildCaseSetFile({ id: 'pilot-week-46', provenance: 'real_world', caseCount: cases.length }, cases, 'Anonymised cases from the pilot.');

describe('case-set files', () => {
  it('ships the synthetic fixtures as a valid, clearly labelled case set', () => {
    const file = shipped();
    expect(caseSetProblems(file)).toEqual([]);
    expect(file).toMatchObject({ format: CASE_SET_FORMAT, contractVersion: '1.1.0', caseSet: { id: 'synthetic-v2', provenance: 'synthetic', caseCount: 20 } });
    expect(file.notice).toMatch(/Synthetic development fixtures.*Not customer data/);
    expect(file.cases.every((c) => c.provenance.kind === 'synthetic')).toBe(true);
    const loaded = loadCaseSet(file);
    expect(loaded.cases.map((c) => c.id)).toEqual(EVALUATION_CASES.map((c) => c.id));
    expect(loaded.caseSet).toEqual(SYNTHETIC_CASE_SET);
  });

  it('accepts a properly labelled, anonymised real-world set', () => {
    expect(caseSetProblems(realSet([realCase()]))).toEqual([]);
  });

  it('refuses a case that does not say where it comes from', () => {
    const file = shipped();
    delete (file.cases[3] as Partial<EvaluationCase>).provenance;
    expect(caseSetProblems(file)).toEqual(['EVAL-004: has no provenance. Every case must say whether it is synthetic or real-world.']);
  });

  it('refuses a set that mixes synthetic and real-world cases', () => {
    const file = shipped();
    file.cases[0] = realCase();
    file.caseSet.caseCount = file.cases.length;
    expect(caseSetProblems(file)).toContain('REAL-001: is real_world in a set declared synthetic. A set must not mix the two.');
  });

  it('refuses a real-world case that is not anonymised, has no consent, or borrows a synthetic id', () => {
    const problems = caseSetProblems(
      realSet([
        realCase({ id: 'EVAL-001' }),
        realCase({ id: 'REAL-002', provenance: { kind: 'real_world', source: '', anonymized: false as never, consentReference: ' ' } }),
      ]),
    );
    expect(problems).toEqual([
      'EVAL-001: ids of the form EVAL-nnn are reserved for synthetic fixtures.',
      'REAL-002: a real-world case must be anonymised, and say so.',
      'REAL-002: a real-world case must name its source.',
      'REAL-002: a real-world case must reference the consent for its use.',
    ]);
  });

  it('refuses any case that still contains a real-looking address', () => {
    const leaky = realCase();
    if (leaky.input.kind === 'email') leaky.input.email.from = { name: 'Someone Real', email: 'someone.real@gmail.com' };
    const [problem] = caseSetProblems(realSet([leaky]));
    expect(problem).toMatch(/REAL-001: contains addresses outside the reserved .example, .test and .invalid domains \(someone\.real@gmail\.com\)/);
  });

  it('refuses the wrong format, another contract major, duplicate ids and a wrong count, all in one message', () => {
    const file = shipped();
    file.cases[1] = clone(file.cases[0]);
    const broken = { ...file, format: 'something-else', contractVersion: '2.0.0', caseSet: { ...file.caseSet, caseCount: 19 } };
    expect(() => loadCaseSet(broken)).toThrow(/"format" must be[\s\S]*"contractVersion" must be 1\.x[\s\S]*caseCount" is 19, but the file holds 20[\s\S]*EVAL-001: the id is used more than once/);
    expect(caseSetProblems(null)).toEqual(['The file is not a JSON object.']);
    expect(caseSetProblems({ ...file, cases: [] })).toContain('"cases" must be a non-empty array.');
  });
});

describe('machine-readable output', () => {
  it('writes a report that identifies its format, versions, case set and target', async () => {
    const report = await runEvaluation(asLiveTarget(new MockExecutiveDesk({ stepDelayMs: 0, seed: false })), EVALUATION_CASES.slice(0, 2), { pollIntervalMs: 1, caseSet: SYNTHETIC_CASE_SET });
    const parsed = JSON.parse(JSON.stringify(report)) as EvaluationReport;
    expect(isReport(parsed)).toBe(true);
    expect(parsed).toMatchObject({ format: REPORT_FORMAT, harnessVersion: '1.0.0', contractVersion: '1.1.0', caseSet: SYNTHETIC_CASE_SET, target: { dataSource: 'live', sandbox: true } });
    expect(Object.keys(parsed.results[0])).toEqual(
      expect.arrayContaining(['caseId', 'provenance', 'dataSource', 'verdict', 'checks', 'expected', 'actual', 'human', 'errors', 'timing', 'usage', 'estimatedCostUsd', 'costSource', 'run', 'approvals']),
    );
    expect(isReport({ ...parsed, format: 'old' })).toBe(false);
  });

  it('renders JUnit XML with failures, errors and skips, and escapes text', async () => {
    const inner = new MockExecutiveDesk({ stepDelayMs: 0, seed: false });
    const target = asLiveTarget(inner, {
      // EVAL-003 comes back with the wrong outcome; EVAL-002 cannot be started at all.
      startEvaluationRun: async (input) => {
        if (input.caseId === 'EVAL-002') throw new Error('boom <&> "quoted"');
        return inner.startEvaluationRun(input);
      },
      getRun: async (id) => {
        const run = await inner.getRun(id);
        return run.triage?.extracted?.title?.startsWith('Revised contract') && run.status === 'completed' ? { ...run, outcome: 'scheduled' } : run;
      },
    });
    const report = await runEvaluation(target, EVALUATION_CASES.slice(0, 4), { pollIntervalMs: 1, skip: { 'EVAL-004': 'not today' } });
    const xml = toJUnit(report);

    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    expect(xml).toContain('<testsuites name="executive-desk-evaluation" tests="4" failures="1" errors="1" skipped="1"');
    expect(xml).toContain('<property name="dataSource" value="live"/>');
    expect(xml).toContain('<property name="provenance" value="synthetic"/>');
    expect(xml).toMatch(/<testcase classname="straightforward" name="EVAL-001 Simple booking at a free time" time="[\d.]+"\/>/);
    expect(xml).toMatch(/<error type="exception" message="boom &lt;&amp;&gt; &quot;quoted&quot;">/);
    expect(xml).toMatch(/<failure type="expectation" message="\d+ check\(s\) failed: outcome/);
    expect(xml).toContain('<skipped message="not today"/>');
    expect(xml).not.toMatch(/boom <&>/);
    expect((xml.match(/<testcase /g) ?? []).length).toBe(4);
  });
});

describe('command line', () => {
  const out = mkdtempSync(join(tmpdir(), 'desk-eval-'));
  afterAll(() => rmSync(out, { recursive: true, force: true }));
  const tsx = resolve(root, 'node_modules/tsx/dist/cli.mjs');
  const run = (args: string[]) => {
    try {
      return { code: 0, stdout: execFileSync(process.execPath, [tsx, 'scripts/eval.ts', ...args], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }), stderr: '' };
    } catch (error) {
      const e = error as { status: number; stdout: string; stderr: string };
      return { code: e.status, stdout: e.stdout, stderr: e.stderr };
    }
  };

  it('runs the fixtures against the mock, prints the report as JSON, and writes the report and JUnit files', () => {
    const junit = join(out, 'junit.xml');
    const result = run(['--target', 'mock', '--out', out, '--junit', junit, '--print-json', '--only', 'EVAL-001,EVAL-019', '--label', 'cli test']);
    expect(result.code).toBe(0);

    const report = JSON.parse(result.stdout) as EvaluationReport; // stdout is the report and nothing else
    expect(report).toMatchObject({ format: REPORT_FORMAT, label: 'cli test', target: { dataSource: 'simulated', name: 'Mock adapter' }, caseSet: { id: 'synthetic-v2', caseCount: 20 } });
    expect(report.results.map((r) => [r.caseId, r.verdict, r.provenance])).toEqual([['EVAL-001', 'pass', 'synthetic'], ['EVAL-019', 'pass', 'synthetic']]);

    const files = readdirSync(out);
    const reportFile = files.find((f) => f.endsWith('.simulated.json'))!;
    expect(reportFile).toMatch(/^report-\d{14}\.simulated\.json$/); // a simulated report cannot be mistaken for a live one by name
    expect(JSON.parse(readFileSync(join(out, reportFile), 'utf8'))).toEqual(report);
    expect(readFileSync(junit, 'utf8')).toContain('tests="2" failures="0" errors="0" skipped="0"');
  }, 60_000);

  it('runs a case-set file, and refuses an invalid one with the reasons', () => {
    const good = join(out, 'pilot.json');
    writeFileSync(good, JSON.stringify(realSet([realCase()])));
    const ok = run(['--target', 'mock', '--cases', good, '--out', out, '--print-json']);
    // The mock has no script for a case it has never seen: reported per case, exit code 1.
    expect(ok.code).toBe(1);
    const report = JSON.parse(ok.stdout) as EvaluationReport;
    expect(report.caseSet).toEqual({ id: 'pilot-week-46', provenance: 'real_world', caseCount: 1 });
    expect(report.results[0]).toMatchObject({ caseId: 'REAL-001', provenance: 'real_world', verdict: 'error' });

    const bad = join(out, 'bad.json');
    const mixed = realSet([realCase(), clone(getCase('EVAL-002'))]);
    writeFileSync(bad, JSON.stringify(mixed));
    const refused = run(['--target', 'mock', '--cases', bad, '--out', out]);
    expect(refused.code).toBe(2);
    expect(refused.stderr).toContain('EVAL-002: is synthetic in a set declared real_world');
  }, 60_000);

  it('refuses to snapshot simulated results and rejects unknown options', () => {
    expect(run(['--target', 'mock', '--snapshot', 'friday'])).toMatchObject({ code: 2, stderr: expect.stringContaining('Simulated results are never saved as snapshots') });
    expect(run(['--base-ulr', 'http://x'])).toMatchObject({ code: 2, stderr: expect.stringContaining('Unknown option --base-ulr') });
    expect(run(['--base-url', 'http://127.0.0.1:9', '--request-timeout', '500'])).toMatchObject({ code: 2, stderr: expect.stringMatching(/Could not reach the backend|did not answer/) });
  }, 60_000);
});
