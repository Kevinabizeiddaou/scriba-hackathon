import type { CaseCategory, CaseSetInfo, EvaluationCase } from '../../api/types';
import { CASES_01_10 } from './cases-01-10';
import { CASES_11_20 } from './cases-11-20';

/** The twenty synthetic evaluation cases, in id order. */
export const EVALUATION_CASES: EvaluationCase[] = [...CASES_01_10, ...CASES_11_20];

/** Identifies the full synthetic set. Bump the suffix when a case's expectations change. */
export const SYNTHETIC_CASE_SET: CaseSetInfo = { id: 'synthetic-v2', provenance: 'synthetic', caseCount: EVALUATION_CASES.length };

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
];

export function categoryLabel(id: CaseCategory): string {
  return CASE_CATEGORIES.find((c) => c.id === id)?.label ?? id;
}

export function getCase(id: string): EvaluationCase {
  const found = EVALUATION_CASES.find((c) => c.id === id);
  if (!found) throw new Error(`Unknown evaluation case: ${id}`);
  return found;
}
