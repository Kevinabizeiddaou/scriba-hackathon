/**
 * Command-line evaluation runner.
 *
 *   npm run eval                              harness self-test (reference scripts and planted defects)
 *   npm run eval -- --target mock             run the cases against the scripted mock, write a report
 *   npm run eval -- --base-url <url>          run the cases against a backend over HTTP
 *
 * Options
 *   --target <mock|http>    where to run. Defaults to http when --base-url is given.
 *   --base-url <url>        backend root including the version, e.g. http://localhost:8000/api/executive-desk/v1
 *   --cookie-env <NAME>     read the Cookie header of an existing Scriba session from this environment variable
 *                           (never pass a session value as an argument)
 *   --cases <file>          case-set file to run instead of the built-in synthetic set
 *   --only <ids>            comma-separated case ids to run
 *   --skip <ids>            comma-separated case ids to skip
 *   --label <text>          label stored in the report
 *   --out <dir>             where the report is written (default: eval-results)
 *   --junit <file>          also write the results as JUnit XML
 *   --print-json            print the report JSON on stdout; progress goes to stderr
 *   --snapshot <day>        friday | saturday | sunday: freeze the summary as that day's snapshot (live, complete runs only)
 *   --pricing <file>        JSON price table: { "<model>": { "inputPerMTokUsd": n, "outputPerMTokUsd": n } }
 *   --timeout <ms>          time budget per case (default 120000)
 *   --poll <ms>             poll interval (default 500)
 *   --request-timeout <ms>  timeout of a single HTTP request (default 15000)
 *   --allow-real-side-effects   run against a backend that is not a sandbox. Use with great care.
 *
 * Exit code: 0 when every executed case passed, 1 when any failed or errored, 2 on a usage or connection problem.
 * The report is always written as JSON (format "executive-desk.evaluation-report/1").
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import type { EvaluationTarget } from '../src/api/client';
import { HttpExecutiveDesk } from '../src/api/httpAdapter';
import { MockExecutiveDesk } from '../src/api/mock/mockAdapter';
import type { CaseSetInfo, EvaluationCase, EvaluationReport, EvaluationResult, SnapshotDay } from '../src/api/types';
import { loadCaseSet } from '../src/evaluation/caseSets';
import { EVALUATION_CASES, SYNTHETIC_CASE_SET } from '../src/evaluation/fixtures';
import { toJUnit } from '../src/evaluation/junit';
import { parsePriceTable, type PriceTable } from '../src/evaluation/pricing';
import { buildSnapshot, snapshotBlocker } from '../src/evaluation/report';
import { runEvaluation } from '../src/evaluation/runner';
import { runSelfTest } from '../src/evaluation/selfTest';
import { fmtDuration } from '../src/lib/time';

const KNOWN = ['target', 'base-url', 'cookie-env', 'cases', 'only', 'skip', 'label', 'out', 'junit', 'print-json', 'snapshot', 'pricing', 'timeout', 'poll', 'request-timeout', 'allow-real-side-effects', 'self-test'];

function parseArgs(argv: string[]): Record<string, string | true> {
  const args: Record<string, string | true> = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) throw new Error(`Unexpected argument: ${arg}`);
    const name = arg.slice(2);
    if (!KNOWN.includes(name)) throw new Error(`Unknown option --${name}.`);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) args[name] = true;
    else {
      args[name] = next;
      i += 1;
    }
  }
  return args;
}

const str = (value: string | true | undefined): string | undefined => (typeof value === 'string' ? value : undefined);
const pad = (text: string, width: number) => (text.length > width ? `${text.slice(0, width - 1)}…` : text.padEnd(width));

/** Human-readable output. Goes to stderr when the report JSON is being printed on stdout. */
let say: (line: string) => void = (line) => console.log(line);

function printResult(r: EvaluationResult): void {
  const cost = r.estimatedCostUsd === null ? '-' : `$${r.estimatedCostUsd.toFixed(4)}`;
  const human = `${r.human.mandatoryApprovals} appr${r.human.rescued ? ', RESCUED' : ''}`;
  const time = r.dataSource === 'live' ? fmtDuration(r.timing.wallClockMs) : '-';
  say(`${pad(r.caseId, 9)} ${pad(r.verdict.toUpperCase(), 8)} ${pad(r.caseTitle, 52)} ${pad(time, 10)} ${pad(human, 16)} ${cost}`);
  if (r.verdict === 'fail' || r.verdict === 'error') {
    for (const c of r.checks.filter((x) => !x.passed && (r.verdict === 'fail' || x.safety))) {
      say(`            x ${c.safety ? '[safety] ' : ''}${c.label}\n              expected: ${c.expected}\n              actual:   ${c.actual}`);
    }
  }
  if (r.verdict === 'error') for (const e of r.errors) say(`            ! ${e.source}/${e.code}: ${e.message}`);
  if (r.skipReason) say(`            - ${r.skipReason}`);
}

