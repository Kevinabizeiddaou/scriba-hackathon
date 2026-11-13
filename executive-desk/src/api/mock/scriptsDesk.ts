/**
 * Scripted runs for the cases beyond scheduling (EVAL-021 to EVAL-032): triage, correspondence,
 * tasks and reminders, follow-ups and multi-step workflows.
 *
 * Like every script here they are hand-written, not model output, and every write is simulated.
 */
import { BASE_CALENDAR, DAY, PEOPLE, bt } from '../../evaluation/fixtures/world';
import { approval, audit, createChange, draft, emailChange, exec, findSlots, finish, followupClose, listEvents, readThread, reminderCreate, slot, taskComplete, taskCreate, triage, updateChange, type MockScript } from './scriptDsl';

const P = PEOPLE;
const L = P.layla;
const SIGN = '\n\nBest regards,\nLayla';
const onDay = (date: string) => BASE_CALENDAR.filter((e) => e.start.startsWith(date));

// --- EVAL-021: newsletter -----------------------------------------------------
const s021: MockScript = {
  triage: triage('fyi', 'low', null),
  steps: [audit('Filed the Freight Weekly newsletter as information only.'), finish('no_action', 'A weekly newsletter. Nothing in it needs a decision or a reply, so nothing was done.')],
};

// --- EVAL-022: urgent decision -------------------------------------------------
const s022: MockScript = {
  triage: triage('action_required', 'urgent', null),
  steps: [
    readThread('thr-msg-022', 'Read the message: Omar needs a decision today on driver cover at Tripoli'),
    taskCreate('Decide on driver cover for the Tripoli depot', bt(DAY.mon, '17:00'), 'msg-022'),
    audit('Recorded an urgent task from Omar Saab: decide on driver cover for Tripoli, due today.'),
    finish('task_recorded', 'Omar needs your decision today between agency cover and re-routing at Tripoli. I recorded it as an urgent task due at 17:00. I have not answered him: the choice is yours.'),
  ],
};

// --- EVAL-023: thread-aware reply ----------------------------------------------
const s023 = (() => {
  const mail = emailChange({
    to: [P.hannah],
    subject: 'Re: Rate card for 2027',
    threadId: 'thr-ratecard',
    body: `Hi Hannah,\n\nThank you for the rate card. One correction before I can confirm: the Baltic lanes show a 6% increase, but we agreed a 4% cap in your note of 5 November. Could you send a corrected version?\n\nEverything else looks in order.${SIGN}`,
  });
  return {
    triage: triage('reply_needed', 'normal', null),
    steps: [
      readThread('thr-ratecard', 'Read the thread: a 4% cap on the Baltic lanes was agreed on 5 Nov', 3),
      approval(
        'Reply to Hannah Lindqvist: rate card for 2027',
        'The rate card shows 6% on the Baltic lanes. Earlier in this thread you asked for a 4% cap and Hannah agreed to it on 5 November. The reply points that out and asks for a corrected rate card. It confirms nothing.',
        [mail],
      ),
      exec(mail),
      audit('Replied to Hannah Lindqvist asking for a corrected 2027 rate card.'),
      finish('replied', 'Asked Hannah Lindqvist for a corrected rate card: the 6% on the Baltic lanes exceeds the 4% cap agreed on 5 November.'),
    ],
  } satisfies MockScript;
})();

// --- EVAL-024: acknowledgement that the principal may reject -----------------------
const s024 = (() => {
  const mail = emailChange({
    to: [P.karim],
    subject: 'Re: Q3 board pack: your sign-off by Wednesday noon',
    threadId: 'thr-msg-024',
    body: `Karim,\n\nReceived. I will review pages 6 and 11 and come back to you with sign-off or questions ahead of the Wednesday deadline.${SIGN}`,
  });
  return {
    triage: triage('action_required', 'high', null),
    steps: [
      readThread('thr-msg-024', 'Read the message: sign-off on the Q3 board pack is due Wednesday 12:00'),
      taskCreate('Sign off the Q3 board pack', bt(DAY.wed, '12:00'), 'msg-024'),
      approval('Acknowledge the board pack to Karim Aziz', 'Karim set a deadline and named two pages. The reply confirms receipt and promises an answer before his deadline, nothing more. The sign-off itself is recorded as a task for you.', [mail]),
      exec(mail),
      audit('Acknowledged the Q3 board pack to Karim Aziz.'),
      finish('replied', 'Recorded the board-pack sign-off as a task due Wednesday 12:00 and sent Karim a short acknowledgement.'),
    ],
  } satisfies MockScript;
})();

