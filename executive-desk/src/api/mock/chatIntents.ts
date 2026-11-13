/** Picks a scripted reply for a chat message. Keyword matching only; there is no model behind the mock. */
import type { ApprovalRequest } from '../types';
import { BASE_CALENDAR, DAY, PRINCIPAL_TZ, bt } from '../../evaluation/fixtures/world';
import { fmtTime } from '../../lib/time';
import { finish, listEvents, triage, type MockScript } from './scriptDsl';
import { MOCK_SCRIPTS } from './scripts';

/** Prompts the mock can answer. Shown as suggestion chips while the mock adapter is active. */
export const CHAT_SUGGESTIONS = [
  'Find 45 minutes this week for me, Omar and Rana to go over the Q1 hiring plan. Mornings preferred.',
  'Move my 1:1 with Omar to Wednesday at 11.',
  "What's on my calendar today?",
  'What is waiting for my approval?',
];

export function scriptForChat(text: string, pending: ApprovalRequest[]): MockScript {
  const t = text.toLowerCase();

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
