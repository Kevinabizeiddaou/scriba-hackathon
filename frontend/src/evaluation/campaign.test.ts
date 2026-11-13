/**
 * Reliability campaigns and comparisons. The reports here come from the scripted mock, wrapped as
 * a live target where a test needs "live" numbers, and are then altered by hand: this file tests
 * the arithmetic and the guards, not an agent.
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterAll, describe, expect, it } from 'vitest'
import { MockExecutiveDesk } from '../harness/mock/mockAdapter'
import type { CheckResult, EvaluationReport, EvaluationResult } from '../harness/types'
import { asLiveTarget, usageOf } from '../test/liveTarget'
import { CampaignError, FAILURE_CLASSES, FAILURE_LABEL, aggregateCampaign, classifyFailure, compareReports, hasDuplicateOperation, hasIncorrectWrite, hasSafetyViolation, kindNotice, renderCampaignMarkdown, renderComparisonMarkdown } from './campaign'
import { DESK_CASE_SET, DESK_SUITE, EVALUATION_CASES, SYNTHETIC_CASE_SET } from './fixtures'
import { summarize } from './report'
import { runEvaluation } from './runner'

const fast = { pollIntervalMs: 1, timeoutMs: 5_000 }
const mock = () => new MockExecutiveDesk({ stepDelayMs: 0, seed: false })
const clone = <T>(value: T): T => structuredClone(value)

const liveReport = (label = 'live') => runEvaluation(asLiveTarget(mock()), DESK_SUITE, { ...fast, caseSet: DESK_CASE_SET, label })
const scriptedReport = () => runEvaluation(mock(), DESK_SUITE, { ...fast, caseSet: DESK_CASE_SET })

/** A copy of the report in which some cases went differently. */
function altered(report: EvaluationReport, change: Record<string, (result: EvaluationResult) => void>, id = `${report.id}-b`): EvaluationReport {
  const copy = clone(report)
  copy.id = id
  for (const result of copy.results) change[result.caseId]?.(result)
  copy.summary = summarize(copy.results)
  return copy
}

const failCheck = (id: string, actual = 'broken', safety?: boolean) => (result: EvaluationResult) => {
  const existing = result.checks.find((check) => check.id === id)
  if (existing) Object.assign(existing, { passed: false, actual })
  else result.checks.push({ id, label: id, safety: safety ?? false, passed: false, expected: 'ok', actual } as CheckResult)
  result.verdict = 'fail'
}

describe('classifying a failure', () => {
  it('names why a run failed from the checks that failed, each class once', async () => {
    const report = await liveReport()
    const result = clone(report.results.find((r) => r.caseId === 'EVAL-031')!)
    expect(classifyFailure(result)).toEqual([]) // a pass has no failure class
    failCheck('approval_gate', 'calendar.create_event (a1) ran with no approval', true)(result)
    failCheck('state:1')(result)
    failCheck('tool:3')(result)
    failCheck('tool:2')(result)
    expect(classifyFailure(result)).toEqual(['unapproved_or_wrong_write', 'wrong_final_state', 'missing_or_wrong_tool_call'])
    expect(hasSafetyViolation(result)).toBe(true)
    expect(hasIncorrectWrite(result)).toBe(true)
    expect(hasDuplicateOperation(result)).toBe(false)
  })

  it('tells a duplicate from an unapproved write, and a timeout from another error', async () => {
    const report = await liveReport()
    const twice = clone(report.results[0])
    failCheck('approval_gate', 'email.send succeeded more than once for one approved change in approval a1', true)(twice)
    expect(classifyFailure(twice)).toEqual(['duplicate_operation'])
    expect(hasDuplicateOperation(twice)).toBe(true)
    expect(hasIncorrectWrite(twice)).toBe(false)

    const slow = clone(report.results[0])
    slow.verdict = 'error'
    slow.errors = [{ source: 'harness', code: 'timeout', message: 'No final status in time.' }]
    expect(classifyFailure(slow)).toEqual(['timeout'])
    slow.errors = [{ source: 'model', code: 'model_overloaded', message: 'x' }]
    expect(classifyFailure(slow)).toEqual(['error'])
  })

  it('has a readable label for every class and maps every kind of check the scorer emits', async () => {
    for (const name of FAILURE_CLASSES) expect(FAILURE_LABEL[name].length, name).toBeGreaterThan(3)
    // Fail every check of every case in both suites: none may fall into "other".
    const reports = [await liveReport(), await runEvaluation(asLiveTarget(mock()), EVALUATION_CASES, { ...fast, caseSet: SYNTHETIC_CASE_SET })]
    const unknown = new Set<string>()
    for (const report of reports) {
      for (const result of report.results) {
        for (const check of result.checks) {
          const one = { ...clone(result), verdict: 'fail' as const, checks: [{ ...check, passed: false }] }
          if (classifyFailure(one).includes('other')) unknown.add(check.id)
        }
      }
    }
    expect([...unknown]).toEqual([])
  })
})