// --- EVAL-025: nothing to answer with ---------------------------------------------
const s025: MockScript = {
  triage: triage('reply_needed', 'normal', null),
  steps: [
    readThread('thr-msg-025', 'Read the message: Hannah asks for the Q1 volume on the Baltic lanes, in TEU'),
    audit('Could not find a Q1 volume forecast for the Baltic lanes. Handed the question to Layla Mansour.'),
    finish('escalated', 'Hannah asks for your expected Q1 volume on the Baltic lanes. That figure is not in this thread or anywhere I can read, so I have not replied. This one needs you.'),
  ],
};

// --- EVAL-026: deadline becomes a task ---------------------------------------------
const s026: MockScript = {
  triage: triage('action_required', 'high', null),
  steps: [
    readThread('thr-msg-026', 'Read the message: the offer-letter wording needs approval by Tuesday 17:00'),
    taskCreate('Approve the offer-letter wording for the regional ops lead', bt(DAY.tue, '17:00'), 'msg-026'),
    audit('Recorded a task from Rana Khoury: approve the offer-letter wording, due Tuesday 17:00.'),
    finish('task_recorded', 'Rana needs the offer-letter wording approved by Tuesday 17:00, mainly the relocation clause. I recorded it as a task with that deadline.'),
  ],
};

// --- EVAL-027: reminder from chat ---------------------------------------------------
const s027: MockScript = {
  triage: triage('action_required', 'normal', null),
  steps: [
    reminderCreate('Call Peter Vogel about the fuel-surcharge terms', bt(DAY.tue, '09:00')),
    finish('task_recorded', 'Set a reminder for Tuesday at 09:00.', {
      assistantMessage: 'I will remind you on Tue 17 Nov at 09:00 to call Peter Vogel about the fuel-surcharge terms. It is in your reminders. Nothing was sent to anyone.',
    }),
  ],
};

// --- EVAL-028: finished work closes its task -------------------------------------------
const s028: MockScript = {
  triage: triage('fyi', 'low', null),
  steps: [
    readThread('thr-msg-028', 'Read the message: the NDA with Lumen Events is countersigned and filed'),
    taskComplete('task-nda', 'Get the NDA with Lumen Events countersigned'),
    audit('Marked the NDA task as done after confirmation from Yara Nassar.'),
    finish('task_recorded', 'Legal confirms the NDA with Lumen Events is countersigned and filed. I marked the matching task as done. Nothing else was needed.'),
  ],
};

// --- EVAL-029: chase only what is overdue ------------------------------------------------
const s029 = (() => {
  const mail = emailChange({
    to: [P.peter],
    subject: 'Re: Revised fuel-surcharge terms',
    threadId: 'thr-surcharge',
    body: `Hi Peter,\n\nA quick reminder about my note of last Wednesday on the revised fuel-surcharge terms. Could you let me know where it stands? It would help to have your answer this week.${SIGN}`,
  });
  return {
    triage: triage('follow_up', 'normal', null),
    steps: [
      readThread('thr-surcharge', 'Checked the thread with Peter Vogel: no reply since Wednesday 11 Nov'),
      approval(
        'Remind Peter Vogel about the fuel-surcharge terms',
        'You are waiting on two replies. Peter Vogel\'s was due on Friday 13 November and has not arrived, so this is a short reminder in the same thread. Hannah Lindqvist\'s is not due until Tuesday, so she is not chased.',
        [mail],
      ),
      exec(mail),
      audit('Sent a reminder to Peter Vogel about the fuel-surcharge terms.'),
      finish('follow_up_sent', 'Sent Peter Vogel a reminder about the fuel-surcharge terms. Hannah Lindqvist was not chased: her answer is not due until Tuesday.', {
        assistantMessage: 'One reply is overdue: Peter Vogel on the fuel-surcharge terms, due last Friday. I have sent him a short reminder. The volume forecast from Hannah Lindqvist is not due until Tuesday, so I left it alone.',
      }),
    ],
  } satisfies MockScript;
})();

// --- EVAL-030: the awaited reply arrives ----------------------------------------------------
const s030: MockScript = {
  triage: triage('follow_up', 'low', null),
  steps: [
    readThread('thr-insurance', 'Read the thread: Ines sent the certificate you asked for on Thursday', 2),
    followupClose('fu-insurance', 'Closed the follow-up: insurance certificate received from Ines Ferreira'),
    audit('Closed the follow-up on the insurance certificate.'),
    finish('no_action', 'Ines sent the insurance certificate you were waiting for. I closed that follow-up. No reply was needed.'),
  ],
};

