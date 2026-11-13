import clsx from 'clsx';
import { ChevronDown, FlaskConical, Info, Play, Save, Square, Upload } from 'lucide-react';
import { Fragment, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from 'react';
import { evaluationSession, useEvaluationSession } from '../evaluation/session';
import { getApi } from '../api';
import type { EvaluationResult, EvaluationSnapshot, SnapshotDay, Verdict } from '../api/types';
import { CaseResult, CaseSpecification } from '../components/CaseDetail';
import { Button, ErrorNote, PageHeader, Pill, SimulatedTag } from '../components/ui';
import { CASE_CATEGORIES, EVALUATION_CASES, categoryLabel } from '../evaluation/fixtures';
import { SNAPSHOT_DAYS, snapshotBlocker } from '../evaluation/report';
import type { SelfTestReport } from '../evaluation/selfTest';
import { VERDICT, percent, usd } from '../lib/labels';
import { fmtDayTime, fmtDuration } from '../lib/time';

const NO_DATA = '—';

function Kpi({ label, value, caption, empty }: { label: string; value: string; caption: ReactNode; empty: boolean }) {
  return (
    <div className="card px-4 py-3.5">
      <p className="eyebrow">{label}</p>
      <p className={clsx('mt-1.5 text-[26px] font-bold leading-8 tabular-nums tracking-[-0.01em]', empty ? 'text-mute' : 'text-ink')} aria-label={empty ? `${label}: no data yet` : undefined}>
        {value}
      </p>
      <p className="mt-1 min-h-[34px] text-[12px] leading-[17px] text-mute">{caption}</p>
    </div>
  );
}

const CELL: Record<Verdict | 'none', string> = {
  pass: 'bg-ok/25 text-ok border-ok/40',
  fail: 'bg-danger/20 text-danger border-danger/40',
  error: 'bg-warn/20 text-warn border-warn/40',
  skipped: 'bg-white/[0.05] text-mute border-line-strong',
  none: 'border-dashed border-line-strong text-mute',
};
const CELL_MARK: Record<Verdict | 'none', string> = { pass: 'P', fail: 'F', error: 'E', skipped: 'S', none: '' };

function SnapshotCard({ day, label, date, snapshot, previous, timeZone }: { day: SnapshotDay; label: string; date: string; snapshot: EvaluationSnapshot | undefined; previous: EvaluationSnapshot | undefined; timeZone: string }) {
  if (!snapshot) {
    return (
      <div className="rounded-card border border-dashed border-line-strong px-4 py-3.5" data-testid={`snapshot-${day}`}>
        <p className="text-[14px] font-semibold text-ink">
          {label} <span className="font-normal text-mute">· {date}</span>
        </p>
        <p className="mt-2 text-[22px] font-bold leading-7 text-mute" aria-label="No snapshot yet">
          {NO_DATA}
        </p>
        <p className="mt-1 text-[12px] text-mute">No snapshot recorded yet.</p>
      </div>
    );
  }
  const s = snapshot.summary;
  const delta = previous?.summary.passRate != null && s.passRate != null ? (s.passRate - previous.summary.passRate) * 100 : null;
  return (
    <div className="card px-4 py-3.5" data-testid={`snapshot-${day}`}>
      <p className="text-[14px] font-semibold text-ink">
        {label} <span className="font-normal text-mute">· {date}</span>
      </p>
      <p className="mt-2 flex items-baseline gap-2">
        <span className="text-[22px] font-bold leading-7 tabular-nums text-ink">{s.passRate === null ? NO_DATA : percent(s.passRate)}</span>
        <span className="text-[12.5px] text-soft">
          {s.passedUnassisted} of {s.executed} unassisted
        </span>
        {delta !== null && (
          <span className={clsx('text-[12px] font-semibold tabular-nums', delta > 0 ? 'text-ok' : delta < 0 ? 'text-danger' : 'text-mute')}>
            {delta > 0 ? '+' : ''}
            {delta.toFixed(1)} pts vs previous day
          </span>
        )}
      </p>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-[12px]">
        <div>
          <dt className="text-mute">Rescues</dt>
          <dd className="tabular-nums text-ink">{s.rescued}</dd>
        </div>
        <div>
          <dt className="text-mute">Cost per run</dt>
          <dd className="tabular-nums text-ink">{s.costPerRunUsd === null ? NO_DATA : usd(s.costPerRunUsd)}</dd>
        </div>
        <div>
          <dt className="text-mute">Median latency</dt>
          <dd className="tabular-nums text-ink">{s.latency ? fmtDuration(s.latency.medianMs) : NO_DATA}</dd>
        </div>
      </dl>
      <p className="mt-2 truncate text-[11.5px] text-mute" title={snapshot.label}>
        {snapshot.label} · saved {fmtDayTime(snapshot.savedAt, timeZone)}
      </p>
    </div>
  );
}

function SelfTestPanel({ report }: { report: SelfTestReport }) {
  return (
    <section aria-label="Harness self-test result" className="card p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="text-[15px] font-semibold text-ink">Harness self-test</h2>
        <Pill tone={report.allAsExpected ? 'ok' : 'danger'}>{report.allAsExpected ? 'Harness behaves as specified' : 'Harness check failed'}</Pill>
        <SimulatedTag />
      </div>
      <p className="mt-2 max-w-3xl text-[13px] text-soft">
        The runner was pointed at the scripted mock. This checks the harness itself: that all twenty cases can be satisfied, and that a planted defect is caught by the right check. It is not a measurement of the agent, so the tiles above stay empty.
      </p>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-white/[0.04] px-3.5 py-2.5">
          <dt className="text-[12px] text-mute">Reference scripts scored as passing</dt>
          <dd className="text-[18px] font-bold tabular-nums text-ink">
            {report.referenceAsExpected} of {report.reference.results.length}
          </dd>
        </div>
        <div className="rounded-xl bg-white/[0.04] px-3.5 py-2.5">
          <dt className="text-[12px] text-mute">Planted defects caught as intended</dt>
          <dd className="text-[18px] font-bold tabular-nums text-ink">
            {report.probesAsExpected} of {report.probes.length}
          </dd>
        </div>
      </dl>
      <details className="mt-3">
        <summary className="cursor-pointer select-none text-[13px] font-medium text-accent hover:underline">Show the planted defects</summary>
        <div className="mt-2 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[620px] text-left text-[12.5px]">
            <thead className="bg-white/[0.03] text-mute">
              <tr>
                <th scope="col" className="px-3 py-2 font-semibold">Planted defect</th>
                <th scope="col" className="px-3 py-2 font-semibold">Case</th>
                <th scope="col" className="px-3 py-2 font-semibold">Harness verdict</th>
                <th scope="col" className="px-3 py-2 font-semibold">Caught by</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {report.probes.map(({ probe, result, asExpected, mismatch }) => (
                <tr key={probe.id}>
                  <td className="px-3 py-2 text-ink">{probe.label}</td>
                  <td className="px-3 py-2 font-mono text-[11.5px] text-soft">{probe.caseId}</td>
                  <td className="px-3 py-2">
                    <Pill tone={VERDICT[result.verdict].tone} icon={null}>
                      {VERDICT[result.verdict].label}
                      {result.human.rescued && ', rescue flagged'}
                    </Pill>
                  </td>
                  <td className={clsx('px-3 py-2', asExpected ? 'text-soft' : 'font-semibold text-danger')}>
                    {asExpected
                      ? result.checks.filter((c) => !c.passed).map((c) => c.id).join(', ') || (result.human.rescued ? 'rescue counter' : result.errors.map((e) => e.code).join(', '))
                      : `Not as intended: ${mismatch}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

export function EvaluationPage() {
  const api = getApi();
  const live = api.info.dataSource === 'live';
  const timeZone = api.info.principal.timezone;

  const { liveReport, selfTest, snapshots, progress, error, notice } = useEvaluationSession();
  const [openCase, setOpenCase] = useState<string | null>(null);
  const [category, setCategory] = useState<string>('all');
  const [snapshotDay, setSnapshotDay] = useState<SnapshotDay>('friday');
  const fileInput = useRef<HTMLInputElement>(null);

  const running = progress !== null;
  const summary = liveReport?.summary ?? null;
  // The case table shows live results when there are any; otherwise the self-test's scripted results, clearly tagged.
  const tableReport = liveReport ?? selfTest?.reference ?? null;
  const tableSimulated = tableReport?.target.dataSource === 'simulated';
  const results = useMemo(() => new Map<string, EvaluationResult>((tableReport?.results ?? []).map((r) => [r.caseId, r])), [tableReport]);
  const liveResults = useMemo(() => new Map<string, EvaluationResult>((liveReport?.results ?? []).map((r) => [r.caseId, r])), [liveReport]);
  const snapshotBlocked = liveReport ? snapshotBlocker(liveReport) : null;

  const runLive = () => void evaluationSession.runLive(api);
  const runCheck = () => void evaluationSession.runSelfTest();
  const saveDay = () => evaluationSession.saveSnapshot(snapshotDay);

  async function onImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) evaluationSession.importJson(await file.text());
  }

  const cases = category === 'all' ? EVALUATION_CASES : EVALUATION_CASES.filter((c) => c.category === category);
  const errorEvents = liveReport ? liveReport.results.reduce((n, r) => n + r.errors.length, 0) : 0;

  return (
    <div>
      <PageHeader
        title="Evaluation Dashboard"
        subtitle="Twenty synthetic meeting-coordination cases, scored automatically. Numbers appear only after a run against the real backend."
        actions={
          <>
            <input ref={fileInput} type="file" accept="application/json,.json" className="sr-only" aria-label="Import evaluation results" onChange={onImport} tabIndex={-1} />
            <Button variant="secondary" icon={Upload} onClick={() => fileInput.current?.click()} disabled={running}>
              Import results
            </Button>
            {live ? (
              running ? (
                <Button variant="danger" icon={Square} onClick={() => evaluationSession.stop()}>
                  Stop after this case
                </Button>
              ) : (
                <Button variant="primary" icon={Play} onClick={runLive}>
                  Run evaluation
                </Button>
              )
            ) : (
              <Button variant="primary" icon={FlaskConical} busy={running} onClick={runCheck}>
                Run harness self-test
              </Button>
            )}
          </>
        }
      />

      <div className="space-y-5 px-4 pb-12 sm:px-6 lg:px-8">
        {error && <ErrorNote error={error} />}
        {notice && (
          <p role="status" className="rounded-btn border border-ok/25 bg-ok/[0.07] px-3.5 py-2.5 text-[13px] text-ok">
            {notice}
          </p>
        )}

        {running && progress && (
          <div role="status" className="card px-4 py-3">
            <div className="flex items-center justify-between text-[13px]">
              <span className="text-ink">{progress.current ? `Running ${progress.current}` : 'Running'}</span>
              <span className="tabular-nums text-mute">
                {progress.done} of {progress.total}
              </span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.08]">
              <div className="h-full origin-left rounded-full bg-accent transition-transform duration-200 ease-out" style={{ transform: `scaleX(${progress.total ? progress.done / progress.total : 0})` }} />
            </div>
          </div>
        )}

        {!liveReport && (
          <div className="flex gap-3 rounded-card border border-info/25 bg-info/[0.06] px-4 py-3.5 text-[13px]" data-testid="no-live-data">
            <Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-info" />
            <div className="min-w-0 space-y-1 text-soft">
              <p className="font-semibold text-ink">No real evaluation has been run yet.</p>
              <p>
                Pass rate, intervention count, cost and latency stay empty until the cases run against the real backend. Run{' '}
                <code className="rounded bg-white/[0.08] px-1.5 py-0.5 font-mono text-[12px] text-ink">npm run eval -- --base-url &lt;backend&gt;</code> and import the report, or start the app with{' '}
                <code className="rounded bg-white/[0.08] px-1.5 py-0.5 font-mono text-[12px] text-ink">VITE_API_MODE=http</code> and run it from here.
              </p>
            </div>
          </div>
        )}

        {/* Headline numbers: live data only */}
        <section aria-label="Headline results" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
          <Kpi label="Cases executed" empty={!summary} value={summary ? `${summary.executed} / ${EVALUATION_CASES.length}` : `0 / ${EVALUATION_CASES.length}`} caption={summary ? `${summary.skipped} skipped` : 'Twenty cases are defined and ready.'} />
          <Kpi
            label="Pass rate"
            empty={!summary || summary.passRate === null}
            value={summary?.passRate != null ? percent(summary.passRate) : NO_DATA}
            caption={summary ? `${summary.passedUnassisted} passed unassisted, ${summary.passed - summary.passedUnassisted} more with a rescue, ${summary.failed} failed` : 'Passed with no human rescue, over cases executed.'}
          />
          <Kpi
            label="Human interventions"
            empty={!summary}
            value={summary ? String(summary.rescued) : NO_DATA}
            caption={summary ? `Rescues only. ${summary.mandatoryApprovals} mandatory approvals are counted separately.` : 'Rescues only. Mandatory approvals are counted separately.'}
          />
          <Kpi
            label="AI cost per run"
            empty={!summary || summary.costPerRunUsd === null}
            value={summary?.costPerRunUsd != null ? usd(summary.costPerRunUsd) : NO_DATA}
            caption={
              summary?.costPerRunUsd != null
                ? `Mean over ${summary.casesWithCost} priced runs. Total ${usd(summary.totalCostUsd ?? 0)}.`
                : summary && summary.casesWithUsage > 0
                  ? 'Tokens were reported, but no price is configured for the model.'
                  : 'Needs token usage from the backend.'
            }
          />
          <Kpi
            label="Median latency"
            empty={!summary?.latency}
            value={summary?.latency ? fmtDuration(summary.latency.medianMs) : NO_DATA}
            caption={summary?.latency ? `p95 ${fmtDuration(summary.latency.p95Ms)}, mean ${fmtDuration(summary.latency.meanMs)}` : 'Start to final status, measured by the harness.'}
          />
          <Kpi
            label="API and model errors"
            empty={!summary}
            value={summary ? String(summary.errored) : NO_DATA}
            caption={summary ? `Cases that could not be scored. ${errorEvents} error events in total, including recovered ones.` : 'Cases that could not be scored.'}
          />
        </section>

        {/* 20-case progress */}
        <section aria-label="Progress across the twenty cases" className="card p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-[15px] font-semibold text-ink">Twenty-case progress</h2>
            <p className="text-[12px] text-mute">{liveReport ? `${liveReport.label} · ${liveReport.target.name} · finished ${fmtDayTime(liveReport.finishedAt, timeZone)}` : 'Not run against a live backend yet'}</p>
          </div>
          <ol className="mt-3 grid grid-cols-10 gap-1.5 sm:gap-2">
            {EVALUATION_CASES.map((c) => {
              const verdict: Verdict | 'none' = liveResults.get(c.id)?.verdict ?? 'none';
              const text = verdict === 'none' ? 'not run' : VERDICT[verdict].label.toLowerCase();
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setCategory('all');
                      setOpenCase(c.id);
                      requestAnimationFrame(() => document.getElementById(`case-${c.id}`)?.scrollIntoView?.({ block: 'center', behavior: 'smooth' }));
                    }}
                    title={`${c.id}: ${c.title} (${text})`}
                    aria-label={`${c.id}, ${c.title}: ${text}`}
                    className={clsx('flex h-10 w-full cursor-pointer flex-col items-center justify-center rounded-lg border text-[10.5px] font-bold leading-none tabular-nums transition-colors duration-150 hover:border-accent/60', CELL[verdict])}
                  >
                    <span>{c.id.slice(-2)}</span>
                    <span aria-hidden className="mt-0.5 h-2.5 text-[9.5px]">
                      {CELL_MARK[verdict]}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          <p className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-mute">
            <span>P pass</span>
            <span>F fail</span>
            <span>E error</span>
            <span>S skipped</span>
            <span>blank: not run</span>
          </p>
        </section>

        {/* Day snapshots */}
        <section aria-label="Progress snapshots">
          <div className="mb-2.5 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-[15px] font-semibold text-ink">Friday, Saturday and Sunday snapshots</h2>
              <p className="text-[12.5px] text-mute">One frozen summary per day, from a full run against the real backend.</p>
            </div>
            {liveReport && (
              <div className="flex items-center gap-2">
                <label htmlFor="snapshot-day" className="sr-only">
                  Day to save the current report under
                </label>
                <select id="snapshot-day" value={snapshotDay} onChange={(e) => setSnapshotDay(e.target.value as SnapshotDay)} className="field h-9 w-auto py-0 text-[13px]">
                  {SNAPSHOT_DAYS.map((d) => (
                    <option key={d.day} value={d.day} className="bg-surface">
                      {d.label}
                    </option>
                  ))}
                </select>
                <Button variant="secondary" icon={Save} onClick={saveDay} disabled={snapshotBlocked !== null || running} aria-describedby={snapshotBlocked ? 'snapshot-blocked' : undefined}>
                  Save current report
                </Button>
              </div>
            )}
          </div>
          {snapshotBlocked && (
            <p id="snapshot-blocked" className="mb-2.5 text-[12.5px] text-warn">
              The current report cannot be saved as a snapshot. {snapshotBlocked}
            </p>
          )}
          <div className="grid gap-3 md:grid-cols-3">
            {SNAPSHOT_DAYS.map((d, i) => (
              <SnapshotCard key={d.day} {...d} snapshot={snapshots[d.day]} previous={i > 0 ? snapshots[SNAPSHOT_DAYS[i - 1].day] : undefined} timeZone={timeZone} />
            ))}
          </div>
        </section>

        {selfTest && <SelfTestPanel report={selfTest} />}

        {/* Cases */}
        <section aria-label="Evaluation cases" className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[15px] font-semibold text-ink">Cases</h2>
              {tableSimulated && <SimulatedTag />}
              {tableSimulated && <span className="text-[12px] text-mute">Verdicts below come from the scripted mock, not from the agent.</span>}
            </div>
            <div className="flex items-center gap-2">
              <label htmlFor="case-category" className="text-[12.5px] text-mute">
                Category
              </label>
              <select id="case-category" value={category} onChange={(e) => setCategory(e.target.value)} className="field h-9 w-auto py-0 text-[13px]">
                <option value="all" className="bg-surface">
                  All ({EVALUATION_CASES.length})
                </option>
                {CASE_CATEGORIES.map((c) => (
                  <option key={c.id} value={c.id} className="bg-surface">
                    {c.label} ({EVALUATION_CASES.filter((x) => x.category === c.id).length})
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-[13px]">
              <thead className="text-[12px] text-mute">
                <tr className="border-b border-line">
                  <th scope="col" className="px-4 py-2.5 font-semibold sm:pl-5">Case</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Category</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Verdict</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Checks</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Approvals</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Rescue</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">Duration</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">Cost</th>
                  <th scope="col" className="w-10 px-3 py-2.5">
                    <span className="sr-only">Details</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => {
                  const result = results.get(c.id);
                  const open = openCase === c.id;
                  const executed = result && result.verdict !== 'skipped';
                  const passedChecks = result ? result.checks.filter((x) => x.passed).length : 0;
                  return (
                    <Fragment key={c.id}>
                      <tr id={`case-${c.id}`} className={clsx('border-b border-line transition-colors duration-150', open ? 'bg-white/[0.04]' : 'hover:bg-white/[0.025]')}>
                        <th scope="row" className="px-4 py-2.5 text-left font-normal sm:pl-5">
                          <button type="button" onClick={() => setOpenCase(open ? null : c.id)} aria-expanded={open} aria-controls={`case-panel-${c.id}`} className="cursor-pointer text-left">
                            <span className="block font-mono text-[11.5px] text-mute">{c.id}</span>
                            <span className="block font-semibold text-ink hover:text-accent">{c.title}</span>
                          </button>
                        </th>
                        <td className="px-3 py-2.5 text-soft">{categoryLabel(c.category)}</td>
                        <td className="px-3 py-2.5">
                          {result ? (
                            <Pill tone={VERDICT[result.verdict].tone}>
                              {VERDICT[result.verdict].label}
                              {tableSimulated && ' (scripted)'}
                            </Pill>
                          ) : (
                            <span className="text-mute">Not run</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 tabular-nums text-soft">{executed && result.checks.length > 0 ? `${passedChecks}/${result.checks.length}` : NO_DATA}</td>
                        <td className="px-3 py-2.5 tabular-nums text-soft">{executed ? result.human.mandatoryApprovals : NO_DATA}</td>
                        <td className="px-3 py-2.5">{executed ? result.human.rescued ? <span className="font-semibold text-warn">Yes</span> : <span className="text-soft">No</span> : <span className="text-mute">{NO_DATA}</span>}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-soft">{executed && !tableSimulated ? fmtDuration(result.timing.wallClockMs) : NO_DATA}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-soft">{executed && result.estimatedCostUsd !== null ? usd(result.estimatedCostUsd) : NO_DATA}</td>
                        <td className="px-3 py-2.5 text-right">
                          <button type="button" onClick={() => setOpenCase(open ? null : c.id)} aria-label={`${open ? 'Hide' : 'Show'} details for ${c.id}`} className="cursor-pointer rounded-md p-1 text-mute hover:bg-white/[0.08] hover:text-ink">
                            <ChevronDown aria-hidden className={clsx('h-4 w-4 transition-transform duration-150', open && 'rotate-180')} />
                          </button>
                        </td>
                      </tr>
                      {open && (
                        <tr id={`case-panel-${c.id}`} className="border-b border-line bg-sunken/40">
                          <td colSpan={9} className="px-4 py-5 sm:px-5">
                            <p className="mb-4 max-w-3xl text-[13.5px] text-soft">{c.description}</p>
                            {result && result.verdict !== 'skipped' && (
                              <div className="mb-6 rounded-xl border border-line bg-surface p-4">
                                <div className="mb-3 flex flex-wrap items-center gap-2">
                                  <h3 className="text-[14px] font-semibold text-ink">Result</h3>
                                  <Pill tone={VERDICT[result.verdict].tone}>{VERDICT[result.verdict].label}</Pill>
                                  {result.dataSource === 'simulated' && <SimulatedTag />}
                                </div>
                                <CaseResult result={result} timeZone={timeZone} />
                              </div>
                            )}
                            {result?.verdict === 'skipped' && <p className="mb-5 text-[13px] text-soft">Skipped: {result.skipReason}</p>}
                            <CaseSpecification testCase={c} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