describe('a campaign', () => {
  it('reports per case how often it passed, how it failed, and whether it is flaky', async () => {
    const first = await liveReport('run 1')
    const second = altered(first, { 'EVAL-023': failCheck('email:must:0'), 'EVAL-018': failCheck('idempotency', 'attempts used different keys', true) })
    const third = altered(first, {
      'EVAL-018': failCheck('no_double_booking', 'overlaps "Board prep"', true),
      'EVAL-031': (result) => { result.human.rescued = true },
      'EVAL-021': (result) => { result.verdict = 'skipped'; result.checks = [] },
    }, `${first.id}-c`)
    const campaign = aggregateCampaign([first, second, third])

    expect(campaign).toMatchObject({ caseSetId: 'desk-v1', dataSource: 'live', runs: 3 })
    const of = (id: string) => campaign.cases.find((item) => item.caseId === id)!
    expect(of('EVAL-001')).toMatchObject({ executed: 3, passed: 3, stability: 'always_passed', failureClasses: {} })
    expect(of('EVAL-023')).toMatchObject({ executed: 3, passed: 2, failed: 1, stability: 'flaky', failureClasses: { wording: 1 }, safetyViolations: 0 })
    expect(of('EVAL-018')).toMatchObject({ passed: 1, failed: 2, stability: 'flaky', failureClasses: { duplicate_operation: 1, double_booking: 1 }, safetyViolations: 2, incorrectWrites: 1, duplicateOperations: 1 })
    // A pass that needed a person is not a pass for reliability.
    expect(of('EVAL-031')).toMatchObject({ passed: 2, rescued: 1, failed: 0, stability: 'flaky' })
    expect(of('EVAL-021')).toMatchObject({ executed: 2, skipped: 1, passed: 2, stability: 'always_passed' })

    expect(campaign.totals).toMatchObject({ caseRuns: 59, passed: 55, rescued: 1, failed: 3, errored: 0, skipped: 1, safetyViolations: 2, incorrectWrites: 1, duplicateOperations: 1, flakyCases: 3, reliableCases: 17 })
    expect(campaign.totals.mandatoryApprovals).toBe(first.summary.mandatoryApprovals * 3)
  })

  it('adds up cost only when every executed run was priced, and tokens when any were reported', async () => {
    // A backend that reports usage and its own cost for a finished run, and nothing for a failed one.
    const inner = mock()
    const target = asLiveTarget(inner, {
      getRun: async (id) => {
        const run = await inner.getRun(id)
        return run.status === 'completed' ? { ...run, usage: usageOf({}, 0.02) } : run
      },
    })
    const first = await runEvaluation(target, DESK_SUITE, { ...fast, caseSet: DESK_CASE_SET })
    const priced = aggregateCampaign([first, altered(first, {})])
    const withUsage = first.results.filter((r) => r.usage).length
    expect(withUsage).toBeGreaterThan(0)
    // The failed-run case reports no usage, so the campaign has no total cost rather than a partial one.
    expect(first.results.some((r) => r.verdict !== 'skipped' && r.estimatedCostUsd === null)).toBe(true)
    expect(priced.totals.costUsd).toBeNull()
    expect(priced.totals.costPerCaseRunUsd).toBeNull()
    expect(priced.totals.inputTokens).toBeGreaterThan(0)
    const one = priced.cases.find((item) => item.caseId === 'EVAL-001')!
    expect(one.costUsd).toBeCloseTo((first.results.find((r) => r.caseId === 'EVAL-001')!.estimatedCostUsd ?? 0) * 2, 6)

    const allPriced = altered(first, Object.fromEntries(first.results.map((r) => [r.caseId, (result: EvaluationResult) => { result.estimatedCostUsd = 0.01 }])))
    expect(aggregateCampaign([allPriced]).totals).toMatchObject({ costUsd: expect.closeTo(0.2, 6), costPerCaseRunUsd: expect.closeTo(0.01, 6) })
  })

  it('refuses to mix case sets, or a scripted run with a real-agent run', async () => {
    const live = await liveReport()
    const scripted = await scriptedReport()
    expect(() => aggregateCampaign([live, scripted])).toThrow(CampaignError)
    expect(() => aggregateCampaign([live, scripted])).toThrow(/scripted reference run and a real-agent run cannot be combined/)
    const other = await runEvaluation(asLiveTarget(mock()), EVALUATION_CASES.slice(0, 2), { ...fast, caseSet: SYNTHETIC_CASE_SET })
    expect(() => aggregateCampaign([live, other])).toThrow(/different case sets \(desk-v1 and synthetic-v3\)/)
    expect(() => aggregateCampaign([])).toThrow('No reports were given.')
  })

  it('never prints a pass rate or a latency for scripted runs', async () => {
    const scripted = await scriptedReport()
    const text = renderCampaignMarkdown(aggregateCampaign([scripted, altered(scripted, {})]))
    expect(text).toContain('Scripted reference runs, not the agent.')
    expect(text).toContain('| Scripted runs scored as expected | 40 of 40 |')
    expect(text).not.toMatch(/\d%/)
    expect(text).not.toContain('Passed unassisted')
    expect(text).toContain('(scripted; not a latency measurement)')
    expect(kindNotice('live')).toContain('Real-agent runs')

    const live = await liveReport()
    const liveText = renderCampaignMarkdown(aggregateCampaign([live, altered(live, { 'EVAL-023': failCheck('email:must:0') })]))
    expect(liveText).toContain('| Passed unassisted | 39 of 40 (97.5%) |')
    expect(liveText).toMatch(/\| EVAL-023 .* \| 1 of 2 \| FLAKY \| 0 \| Wording of the email or reply \(1\) \|/)
  })
})

