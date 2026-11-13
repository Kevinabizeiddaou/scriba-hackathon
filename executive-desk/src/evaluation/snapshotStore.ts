/**
 * Where the dashboard keeps evaluation results between visits.
 *
 * Two sources are merged:
 *   - eval-results/snapshots/*.json, written by `npm run eval -- --snapshot <day>` and committed;
 *   - this browser's localStorage, for runs started from the dashboard.
 * Only live results are ever stored. Simulated self-test output is not kept.
 */
import type { EvaluationReport, EvaluationSnapshot, SnapshotDay } from '../api/types';
import { isReport, isSnapshot } from './report';

const SNAPSHOT_KEY = 'executive-desk.eval.snapshots';
const REPORT_KEY = 'executive-desk.eval.lastLiveReport';

const committed = import.meta.glob('../../eval-results/snapshots/*.json', { eager: true, import: 'default' }) as Record<string, unknown>;

function read(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage is full or unavailable. The dashboard still works for this visit.
  }
}

export function loadSnapshots(): Partial<Record<SnapshotDay, EvaluationSnapshot>> {
  const stored = read(SNAPSHOT_KEY);
  const candidates = [...Object.values(committed), ...(stored && typeof stored === 'object' ? Object.values(stored as object) : [])].filter(isSnapshot);
  const byDay: Partial<Record<SnapshotDay, EvaluationSnapshot>> = {};
  for (const snapshot of candidates) {
    const existing = byDay[snapshot.day];
    if (!existing || Date.parse(snapshot.savedAt) > Date.parse(existing.savedAt)) byDay[snapshot.day] = snapshot;
  }
  return byDay;
}

export function saveSnapshot(snapshot: EvaluationSnapshot): void {
  if (!isSnapshot(snapshot)) throw new Error('Only a snapshot of a live report can be saved.');
  const stored = read(SNAPSHOT_KEY);
  write(SNAPSHOT_KEY, { ...(stored && typeof stored === 'object' ? stored : {}), [snapshot.day]: snapshot });
}

export function loadLastLiveReport(): EvaluationReport | null {
  const stored = read(REPORT_KEY);
  return isReport(stored) && stored.target.dataSource === 'live' ? stored : null;
}

export function saveLastLiveReport(report: EvaluationReport): void {
  if (report.target.dataSource === 'live') write(REPORT_KEY, report);
}
