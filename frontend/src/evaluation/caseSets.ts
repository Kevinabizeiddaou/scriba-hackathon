/**
 * Case-set files: how evaluation cases are stored and loaded, and how synthetic fixtures are
 * kept apart from cases derived from real requests.
 *
 * A file holds one set, and a set has one kind of provenance. The loader refuses anything
 * ambiguous: a case with no provenance, a set that mixes kinds, a "real-world" case that
 * reuses a synthetic id or still contains a real-looking address.
 */
import { CONTRACT_VERSION, type CaseSetInfo, type EvaluationCase } from '../harness/types';

export const CASE_SET_FORMAT = 'executive-desk.case-set/1';

export interface CaseSetFile {
  format: typeof CASE_SET_FORMAT;
  notice: string;
  contractVersion: string;
  caseSet: CaseSetInfo;
  cases: EvaluationCase[];
}

/** Ids of this shape are reserved for the synthetic fixtures that ship with the harness. */
const SYNTHETIC_ID = /^EVAL-\d{3}$/;
/** Top-level domains that can never resolve (RFC 2606). Anonymised cases must use them. */
const RESERVED_DOMAIN = /\.(example|test|invalid)$/i;

export function buildCaseSetFile(caseSet: CaseSetInfo, cases: EvaluationCase[], notice: string): CaseSetFile {
  return { format: CASE_SET_FORMAT, notice, contractVersion: CONTRACT_VERSION, caseSet, cases };
}

/** Returns every reason the value is not a usable case set. An empty list means it is. */
export function caseSetProblems(value: unknown): string[] {
  const problems: string[] = [];
  const file = value as Partial<CaseSetFile> | null;
  if (!file || typeof file !== 'object') return ['The file is not a JSON object.'];
  if (file.format !== CASE_SET_FORMAT) problems.push(`"format" must be "${CASE_SET_FORMAT}".`);
  if (typeof file.contractVersion !== 'string' || file.contractVersion.split('.')[0] !== CONTRACT_VERSION.split('.')[0]) {
    problems.push(`"contractVersion" must be ${CONTRACT_VERSION.split('.')[0]}.x; the cases were written for a different contract.`);
  }
  const set = file.caseSet;
  if (!set || typeof set.id !== 'string' || !set.id || (set.provenance !== 'synthetic' && set.provenance !== 'real_world')) {
    problems.push('"caseSet" needs an id and a provenance of "synthetic" or "real_world".');
  }
  if (!Array.isArray(file.cases) || file.cases.length === 0) {
    problems.push('"cases" must be a non-empty array.');
    return problems;
  }
  if (set && typeof set.caseCount === 'number' && set.caseCount !== file.cases.length) {
    problems.push(`"caseSet.caseCount" is ${set.caseCount}, but the file holds ${file.cases.length} cases.`);
  }

  const seen = new Set<string>();
  for (const [index, item] of file.cases.entries()) {
    const c = item as Partial<EvaluationCase> | null;
    const name = typeof c?.id === 'string' && c.id ? c.id : `cases[${index}]`;
    if (!c || typeof c !== 'object' || typeof c.id !== 'string' || !c.id) {
      problems.push(`${name}: missing id.`);
      continue;
    }
    if (seen.has(c.id)) problems.push(`${name}: the id is used more than once.`);
    seen.add(c.id);
    if (!c.input || !c.context || !c.expected) problems.push(`${name}: needs input, context and expected.`);

    const provenance = c.provenance;
    if (!provenance || (provenance.kind !== 'synthetic' && provenance.kind !== 'real_world')) {
      problems.push(`${name}: has no provenance. Every case must say whether it is synthetic or real-world.`);
      continue;
    }
    if (set && provenance.kind !== set.provenance) problems.push(`${name}: is ${provenance.kind} in a set declared ${set.provenance}. A set must not mix the two.`);
    if (provenance.kind === 'real_world') {
      if (SYNTHETIC_ID.test(c.id)) problems.push(`${name}: ids of the form EVAL-nnn are reserved for synthetic fixtures.`);
      if (provenance.anonymized !== true) problems.push(`${name}: a real-world case must be anonymised, and say so.`);
      if (!provenance.source?.trim()) problems.push(`${name}: a real-world case must name its source.`);
      if (!provenance.consentReference?.trim()) problems.push(`${name}: a real-world case must reference the consent for its use.`);
    }
    // Whatever the provenance, no case file may carry an address that could belong to a real person.
    const addresses = JSON.stringify(c).match(/[\w.+-]+@[\w-]+(\.[\w-]+)+/g) ?? [];
    const real = [...new Set(addresses.filter((address) => !RESERVED_DOMAIN.test(address)))];
    if (real.length > 0) problems.push(`${name}: contains addresses outside the reserved .example, .test and .invalid domains (${real.slice(0, 3).join(', ')}). Replace them before committing.`);
  }
  return problems;
}

/** Parses and validates a case-set file. Throws one error listing every problem. */
export function loadCaseSet(value: unknown): { caseSet: CaseSetInfo; cases: EvaluationCase[] } {
  const problems = caseSetProblems(value);
  if (problems.length > 0) throw new Error(`Not a valid case set:\n- ${problems.join('\n- ')}`);
  const file = value as CaseSetFile;
  return { caseSet: { ...file.caseSet, caseCount: file.cases.length }, cases: file.cases };
}
