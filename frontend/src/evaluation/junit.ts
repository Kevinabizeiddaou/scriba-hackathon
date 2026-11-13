/** Renders an evaluation report as JUnit XML, for CI systems that read test results in that format. */
import type { EvaluationReport, EvaluationResult } from '../harness/types';

function esc(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '');
}

function testCase(result: EvaluationResult): string {
  const attrs = `classname="${esc(result.category)}" name="${esc(`${result.caseId} ${result.caseTitle}`)}" time="${(result.timing.wallClockMs / 1000).toFixed(3)}"`;
  if (result.verdict === 'pass') return `    <testcase ${attrs}/>`;
  if (result.verdict === 'skipped') return `    <testcase ${attrs}>\n      <skipped message="${esc(result.skipReason ?? 'not executed')}"/>\n    </testcase>`;

  const failedChecks = result.checks.filter((c) => !c.passed);
  if (result.verdict === 'error') {
    const first = result.errors[0];
    const body = result.errors.map((e) => `${e.source}/${e.code}: ${e.message}`).join('\n');
    return `    <testcase ${attrs}>\n      <error type="${esc(first?.code ?? 'error')}" message="${esc(first?.message ?? 'The case could not be scored.')}">${esc(body)}</error>\n    </testcase>`;
  }
  const body = failedChecks.map((c) => `${c.safety ? '[safety] ' : ''}${c.label}\n  expected: ${c.expected}\n  actual:   ${c.actual}`).join('\n');
  const message = `${failedChecks.length} check(s) failed: ${failedChecks.map((c) => c.id).join(', ')}`;
  return `    <testcase ${attrs}>\n      <failure type="${failedChecks.some((c) => c.safety) ? 'safety' : 'expectation'}" message="${esc(message)}">${esc(body)}</failure>\n    </testcase>`;
}

export function toJUnit(report: EvaluationReport): string {
  const s = report.summary;
  const seconds = report.results.reduce((sum, r) => sum + r.timing.wallClockMs, 0) / 1000;
  const properties = [
    ['reportId', report.id],
    ['label', report.label],
    ['target', report.target.name],
    ['dataSource', report.target.dataSource],
    ['caseSet', report.caseSet.id],
    ['provenance', report.caseSet.provenance],
    ['contractVersion', report.contractVersion],
    ['harnessVersion', report.harnessVersion],
    ['humanRescues', String(s.rescued)],
    ['mandatoryApprovals', String(s.mandatoryApprovals)],
  ];
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<testsuites name="executive-desk-evaluation" tests="${s.total}" failures="${s.failed}" errors="${s.errored}" skipped="${s.skipped}" time="${seconds.toFixed(3)}">`,
    `  <testsuite name="${esc(`${report.caseSet.id} (${report.target.dataSource})`)}" tests="${s.total}" failures="${s.failed}" errors="${s.errored}" skipped="${s.skipped}" time="${seconds.toFixed(3)}" timestamp="${esc(report.startedAt)}">`,
    '    <properties>',
    ...properties.map(([name, value]) => `      <property name="${esc(name)}" value="${esc(value)}"/>`),
    '    </properties>',
    ...report.results.map(testCase),
    '  </testsuite>',
    '</testsuites>',
    '',
  ].join('\n');
}
