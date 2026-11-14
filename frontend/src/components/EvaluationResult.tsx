/**
 * One evaluation report, shown under the name of what produced it. A mock report gets counts
 * and no rate; a scripted-model report gets its numbers with a plain statement that no model
 * took part; only a real-model report is the secretary's result. The three never share a panel.
 */
import clsx from 'clsx';
import type { EvaluationReport } from '../harness/types';
import { AREA_LABEL } from '../evaluation/fixtures';
import { PROVENANCE, metricsOf, provenanceOf } from '../evaluation/provenance';
import { summarizeByArea } from '../evaluation/report';
import { fmtDayTime } from '../lib/time';
import { Pill } from './ui';

const NO_DATA = '—';

function Figure({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: 'ok' | 'danger' | 'mute' }) {
  return (
    <div className="min-w-0 bg-surface px-3.5 py-2.5">
      <dt className="eyebrow">{label}</dt>
      <dd className={clsx('mt-0.5 text-[20px] font-bold leading-7 tabular-nums', tone === 'ok' ? 'text-ok' : tone === 'danger' ? 'text-danger' : tone === 'mute' ? 'text-mute' : 'text-ink')}>{value}</dd>
      {note && <dd className="text-xs leading-[17px] text-mute">{note}</dd>}
    </div>
  );
}

export function EvaluationResultPanel({ report, timeZone }: { report: EvaluationReport; timeZone: string }) {
  const origin = provenanceOf(report);
  const info = PROVENANCE[origin];
  const m = metricsOf(report);
  const byArea = summarizeByArea(report.results);
  const failures = report.results.filter((result) => result.verdict === 'fail' || result.verdict === 'error');
  // A mock run proves the harness. Giving it a rate would invite reading it as performance.
  const showRate = origin === 'scripted' || origin === 'real';

  return (
    <section aria-label={info.label} className="card p-4 sm:p-5" data-testid={`evaluation-result-${origin}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="text-[15px] font-semibold text-ink">{info.label}</h2>
        <Pill tone={info.tone} icon={null}>{origin === 'real' ? 'The secretary\'s result' : 'Not an agent result'}</Pill>
      </div>
      <p className="mt-1.5 max-w-3xl text-[12.5px] leading-[19px] text-soft">{info.means}</p>
      <p className="mt-1 break-words text-xs text-mute">
        {report.label} · {report.target.name}
        {report.target.sandbox ? ' · sandbox' : ''} · case set {report.caseSet.id} · finished {fmtDayTime(report.finishedAt, timeZone)}
      </p>

      <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 xl:grid-cols-6">
        <Figure label="Passed" value={`${m.passed} of ${m.executed}`} tone={m.passed > 0 ? 'ok' : undefined} />
        <Figure label="Failed" value={String(m.failed)} tone={m.failed > 0 ? 'danger' : undefined} note={m.errored > 0 ? `plus ${m.errored} that could not be scored` : undefined} />
        <Figure label="Pass rate" value={showRate && m.passRate !== null ? `${Math.round(m.passRate * 100)}%` : NO_DATA} tone={showRate ? undefined : 'mute'} note={showRate ? (origin === 'scripted' ? 'Of the rules alone, not of the agent' : 'Passed over executed') : 'Not given for a mock run'} />
        <Figure label="Safety violations" value={String(m.safetyViolations)} tone={m.safetyViolations > 0 ? 'danger' : 'ok'} note="Cases where a safety check failed" />
        <Figure label="Median latency" value={m.medianLatencyMs !== null ? `${(m.medianLatencyMs / 1000).toFixed(1)} s` : NO_DATA} tone={m.medianLatencyMs === null ? 'mute' : undefined} note={m.medianLatencyMs === null ? 'Not reported for this target' : 'Start to final status'} />
        <Figure label="Cost" value={m.totalCostUsd !== null ? `$${m.totalCostUsd.toFixed(4)}` : NO_DATA} tone={m.totalCostUsd === null ? 'mute' : undefined} note={m.totalCostUsd === null ? (m.casesWithUsage === 0 ? 'No model call was recorded' : 'Usage reported, no price known') : `Over ${m.casesWithUsage} cases with usage`} />
      </dl>

      <ul className="mt-3 grid gap-x-5 gap-y-1 text-[12.5px] text-soft sm:grid-cols-2" aria-label="Results by area">
        {byArea.map((area) => (
          <li key={area.area} className="flex justify-between gap-3">
            <span>{AREA_LABEL[area.area]}</span>
            <span className="tabular-nums text-ink">{area.passedUnassisted} of {area.executed} passed</span>
          </li>
        ))}
      </ul>

      {failures.length > 0 && (
        <details className="mt-3">
          <summary className="tap cursor-pointer text-[12.5px] font-medium text-accent">{failures.length} case{failures.length === 1 ? '' : 's'} did not pass</summary>
          <ul className="mt-2 space-y-1.5 text-[12.5px]">
            {failures.map((result) => (
              <li key={result.caseId}>
                <span className="font-semibold tabular-nums text-ink">{result.caseId}</span> <span className="text-soft">{result.caseTitle}</span>
                <span className="block break-words text-xs text-mute">
                  {result.verdict === 'error' ? `Could not be scored: ${result.errors.map((error) => error.code).join(', ') || 'no reason recorded'}` : `Failed checks: ${result.checks.filter((check) => !check.passed).map((check) => check.id).join(', ')}`}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
