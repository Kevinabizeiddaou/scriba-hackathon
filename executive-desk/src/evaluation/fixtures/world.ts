/**
 * The synthetic world every evaluation case is set in.
 *
 * Everything here is invented for development: the company, the people, the calendar.
 * All addresses use the reserved ".example" top-level domain so they can never resolve.
 * Do not describe these fixtures as customer cases.
 *
 * The simulated week is Monday 16 to Friday 20 November 2026. The principal works in
 * Asia/Beirut, which is UTC+02:00 on those dates. Other zones on those dates:
 * New York UTC-05:00, London UTC+00:00, Dubai UTC+04:00, Singapore UTC+08:00.
 */
import type {
  CalendarEvent,
  CaseContext,
  CaseExpectation,
  CaseProvenance,
  ContextFollowUp,
  ContextTask,
  ExpectedToolCall,
  FaultInjection,
  ForbiddenToolCall,
  ISODateTime,
  Participant,
  SampleEmail,
  ToolName,
} from '../../api/types';

export const PRINCIPAL_TZ = 'Asia/Beirut';

/** Stamped on every case in this folder. */
export const SYNTHETIC: CaseProvenance = { kind: 'synthetic', note: 'Invented for development. Not derived from any real request or customer.' };

export const DAY = {
  mon: '2026-11-16',
  tue: '2026-11-17',
  wed: '2026-11-18',
  thu: '2026-11-19',
  fri: '2026-11-20',
} as const;

/** Beirut wall-clock time on a given date, as an RFC 3339 instant. */
export function bt(date: string, time: string): ISODateTime {
  return `${date}T${time}:00+02:00`;
}

/** The moment most requests arrive: Monday 16 November 2026, 08:30 Beirut time. */
export const NOW = bt(DAY.mon, '08:30');

export const PEOPLE = {
  layla: { name: 'Layla Mansour', email: 'layla.mansour@cedarvale.example' },
  omar: { name: 'Omar Saab', email: 'omar.saab@cedarvale.example' },
  rana: { name: 'Rana Khoury', email: 'rana.khoury@cedarvale.example' },
  karim: { name: 'Karim Aziz', email: 'karim.aziz@cedarvale.example' },
  maya: { name: 'Maya Okafor', email: 'maya.okafor@brightwell.example' },
  daniel: { name: 'Daniel Reyes', email: 'daniel.reyes@altamira.example' },
  priya: { name: 'Priya Nair', email: 'priya.nair@hudson-analytics.example' },
  weiLing: { name: 'Wei Ling Tan', email: 'weiling.tan@straitscargo.example' },
  marcus: { name: 'Marcus Lim', email: 'marcus.lim@straitscargo.example' },
  james: { name: 'James Whitcombe', email: 'james.whitcombe@thameside.example' },
  sofia: { name: 'Sofia Marchetti', email: 'sofia.marchetti@lumen-events.example' },
  tom: { name: 'Tom Becker', email: 'tom.becker@halepartners.example' },
  greg: { name: 'Greg Dalton', email: 'greg.dalton@northpier.example' },
  vendor: { name: 'Marcus Hale', email: 'm.hale@fastmeet-scheduling.example' },
} satisfies Record<string, Participant>;

export const PRINCIPAL: CaseContext['principal'] = {
  ...PEOPLE.layla,
  timezone: PRINCIPAL_TZ,
  workingHours: { days: [1, 2, 3, 4, 5], start: '09:00', end: '18:00' },
};

export function ev(
  id: string,
  title: string,
  date: string,
  start: string,
  end: string,
  attendees: Participant[] = [],
  location: string | null = null,
): CalendarEvent {
  return {
    id,
    title,
    start: bt(date, start),
    end: bt(date, end),
    timezone: PRINCIPAL_TZ,
    attendees: [PEOPLE.layla, ...attendees],
    location,
    description: null,
    status: 'confirmed',
  };
}

