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
 *   --scriba-url <url>      a Scriba API root, e.g. http://localhost:8788. The backend is asked whether it has
 *                           sandbox evaluation routes before anything is sent; the base URL becomes <url>/desk/eval/v1
 *   --signin                with --scriba-url: sign in with POST /auth/signin using EVAL_EMAIL and EVAL_PASSWORD from the
 *                           environment, and use the session cookie Scriba sets for the run
 *   --cookie-env <NAME>     read the Cookie header of an existing Scriba session from this environment variable
 *                           (never pass a session value or a password as an argument)
 *   --suite <name>          built-in suite: desk (default), scheduling, holdout (reworded variations of desk), or all
 *   --cases <file>          case-set file to run instead of a built-in suite
 *   --only <ids>            comma-separated case ids to run
 *   --skip <ids>            comma-separated case ids to skip
 *   --repeat <n>            run the selected cases n times (2 to 20) and write a reliability campaign
 *   --compare <file>        compare two report files instead of running anything; needs --with
 *   --with <file>           the report to compare against the one given to --compare
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
import type { EvaluationTarget } from '../src/harness/client';
import { HttpExecutiveDesk } from '../src/harness/httpAdapter';
import { DESK_ORIGIN, EVALUATION_BASE_PATH, probeEvaluationSupport, signInToScriba } from '../src/evaluation/scribaSession';
import { MockExecutiveDesk } from '../src/harness/mock/mockAdapter';
import type { CaseSetInfo, EvaluationCase, EvaluationReport, EvaluationResult, SnapshotDay } from '../src/harness/types';
import { loadCaseSet } from '../src/evaluation/caseSets';
import { AREA_LABEL, SUITES, type SuiteName } from '../src/evaluation/fixtures';
import { toJUnit } from '../src/evaluation/junit';
import { parsePriceTable, type PriceTable } from '../src/evaluation/pricing';
import { buildSnapshot, isReport, snapshotBlocker, summarizeByArea } from '../src/evaluation/report';
import { aggregateCampaign, compareReports, renderCampaignMarkdown, renderComparisonMarkdown } from '../src/evaluation/campaign';
import { runEvaluation } from '../src/evaluation/runner';
import { runSelfTest } from '../src/evaluation/selfTest';
import { fmtDuration } from '../src/lib/time';

const KNOWN = ['target', 'base-url', 'scriba-url', 'signin', 'cookie-env', 'suite', 'cases', 'only', 'skip', 'repeat', 'compare', 'with', 'label', 'out', 'junit', 'print-json', 'snapshot', 'pricing', 'timeout', 'poll', 'request-timeout', 'allow-real-side-effects', 'self-test'];

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

