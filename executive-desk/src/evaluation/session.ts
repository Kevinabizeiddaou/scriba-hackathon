/**
 * The evaluation dashboard's state, kept outside the page component.
 *
 * A live evaluation takes minutes. If its state lived in the page, leaving the page would
 * drop the progress bar and the Stop button while the run carried on, and coming back would
 * let a second run start against the same backend. Here there is one session per browser tab:
 * the page subscribes to it, and a run in progress blocks another from starting.
 */
import { useSyncExternalStore } from 'react';
import type { EvaluationTarget } from '../api/client';
import type { EvaluationReport, EvaluationSnapshot, SnapshotDay } from '../api/types';
import { EVALUATION_CASES, SYNTHETIC_CASE_SET } from './fixtures';
import { buildSnapshot, isReport, isSnapshot } from './report';
import { runEvaluation } from './runner';
import { runSelfTest, type SelfTestReport } from './selfTest';
import { loadLastLiveReport, loadSnapshots, saveLastLiveReport, saveSnapshot } from './snapshotStore';

export interface EvaluationSessionState {
  liveReport: EvaluationReport | null;
  selfTest: SelfTestReport | null;
  snapshots: Partial<Record<SnapshotDay, EvaluationSnapshot>>;
  progress: { done: number; total: number; current: string | null } | null;
  error: Error | null;
  notice: string | null;
}

let state: EvaluationSessionState | null = null;
let abort: AbortController | null = null;
const listeners = new Set<() => void>();

function current(): EvaluationSessionState {
  if (!state) {
    state = { liveReport: loadLastLiveReport(), selfTest: null, snapshots: loadSnapshots(), progress: null, error: null, notice: null };
  }
  return state;
}

function set(patch: Partial<EvaluationSessionState>): void {
  state = { ...current(), ...patch };
  for (const listener of listeners) listener();
}

const asError = (cause: unknown) => (cause instanceof Error ? cause : new Error(String(cause)));

export const evaluationSession = {
  getState: current,

  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },

  /** Runs the full case set against a live target. Does nothing if a run is already in progress. */
  async runLive(target: EvaluationTarget): Promise<void> {
    if (current().progress) return;
    abort = new AbortController();
    set({ error: null, notice: null, progress: { done: 0, total: EVALUATION_CASES.length, current: EVALUATION_CASES[0].id } });
    try {
      const report = await runEvaluation(target, EVALUATION_CASES, {
        caseSet: SYNTHETIC_CASE_SET,
        signal: abort.signal,
        onProgress: ({ done, total, current: caseId }) => set({ progress: { done, total, current: caseId } }),
      });
      if (report.target.dataSource === 'live') {
        saveLastLiveReport(report);
        set({ liveReport: report });
      } else {
        set({ notice: 'That backend reports a scripted agent, so its results are simulated and are not shown as evaluation numbers.' });
      }
    } catch (cause) {
      set({ error: asError(cause) });
    } finally {
      abort = null;
      set({ progress: null });
    }
  },

  /** Asks a live run to stop after the case it is on. */
  stop(): void {
    abort?.abort();
  },

  async runSelfTest(): Promise<void> {
    if (current().progress) return;
    set({ error: null, notice: null, progress: { done: 0, total: 1, current: null } });
    try {
      const report = await runSelfTest({ onProgress: (done, total) => set({ progress: { done, total, current: null } }) });
      set({ selfTest: report });
    } catch (cause) {
      set({ error: asError(cause) });
    } finally {
      set({ progress: null });
    }
  },

  /** Accepts a report or snapshot file written by `npm run eval`. Simulated reports are refused. */
  importJson(text: string): void {
    set({ error: null, notice: null });
    try {
      const parsed: unknown = JSON.parse(text);
      if (isSnapshot(parsed)) {
        saveSnapshot(parsed);
        set({ snapshots: loadSnapshots(), notice: `Imported the ${parsed.day} snapshot.` });
      } else if (isReport(parsed)) {
        if (parsed.target.dataSource !== 'live') throw new Error('That file is a simulated report. Only reports from a live backend are shown as results.');
        saveLastLiveReport(parsed);
        set({ liveReport: parsed, notice: `Imported "${parsed.label}".` });
      } else {
        throw new Error('That file is not an evaluation report or snapshot from this version of the harness.');
      }
    } catch (cause) {
      set({ error: asError(cause) });
    }
  },

  saveSnapshot(day: SnapshotDay): void {
    const report = current().liveReport;
    if (!report) return;
    try {
      saveSnapshot(buildSnapshot(report, day, new Date().toISOString()));
      set({ snapshots: loadSnapshots(), error: null, notice: `Saved as the ${day} snapshot in this browser.` });
    } catch (cause) {
      set({ error: asError(cause) });
    }
  },

  /** For tests: forget everything and read storage again on next use. */
  reset(): void {
    abort?.abort();
    abort = null;
    state = null;
  },
};

export function useEvaluationSession(): EvaluationSessionState {
  return useSyncExternalStore(evaluationSession.subscribe, evaluationSession.getState);
}