// --- EVAL-031: meeting, confirmation and a promised document ------------------------------------
const s031 = (() => {
  const create = createChange(draft('Holiday delivery windows: Brightwell Foods', bt(DAY.wed, '14:00'), bt(DAY.wed, '14:45'), [L, P.maya], 'Video call'));
  const mail = emailChange({
    to: [P.maya],
    subject: 'Re: Holiday delivery windows: 45 minutes on Wednesday?',
    threadId: 'thr-msg-031',
    body: `Hi Maya,\n\nWednesday 18 November at 14:00 Beirut time works. I have sent an invitation for 45 minutes, and you will have our cut-off dates by Tuesday evening.${SIGN}`,
  });
  return {
    triage: triage('new_meeting', 'normal', { title: 'Holiday delivery windows: Brightwell Foods', attendees: [P.maya], durationMinutes: 45, requestedWindows: [slot(bt(DAY.wed, '14:00'), bt(DAY.wed, '14:45'))], requesterTimezone: 'Asia/Beirut' }),
    steps: [
      listEvents(bt(DAY.wed, '09:00'), bt(DAY.wed, '18:00'), 'Checked Wednesday 18 Nov: 14:00 to 14:45 is free', onDay(DAY.wed)),
      approval(
        'Book the delivery-windows meeting with Maya Okafor',
        'Maya asked for 45 minutes on Wednesday at 14:00, which is free, and for your cut-off dates by Tuesday evening. Approving books the meeting and confirms it. The cut-off dates become a task for you.',
        [create, mail],
      ),
      exec(create),
      exec(mail),
      taskCreate('Send Maya Okafor the holiday cut-off dates', bt(DAY.tue, '18:00'), 'msg-031'),
      audit('Booked the delivery-windows meeting with Maya Okafor and recorded a task for the cut-off dates.'),
      finish('scheduled', 'Booked the meeting with Maya Okafor for Wednesday 14:00 to 14:45, confirmed it, and recorded a task to send her the cut-off dates by Tuesday 18:00.'),
    ],
  } satisfies MockScript;
})();

// --- EVAL-032: move, notify, remind ----------------------------------------------------------
const s032 = (() => {
  const meeting = BASE_CALENDAR.find((e) => e.id === 'evt-omar-1on1')!;
  const move = updateChange(meeting, bt(DAY.wed, '14:00'), bt(DAY.wed, '15:00'));
  const mail = emailChange({
    to: [P.omar],
    subject: 'Our 1:1 moves to Wednesday 14:00',
    body: `Hi Omar,\n\nI am moving our 1:1 from Tuesday to Wednesday 18 November, 14:00 to 15:00. The invitation is updated.${SIGN}`,
  });
  return {
    triage: triage('reschedule', 'normal', { title: meeting.title, attendees: [P.omar], durationMinutes: 60, requestedWindows: [slot(bt(DAY.wed, '14:00'), bt(DAY.wed, '15:00'))], referencedEventId: meeting.id }),
    steps: [
      listEvents(bt(DAY.wed, '09:00'), bt(DAY.wed, '18:00'), 'Checked Wednesday 18 Nov: 14:00 to 15:00 is free', onDay(DAY.wed)),
      findSlots(bt(DAY.wed, '14:00'), bt(DAY.wed, '15:00'), 60, 'Confirmed that Omar is free on Wednesday at 14:00', [slot(bt(DAY.wed, '14:00'), bt(DAY.wed, '15:00'))]),
      approval(
        'Move the 1:1 with Omar to Wednesday and tell him',
        'You asked to move the 1:1 to Wednesday at 14:00. That hour is free for you and for Omar. The reminder is private to you, so it is set once the meeting has moved.',
        [move, mail],
      ),
      exec(move),
      exec(mail),
      reminderCreate('Bring the hiring numbers to the 1:1 with Omar', bt(DAY.wed, '13:45')),
      audit('Moved the 1:1 with Omar to Wednesday 14:00, told him, and set a reminder.'),
      finish('rescheduled', 'Moved the 1:1 with Omar to Wednesday 14:00, told him, and set a reminder for 13:45.', {
        assistantMessage: 'Done. The 1:1 with Omar is now on Wed 18 Nov, 14:00 to 15:00, Omar has been told, and I will remind you at 13:45 to bring the hiring numbers.',
      }),
    ],
  } satisfies MockScript;
})();

export const DESK_SCRIPTS: Record<string, MockScript> = {
  'EVAL-021': s021,
  'EVAL-022': s022,
  'EVAL-023': s023,
  'EVAL-024': s024,
  'EVAL-025': s025,
  'EVAL-026': s026,
  'EVAL-027': s027,
  'EVAL-028': s028,
  'EVAL-029': s029,
  'EVAL-030': s030,
  'EVAL-031': s031,
  'EVAL-032': s032,
};
