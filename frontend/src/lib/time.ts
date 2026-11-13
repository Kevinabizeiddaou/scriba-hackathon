/** Time helpers shared by the UI, the mock adapter and the evaluation scorer. No dependencies. */

export interface LocalParts {
  /** YYYY-MM-DD in the given zone. */
  date: string;
  /** HH:mm (24-hour) in the given zone. */
  time: string;
  /** 1 = Monday ... 7 = Sunday. */
  weekday: number;
  weekdayShort: string;
  day: string;
  monthShort: string;
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string): Intl.DateTimeFormat {
  let f = formatters.get(timeZone);
  if (!f) {
    f = new Intl.DateTimeFormat('en-GB', {
      timeZone,
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    });
    formatters.set(timeZone, f);
  }
  return f;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function localParts(iso: string, timeZone: string): LocalParts {
  const parts = Object.fromEntries(formatter(timeZone).formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  const month = String(MONTHS.indexOf(parts.month) + 1).padStart(2, '0');
  return {
    date: `${parts.year}-${month}-${parts.day.padStart(2, '0')}`,
    time: `${parts.hour}:${parts.minute}`,
    weekday: WEEKDAYS.indexOf(parts.weekday) + 1,
    weekdayShort: parts.weekday,
    day: parts.day,
    monthShort: parts.month,
  };
}

/** "Tue 17 Nov" */
export function fmtDay(iso: string, timeZone: string): string {
  const p = localParts(iso, timeZone);
  return `${p.weekdayShort} ${p.day} ${p.monthShort}`;
}

/** "11:00" */
export function fmtTime(iso: string, timeZone: string): string {
  return localParts(iso, timeZone).time;
}

/** "Tue 17 Nov, 11:00" */
export function fmtDayTime(iso: string, timeZone: string): string {
  return `${fmtDay(iso, timeZone)}, ${fmtTime(iso, timeZone)}`;
}

/** "Tue 17 Nov, 11:00 to 11:30", or both days when the range crosses midnight. */
export function fmtRange(start: string, end: string, timeZone: string): string {
  const sameDay = localParts(start, timeZone).date === localParts(end, timeZone).date;
  return sameDay
    ? `${fmtDayTime(start, timeZone)} to ${fmtTime(end, timeZone)}`
    : `${fmtDayTime(start, timeZone)} to ${fmtDayTime(end, timeZone)}`;
}

/** "840 ms", "3.2 s", "1 min 12 s" */
export function fmtDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes} min ${seconds} s`;
}

export function minutesBetween(start: string, end: string): number {
  return (Date.parse(end) - Date.parse(start)) / 60_000;
}

export function overlaps(a: { start: string; end: string }, b: { start: string; end: string }): boolean {
  return Date.parse(a.start) < Date.parse(b.end) && Date.parse(b.start) < Date.parse(a.end);
}

const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

/** True for a timestamp that carries an explicit offset, so it names one instant. */
export function isInstant(value: unknown): value is string {
  return typeof value === 'string' && RFC3339.test(value) && !Number.isNaN(Date.parse(value));
}
