/** Picks a scripted reply for a chat message. Keyword matching only; there is no model behind the mock. */
import type { ApprovalRequest, Participant } from '../types';
import { BASE_CALENDAR, DAY, PEOPLE, PRINCIPAL_TZ, bt } from '../../evaluation/fixtures/world';
import { fmtTime } from '../../lib/time';
import { approval, audit, createChange, draft, emailChange, exec, failing, finish, findSlots, listEvents, reminderCreate, slot, triage, updateChange, type MockScript } from './scriptDsl';
import { MOCK_SCRIPTS } from './scripts';

const MULTI_STEP = 'Move my 1:1 with Omar to Wednesday at 14:00, let him know, and remind me to bring the hiring numbers.';
const REMINDER = 'Remind me tomorrow at 9 to call Peter Vogel about the fuel-surcharge terms.';
const BOOKING_THAT_FAILS_ONCE = 'Book 30 minutes with Yara on Thursday at 15:00 about the insurance renewal and send her the invite.';

/** Prompts the mock can answer. Shown as suggestion chips while the mock adapter is active. */
export const CHAT_SUGGESTIONS = [
  'Find 45 minutes this week for me, Omar and Rana to go over the Q1 hiring plan. Mornings preferred.',
  'Move my 1:1 with Omar to Wednesday at 11.',
  MULTI_STEP,
  REMINDER,
  BOOKING_THAT_FAILS_ONCE,
  "What's on my calendar today?",
  'What is waiting for my approval?',
];

const L = PEOPLE.layla;
const YARA: Participant = { name: 'Yara Nassar', email: 'yara.nassar@cedarvale-holdings.example' };
const SIGN = '\n\nBest regards,\nLayla';

