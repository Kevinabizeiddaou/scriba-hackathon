import { describe, expect, it } from 'vitest';
import { matchArg, matchArgs } from './matchers';

describe('argument matchers', () => {
  it('compares timestamps as instants, whatever offset they are written in', () => {
    expect(matchArg({ $instant: '2026-11-18T10:00:00-05:00' }, '2026-11-18T17:00:00+02:00')).toBe(true);
    expect(matchArg({ $instant: '2026-11-18T10:00:00-05:00' }, '2026-11-18T10:00:00+02:00')).toBe(false);
    expect(matchArg('2026-11-18T15:00:00Z', '2026-11-18T17:00:00+02:00')).toBe(true);
  });

  it('rejects a timestamp with no offset rather than guessing its zone', () => {
    expect(matchArg({ $instant: '2026-11-18T17:00:00+02:00' }, '2026-11-18T17:00:00')).toBe(false);
    expect(matchArg({ $instantBetween: ['2026-11-18T00:00:00+02:00', '2026-11-19T00:00:00+02:00'] }, '2026-11-18 17:00')).toBe(false);
  });

  it('checks ranges inclusively', () => {
    const between = { $instantBetween: ['2026-11-18T12:00:00+02:00', '2026-11-18T17:00:00+02:00'] as [string, string] };
    expect(matchArg(between, '2026-11-18T12:00:00+02:00')).toBe(true);
    expect(matchArg(between, '2026-11-18T17:00:00+02:00')).toBe(true);
    expect(matchArg(between, '2026-11-18T17:00:01+02:00')).toBe(false);
  });

  it('checks local wall-clock time in the named zone', () => {
    const morning = { $localTimeBetween: { timezone: 'Asia/Beirut', from: '09:00', to: '11:15' } };
    expect(matchArg(morning, '2026-11-18T07:00:00Z')).toBe(true); // 09:00 Beirut
    expect(matchArg(morning, '2026-11-18T09:00:00Z')).toBe(true); // 11:00 Beirut
    expect(matchArg(morning, '2026-11-18T09:00:00+08:00')).toBe(false); // 03:00 Beirut
  });

  it('matches address lists case-insensitively, as strings or as participants', () => {
    expect(matchArg({ $includes: ['A@x.example'] }, ['a@x.example', 'b@x.example'])).toBe(true);
    expect(matchArg({ $includes: ['a@x.example'] }, [{ name: 'A', email: 'A@X.example' }])).toBe(true);
    expect(matchArg({ $includes: ['a@x.example', 'c@x.example'] }, ['a@x.example'])).toBe(false);
    // A bare string is read as a one-item list, so a ban on an address cannot be dodged by sending a string.
    expect(matchArg({ $includes: ['a@x.example'] }, 'A@x.example')).toBe(true);
    expect(matchArg({ $excludes: ['evil@x.example'] }, 'evil@x.example')).toBe(false);
    expect(matchArg({ $includes: ['a@x.example'] }, 42)).toBe(false);
    expect(matchArg({ $excludes: ['evil@x.example'] }, ['a@x.example'])).toBe(true);
    expect(matchArg({ $excludes: ['evil@x.example'] }, ['EVIL@x.example'])).toBe(false);
    expect(matchArg({ $excludes: ['evil@x.example'] }, undefined)).toBe(true);
  });

  it('combines matchers with $all and matches text', () => {
    expect(matchArg({ $all: [{ $contains: 'beirut' }, { $matches: '^hello' }] }, 'Hello from Beirut')).toBe(true);
    expect(matchArg({ $all: [{ $contains: 'beirut' }, { $matches: '^bye' }] }, 'Hello from Beirut')).toBe(false);
  });

  it('matches top-level keys only and treats a missing key as a mismatch', () => {
    expect(matchArgs({ eventId: 'evt-1' }, { eventId: 'evt-1', extra: true })).toBe(true);
    expect(matchArgs({ eventId: 'evt-1' }, {})).toBe(false);
    expect(matchArgs(undefined, {})).toBe(true);
  });
});
