import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { MockExecutiveDesk } from '../../harness/mock/mockAdapter';
import type { EvaluationCase } from '../../harness/types';
import { localParts } from '../../lib/time';
import { aggregateCampaign } from '../campaign';
import { runEvaluation } from '../runner';
import { DESK_CASE_SET, DESK_SUITE, HOLDOUT_CASES, HOLDOUT_CASE_SET, SUITES, baseCaseId, getCase, isHoldoutId } from './index';

const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

/** The text that triggers the run: the email body with its subject, or the last chat message. */
function trigger(c: EvaluationCase): string {
  return c.input.kind === 'email' ? `${c.input.email.subject}\n${c.input.email.bodyText}` : c.input.messages.at(-1)!.text;
}
const dates = (text: string) => [...text.matchAll(/\b(\d{1,2}) (November|March)\b/g)].map((m) => `${m[1]} ${m[2]}`).sort();
const clockTimes = (text: string) => [...text.matchAll(/\b(\d{1,2}):(\d{2})\b/g)].map((m) => `${m[1]}:${m[2]}`).sort();

describe('holdout variations', () => {
  it('has one variation for each desk case, in the same order', () => {
    expect(HOLDOUT_CASES.map((c) => c.id)).toEqual(DESK_SUITE.map((c) => `${c.id}-H1`));
    expect(HOLDOUT_CASE_SET).toEqual({ id: 'desk-holdout-v1', provenance: 'synthetic', caseCount: 20 });
    expect(SUITES.holdout.cases).toBe(HOLDOUT_CASES);
    for (const c of HOLDOUT_CASES) {
      expect(isHoldoutId(c.id)).toBe(true);
      expect(c.tags).toContain('holdout');
    }
    expect(isHoldoutId('EVAL-026')).toBe(false);
    expect(baseCaseId('EVAL-026-H1')).toBe('EVAL-026');
    expect(baseCaseId('EVAL-026')).toBe('EVAL-026');
  });

  it('does not rewrite the official expectations: a variation uses its base case\'s own objects', () => {
    for (const c of HOLDOUT_CASES) {
      const base = getCase(baseCaseId(c.id));
      expect(c.expected, c.id).toBe(base.expected);
      expect(c.context, c.id).toBe(base.context);
      expect(c.area).toBe(base.area);
      expect(c.provenance).toEqual(base.provenance);
      expect(c.successCriteria).toBe(base.successCriteria);
      expect(c.failureConditions).toBe(base.failureConditions);
    }
    // And building the variations left the official cases as they were.
    expect(DESK_SUITE.every((c) => !c.tags.includes('holdout') && !c.title.includes('reworded'))).toBe(true);
  });

  it('changes the wording and nothing else: same sender, recipients, time, thread and earlier messages', () => {
    for (const c of HOLDOUT_CASES) {
      const base = getCase(baseCaseId(c.id));
      expect(trigger(c), c.id).not.toBe(trigger(base));
      expect(c.input.kind).toBe(base.input.kind);
      if (c.input.kind === 'email' && base.input.kind === 'email') {
        const { subject: _s, bodyText: _b, ...rest } = c.input.email;
        const { subject: _bs, bodyText: _bb, ...baseRest } = base.input.email;
        expect(rest, c.id).toEqual(baseRest);
        expect(c.input.thread, c.id).toEqual(base.input.thread);
      } else if (c.input.kind === 'conversation' && base.input.kind === 'conversation') {
        expect(c.input.messages.slice(0, -1)).toEqual(base.input.messages.slice(0, -1));
        expect(c.input.messages.at(-1)!.role).toBe('user');
      }
    }
    expect(new Set(HOLDOUT_CASES.map(trigger)).size).toBe(HOLDOUT_CASES.length);
  });

  it('keeps every date and every clock time the official message states', () => {
    for (const c of HOLDOUT_CASES) {
      const base = getCase(baseCaseId(c.id));
      expect(dates(trigger(c)), `${c.id} dates`).toEqual(dates(trigger(base)));
      // A variation may write a time differently ("10 in the morning", "12:00" for "noon"), but it may not
      // introduce one the original does not state.
      const stated = [...clockTimes(trigger(base)).map((t) => t.padStart(5, '0')), ...(/\bnoon\b/i.test(trigger(base)) ? ['12:00'] : [])];
      for (const time of clockTimes(trigger(c))) expect(stated, `${c.id} ${time}`).toContain(time.padStart(5, '0'));
    }
  });

  it('writes weekday names that agree with their dates, and only reserved addresses', () => {
    for (const c of HOLDOUT_CASES) {
      for (const match of trigger(c).matchAll(/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(\d{1,2})\s+november\b/gi)) {
        const iso = `2026-11-${match[2].padStart(2, '0')}T12:00:00+02:00`;
        expect(WEEKDAYS[localParts(iso, 'Asia/Beirut').weekday - 1], `${c.id}: "${match[0]}"`).toBe(match[1].toLowerCase());
      }
      for (const address of JSON.stringify(c.input).match(/[\w.+-]+@[\w.-]+\.[a-z]+/gi) ?? []) expect(address, c.id).toMatch(/\.example$/);
    }
  });

  it('keeps the injected address in the injection variation, so the same bans apply', () => {
    const injected = HOLDOUT_CASES.find((c) => c.id === 'EVAL-019-H1')!;
    const banned = injected.expected.forbidden.flatMap((ban) => JSON.stringify(ban.args ?? {}).match(/[\w.+-]+@[\w.-]+\.example/g) ?? []);
    expect(banned.length).toBeGreaterThan(0);
    expect(trigger(injected)).toContain(banned[0]);
    expect(trigger(injected)).not.toMatch(/SYSTEM NOTE/); // a different disguise from the official case
  });

  it('is satisfiable: the reference scripts pass every variation, reported as its own case set', async () => {
    const report = await runEvaluation(new MockExecutiveDesk({ stepDelayMs: 0, seed: false }), HOLDOUT_CASES, { pollIntervalMs: 1, timeoutMs: 5_000, caseSet: HOLDOUT_CASE_SET });
    const notPassing = report.results.filter((r) => r.verdict !== 'pass').map((r) => `${r.caseId}: ${r.checks.filter((c) => !c.passed).map((c) => c.id).join(', ')}`);
    expect(notPassing).toEqual([]);
    expect(report.caseSet.id).toBe('desk-holdout-v1');
    expect(report.target.dataSource).toBe('simulated');

    // A holdout report is never folded into the official suite's numbers.
    const official = await runEvaluation(new MockExecutiveDesk({ stepDelayMs: 0, seed: false }), DESK_SUITE.slice(0, 2), { pollIntervalMs: 1, timeoutMs: 5_000, caseSet: DESK_CASE_SET });
    expect(() => aggregateCampaign([official, report])).toThrow(/different case sets \(desk-v1 and desk-holdout-v1\)/);
  });

  it('is not published with the cases it shadows', () => {
    const root = resolve(__dirname, '../../..');
    for (const file of readdirSync(resolve(root, 'fixtures')).filter((name) => name.endsWith('.json'))) {
      expect(readFileSync(resolve(root, 'fixtures', file), 'utf8'), file).not.toContain('-H1');
    }
    for (const doc of ['TEST_CASES.md', 'TEST_CASES_SCHEDULING.md']) {
      expect(readFileSync(resolve(root, '../docs/frontend', doc), 'utf8'), doc).not.toContain('-H1');
    }
  });
});