/** Layla's standing week. Individual cases add to it. */
export const BASE_CALENDAR: CalendarEvent[] = [
  ev('evt-lead-sync', 'Weekly leadership sync', DAY.mon, '10:00', '11:00', [PEOPLE.omar, PEOPLE.rana, PEOPLE.karim], 'Boardroom'),
  ev('evt-altamira', 'Vendor review: Altamira Freight', DAY.mon, '15:00', '16:00', [PEOPLE.daniel], 'Video call'),
  ev('evt-board-prep', 'Board prep with Karim', DAY.tue, '09:30', '10:30', [PEOPLE.karim]),
  ev('evt-omar-1on1', '1:1 with Omar', DAY.tue, '14:00', '15:00', [PEOPLE.omar]),
  ev('evt-q-planning', 'Quarterly planning workshop', DAY.wed, '11:00', '12:30', [PEOPLE.omar, PEOPLE.rana, PEOPLE.karim], 'Boardroom'),
  ev('evt-recruiter', 'Recruiter check-in', DAY.wed, '16:00', '16:30', [PEOPLE.tom], 'Phone'),
  ev('evt-brightwell', 'Customer call: Brightwell Foods', DAY.thu, '10:00', '11:00', [PEOPLE.maya], 'Video call'),
  ev('evt-lunch-hold', 'Lunch (hold)', DAY.thu, '13:00', '14:00'),
  ev('evt-finance', 'Finance review', DAY.fri, '09:00', '10:00', [PEOPLE.karim]),
  ev('evt-focus', 'Focus block: strategy memo', DAY.fri, '15:00', '17:00'),
];

export function context(over: { now?: ISODateTime; extraEvents?: CalendarEvent[]; faults?: FaultInjection[]; tasks?: ContextTask[]; followUps?: ContextFollowUp[] } = {}): CaseContext {
  return {
    now: over.now ?? NOW,
    principal: PRINCIPAL,
    calendar: [...BASE_CALENDAR, ...(over.extraEvents ?? [])].sort((a, b) => Date.parse(a.start) - Date.parse(b.start)),
    tasks: over.tasks ?? [],
    followUps: over.followUps ?? [],
    faults: over.faults ?? [],
  };
}

export function email(
  id: string,
  from: Participant,
  sentAt: ISODateTime,
  subject: string,
  bodyText: string,
  opts: { threadId?: string; to?: Participant[]; cc?: Participant[] } = {},
): SampleEmail {
  return {
    id,
    threadId: opts.threadId ?? `thr-${id}`,
    from,
    to: opts.to ?? [PEOPLE.layla],
    cc: opts.cc ?? [],
    sentAt,
    subject,
    bodyText,
  };
}

/** Fills in the fields most cases leave at their defaults. */
export function expectation(
  e: Pick<CaseExpectation, 'behavior' | 'classifications' | 'outcomes'> & Partial<CaseExpectation>,
): CaseExpectation {
  return {
    runStatuses: ['completed'],
    toolCalls: [],
    whenOutcome: {},
    forbidden: [],
    order: [],
    approvals: [],
    harnessDecision: 'approve',
    outboundEmail: null,
    proposedSlots: null,
    chatReply: null,
    flags: [],
    state: [],
    ...e,
  };
}

/** Every case that reasons about availability must read the calendar first. */
export const CALENDAR_READ: ExpectedToolCall = {
  tool: ['calendar.list_events', 'calendar.find_free_slots'],
  why: 'Availability must be read from the calendar, never assumed.',
};

export function forbid(tool: ToolName, why: string, includeProposed = true): ForbiddenToolCall {
  return { tool, includeProposed, why };
}

/** For cases where nothing on the calendar may change, not even as a proposal. */
export function noCalendarWrites(why: string): ForbiddenToolCall[] {
  return [
    forbid('calendar.create_event', why),
    forbid('calendar.update_event', why),
    forbid('calendar.cancel_event', why),
  ];
}