function printSummary(report: EvaluationReport): void {
  const s = report.summary;
  const live = report.target.dataSource === 'live';
  const pct = s.passRate === null ? 'n/a' : `${(s.passRate * 100).toFixed(1)}%`;
  say('');
  say(`Target:               ${report.target.name} (${report.target.dataSource}${report.target.sandbox === null ? '' : report.target.sandbox ? ', sandbox' : ', NOT a sandbox'})`);
  say(`Case set:             ${report.caseSet.id} (${report.caseSet.provenance}), ${report.results.length} of ${report.caseSet.caseCount} cases in this run`);
  say(`Cases:                ${s.executed} executed, ${s.skipped} skipped`);
  // A percentage is an agent result. For a scripted target only the counts are shown.
  say(
    live
      ? `Passed unassisted:    ${s.passedUnassisted} (${pct})   passed with rescue: ${s.passed - s.passedUnassisted}   failed: ${s.failed}   errors: ${s.errored}`
      : `Scripts matching:     ${s.passed} of ${s.executed} scripted runs scored as expected   not matching: ${s.failed}   errors: ${s.errored}`,
  );
  say(`Human involvement:    ${s.mandatoryApprovals} mandatory approvals, ${s.rescued} rescues, ${s.unexpectedApprovals} unexpected approval requests`);
  say(`Latency:              ${!live ? 'not reported for a scripted target' : s.latency ? `median ${fmtDuration(s.latency.medianMs)}, p95 ${fmtDuration(s.latency.p95Ms)}` : 'n/a'}`);
  say(`Tokens:               ${s.casesWithUsage > 0 ? `${s.totalInputTokens} in, ${s.totalOutputTokens} out (${s.casesWithUsage} cases reported usage)` : 'not reported by the target'}`);
  say(`Cost per run:         ${s.costPerRunUsd === null ? 'n/a (no usage or no pricing)' : `$${s.costPerRunUsd.toFixed(4)} over ${s.casesWithCost} cases`}`);
  if (!live) say('\nThis target is a scripted stand-in. These results are simulated and say nothing about the agent.');
}

async function selfTest(): Promise<number> {
  say('Harness self-test against the scripted mock. No model is called and nothing is sent.');
  say('These results show whether the harness works. They are not agent performance.\n');
  const report = await runSelfTest();
  say(`Reference scripts scored as passing:   ${report.referenceAsExpected}/${report.reference.results.length}`);
  for (const r of report.reference.results.filter((x) => x.verdict !== 'pass')) printResult(r);
  say(`Planted defects caught as intended:    ${report.probesAsExpected}/${report.probes.length}`);
  for (const p of report.probes) {
    const failed = p.result.checks.filter((c) => !c.passed).map((c) => c.id).join(', ') || (p.result.human.rescued ? 'rescue flagged' : p.result.errors.map((e) => e.code).join(', ') || '-');
    say(`  ${p.asExpected ? 'ok  ' : 'MISS'} ${pad(p.probe.id, 24)} ${pad(p.probe.caseId, 9)} ${pad(p.result.verdict, 6)} ${failed}${p.mismatch ? `\n       ${p.mismatch}` : ''}`);
  }
  say(report.allAsExpected ? '\nSelf-test passed.' : '\nSelf-test FAILED: the harness does not behave as specified.');
  return report.allAsExpected ? 0 : 1;
}

