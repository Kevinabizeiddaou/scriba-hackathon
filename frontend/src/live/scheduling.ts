/**
 * Pure helpers for the scheduling workspace. They turn the Desk overlay's availability answers
 * (BACKEND_CONTRACT section 4) into what the screen says, and keep one rule in one place:
 * a calendar that could not be read makes availability unknown, never free.
 */
import type { CalendarRead, DeskAvailability, DeskSlotCheck, IncompleteReason, Slot } from '../api/desk'

/** Python's weekday numbering, as the backend sends it: 0 is Monday. */
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export function weekdayNames(weekdays: number[]): string {
  if (weekdays.length === 0) return 'every day'
  const sorted = [...new Set(weekdays)].filter(day => day >= 0 && day <= 6).sort((a, b) => a - b)
  const consecutive = sorted.every((day, index) => index === 0 || day === sorted[index - 1] + 1)
  if (consecutive && sorted.length > 2) return `${WEEKDAYS[sorted[0]]} to ${WEEKDAYS[sorted.at(-1)!]}`
  return sorted.map(day => WEEKDAYS[day]).join(', ')
}

export const INCOMPLETE_REASON: Record<IncompleteReason, { title: string; detail: string }> = {
  no_calendar_connected: {
    title: 'No calendar is connected',
    detail: 'Connect Google Calendar or Outlook Calendar in Scriba. Until then no time can be offered or verified.',
  },
  calendar_unreadable: {
    title: 'A connected calendar could not be read',
    detail: 'No free time is offered, because a calendar that cannot be read may hold a meeting. Its availability is unknown, not free.',
  },
  invalid_preferences: {
    title: 'Your working-hours preferences could not be used',
    detail: 'Correct the time zone and working hours in Scriba, then look again.',
  },
}

const CALENDAR_ERROR: Record<string, string> = {
  reconnect_required: 'needs to be reconnected',
  permission_missing: 'is missing calendar permission',
  provider_error: 'did not answer',
  range_too_large: 'holds too many events in this range to read safely',
}

export function calendarProblem(calendar: CalendarRead): string | null {
  if (calendar.ok) return null
  return CALENDAR_ERROR[calendar.error ?? ''] ?? `failed (${calendar.error ?? 'unknown error'})`
}

export type SlotVerdict = 'free' | 'conflict' | 'unknown'

/**
 * What one checked time is. `free` only when the backend says true: null means a calendar was
 * unreadable, and is reported as unknown even though no conflict was found.
 */
export function slotVerdict(check: Pick<DeskSlotCheck, 'free'>): SlotVerdict {
  return check.free === true ? 'free' : check.free === false ? 'conflict' : 'unknown'
}

/** Free slots are shown only from a complete read, whatever the array holds. */
export function offeredSlots(availability: Pick<DeskAvailability, 'complete' | 'slots'>): Slot[] {
  return availability.complete ? availability.slots : []
}

/** A local date (YYYY-MM-DD) plus a number of days, as a date. Dates are sent without an offset so the backend reads them in the user's zone. */
export function addDays(date: string, days: number): string {
  const base = Date.parse(`${date}T00:00:00Z`)
  if (Number.isNaN(base)) return date
  return new Date(base + days * 86_400_000).toISOString().slice(0, 10)
}

export const MAX_RANGE_DAYS = 31

/** The range the screen asks for: whole days, never more than the backend's 31-day limit. */
export function rangeFor(date: string, days: number): { start: string; end: string } {
  const span = Math.max(1, Math.min(MAX_RANGE_DAYS, Math.round(days)))
  return { start: `${date}T00:00:00`, end: `${addDays(date, span)}T00:00:00` }
}

/** End of a meeting that starts at a local date-time (YYYY-MM-DDTHH:MM), without an offset. */
export function localEnd(start: string, minutes: number): string | null {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/.exec(start)
  if (!match) return null
  const base = Date.parse(`${match[1]}T${match[2]}:${match[3]}:00Z`)
  if (Number.isNaN(base)) return null
  return new Date(base + minutes * 60_000).toISOString().slice(0, 16)
}

/** Groups slots or busy periods by the local day they start on, in the given zone's wall-clock date. */
export function byDay<T extends { start: string }>(items: T[], dayOf: (iso: string) => string): Array<{ day: string; items: T[] }> {
  const groups: Array<{ day: string; items: T[] }> = []
  for (const item of items) {
    const day = dayOf(item.start)
    const last = groups.at(-1)
    if (last?.day === day) last.items.push(item)
    else groups.push({ day, items: [item] })
  }
  return groups
}
