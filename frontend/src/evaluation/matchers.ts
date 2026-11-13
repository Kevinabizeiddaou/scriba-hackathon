/** Evaluates ArgMatcher expressions against the input of a tool call. */
import type { ArgMatcher } from '../harness/types';
import { isInstant, localParts } from '../lib/time';

/**
 * Lower-cased strings from an array of strings or of objects with an `email` field.
 * A bare string counts as a one-item list, so a recipient sent as "a@x" instead of ["a@x"]
 * is still seen by a ban on that address.
 */
function toStringList(value: unknown): string[] | null {
  if (typeof value === 'string') return [value.trim().toLowerCase()];
  if (!Array.isArray(value)) return null;
  return value.map((item) => {
    if (typeof item === 'string') return item.toLowerCase();
    if (item && typeof item === 'object' && typeof (item as { email?: unknown }).email === 'string') {
      return (item as { email: string }).email.toLowerCase();
    }
    return String(item).toLowerCase();
  });
}

export function matchArg(matcher: ArgMatcher, actual: unknown): boolean {
  if (matcher === null || typeof matcher !== 'object') {
    if (isInstant(matcher) && isInstant(actual)) return Date.parse(matcher) === Date.parse(actual);
    return matcher === actual;
  }
  if ('$instant' in matcher) {
    return isInstant(actual) && Date.parse(actual) === Date.parse(matcher.$instant);
  }
  if ('$instantBetween' in matcher) {
    if (!isInstant(actual)) return false;
    const t = Date.parse(actual);
    return t >= Date.parse(matcher.$instantBetween[0]) && t <= Date.parse(matcher.$instantBetween[1]);
  }
  if ('$localTimeBetween' in matcher) {
    if (!isInstant(actual)) return false;
    const { timezone, from, to } = matcher.$localTimeBetween;
    const time = localParts(actual, timezone).time;
    return time >= from && time <= to;
  }
  if ('$contains' in matcher) {
    return typeof actual === 'string' && actual.toLowerCase().includes(matcher.$contains.toLowerCase());
  }
  if ('$matches' in matcher) {
    return typeof actual === 'string' && new RegExp(matcher.$matches, 'i').test(actual);
  }
  if ('$includes' in matcher) {
    const list = toStringList(actual);
    return list !== null && matcher.$includes.every((wanted) => list.includes(wanted.toLowerCase()));
  }
  if ('$excludes' in matcher) {
    const list = toStringList(actual) ?? [];
    return matcher.$excludes.every((banned) => !list.includes(banned.toLowerCase()));
  }
  if ('$all' in matcher) {
    return matcher.$all.every((m) => matchArg(m, actual));
  }
  return false;
}

export function describeMatcher(matcher: ArgMatcher): string {
  if (matcher === null || typeof matcher !== 'object') return JSON.stringify(matcher);
  if ('$instant' in matcher) return `at ${matcher.$instant}`;
  if ('$instantBetween' in matcher) return `between ${matcher.$instantBetween[0]} and ${matcher.$instantBetween[1]}`;
  if ('$localTimeBetween' in matcher) {
    const { timezone, from, to } = matcher.$localTimeBetween;
    return `${from} to ${to} ${timezone} time`;
  }
  if ('$contains' in matcher) return `contains "${matcher.$contains}"`;
  if ('$matches' in matcher) return `matches /${matcher.$matches}/i`;
  if ('$includes' in matcher) return `includes ${matcher.$includes.join(', ')}`;
  if ('$excludes' in matcher) return `excludes ${matcher.$excludes.join(', ')}`;
  return matcher.$all.map(describeMatcher).join(' and ');
}

export function describeArgs(args: Record<string, ArgMatcher> | undefined): string {
  if (!args || Object.keys(args).length === 0) return '';
  return Object.entries(args)
    .map(([key, matcher]) => `${key} ${describeMatcher(matcher)}`)
    .join('; ');
}

/** True when every matcher is satisfied by the corresponding top-level key of `input`. */
export function matchArgs(args: Record<string, ArgMatcher> | undefined, input: Record<string, unknown>): boolean {
  if (!args) return true;
  return Object.entries(args).every(([key, matcher]) => matchArg(matcher, input[key]));
}