async function main(): Promise<number> {
  const args = parseArgs(process.argv.slice(2));
  if (args['print-json']) say = (line) => console.error(line);

  const baseUrl = str(args['base-url']);
  const targetKind = str(args.target) ?? (baseUrl ? 'http' : null);
  if (args['self-test'] || targetKind === null) {
    if (args.snapshot) throw new Error('--snapshot needs a real backend (--base-url). Simulated results are never saved as snapshots.');
    return selfTest();
  }
  if (targetKind !== 'mock' && targetKind !== 'http') throw new Error('--target must be mock or http.');
  if (targetKind === 'http' && !baseUrl) throw new Error('--target http needs --base-url.');

  // Which cases.
  let cases: EvaluationCase[] = EVALUATION_CASES;
  let caseSet: CaseSetInfo = SYNTHETIC_CASE_SET;
  const casesFile = str(args.cases);
  if (casesFile) ({ cases, caseSet } = loadCaseSet(JSON.parse(readFileSync(casesFile, 'utf8'))));

  const only = str(args.only)?.split(',').map((s) => s.trim());
  const skipIds = str(args.skip)?.split(',').map((s) => s.trim()) ?? [];
  const known = new Set(cases.map((c) => c.id));
  for (const id of [...(only ?? []), ...skipIds]) if (!known.has(id)) throw new Error(`Unknown case id: ${id}`);

  const snapshotDay = str(args.snapshot) as SnapshotDay | undefined;
  if (snapshotDay && !['friday', 'saturday', 'sunday'].includes(snapshotDay)) throw new Error('--snapshot must be friday, saturday or sunday.');
  if (snapshotDay && targetKind !== 'http') throw new Error('--snapshot needs a real backend. Simulated results are never saved as snapshots.');
  if (snapshotDay && (only || skipIds.length > 0)) throw new Error('A snapshot must cover the whole case set. Remove --only and --skip.');

  let pricing: PriceTable | undefined;
  const pricingFile = str(args.pricing);
  if (pricingFile) pricing = parsePriceTable(JSON.parse(readFileSync(pricingFile, 'utf8')));

  // Which target.
  let target: EvaluationTarget;
  if (targetKind === 'mock') {
    target = new MockExecutiveDesk({ stepDelayMs: 0, seed: false });
  } else {
    const cookieEnv = str(args['cookie-env']);
    const cookie = cookieEnv ? process.env[cookieEnv] : undefined;
    if (cookieEnv && !cookie) throw new Error(`Environment variable ${cookieEnv} is not set.`);
    target = new HttpExecutiveDesk({
      baseUrl: baseUrl!.replace(/\/$/, ''),
      sessionCookie: () => cookie ?? null,
      timeoutMs: Number(str(args['request-timeout']) ?? 15_000),
    });
    // Fail early, with the real reason, if the backend is unreachable or speaks another contract.
    const meta = await target.getMeta();
    say(`Connected to ${meta.service}: contract ${meta.contractVersion}, agent ${meta.agent}, sandbox ${meta.sandbox}.`);
  }

  const selected = cases.filter((c) => !only || only.includes(c.id));
  say(`Running ${selected.length} ${caseSet.provenance} case(s) from ${caseSet.id} against ${targetKind === 'mock' ? 'the scripted mock' : baseUrl}\n`);
  const report = await runEvaluation(target, selected, {
    label: str(args.label) ?? `${targetKind === 'mock' ? 'Scripted mock' : 'Evaluation'} ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`,
    caseSet,
    skip: Object.fromEntries(skipIds.map((id) => [id, 'Skipped with --skip.'])),
    pricing,
    timeoutMs: Number(str(args.timeout) ?? 120_000),
    pollIntervalMs: Number(str(args.poll) ?? (targetKind === 'mock' ? 1 : 500)),
    requireSimulated: args['allow-real-side-effects'] !== true,
    onProgress: ({ last, current }) => {
      if (last && current !== last.caseId) printResult(last);
    },
  });
  printSummary(report);

  const outDir = resolve(str(args.out) ?? 'eval-results');
  mkdirSync(outDir, { recursive: true });
  const file = resolve(outDir, `${report.id}${report.target.dataSource === 'live' ? '' : '.simulated'}.json`);
  const json = `${JSON.stringify(report, null, 2)}\n`;
  writeFileSync(file, json);
  say(`\nReport written to ${file}`);

  const junitFile = str(args.junit);
  if (junitFile) {
    mkdirSync(dirname(resolve(junitFile)), { recursive: true });
    writeFileSync(resolve(junitFile), toJUnit(report));
    say(`JUnit XML written to ${resolve(junitFile)}`);
  }

  if (snapshotDay) {
    const blocker = snapshotBlocker(report);
    if (blocker) throw new Error(`No snapshot was saved. ${blocker}`);
    const snapshotDir = resolve(outDir, 'snapshots');
    mkdirSync(snapshotDir, { recursive: true });
    const snapshotFile = resolve(snapshotDir, `${snapshotDay}.json`);
    writeFileSync(snapshotFile, `${JSON.stringify(buildSnapshot(report, snapshotDay, new Date().toISOString()), null, 2)}\n`);
    say(`Snapshot written to ${snapshotFile}. Commit it to show it on the dashboard.`);
  }

  if (args['print-json']) process.stdout.write(json);
  return report.summary.failed + report.summary.errored > 0 ? 1 : 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(`Error: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(2);
  });
