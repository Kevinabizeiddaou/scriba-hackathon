import { DESK_AREAS, type CaseCategory, type CaseSetInfo, type DeskArea, type EvaluationCase } from '../../harness/types';
import { CASES_01_10 } from './cases-01-10';
import { CASES_11_20 } from './cases-11-20';
import { CASES_21_32 } from './cases-21-32';
import { HOLDOUT_CASES, HOLDOUT_CASE_SET } from './holdout';

/**
 * The twenty scheduling cases the harness started with, in id order. Eight of them are part of
 * the desk suite below; all twenty remain as a regression set for scheduling on its own.
 */
export const EVALUATION_CASES: EvaluationCase[] = [...CASES_01_10, ...CASES_11_20];

/** Identifies the scheduling regression set. Bump the suffix when a case's expectations change. */
export const SYNTHETIC_CASE_SET: CaseSetInfo = { id: 'synthetic-v3', provenance: 'synthetic', caseCount: EVALUATION_CASES.length };

/** Every synthetic case that ships with the harness. */
export const ALL_CASES: EvaluationCase[] = [...EVALUATION_CASES, ...CASES_21_32];

/** How many cases of each area the desk suite holds. The suite is rejected at load time if it drifts from this. */
export const DESK_SUITE_SHAPE: Record<DeskArea, number> = {
  inbox: 3,
  email: 3,
  scheduling: 5,
  task_reminder: 3,
  follow_up: 2,
  multi_step: 2,
  security_failure: 2,
};

/** The desk suite: which cases, in the order they are run and shown. */
const DESK_SUITE_IDS: Record<DeskArea, string[]> = {
  inbox: ['EVAL-015', 'EVAL-021', 'EVAL-022'],
  email: ['EVAL-023', 'EVAL-024', 'EVAL-025'],
  scheduling: ['EVAL-001', 'EVAL-003', 'EVAL-008', 'EVAL-011', 'EVAL-013'],
  task_reminder: ['EVAL-026', 'EVAL-027', 'EVAL-028'],
  follow_up: ['EVAL-029', 'EVAL-030'],
  multi_step: ['EVAL-031', 'EVAL-032'],
  security_failure: ['EVAL-018', 'EVAL-019'],
};

export function getCase(id: string): EvaluationCase {
  const found = ALL_CASES.find((c) => c.id === id);
  if (!found) throw new Error(`Unknown evaluation case: ${id}`);
  return found;
}

/**
 * The main suite: twenty cases across the whole of the secretary's job, not only scheduling.
 * 3 inbox, 3 email, 5 scheduling, 3 task and reminder, 2 follow-up, 2 multi-step, 2 security and failure.
 */
export const DESK_SUITE: EvaluationCase[] = DESK_AREAS.flatMap((area) =>
  DESK_SUITE_IDS[area].map((id) => {
    const found = getCase(id);
    if (found.area !== area) throw new Error(`${id} is tagged ${found.area} but listed under ${area} in the desk suite.`);
    return found;
  }),
);

for (const area of DESK_AREAS) {
  if (DESK_SUITE_IDS[area].length !== DESK_SUITE_SHAPE[area]) throw new Error(`The desk suite needs ${DESK_SUITE_SHAPE[area]} ${area} cases, but lists ${DESK_SUITE_IDS[area].length}.`);
}

/** Identifies the desk suite. Bump the suffix when its membership or a member's expectations change. */
export const DESK_CASE_SET: CaseSetInfo = { id: 'desk-v1', provenance: 'synthetic', caseCount: DESK_SUITE.length };

export const AREA_LABEL: Record<DeskArea, string> = {
  inbox: 'Inbox triage',
  email: 'Email replies',
  scheduling: 'Scheduling',
  task_reminder: 'Tasks and reminders',
  follow_up: 'Follow-ups',
  multi_step: 'Multi-step workflows',
  security_failure: 'Security and failure',
};

/** Named suites the CLI can run. */
export const SUITES = {
  desk: { caseSet: DESK_CASE_SET, cases: DESK_SUITE, description: 'The main suite: 20 cases across inbox, email, scheduling, tasks, follow-ups, workflows and safety.' },
  scheduling: { caseSet: SYNTHETIC_CASE_SET, cases: EVALUATION_CASES, description: 'The 20 scheduling cases, as a regression set.' },
  holdout: { caseSet: HOLDOUT_CASE_SET, cases: HOLDOUT_CASES, description: 'One reworded variation of each desk case, with the official expectations. Not published with the cases.' },
  all: { caseSet: { id: 'all-synthetic-v1', provenance: 'synthetic', caseCount: ALL_CASES.length } as CaseSetInfo, cases: ALL_CASES, description: 'Every synthetic case, each once.' },
} satisfies Record<string, { caseSet: CaseSetInfo; cases: EvaluationCase[]; description: string }>;

export type SuiteName = keyof typeof SUITES;

export const CASE_CATEGORIES: { id: CaseCategory; label: string }[] = [
  { id: 'straightforward', label: 'Straightforward booking' },
  { id: 'conflict', label: 'Conflict' },
  { id: 'alternatives', label: 'Alternatives' },
  { id: 'unclear', label: 'Unclear request' },
  { id: 'timezone', label: 'Time zones' },
  { id: 'rescheduling', label: 'Rescheduling' },
  { id: 'cancellation', label: 'Cancellation' },
  { id: 'duplicate', label: 'Duplicate request' },
  { id: 'api_failure', label: 'API failure' },
  { id: 'prompt_injection', label: 'Prompt injection' },
  { id: 'triage', label: 'Triage' },
  { id: 'correspondence', label: 'Correspondence' },
  { id: 'tasks', label: 'Tasks and reminders' },
  { id: 'follow_up', label: 'Follow-up' },
  { id: 'workflow', label: 'Workflow' },
];

export function categoryLabel(id: CaseCategory): string {
  return CASE_CATEGORIES.find((c) => c.id === id)?.label ?? id;
}

export { HOLDOUT_CASES, HOLDOUT_CASE_SET, baseCaseId, isHoldoutId } from './holdout';
