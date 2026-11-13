/**
 * Writes the evaluation cases as plain JSON, so a backend in any language can load them.
 * Run with: npm run fixtures:export
 *
 *   fixtures/evaluation-cases.json             the desk suite (the main twenty)
 *   fixtures/scheduling-regression-cases.json  the twenty scheduling cases
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildCaseSetFile } from '../src/evaluation/caseSets';
import { SUITES } from '../src/evaluation/fixtures';

const dir = resolve(dirname(fileURLToPath(import.meta.url)), '../fixtures');
mkdirSync(dir, { recursive: true });
const NOTICE =
  'Synthetic development fixtures for Scriba Executive Desk. Invented people, companies and calendars. Not customer data. Generated from src/evaluation/fixtures/*.ts: edit there, then run npm run fixtures:export.';

for (const [file, suite] of [
  ['evaluation-cases.json', SUITES.desk],
  ['scheduling-regression-cases.json', SUITES.scheduling],
] as const) {
  writeFileSync(resolve(dir, file), `${JSON.stringify(buildCaseSetFile(suite.caseSet, suite.cases, NOTICE), null, 2)}\n`);
  console.log(`Wrote ${suite.cases.length} cases (${suite.caseSet.id}) to fixtures/${file}`);
}