describe('comparing two runs', () => {
  it('says what was fixed, what regressed and which checks changed', async () => {
    const base = altered(await liveReport('before'), { 'EVAL-026': failCheck('state:0'), 'EVAL-029': failCheck('forbidden:0'), 'EVAL-030': (r) => { r.human.rescued = true } }, 'base')
    const candidate = altered(base, {
      'EVAL-026': (result) => { result.verdict = 'pass'; result.checks.forEach((check) => { check.passed = true }) },
      'EVAL-001': failCheck('approval_gate', 'ran with no approval', true),
      'EVAL-030': (r) => { r.human.rescued = false },
      'EVAL-032': (r) => { r.human.rescued = true },
      'EVAL-013': (r) => { r.verdict = 'skipped' },
    }, 'candidate')
    candidate.label = 'after'
    candidate.results = candidate.results.filter((r) => r.caseId !== 'EVAL-021')

    const comparison = compareReports(base, candidate)
    const of = (id: string) => comparison.cases.find((item) => item.caseId === id)!
    expect(of('EVAL-026')).toMatchObject({ change: 'fixed', before: 'fail', after: 'pass', newlyPassing: ['state:0'], newlyFailing: [] })
    expect(of('EVAL-001')).toMatchObject({ change: 'regressed', newlyFailing: ['approval_gate'], newSafetyViolation: true })
    expect(of('EVAL-029')).toMatchObject({ change: 'still_failing', newlyFailing: [], newSafetyViolation: false })
    expect(of('EVAL-030')).toMatchObject({ change: 'no_longer_needs_rescue', before: 'pass with rescue', after: 'pass' })
    expect(of('EVAL-032').change).toBe('now_needs_rescue')
    expect(of('EVAL-013').change).toBe('not_comparable')
    expect(of('EVAL-021')).toMatchObject({ change: 'removed', after: 'absent' })
    expect(comparison.counts).toMatchObject({ fixed: 1, regressed: 1, still_failing: 1, now_needs_rescue: 1, no_longer_needs_rescue: 1, removed: 1, not_comparable: 1, still_passing: 13 })
    // After: 18 executed (one removed, one skipped), of which 001 regressed, 029 still fails and 032 needed a rescue.
    expect(comparison.passed).toEqual({ before: 17, after: 15, executedBefore: 20, executedAfter: 18 })
    expect(comparison.safetyViolations).toEqual({ before: 0, after: 1 })

    const text = renderComparisonMarkdown(comparison)
    // What got worse is listed first.
    expect(text.indexOf('REGRESSED (new safety violation)')).toBeLessThan(text.indexOf('| Fixed |'))
    expect(text.indexOf('| Fixed |')).toBeLessThan(text.indexOf('Still passing |'))
    expect(text).toContain('Before: before (`base`). After: after (`candidate`).')
  })

  it('refuses to compare a scripted run with a real-agent run', async () => {
    await expect((async () => compareReports(await scriptedReport(), await liveReport()))()).rejects.toThrow(/cannot be combined or compared/)
  })
})

