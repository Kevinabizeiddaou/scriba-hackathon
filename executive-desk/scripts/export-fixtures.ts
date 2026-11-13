/**
 * Writes the evaluation cases as plain JSON, so a backend in any language can load them.
 * Run with: npm run fixtures:export
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { EVALUATION_CASES } from '../src/evaluation/fixtures';

const out = resolve(dirname(fileURLToPath(import.meta.url)), '../fixtures/evaluation-cases.json');
mkdirSync(dirname(out), { recursive: true });
writeFileSync(
  out,
  `${JSON.stringify(
    {
      notice: 'Synthetic development fixtures for Scriba Executive Desk. Invented people, companies and calendars. Not customer data.',
      contractVersion: '0.1',
      generatedFrom: 'src/evaluation/fixtures/*.ts (edit there, then run npm run fixtures:export)',
      cases: EVALUATION_CASES,
    },
    null,
    2,
  )}\n`,
);
console.log(`Wrote ${EVALUATION_CASES.length} cases to ${out}`);
