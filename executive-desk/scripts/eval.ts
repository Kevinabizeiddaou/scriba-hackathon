/**
 * Command-line evaluation runner.
 *
 *   npm run eval                                  harness self-test against the scripted mock
 *   npm run eval -- --base-url http://localhost:8000/api/executive-desk
 *                                                 run the twenty cases against a real backend
 *
 * Options (real backend):
 *   --base-url <url>        backend root, as in docs/API_CONTRACT.md
 *   --token-env <NAME>      read a bearer token from this environment variable (never pass a token as an argument)
 *   --only <ids>            comma-separated case ids to run, e.g. EVAL-001,EVAL-008
 *   --skip <ids>            comma-separated case ids to skip
 *   --label <text>          label stored in the report
 *   --out <dir>             where to write the report JSON (default: eval-results)
 *   --snapshot <day>        friday | saturday | sunday: also save the summary as that day's snapshot
 *   --pricing <file>        JSON price table: { "<model>": { "inputPerMTokUsd": n, "outputPerMTokUsd": n } }
 *   --timeout <ms>          per-case timeout (default 120000)
 *   --poll <ms>             poll interval (default 500)
 *   --allow-real-side-effects   do not fail side effects that are not marked simulated. Use with care.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { HttpExecutiveDesk } from '../src/api/httpAdapter';
import type { EvaluationReport, EvaluationResult, SnapshotDay } from '../src/api/types';
import { EVALUATION_CASES, SYNTHETIC_CASE_SET } from '../src/evaluation/fixtures';
import { PRINCIPAL } from '../src/evaluation/fixtures/world';
import { parsePriceTable, type PriceTable } from '../src/evaluation/pricing';
import { buildSnapshot } from '../src/evaluation/report';
import { runEvaluation } from '../src/evaluation/runner';
import { runSelfTest } from '../src/evaluation/selfTest';
import { fmtDuration } from '../src/lib/time';

function parseArgs(argv: string[]): Record<string, string | true> {
  const args: Record<string, string | true> = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) throw new Error(`Unexpected argument: ${arg}`);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) args[arg.slice(2)] = true;
    else {
      args[arg.slice(2)] = next;
      i += 1;
    }
  }
  return args;
}

const str = (value: string | true | undefined): string | undefined => (typeof value === 'string' ? value : undefined);
const pad = (text: string, width: number) => (text.length > width ? `${text.slice(0, width - 1)}…` : text.padEnd(width));

function printResult(r: EvaluationResult): void {
  const cost = r.estimatedCostUsd === null ? '-' : `$${r.estimatedCostUsd.toFixed(4)}`;
  const human = `${r.human.mandatoryApprovals} appr${r.human.rescued ? ', RESCUED' : ''}`;
  console.log(`${pad(r.caseId, 9)} ${pad(r.verdict.toUpperCase(), 8)} ${pad(r.caseTitle, 52)} ${pad(fmtDuration(r.timing.wallClockMs), 10)} ${pad(human, 16)} ${cost}`);
  for (const c of r.checks.filter((x) => !x.passed)) console.log(`            x ${c.label}\n              expected: ${c.expected}\n              actual:   ${c.actual}`);
  if (r.verdict === 'error') for (const e of r.errors) console.log(`            ! ${e.source}/${e.code}: ${e.message}`);
  if (r.skipReason) console.log(`            - ${r.skipReason}`);
}

function printSummary(report: EvaluationReport): void {
  const s = report.summary;
  const pct = s.passRate === null ? 'n/a' : `${(s.passRate * 100).toFixed(1)}%`;
  console.log('');
  console.log(`Target:               ${report.target.name} (${report.target.dataSource})`);
  console.log(`Cases:                ${s.executed} executed of ${s.total}, ${s.skipped} skipped`);
  console.log(`Passed unassisted:    ${s.passedUnassisted} (${pct})   passed with rescue: ${s.passed - s.passedUnassisted}   failed: ${s.failed}   errors: ${s.errored}`);
  console.log(`Human involvement:    ${s.mandatoryApprovals} mandatory approvals, ${s.rescued} rescues, ${s.unexpectedApprovals} unexpected approval requests`);
  console.log(`Latency:              ${s.latency ? `median ${fmtDuration(s.latency.medianMs)}, p95 ${fmtDuration(s.latency.p95Ms)}` : 'n/a'}`);
  console.log(`Tokens:               ${s.casesWithUsage > 0 ? `${s.totalInputTokens} in, ${s.totalOutputTokens} out (${s.casesWithUsage} cases reported usage)` : 'not reported by the target'}`);
  console.log(`Cost per run:         ${s.costPerRunUsd === null ? 'n/a (no usage or no pricing)' : `$${s.costPerRunUsd.toFixed(4)} over ${s.casesWithCost} cases`}`);
}

async function selfTest(): Promise<number> {
  console.log('Harness self-test against the scripted mock. No model is called and nothing is sent.');
  console.log('These results show whether the harness works. They are not agent performance.\n');
  const report = await runSelfTest();
  console.log(`Reference scripts scored as passing:   ${report.referenceAsExpected}/${report.reference.results.length}`);
  for (const r of report.reference.results.filter((x) => x.verdict !== 'pass')) printResult(r);
  console.log(`Planted defects caught as intended:    ${report.probesAsExpected}/${report.probes.length}`);
  for (const p of report.probes) {
    const failed = p.result.checks.filter((c) => !c.passed).map((c) => c.id).join(', ') || (p.result.human.rescued ? 'rescue flagged' : p.result.errors.map((e) => e.code).join(', ') || '-');
    console.log(`  ${p.asExpected ? 'ok  ' : 'MISS'} ${pad(p.probe.id, 20)} ${pad(p.probe.caseId, 9)} ${pad(p.result.verdict, 6)} ${failed}${p.mismatch ? `\n       ${p.mismatch}` : ''}`);
  }
  console.log(report.allAsExpected ? '\nSelf-test passed.' : '\nSelf-test FAILED: the harness does not behave as specified.');
  return report.allAsExpected ? 0 : 1;
}

async function main(): Promise<number> {
  const args = parseArgs(process.argv.slice(2));
  const baseUrl = str(args['base-url']);
  if (!baseUrl) {
    if (args.snapshot) throw new Error('--snapshot needs a real backend (--base-url). Simulated results are never saved as snapshots.');
    return selfTest();
  }

  const tokenEnv = str(args['token-env']);
  const token = tokenEnv ? process.env[tokenEnv] : undefined;
  if (tokenEnv && !token) throw new Error(`Environment variable ${tokenEnv} is not set.`);

  const only = str(args.only)?.split(',').map((s) => s.trim());
  const skipIds = str(args.skip)?.split(',').map((s) => s.trim()) ?? [];
  const known = new Set(EVALUATION_CASES.map((c) => c.id));
  for (const id of [...(only ?? []), ...skipIds]) if (!known.has(id)) throw new Error(`Unknown case id: ${id}`);

  const snapshotDay = str(args.snapshot) as SnapshotDay | undefined;
  if (snapshotDay && !['friday', 'saturday', 'sunday'].includes(snapshotDay)) throw new Error('--snapshot must be friday, saturday or sunday.');
  if (snapshotDay && (only || skipIds.length > 0)) throw new Error('A snapshot must cover all twenty cases. Remove --only and --skip.');

  let pricing: PriceTable | undefined;
  const pricingFile = str(args.pricing);
  if (pricingFile) pricing = parsePriceTable(JSON.parse(readFileSync(pricingFile, 'utf8')));

  const target = new HttpExecutiveDesk({
    baseUrl: baseUrl.replace(/\/$/, ''),
    principal: { name: PRINCIPAL.name, email: PRINCIPAL.email, timezone: PRINCIPAL.timezone },
    getToken: () => token ?? null,
  });

  const cases = EVALUATION_CASES.filter((c) => !only || only.includes(c.id));
  console.log(`Running ${cases.length} case(s) against ${baseUrl}\n`);
  const report = await runEvaluation(target, cases, {
    label: str(args.label) ?? `Evaluation ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`,
    caseSet: SYNTHETIC_CASE_SET,
    skip: Object.fromEntries(skipIds.map((id) => [id, 'Skipped with --skip.'])),
    pricing,
    timeoutMs: Number(str(args.timeout) ?? 120_000),
    pollIntervalMs: Number(str(args.poll) ?? 500),
    requireSimulated: args['allow-real-side-effects'] !== true,
    onProgress: ({ last, current }) => {
      if (last && current !== last.caseId) printResult(last);
    },
  });
  // onProgress reports each result when the next case starts; print nothing twice.
  printSummary(report);

  const outDir = resolve(str(args.out) ?? 'eval-results');
  mkdirSync(outDir, { recursive: true });
  const file = resolve(outDir, `${report.id}.json`);
  writeFileSync(file, `${JSON.stringify(report, null, 2)}\n`);
  console.log(`\nReport written to ${file}`);

  if (snapshotDay) {
    const snapshotDir = resolve(outDir, 'snapshots');
    mkdirSync(snapshotDir, { recursive: true });
    const snapshotFile = resolve(snapshotDir, `${snapshotDay}.json`);
    writeFileSync(snapshotFile, `${JSON.stringify(buildSnapshot(report, snapshotDay, new Date().toISOString()), null, 2)}\n`);
    console.log(`Snapshot written to ${snapshotFile}. Commit it to show it on the dashboard.`);
  }

  return report.summary.failed + report.summary.errored > 0 ? 1 : 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(`Error: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(2);
  });