/** Three steps behind one approval: move the meeting, tell Omar, then set a private reminder. */
function moveNotifyRemind(): MockScript {
  const meeting = BASE_CALENDAR.find((e) => e.id === 'evt-omar-1on1')!;
  const move = updateChange(meeting, bt(DAY.wed, '14:00'), bt(DAY.wed, '15:00'));
  const mail = emailChange({
    to: [PEOPLE.omar],
    subject: 'Our 1:1 moves to Wednesday 14:00',
    body: `Hi Omar,\n\nI am moving our 1:1 from Tuesday to Wednesday 18 November, 14:00 to 15:00. The invitation is updated.${SIGN}`,
  });
  return {
    triage: triage('reschedule', 'normal', { title: meeting.title, attendees: [PEOPLE.omar], durationMinutes: 60, requestedWindows: [slot(bt(DAY.wed, '14:00'), bt(DAY.wed, '15:00'))], referencedEventId: meeting.id }),
    steps: [
      listEvents(bt(DAY.wed, '00:00'), bt(DAY.wed, '23:59'), 'Checked Wednesday 18 Nov on both calendars: 14:00 to 15:00 is free', BASE_CALENDAR.filter((e) => e.start.startsWith(DAY.wed))),
      findSlots(bt(DAY.wed, '14:00'), bt(DAY.wed, '15:00'), 60, 'Confirmed that Omar is free on Wednesday at 14:00', [slot(bt(DAY.wed, '14:00'), bt(DAY.wed, '15:00'))]),
      approval(
        'Move the 1:1 with Omar to Wednesday and tell him',
        'You asked to move the 1:1 to Wednesday at 14:00. That hour is free on both of your calendars and on Omar\'s. It also clears the overlap with the Group risk committee on Tuesday. The reminder is private to you, so it is set once the meeting has moved.',
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
  };
}

/** A reminder is private to the principal and changes nothing outside, so it needs no approval. */
function remindToCall(): MockScript {
  return {
    triage: triage('action_required', 'normal', null),
    steps: [
      reminderCreate('Call Peter Vogel about the fuel-surcharge terms', bt(DAY.tue, '09:00')),
      finish('task_recorded', 'Set a reminder for Tuesday at 09:00.', {
        assistantMessage: 'I will remind you on Tue 17 Nov at 09:00 to call Peter Vogel about the fuel-surcharge terms. It is in your reminders. Nothing was sent to anyone.',
      }),
    ],
  };
}

/**
 * A booking whose calendar write fails the first time it is asked for and works the second time.
 * It exists to show the failure and recovery states; the outage is scripted, not real.
 */
function bookWithYara(attempt: number): MockScript {
  const create = createChange(draft('Insurance renewal: preparation', bt(DAY.thu, '15:00'), bt(DAY.thu, '15:30'), [L, YARA], 'Video call'));
  const mail = emailChange({
    to: [YARA],
    subject: 'Insurance renewal: 30 minutes on Thursday',
    body: `Hi Yara,\n\nI have put 30 minutes in our calendars for Thursday 19 November at 15:00 to prepare the insurance renewal.${SIGN}`,
  });
  const steps: MockScript['steps'] = [
    listEvents(bt(DAY.thu, '00:00'), bt(DAY.thu, '23:59'), 'Checked Thursday 19 Nov on both calendars: 15:00 to 15:30 is free', BASE_CALENDAR.filter((e) => e.start.startsWith(DAY.thu))),
    approval('Book insurance renewal preparation with Yara Nassar', 'You asked for 30 minutes with Yara on Thursday at 15:00. That time is free on both of your calendars.', [create, mail]),
  ];
  if (attempt === 1) {
    steps.push(
      failing(create, 'calendar_unavailable', 'The calendar service did not respond.', true),
      audit('The calendar write failed. The invitation email was not sent.'),
      finish('escalated', 'The calendar service did not respond, so the meeting was not created and nothing was sent to Yara Nassar.', {
        status: 'failed',
        error: { code: 'calendar_unavailable', message: 'The calendar service did not respond.', source: 'tool', retryable: true },
        assistantMessage: 'I could not book this. The calendar service did not respond, so the meeting was not created and I did not email Yara. Nothing was repeated automatically. You can ask me to try again.',
      }),
    );
  } else {
    steps.push(
      exec(create),
      exec(mail),
      audit('Booked the insurance renewal preparation with Yara Nassar.'),
      finish('scheduled', 'Booked 30 minutes with Yara Nassar on Thursday at 15:00 and sent her the invitation.', {
        assistantMessage: 'Done. The insurance renewal preparation is booked for Thu 19 Nov, 15:00 to 15:30, and Yara has the invitation.',
      }),
    );
  }
  return { triage: triage('new_meeting', 'normal', { title: 'Insurance renewal: preparation', attendees: [YARA], durationMinutes: 30, requestedWindows: [slot(bt(DAY.thu, '15:00'), bt(DAY.thu, '15:30'))] }), steps };
}

/**
 * @param attempt 1 the first time this exact message is sent in a conversation, 2 the second time, and so on.
 */
export function scriptForChat(text: string, pending: ApprovalRequest[], attempt = 1): MockScript {
  const t = text.toLowerCase();

  if (/(move|reschedul|shift)/.test(t) && /(omar|1:1|one-on-one)/.test(t) && /remind/.test(t)) return moveNotifyRemind();
  if (/^remind me/.test(t)) return remindToCall();
  if (/(book|schedule)/.test(t) && /yara/.test(t)) return bookWithYara(attempt);
  if (/(move|reschedul|shift)/.test(t) && /(omar|1:1|one-on-one)/.test(t)) return MOCK_SCRIPTS['EVAL-012'];
  if (/(find|book|schedule|set up)/.test(t) && /(hiring|rana|omar)/.test(t)) return MOCK_SCRIPTS['EVAL-002'];

  if (/(approv|waiting|pending)/.test(t)) {
    const message =
      pending.length === 0
        ? 'Nothing is waiting for your approval right now.'
        : `${pending.length} ${pending.length === 1 ? 'item is' : 'items are'} waiting for your approval:\n${pending
            .map((a) => `- ${a.title}`)
            .join('\n')}\nYou can decide each one in the Approval Center.`;
    return {
      triage: triage('not_meeting_related', 'normal', null),
      steps: [finish('no_action', 'Listed the approvals that are waiting.', { assistantMessage: message })],
    };
  }

  if (/(calendar|agenda|schedule|today|meetings)/.test(t)) {
    const today = BASE_CALENDAR.filter((e) => e.start.startsWith(DAY.mon));
    const lines = today.map((e) => `- ${fmtTime(e.start, PRINCIPAL_TZ)} to ${fmtTime(e.end, PRINCIPAL_TZ)}: ${e.title}`);
    return {
      triage: triage('availability_query', 'normal', null),
      steps: [
        listEvents(bt(DAY.mon, '00:00'), bt(DAY.mon, '23:59'), `Read today's calendar: ${today.length} meetings`, today),
        finish('no_action', "Listed today's meetings.", {
          assistantMessage: `Today, Monday 16 November, you have ${today.length} meetings:\n${lines.join('\n')}`,
        }),
      ],
    };
  }

  return {
    triage: triage('not_meeting_related', 'low', null),
    steps: [
      finish('no_action', 'No scripted reply matched this message.', {
        assistantMessage:
          'I am running on the mock adapter, so I can only answer a few scripted prompts. Try one of the suggestions under the message box. Once the real backend is connected, I will handle free-form requests.',
      }),
    ],
  };
}