const stamp = () => new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
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
  for (const row of summarizeByArea(report.results)) {
    const counts = live ? `${row.passedUnassisted} of ${row.executed} passed unassisted` : `${row.passedUnassisted} of ${row.executed} scripted runs as expected`;
    say(`  ${pad(AREA_LABEL[row.area], 22)}${counts}${row.failed ? `, ${row.failed} failed` : ''}${row.errored ? `, ${row.errored} errors` : ''}${row.total > row.executed ? `, ${row.total - row.executed} skipped` : ''}`);
  }
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

  const compareFile = str(args.compare);
  if (compareFile || args.with) {
    const withFile = str(args.with);
    if (!compareFile || !withFile) throw new Error('--compare <before.json> needs --with <after.json>.');
    const load = (file: string) => {
      const parsed: unknown = JSON.parse(readFileSync(file, 'utf8'));
      if (!isReport(parsed)) throw new Error(`${file} is not an evaluation report.`);
      return parsed;
    };
    const comparison = compareReports(load(compareFile), load(withFile));
    const markdown = renderComparisonMarkdown(comparison);
    console.log(markdown);
    if (args.out) {
      const outDir = resolve(str(args.out)!);
      mkdirSync(outDir, { recursive: true });
      const file = resolve(outDir, `comparison-${stamp()}${comparison.dataSource === 'live' ? '' : '.simulated'}.md`);
      writeFileSync(file, markdown);
      console.error(`Comparison written to ${file}`);
    }
    // A regression or a new safety violation is a failing exit code, so a script can gate on it.
    return comparison.counts.regressed + comparison.cases.filter((item) => item.newSafetyViolation).length > 0 ? 1 : 0;
  }

  const repeat = Number(str(args.repeat) ?? 1);
  if (!Number.isInteger(repeat) || repeat < 1 || repeat > 20) throw new Error('--repeat must be a whole number from 1 to 20.');

  const scribaUrl = str(args['scriba-url'])?.replace(/[/]+$/, '');
  if (args.signin === true && !scribaUrl) throw new Error('--signin needs --scriba-url.');
  const baseUrl = str(args['base-url']) ?? (scribaUrl ? `${scribaUrl}${EVALUATION_BASE_PATH}` : undefined);
  const targetKind = str(args.target) ?? (baseUrl ? 'http' : null);
  if (args['self-test'] || targetKind === null) {
    if (args.snapshot) throw new Error('--snapshot needs a real backend (--base-url). Simulated results are never saved as snapshots.');
    return selfTest();
  }
  if (targetKind !== 'mock' && targetKind !== 'http') throw new Error('--target must be mock or http.');
  if (targetKind === 'http' && !baseUrl) throw new Error('--target http needs --base-url.');

  // Which cases.
  const suiteName = str(args.suite) ?? 'desk';
  if (!(suiteName in SUITES)) throw new Error(`--suite must be one of: ${Object.keys(SUITES).join(', ')}.`);
  let cases: EvaluationCase[] = SUITES[suiteName as SuiteName].cases;
  let caseSet: CaseSetInfo = SUITES[suiteName as SuiteName].caseSet;
  const casesFile = str(args.cases);
  if (casesFile && args.suite) throw new Error('Use --suite or --cases, not both.');
  if (casesFile) ({ cases, caseSet } = loadCaseSet(JSON.parse(readFileSync(casesFile, 'utf8'))));

  const only = str(args.only)?.split(',').map((s) => s.trim());
  const skipIds = str(args.skip)?.split(',').map((s) => s.trim()) ?? [];
  const known = new Set(cases.map((c) => c.id));
  for (const id of [...(only ?? []), ...skipIds]) if (!known.has(id)) throw new Error(`Unknown case id: ${id}`);

  const snapshotDay = str(args.snapshot) as SnapshotDay | undefined;
  if (snapshotDay && !['friday', 'saturday', 'sunday'].includes(snapshotDay)) throw new Error('--snapshot must be friday, saturday or sunday.');
  if (snapshotDay && targetKind !== 'http') throw new Error('--snapshot needs a real backend. Simulated results are never saved as snapshots.');
  if (snapshotDay && (only || skipIds.length > 0)) throw new Error('A snapshot must cover the whole case set. Remove --only and --skip.');
  if (snapshotDay && repeat > 1) throw new Error('A snapshot is one run. Remove --repeat.');

  let pricing: PriceTable | undefined;
  const pricingFile = str(args.pricing);
  if (pricingFile) pricing = parsePriceTable(JSON.parse(readFileSync(pricingFile, 'utf8')));

  // Which target.
  let target: EvaluationTarget;
  if (targetKind === 'mock') {
    target = new MockExecutiveDesk({ stepDelayMs: 0, seed: false });
  } else {
    const cookieEnv = str(args['cookie-env']);
    let cookie = cookieEnv ? process.env[cookieEnv] : undefined;
    if (cookieEnv && !cookie) throw new Error(`Environment variable ${cookieEnv} is not set.`);
    if (scribaUrl) {
      // A Scriba backend: authenticate the way Scriba does (session cookie, Desk origin), then ask
      // whether it can be evaluated at all. Nothing is posted to a backend without sandbox routes.
      if (args.signin === true) {
        const email = process.env.EVAL_EMAIL;
        const password = process.env.EVAL_PASSWORD;
        if (!email || !password) throw new Error('--signin needs EVAL_EMAIL and EVAL_PASSWORD in the environment.');
        cookie = await signInToScriba({ apiRoot: scribaUrl, email, password });
        say('Signed in to Scriba. The session is kept in memory for this run only.');
      }
      const support = await probeEvaluationSupport({ apiRoot: scribaUrl, cookie: cookie ?? null });
      if (!support.supported) throw new Error(support.detail);
    }
    target = new HttpExecutiveDesk({
      baseUrl: baseUrl!.replace(/\/$/, ''),
      sessionCookie: () => cookie ?? null,
      origin: scribaUrl ? DESK_ORIGIN : undefined,
      timeoutMs: Number(str(args['request-timeout']) ?? 15_000),
    });
    // Fail early, with the real reason, if the backend is unreachable or speaks another contract.
    const meta = await target.getMeta();
    say(`Connected to ${meta.service}: contract ${meta.contractVersion}, agent ${meta.agent}, sandbox ${meta.sandbox}.`);
  }

  const selected = cases.filter((c) => !only || only.includes(c.id));
  say(`Running ${selected.length} ${caseSet.provenance} case(s) from ${caseSet.id} against ${targetKind === 'mock' ? 'the scripted mock' : baseUrl}\n`);
  const baseLabel = str(args.label) ?? `${targetKind === 'mock' ? 'Scripted mock' : 'Evaluation'} ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`;
  const outDir = resolve(str(args.out) ?? 'eval-results');
  mkdirSync(outDir, { recursive: true });
  const reports: EvaluationReport[] = [];
  let report!: EvaluationReport;
  let json = '';
  for (let round = 1; round <= repeat; round += 1) {
  if (repeat > 1) say(`\n--- Run ${round} of ${repeat} ---`);
  report = await runEvaluation(target, selected, {
    label: repeat > 1 ? `${baseLabel} (run ${round} of ${repeat})` : baseLabel,
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

  // Runs of a campaign can finish within the same second; each keeps its own id and file.
  if (repeat > 1) report.id = `${report.id}-run${round}`;
  const file = resolve(outDir, `${report.id}${report.target.dataSource === 'live' ? '' : '.simulated'}.json`);
  json = `${JSON.stringify(report, null, 2)}\n`;
  writeFileSync(file, json);
  say(`\nReport written to ${file}`);
  reports.push(report);
  }

  if (repeat > 1) {
    const campaign = aggregateCampaign(reports);
    const suffix = campaign.dataSource === 'live' ? '' : '.simulated';
    const name = `campaign-${stamp()}`;
    writeFileSync(resolve(outDir, `${name}${suffix}.json`), `${JSON.stringify(campaign, null, 2)}\n`);
    const markdown = renderCampaignMarkdown(campaign);
    writeFileSync(resolve(outDir, `${name}${suffix}.md`), markdown);
    say(`\n${markdown}`);
    say(`Campaign written to ${resolve(outDir, `${name}${suffix}.md`)} and .json`);
  }

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
  return reports.some((item) => item.summary.failed + item.summary.errored > 0) ? 1 : 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(`Error: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(2);
  });
