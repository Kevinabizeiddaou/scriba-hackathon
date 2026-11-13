import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { SIDE_EFFECT_TOOLS, TOOL_NAMES, type CaseCategory, type EvaluationCase } from '../../api/types';
import { localParts, overlaps } from '../../lib/time';
import { CASE_CATEGORIES, EVALUATION_CASES } from './index';

const WEEKDAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

function allEmails(c: EvaluationCase) {
  return c.input.kind === 'email' ? [...c.input.thread, c.input.email] : [];
}

describe('evaluation fixtures', () => {
  it('has exactly twenty cases with unique sequential ids', () => {
    expect(EVALUATION_CASES).toHaveLength(20);
    expect(EVALUATION_CASES.map((c) => c.id)).toEqual(Array.from({ length: 20 }, (_, i) => `EVAL-${String(i + 1).padStart(3, '0')}`));
  });

  it('covers every required category', () => {
    const covered = new Set<CaseCategory>(EVALUATION_CASES.map((c) => c.category));
    for (const { id } of CASE_CATEGORIES) expect(covered, `category ${id}`).toContain(id);
  });

  it('includes both email and chat inputs', () => {
    const kinds = new Set(EVALUATION_CASES.map((c) => c.input.kind));
    expect(kinds).toEqual(new Set(['email', 'conversation']));
  });

  it('marks every case synthetic and uses only reserved .example addresses', () => {
    for (const c of EVALUATION_CASES) {
      expect(c.synthetic).toBe(true);
      const addresses = JSON.stringify(c).match(/[\w.+-]+@[\w.-]+\.[a-z]+/gi) ?? [];
      expect(addresses.length).toBeGreaterThan(0);
      for (const address of addresses) expect(address, `${c.id}: ${address}`).toMatch(/\.example$/);
    }
  });

  it('gives every case prose criteria a human can judge by', () => {
    for (const c of EVALUATION_CASES) {
      expect(c.expected.behavior.length, c.id).toBeGreaterThan(40);
      expect(c.successCriteria.length, c.id).toBeGreaterThan(0);
      expect(c.failureConditions.length, c.id).toBeGreaterThan(0);
      expect(c.expected.outcomes.length, c.id).toBeGreaterThan(0);
      expect(c.expected.classifications.length, c.id).toBeGreaterThan(0);
    }
  });

  it('only references known tools', () => {
    const known = new Set<string>(TOOL_NAMES);
    for (const c of EVALUATION_CASES) {
      const tools = [
        ...c.expected.toolCalls.flatMap((t) => (Array.isArray(t.tool) ? t.tool : [t.tool])),
        ...c.expected.forbidden.map((f) => f.tool),
        ...c.expected.order.flat(),
        ...c.context.faults.map((f) => f.tool),
      ];
      for (const tool of tools) expect(known, `${c.id}: ${tool}`).toContain(tool);
      for (const a of c.expected.approvals) expect(SIDE_EFFECT_TOOLS).toContain(a.tool);
    }
  });

  it('requires approval for every side effect a case expects', () => {
    for (const c of EVALUATION_CASES) {
      const approved = new Set(c.expected.approvals.map((a) => a.tool));
      for (const call of c.expected.toolCalls) {
        for (const tool of Array.isArray(call.tool) ? call.tool : [call.tool]) {
          if ((SIDE_EFFECT_TOOLS as readonly string[]).includes(tool)) expect(approved, `${c.id}: ${tool}`).toContain(tool);
        }
      }
    }
  });

  it('has a calendar with valid, non-overlapping events', () => {
    for (const c of EVALUATION_CASES) {
      const events = c.context.calendar;
      expect(new Set(events.map((e) => e.id)).size, c.id).toBe(events.length);
      for (const e of events) expect(Date.parse(e.end), `${c.id} ${e.id}`).toBeGreaterThan(Date.parse(e.start));
      for (let i = 0; i < events.length; i += 1) {
        for (let j = i + 1; j < events.length; j += 1) {
          expect(overlaps(events[i], events[j]), `${c.id}: ${events[i].id} overlaps ${events[j].id}`).toBe(false);
        }
      }
    }
  });

  it('delivers every email before the moment the case starts', () => {
    for (const c of EVALUATION_CASES) {
      for (const message of allEmails(c)) {
        expect(Date.parse(message.sentAt), `${c.id} ${message.id}`).toBeLessThanOrEqual(Date.parse(c.context.now));
      }
    }
  });

  it('writes weekday names that agree with the dates next to them, except in the mismatch case', () => {
    // "Tuesday 17 November" must really be a Tuesday. EVAL-007 is the deliberate exception.
    const pattern = /\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(\d{1,2})\s+november\b/gi;
    for (const c of EVALUATION_CASES) {
      if (c.id === 'EVAL-007') continue;
      const text = [...allEmails(c).map((m) => m.bodyText), ...(c.input.kind === 'conversation' ? c.input.messages.map((m) => m.text) : [])].join('\n');
      for (const match of text.matchAll(pattern)) {
        const iso = `2026-11-${match[2].padStart(2, '0')}T12:00:00+02:00`;
        const actual = WEEKDAY_NAMES[localParts(iso, 'Asia/Beirut').weekday - 1];
        expect(actual, `${c.id}: "${match[0]}"`).toBe(match[1].toLowerCase());
      }
    }
  });

  it('keeps the exported JSON in step with the TypeScript source', () => {
    const file = resolve(__dirname, '../../../fixtures/evaluation-cases.json');
    const exported = JSON.parse(readFileSync(file, 'utf8'));
    expect(exported.cases).toEqual(JSON.parse(JSON.stringify(EVALUATION_CASES)));
  });
});
