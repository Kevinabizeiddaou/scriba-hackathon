import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { DESK_AREAS, INTERNAL_WRITE_TOOLS, SIDE_EFFECT_TOOLS, TOOL_NAMES, type CaseCategory, type EvaluationCase } from '../../harness/types';
import { localParts, overlaps } from '../../lib/time';
import { ALL_CASES, CASE_CATEGORIES, DESK_CASE_SET, DESK_SUITE, DESK_SUITE_SHAPE, EVALUATION_CASES, SYNTHETIC_CASE_SET } from './index';
import { renderCasesMarkdown } from './markdown';

const WEEKDAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

function allEmails(c: EvaluationCase) {
  return c.input.kind === 'email' ? [...c.input.thread, c.input.email] : [];
}

describe('evaluation fixtures', () => {
  it('keeps the twenty scheduling cases as a regression set with sequential ids', () => {
    expect(EVALUATION_CASES).toHaveLength(20);
    expect(EVALUATION_CASES.map((c) => c.id)).toEqual(Array.from({ length: 20 }, (_, i) => `EVAL-${String(i + 1).padStart(3, '0')}`));
    expect(SYNTHETIC_CASE_SET).toEqual({ id: 'synthetic-v3', provenance: 'synthetic', caseCount: 20 });
  });

  it('has thirty-two cases in all, with unique sequential ids', () => {
    expect(ALL_CASES.map((c) => c.id)).toEqual(Array.from({ length: 32 }, (_, i) => `EVAL-${String(i + 1).padStart(3, '0')}`));
  });

  it('covers every required category', () => {
    const covered = new Set<CaseCategory>(ALL_CASES.map((c) => c.category));
    for (const { id } of CASE_CATEGORIES) expect(covered, `category ${id}`).toContain(id);
  });

  it('includes both email and chat inputs', () => {
    const kinds = new Set(ALL_CASES.map((c) => c.input.kind));
    expect(kinds).toEqual(new Set(['email', 'conversation']));
  });

  it('marks every case synthetic and uses only reserved .example addresses', () => {
    for (const c of ALL_CASES) {
      expect(c.provenance.kind).toBe('synthetic');
      const addresses = JSON.stringify(c).match(/[\w.+-]+@[\w.-]+\.[a-z]+/gi) ?? [];
      expect(addresses.length).toBeGreaterThan(0);
      for (const address of addresses) expect(address, `${c.id}: ${address}`).toMatch(/\.example$/);
    }
  });

  it('gives every case prose criteria a human can judge by', () => {
    for (const c of ALL_CASES) {
      expect(c.expected.behavior.length, c.id).toBeGreaterThan(40);
      expect(c.successCriteria.length, c.id).toBeGreaterThan(0);
      expect(c.failureConditions.length, c.id).toBeGreaterThan(0);
      expect(c.expected.outcomes.length, c.id).toBeGreaterThan(0);
      expect(c.expected.classifications.length, c.id).toBeGreaterThan(0);
    }
  });

  it('only references known tools', () => {
    const known = new Set<string>(TOOL_NAMES);
    for (const c of ALL_CASES) {
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
    for (const c of ALL_CASES) {
      const approved = new Set(c.expected.approvals.map((a) => a.tool));
      for (const call of c.expected.toolCalls) {
        for (const tool of Array.isArray(call.tool) ? call.tool : [call.tool]) {
          if ((SIDE_EFFECT_TOOLS as readonly string[]).includes(tool)) expect(approved, `${c.id}: ${tool}`).toContain(tool);
        }
      }
    }
  });

  it('has a calendar with valid, non-overlapping events', () => {
    for (const c of ALL_CASES) {
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
    for (const c of ALL_CASES) {
      for (const message of allEmails(c)) {
        expect(Date.parse(message.sentAt), `${c.id} ${message.id}`).toBeLessThanOrEqual(Date.parse(c.context.now));
      }
    }
  });

  it('writes weekday names that agree with the dates next to them, except in the mismatch case', () => {
    // "Tuesday 17 November" must really be a Tuesday. EVAL-007 is the deliberate exception.
    const pattern = /\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(\d{1,2})\s+november\b/gi;
    for (const c of ALL_CASES) {
      if (c.id === 'EVAL-007') continue;
      const text = [...allEmails(c).map((m) => m.bodyText), ...(c.input.kind === 'conversation' ? c.input.messages.map((m) => m.text) : [])].join('\n');
      for (const match of text.matchAll(pattern)) {
        const iso = `2026-11-${match[2].padStart(2, '0')}T12:00:00+02:00`;
        const actual = WEEKDAY_NAMES[localParts(iso, 'Asia/Beirut').weekday - 1];
        expect(actual, `${c.id}: "${match[0]}"`).toBe(match[1].toLowerCase());
      }
    }
  });

  it('keeps the exported JSON files in step with the TypeScript source', () => {
    const read = (name: string) => JSON.parse(readFileSync(resolve(__dirname, '../../../fixtures', name), 'utf8'));
    expect(read('evaluation-cases.json').cases).toEqual(JSON.parse(JSON.stringify(DESK_SUITE)));
    expect(read('evaluation-cases.json').caseSet).toEqual(DESK_CASE_SET);
    expect(read('scheduling-regression-cases.json').cases).toEqual(JSON.parse(JSON.stringify(EVALUATION_CASES)));
    expect(read('scheduling-regression-cases.json').caseSet).toEqual(SYNTHETIC_CASE_SET);
  });

  it('keeps the generated case documents in step with the TypeScript source', () => {
    const read = (name: string) => readFileSync(resolve(__dirname, '../../../../docs/frontend', name), 'utf8').replace(/\r\n/g, '\n');
    expect(read('TEST_CASES.md')).toBe(renderCasesMarkdown(DESK_SUITE, 'desk'));
    expect(read('TEST_CASES_SCHEDULING.md')).toBe(renderCasesMarkdown(EVALUATION_CASES, 'scheduling'));
  });
});

describe('the desk suite', () => {
  const byArea = (area: string) => DESK_SUITE.filter((c) => c.area === area).map((c) => c.id);

  it('has twenty cases: 3 inbox, 3 email, 5 scheduling, 3 task and reminder, 2 follow-up, 2 multi-step, 2 security and failure', () => {
    expect(DESK_SUITE).toHaveLength(20);
    expect(new Set(DESK_SUITE.map((c) => c.id)).size).toBe(20);
    expect(DESK_SUITE_SHAPE).toEqual({ inbox: 3, email: 3, scheduling: 5, task_reminder: 3, follow_up: 2, multi_step: 2, security_failure: 2 });
    for (const area of DESK_AREAS) expect(byArea(area), area).toHaveLength(DESK_SUITE_SHAPE[area]);
    expect(DESK_CASE_SET).toEqual({ id: 'desk-v1', provenance: 'synthetic', caseCount: 20 });
  });

  it('keeps eight of the original scheduling fixtures and adds twelve new cases', () => {
    const kept = DESK_SUITE.filter((c) => EVALUATION_CASES.includes(c)).map((c) => c.id);
    expect(kept.sort()).toEqual(['EVAL-001', 'EVAL-003', 'EVAL-008', 'EVAL-011', 'EVAL-013', 'EVAL-015', 'EVAL-018', 'EVAL-019']);
    expect(DESK_SUITE.filter((c) => !EVALUATION_CASES.includes(c))).toHaveLength(12);
  });

  it('covers a tool failure and a prompt injection under security and failure', () => {
    const cases = DESK_SUITE.filter((c) => c.area === 'security_failure');
    expect(cases.some((c) => c.context.faults.length > 0)).toBe(true);
    expect(cases.some((c) => c.category === 'prompt_injection')).toBe(true);
  });

  it('states for every case what must be true afterwards, as state assertions or as bans', () => {
    for (const c of DESK_SUITE) {
      expect(c.expected.state.length + c.expected.forbidden.length, c.id).toBeGreaterThan(0);
      for (const assertion of c.expected.state) expect(assertion.why.length, c.id).toBeGreaterThan(10);
    }
    // Every case that expects a write says what the write must leave behind.
    const writes = new Set<string>([...SIDE_EFFECT_TOOLS.filter((t) => t !== 'email.send'), ...INTERNAL_WRITE_TOOLS]);
    for (const c of DESK_SUITE) {
      const expectsWrite = c.expected.toolCalls.some((call) => (Array.isArray(call.tool) ? call.tool : [call.tool]).some((tool) => writes.has(tool)));
      if (expectsWrite) expect(c.expected.state.length, `${c.id} expects a write but asserts no state`).toBeGreaterThan(0);
    }
  });

  it('never asks for approval of a task, a reminder or a follow-up, which are the principal\'s own records', () => {
    for (const c of ALL_CASES) for (const a of c.expected.approvals) expect(INTERNAL_WRITE_TOOLS as readonly string[], c.id).not.toContain(a.tool);
  });

  it('exercises a rejected proposal, chat input, a thread and both kinds of starting state', () => {
    expect(DESK_SUITE.some((c) => c.expected.harnessDecision === 'reject')).toBe(true);
    expect(DESK_SUITE.some((c) => c.input.kind === 'conversation')).toBe(true);
    expect(DESK_SUITE.some((c) => c.input.kind === 'email' && c.input.thread.length >= 2)).toBe(true);
    expect(DESK_SUITE.some((c) => c.context.tasks.length > 0)).toBe(true);
    expect(DESK_SUITE.some((c) => c.context.followUps.length > 0)).toBe(true);
    expect(DESK_SUITE.filter((c) => c.expected.priorities.length > 0).length).toBeGreaterThanOrEqual(3);
  });
});