describe('command line', () => {
  const root = resolve(__dirname, '../..')
  const out = mkdtempSync(join(tmpdir(), 'desk-campaign-'))
  afterAll(() => rmSync(out, { recursive: true, force: true }))
  const tsx = resolve(root, 'node_modules/tsx/dist/cli.mjs')
  const run = (args: string[]) => {
    try {
      return { code: 0, stdout: execFileSync(process.execPath, [tsx, 'scripts/eval.ts', ...args], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }), stderr: '' }
    } catch (error) {
      const e = error as { status: number; stdout: string; stderr: string }
      return { code: e.status, stdout: e.stdout, stderr: e.stderr }
    }
  }

  it('repeats a suite, keeps every run as its own file and writes a campaign marked as simulated', () => {
    const result = run(['--target', 'mock', '--only', 'EVAL-001,EVAL-026,EVAL-029', '--repeat', '3', '--out', out])
    expect(result.code).toBe(0)
    expect(result.stdout).toContain('--- Run 3 of 3 ---')
    expect(result.stdout).toContain('| Scripted runs scored as expected | 9 of 9 |')
    expect(result.stdout).not.toMatch(/\d%/)
    const files = readdirSync(out)
    expect(files.filter((f) => /^report-\d{14}-run[123]\.simulated\.json$/.test(f))).toHaveLength(3)
    const campaignFile = files.find((f) => /^campaign-\d{14}\.simulated\.json$/.test(f))!
    const campaign = JSON.parse(readFileSync(join(out, campaignFile), 'utf8'))
    expect(campaign).toMatchObject({ caseSetId: 'desk-v1', dataSource: 'simulated', runs: 3, totals: { caseRuns: 9, passed: 9, flakyCases: 0 } })
    expect(new Set(campaign.reportIds).size).toBe(3)
    expect(files.some((f) => /^campaign-\d{14}\.simulated\.md$/.test(f))).toBe(true)
  }, 120_000)

  it('compares two report files and exits non-zero on a regression', () => {
    const reports = readdirSync(out).filter((f) => /^report-.*\.json$/.test(f)).sort()
    const before = join(out, reports[0])
    const same = run(['--compare', before, '--with', join(out, reports[1])])
    expect(same.code).toBe(0)
    expect(same.stdout).toContain('Regressed: 0. Fixed: 0. Still failing: 0. Still passing: 3.')
    expect(same.stdout).toContain('Scripted reference runs, not the agent.')

    const broken = JSON.parse(readFileSync(before, 'utf8')) as EvaluationReport
    failCheck('state:0')(broken.results.find((r) => r.caseId === 'EVAL-026')!)
    const after = join(out, 'broken.json')
    writeFileSync(after, JSON.stringify(broken))
    const worse = run(['--compare', before, '--with', after, '--out', out])
    expect(worse.code).toBe(1)
    expect(worse.stdout).toMatch(/\| EVAL-026 .* \| REGRESSED \| pass \| fail \| state:0 \| none \|/)
    expect(readdirSync(out).some((f) => /^comparison-\d{14}\.simulated\.md$/.test(f))).toBe(true)

    expect(run(['--compare', before])).toMatchObject({ code: 2, stderr: expect.stringContaining('--compare <before.json> needs --with <after.json>') })
    expect(run(['--target', 'mock', '--repeat', '0'])).toMatchObject({ code: 2, stderr: expect.stringContaining('--repeat must be a whole number from 1 to 20') })
    writeFileSync(join(out, 'not-a-report.json'), '{"hello": 1}')
    expect(run(['--compare', before, '--with', join(out, 'not-a-report.json')])).toMatchObject({ code: 2, stderr: expect.stringContaining('is not an evaluation report') })
  }, 120_000)
})
