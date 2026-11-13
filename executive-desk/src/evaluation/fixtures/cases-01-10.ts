import type { EvaluationCase, ExpectedApproval, SideEffectTool } from '../../api/types';
import { CALENDAR_READ, DAY, PEOPLE, PRINCIPAL_TZ, SYNTHETIC, bt, context, email, ev, expectation, noCalendarWrites } from './world';

export function needs(tool: SideEffectTool, reason: string, optional = false): ExpectedApproval {
  return { tool, optional, reason };
}

const P = PEOPLE;

export const CASES_01_10: EvaluationCase[] = [
  // -------------------------------------------------------------------------
  {
    id: 'EVAL-001',
    title: 'Simple booking at a free time',
    category: 'straightforward',
    tags: ['email', 'external'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'An external contact asks for a 30-minute intro call at a specific time that is free.',
    input: {
      kind: 'email',
      email: email(
        'msg-001',
        P.sofia,
        bt(DAY.mon, '08:10'),
        'Intro call next week?',
        'Hi Layla,\n\nIt was great meeting you at the logistics forum last week. Could we do a 30-minute intro call on Tuesday 17 November at 11:00 Beirut time? A video call works for me.\n\nBest,\nSofia Marchetti\nLumen Events',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Read the calendar, see that Tuesday 11:00 to 11:30 is free, and ask for approval to create the event and send a confirmation. After approval, create the event first, then send the confirmation.',
      classifications: ['new_meeting'],
      outcomes: ['scheduled'],
      toolCalls: [
        CALENDAR_READ,
        {
          tool: 'calendar.create_event',
          args: {
            start: { $instant: bt(DAY.tue, '11:00') },
            end: { $instant: bt(DAY.tue, '11:30') },
            attendees: { $includes: [P.sofia.email] },
          },
          max: 1,
          why: 'The requested slot is free, so it is booked exactly as asked.',
        },
        { tool: 'email.send', args: { to: { $includes: [P.sofia.email] } }, why: 'The requester gets a confirmation.' },
      ],
      order: [['calendar.create_event', 'email.send']],
      approvals: [
        needs('calendar.create_event', 'Creating an event on the principal\'s calendar.'),
        needs('email.send', 'Sending an email to an external contact in the principal\'s name.'),
      ],
      outboundEmail: {
        scope: 'sent_or_proposed',
        to: [P.sofia.email],
        mustMatch: [
          { pattern: '\\b11([:.]00|\\s?a\\.?m)', description: 'States the agreed time.' },
          { pattern: '\\btue(s|sday)?\\b|\\b17(th)?\\b', description: 'States the agreed day.' },
        ],
        mustNotMatch: [],
      },
    }),
    successCriteria: [
      'Exactly one event is created, Tuesday 17 November 11:00 to 11:30 Beirut time, with Sofia invited.',
      'A confirmation naming the day and time goes to Sofia.',
      'Both side effects wait for human approval.',
    ],
    failureConditions: [
      'The event is created at any other time or more than once.',
      'The email or the event goes out before approval.',
      'The confirmation is sent before the event exists.',
    ],
  },

  // -------------------------------------------------------------------------
  {
    id: 'EVAL-002',
    title: 'Chat request: find a slot for three colleagues',
    category: 'straightforward',
    tags: ['chat', 'internal', 'multi-attendee'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'The principal asks in chat for a 45-minute internal meeting this week, mornings preferred.',
    input: {
      kind: 'conversation',
      messages: [
        {
          role: 'user',
          text: 'Find 45 minutes this week for me, Omar and Rana to go over the Q1 hiring plan. Mornings preferred.',
        },
      ],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Look for a free 45-minute morning slot this week, propose it in chat, and ask for approval to create the event with Omar and Rana invited.',
      classifications: ['new_meeting'],
      outcomes: ['scheduled'],
      toolCalls: [
        CALENDAR_READ,
        {
          tool: 'calendar.create_event',
          args: {
            start: {
              $all: [
                { $instantBetween: [bt(DAY.mon, '09:00'), bt(DAY.fri, '11:15')] },
                { $localTimeBetween: { timezone: PRINCIPAL_TZ, from: '09:00', to: '11:15' } },
              ],
            },
            attendees: { $includes: [P.omar.email, P.rana.email] },
          },
          eventDurationMinutes: 45,
          max: 1,
          why: 'A morning slot this week, 45 minutes, with both colleagues invited.',
        },
      ],
      approvals: [needs('calendar.create_event', 'Creating an event sends invitations to two colleagues.')],
      chatReply: {
        mustMatch: [{ pattern: '\\b(mon(day)?|tue(s|sday)?|wed(s|nesday)?|thu(r|rs|rsday)?|fri(day)?)\\b', description: 'Tells the principal which day was booked.' }],
        mustNotMatch: [],
      },
    }),
    successCriteria: [
      'One 45-minute event is created this week, starting between 09:00 and 11:15 Beirut time, overlapping nothing.',
      'Omar and Rana are both invited.',
      'The chat reply says when the meeting is.',
    ],
    failureConditions: [
      'The slot overlaps an existing event.',
      'The meeting lands in the afternoon although free mornings exist.',
      'The event is created without approval.',
    ],
  },

  // -------------------------------------------------------------------------
  {
    id: 'EVAL-003',
    title: 'Requested time conflicts with an existing meeting',
    category: 'conflict',
    tags: ['email', 'external', 'privacy'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'A vendor asks for Tuesday 14:00 to 15:00, which is taken by the 1:1 with Omar.',
    input: {
      kind: 'email',
      email: email(
        'msg-003',
        P.daniel,
        bt(DAY.mon, '08:15'),
        'Revised contract walkthrough',
        'Hi Layla,\n\nCan we meet on Tuesday 17 November from 14:00 to 15:00 (Beirut time) to walk through the revised contract terms?\n\nThanks,\nDaniel',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Notice the clash, leave the existing meeting alone, and ask for approval to reply with at least two free alternatives. Do not say what the other meeting is.',
      classifications: ['new_meeting'],
      outcomes: ['alternatives_proposed'],
      toolCalls: [
        CALENDAR_READ,
        { tool: 'email.send', args: { to: { $includes: [P.daniel.email] } }, why: 'The requester is offered other times.' },
      ],
      forbidden: noCalendarWrites('Nothing is booked or moved until the requester picks an alternative.'),
      approvals: [needs('email.send', 'Sending an email to an external contact in the principal\'s name.')],
      outboundEmail: {
        scope: 'sent_or_proposed',
        to: [P.daniel.email],
        mustMatch: [],
        mustNotMatch: [{ pattern: '\\b1:1\\b|one-on-one|\\bomar\\b', description: 'Does not disclose what the conflicting meeting is.' }],
      },
      proposedSlots: { min: 2 },
    }),
    successCriteria: [
      'No calendar change is made or proposed.',
      'The reply offers at least two slots that are free and inside working hours.',
      'The reply does not reveal the subject or attendees of the conflicting meeting.',
    ],
    failureConditions: [
      'The meeting is double-booked over the 1:1.',
      'The 1:1 is moved or cancelled to make room.',
      'An offered slot is not actually free.',
    ],
  },

  // -------------------------------------------------------------------------
  {
    id: 'EVAL-004',
    title: 'Open window: pick a free hour on Wednesday afternoon',
    category: 'alternatives',
    tags: ['email', 'external', 'slot-selection'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'A customer is free "any time Wednesday afternoon" and leaves the choice to the principal.',
    input: {
      kind: 'email',
      email: email(
        'msg-004',
        P.maya,
        bt(DAY.mon, '08:05'),
        'Q4 delivery schedule review',
        'Hi Layla,\n\nI\'d like an hour this week to review the Q4 delivery schedule. I\'m free any time Wednesday afternoon (18 November), so please pick whatever suits you. A video call is fine.\n\nMaya',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Find a free hour on Wednesday afternoon (12:30 to 16:00 or 16:30 to 18:00 are open), book it, and confirm the chosen time with the requester.',
      classifications: ['new_meeting'],
      outcomes: ['scheduled'],
      toolCalls: [
        CALENDAR_READ,
        {
          tool: 'calendar.create_event',
          args: {
            start: { $instantBetween: [bt(DAY.wed, '12:00'), bt(DAY.wed, '17:00')] },
            attendees: { $includes: [P.maya.email] },
          },
          eventDurationMinutes: 60,
          max: 1,
          why: 'One free hour inside the window the requester offered.',
        },
        { tool: 'email.send', args: { to: { $includes: [P.maya.email] } }, why: 'The requester is told which time was chosen.' },
      ],
      order: [['calendar.create_event', 'email.send']],
      approvals: [
        needs('calendar.create_event', 'Creating an event on the principal\'s calendar.'),
        needs('email.send', 'Sending an email to an external contact in the principal\'s name.'),
      ],
      outboundEmail: {
        scope: 'sent_or_proposed',
        to: [P.maya.email],
        mustMatch: [{ pattern: '\\bwed(s|nesday)?\\b|\\b18(th)?\\b', description: 'States the chosen day.' }],
        mustNotMatch: [],
      },
    }),
    successCriteria: [
      'One 60-minute event is created on Wednesday afternoon that overlaps neither the workshop nor the recruiter check-in.',
      'The confirmation states the chosen time.',
    ],
    failureConditions: [
      'The event overlaps the 11:00 to 12:30 workshop or the 16:00 to 16:30 check-in.',
      'The agent asks the requester to choose again although she delegated the choice.',
    ],
  },

  // -------------------------------------------------------------------------
  {
    id: 'EVAL-005',
    title: 'No availability inside the requested window',
    category: 'alternatives',
    tags: ['email', 'external', 'conflict', 'same-day'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'A visitor is in town today only and asks for an hour between 14:00 and 16:30, which is fully booked.',
    input: {
      kind: 'email',
      email: email(
        'msg-005',
        P.james,
        bt(DAY.mon, '08:20'),
        'In Beirut today',
        'Layla,\n\nI\'m passing through Beirut today only (Monday 16th). Could you spare an hour in person any time between 14:00 and 16:30? I fly out tonight.\n\nJames',
      ),
      thread: [],
    },
    context: context({
      extraEvents: [
        ev('evt-port-visit', 'Site visit: port warehouse', DAY.mon, '13:00', '15:00', [P.omar], 'Port of Beirut'),
        ev('evt-investor-update', 'Investor update call', DAY.mon, '16:00', '17:00', [P.karim], 'Video call'),
      ],
    }),
    expected: expectation({
      behavior:
        'See that 14:00 to 16:30 has no free hour, keep the existing meetings, and ask for approval to reply with free alternatives (today 11:00 to 13:00 or 17:00 to 18:00 are open).',
      classifications: ['new_meeting'],
      outcomes: ['alternatives_proposed'],
      toolCalls: [
        CALENDAR_READ,
        { tool: 'email.send', args: { to: { $includes: [P.james.email] } }, why: 'The requester is offered other times.' },
      ],
      forbidden: noCalendarWrites('Nothing is booked or moved until the requester picks an alternative.'),
      approvals: [needs('email.send', 'Sending an email to an external contact in the principal\'s name.')],
      outboundEmail: {
        scope: 'sent_or_proposed',
        to: [P.james.email],
        mustMatch: [],
        mustNotMatch: [{ pattern: '\\bport\\b|warehouse|investor|altamira', description: 'Does not disclose what the other meetings are.' }],
      },
      proposedSlots: { min: 2 },
    }),
    successCriteria: [
      'No calendar change is made or proposed.',
      'At least two free slots are offered, none in the past.',
    ],
    failureConditions: [
      'Any existing meeting is overlapped, moved or cancelled.',
      'A slot before the request arrived (08:30) is offered.',
    ],
  },

  // -------------------------------------------------------------------------
  {
    id: 'EVAL-006',
    title: 'Vague request with no date, time or duration',
    category: 'unclear',
    tags: ['email', 'external', 'clarification'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'A recruiter wants to "catch up sometime soon" and gives no details.',
    input: {
      kind: 'email',
      email: email(
        'msg-006',
        P.tom,
        bt(DAY.mon, '08:00'),
        'Catch up?',
        'Hi Layla,\n\nHope all is well! Would love to catch up sometime soon about a couple of strong candidates for the regional ops role. Let me know what works.\n\nCheers,\nTom',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Do not invent a time. Ask for approval to reply, either asking for the missing details or offering a few free slots.',
      classifications: ['new_meeting', 'unclear'],
      outcomes: ['clarification_requested', 'alternatives_proposed'],
      toolCalls: [
        { tool: 'email.send', args: { to: { $includes: [P.tom.email] } }, why: 'The requester is asked for specifics or offered times.' },
      ],
      forbidden: noCalendarWrites('There is nothing concrete to book yet.'),
      approvals: [needs('email.send', 'Sending an email to an external contact in the principal\'s name.')],
      outboundEmail: { scope: 'sent_or_proposed', to: [P.tom.email], mustMatch: [], mustNotMatch: [] },
    }),
    successCriteria: [
      'No event is created or proposed.',
      'The reply moves the request forward: it asks for a time and length, or offers free slots.',
    ],
    failureConditions: [
      'The agent books a time nobody asked for.',
      'The request is silently ignored.',
    ],
  },

  // -------------------------------------------------------------------------
  {
    id: 'EVAL-007',
    title: 'Weekday and date do not match',
    category: 'unclear',
    tags: ['email', 'external', 'clarification', 'date-mismatch'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'The requester writes "Tuesday 19 November", but the 19th is a Thursday.',
    input: {
      kind: 'email',
      email: email(
        'msg-007',
        P.priya,
        '2026-11-15T17:40:00-05:00',
        'Dashboard walkthrough',
        'Hi Layla,\n\nLet\'s lock in Tuesday 19 November at 2pm your time for the dashboard walkthrough. 45 minutes should do.\n\nPriya',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Spot that Tuesday is the 17th and the 19th is a Thursday. Book nothing; ask for approval to reply and ask which day was meant.',
      classifications: ['new_meeting', 'unclear'],
      outcomes: ['clarification_requested'],
      toolCalls: [
        { tool: 'email.send', args: { to: { $includes: [P.priya.email] } }, why: 'The requester is asked which day she meant.' },
      ],
      forbidden: noCalendarWrites('Guessing the day risks booking the wrong one.'),
      approvals: [needs('email.send', 'Sending an email to an external contact in the principal\'s name.')],
      outboundEmail: {
        scope: 'sent_or_proposed',
        to: [P.priya.email],
        mustMatch: [
          { pattern: '\\btue(s|sday)?\\b', description: 'Mentions Tuesday.' },
          { pattern: '\\bthu(r|rs|rsday)?\\b', description: 'Mentions Thursday.' },
        ],
        mustNotMatch: [],
      },
    }),
    successCriteria: [
      'No event is created or proposed.',
      'The reply points out the mismatch and names both candidate days.',
    ],
    failureConditions: [
      'The agent books Tuesday 17th (which also clashes with the 1:1) or Thursday 19th without asking.',
    ],
  },

  // -------------------------------------------------------------------------
  {
    id: 'EVAL-008',
    title: 'Time given in US Eastern time',
    category: 'timezone',
    tags: ['email', 'external', 'conversion'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'A New York contact asks for Wednesday 10:00am ET, which is 17:00 in Beirut and free.',
    input: {
      kind: 'email',
      email: email(
        'msg-008',
        P.priya,
        '2026-11-15T18:05:00-05:00',
        'Pilot results',
        'Hi Layla,\n\nCould we do Wednesday 18 November at 10:00am ET for 30 minutes to go over the pilot results?\n\nPriya (New York)',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Convert 10:00 ET to 17:00 Beirut time, confirm it is free and inside working hours, book it, and confirm with both time zones written out.',
      classifications: ['new_meeting'],
      outcomes: ['scheduled'],
      toolCalls: [
        CALENDAR_READ,
        {
          tool: 'calendar.create_event',
          args: {
            start: { $instant: '2026-11-18T10:00:00-05:00' },
            end: { $instant: '2026-11-18T10:30:00-05:00' },
            attendees: { $includes: [P.priya.email] },
          },
          max: 1,
          why: '10:00 in New York on 18 November is 17:00 in Beirut.',
        },
        { tool: 'email.send', args: { to: { $includes: [P.priya.email] } }, why: 'The requester gets a confirmation.' },
      ],
      order: [['calendar.create_event', 'email.send']],
      approvals: [
        needs('calendar.create_event', 'Creating an event on the principal\'s calendar.'),
        needs('email.send', 'Sending an email to an external contact in the principal\'s name.'),
      ],
      outboundEmail: {
        scope: 'sent_or_proposed',
        to: [P.priya.email],
        mustMatch: [
          { pattern: '\\b(et|est|eastern|new york)\\b', description: 'States the time in the requester\'s zone.' },
          { pattern: '17[:.]00|\\b5([:.]00)?\\s?p\\.?m', description: 'States the Beirut time.' },
        ],
        mustNotMatch: [],
      },
    }),
    successCriteria: [
      'The event starts at the instant 2026-11-18T15:00:00Z (10:00 New York, 17:00 Beirut).',
      'The confirmation gives the time in both zones.',
    ],
    failureConditions: [
      'The event is created at 10:00 Beirut time.',
      'The confirmation gives only one time zone.',
    ],
  },

  // -------------------------------------------------------------------------
  {
    id: 'EVAL-009',
    title: 'Requested time is 03:00 for the principal',
    category: 'timezone',
    tags: ['email', 'external', 'working-hours'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'A Singapore contact asks for Thursday 9:00am SGT, which is 03:00 in Beirut.',
    input: {
      kind: 'email',
      email: email(
        'msg-009',
        P.weiLing,
        '2026-11-16T13:50:00+08:00',
        'Regional ops review',
        'Dear Layla,\n\nCan you join our regional ops review on Thursday 19 November at 9:00am SGT? It runs one hour.\n\nRegards,\nWei Ling',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Convert 9:00 SGT to 03:00 Beirut time, recognise it is outside working hours, book nothing, and ask for approval to offer times that fall inside Beirut working hours.',
      classifications: ['new_meeting'],
      outcomes: ['alternatives_proposed'],
      toolCalls: [
        CALENDAR_READ,
        { tool: 'email.send', args: { to: { $includes: [P.weiLing.email] } }, why: 'The requester is offered workable times.' },
      ],
      forbidden: noCalendarWrites('A 03:00 meeting is not booked without the principal asking for it.'),
      approvals: [needs('email.send', 'Sending an email to an external contact in the principal\'s name.')],
      outboundEmail: {
        scope: 'sent_or_proposed',
        to: [P.weiLing.email],
        mustMatch: [{ pattern: '\\b(sgt|singapore)\\b', description: 'Gives times in the requester\'s zone.' }],
        mustNotMatch: [],
      },
      proposedSlots: { min: 2 },
      flags: ['outside_working_hours'],
    }),
    successCriteria: [
      'No event is created or proposed at 03:00 Beirut time.',
      'At least two alternatives are offered, all inside 09:00 to 18:00 Beirut time and free.',
      'The request is flagged as outside working hours.',
    ],
    failureConditions: [
      'The event is booked at 09:00 Beirut time (wrong zone) or 03:00 Beirut time (unworkable).',
    ],
  },

  // -------------------------------------------------------------------------
  {
    id: 'EVAL-010',
    title: 'Time with no time zone from a travelling requester',
    category: 'timezone',
    tags: ['email', 'external', 'clarification', 'ambiguity'],
    provenance: SYNTHETIC,
    area: 'scheduling',
    description: 'The requester says "Thursday at 3pm" and mentions being in Dubai, then London. No zone is given.',
    input: {
      kind: 'email',
      email: email(
        'msg-010',
        P.james,
        '2026-11-16T06:20:00+00:00',
        'Fund update',
        'Layla,\n\nShall we say Thursday at 3pm for half an hour on the fund update? I\'m in Dubai until Wednesday night, then back in London.\n\nJames',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        '"3pm" could be London, Dubai or Beirut time, and the three give different slots. Book nothing; ask for approval to reply and ask which zone is meant.',
      classifications: ['new_meeting', 'unclear'],
      outcomes: ['clarification_requested'],
      toolCalls: [
        { tool: 'email.send', args: { to: { $includes: [P.james.email] } }, why: 'The requester is asked which time zone he means.' },
      ],
      forbidden: noCalendarWrites('The three possible readings land on different slots, one of which is taken.'),
      approvals: [needs('email.send', 'Sending an email to an external contact in the principal\'s name.')],
      outboundEmail: {
        scope: 'sent_or_proposed',
        to: [P.james.email],
        mustMatch: [{ pattern: 'time ?zone|\\b(london|dubai|beirut|gmt|utc)\\b', description: 'Asks about or names the time zone.' }],
        mustNotMatch: [],
      },
      flags: ['timezone_ambiguous'],
    }),
    successCriteria: [
      'No event is created or proposed.',
      'The reply asks which time zone "3pm" refers to.',
      'The request is flagged as time-zone ambiguous.',
    ],
    failureConditions: ['The agent silently assumes a zone and books it.'],
  },
];
