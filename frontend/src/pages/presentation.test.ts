import { describe, expect, it } from 'vitest';
import type { ActivityEntry } from '../harness/workspace';
import { summariseSteps } from '../live/LiveChatPage';
import { collapseRepeats } from './ActivityPage';

const entry = (over: Partial<ActivityEntry>): ActivityEntry => ({
  id: 'a',
  at: '2026-11-16T06:41:00Z',
  kind: 'calendar',
  actor: 'agent',
  title: 'Create "Signing prep": failed',
  detail: null,
  outcome: 'failed',
  simulated: true,
  link: null,
  ...over,
});

describe('activity: repeated records', () => {
  it('folds identical consecutive records into one row with a count and the earliest time', () => {
    const rows = collapseRepeats([
      entry({ id: '3', at: '2026-11-16T06:43:00Z' }),
      entry({ id: '2', at: '2026-11-16T06:42:00Z' }),
      entry({ id: '1', at: '2026-11-16T06:41:00Z' }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].attempts).toBe(3);
    // Records are newest first: the row keeps the newest and remembers when the first attempt was.
    expect(rows[0].entry.id).toBe('3');
    expect(rows[0].firstAt).toBe('2026-11-16T06:41:00Z');
  });

  it('never folds records that differ in title, kind, outcome or who acted', () => {
    const differing: Partial<ActivityEntry>[] = [{ title: 'Create "Other": failed' }, { kind: 'email' }, { outcome: 'done' }, { actor: 'human' }];
    for (const change of differing) {
      const rows = collapseRepeats([entry({ id: '2' }), entry({ id: '1', ...change })]);
      expect(rows.map((row) => row.attempts), JSON.stringify(change)).toEqual([1, 1]);
    }
  });

  it('does not fold the same record across something that happened in between', () => {
    const rows = collapseRepeats([entry({ id: '3' }), entry({ id: '2', kind: 'system', title: 'Handed to you' }), entry({ id: '1' })]);
    expect(rows.map((row) => row.attempts)).toEqual([1, 1, 1]);
    expect(rows.every((row) => row.firstAt === null)).toBe(true);
  });

  it('loses no record: the counts add up to what came in', () => {
    const input = [entry({ id: '5' }), entry({ id: '4' }), entry({ id: '3', outcome: 'done' }), entry({ id: '2' }), entry({ id: '1' })];
    expect(collapseRepeats(input).reduce((sum, row) => sum + row.attempts, 0)).toBe(input.length);
    expect(collapseRepeats([])).toEqual([]);
  });
});

describe('chat: a reply with several actions', () => {
  it('says how many actions there are and where each stands, from the server statuses', () => {
    expect(summariseSteps(['awaiting_approval', 'executed', 'awaiting_approval'])).toBe('3 actions in this reply: 2 awaiting approval, 1 completed.');
    expect(summariseSteps(['failed', 'partially_executed'])).toBe('2 actions in this reply: 1 failed, 1 partly completed.');
  });

  it('never counts an approved or running action as completed', () => {
    const line = summariseSteps(['approved', 'executing']);
    expect(line).toBe('2 actions in this reply: 2 executing.');
    expect(line).not.toMatch(/completed/);
  });

  it('does not guess a status it does not know into a finished one', () => {
    expect(summariseSteps(['something_new', 'executed'])).toBe('2 actions in this reply: 1 planning, 1 completed.');
  });
});
