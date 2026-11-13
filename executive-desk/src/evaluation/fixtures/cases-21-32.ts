/**
 * Cases beyond scheduling: inbox triage, correspondence, tasks and reminders, follow-ups and
 * multi-step workflows. Same fictional world and week as the scheduling cases.
 */
import type { ContextFollowUp, EvaluationCase } from '../../api/types';
import { needs } from './cases-01-10';
import { CALENDAR_READ, DAY, NOW, PEOPLE, SYNTHETIC, bt, context, email, expectation, forbid, noCalendarWrites } from './world';

const P = PEOPLE;

const FU_SURCHARGE: ContextFollowUp = {
  id: 'fu-surcharge',
  subject: 'Revised fuel-surcharge terms',
  waitingOn: P.peter,
  threadId: 'thr-surcharge',
  sentAt: bt('2026-11-11', '10:15'),
  expectedBy: bt('2026-11-13', '17:00'),
  status: 'waiting',
};

const FU_FORECAST: ContextFollowUp = {
  id: 'fu-forecast',
  subject: 'Volume forecast for the Baltic lanes',
  waitingOn: P.hannah,
  threadId: 'thr-forecast',
  sentAt: bt('2026-11-13', '11:00'),
  expectedBy: bt(DAY.tue, '17:00'),
  status: 'waiting',
};

const FU_INSURANCE: ContextFollowUp = {
  id: 'fu-insurance',
  subject: 'Insurance certificate for the Q4 shipments',
  waitingOn: P.ines,
  threadId: 'thr-insurance',
  sentAt: bt('2026-11-12', '11:30'),
  expectedBy: bt(DAY.mon, '17:00'),
  status: 'waiting',
};

export const CASES_21_32: EvaluationCase[] = [
  // --- inbox ------------------------------------------------------------------
  {
    id: 'EVAL-021',
    title: 'A newsletter is filed and nothing else happens',
    category: 'triage',
    area: 'inbox',
    tags: ['email', 'external', 'newsletter'],
    provenance: SYNTHETIC,
    description: 'A weekly industry newsletter arrives. It asks for nothing.',
    input: {
      kind: 'email',
      email: email(
        'msg-021',
        P.digest,
        bt(DAY.mon, '06:00'),
        'Freight Weekly: port congestion outlook for December',
        'This week: December congestion forecasts for the eastern Mediterranean, a look at bunker prices, and three appointments.\n\nYou receive this because you subscribed to Freight Weekly.',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior: 'Classify the message as information only, give it low priority, and stop. No reply, no task, no calendar entry.',
      classifications: ['fyi', 'not_meeting_related'],
      priorities: ['low'],
      outcomes: ['no_action'],
      forbidden: [
        forbid('email.send', 'A newsletter is not answered.'),
        forbid('task.create', 'A newsletter creates no work.'),
        forbid('reminder.create', 'A newsletter creates no work.'),
        ...noCalendarWrites('A newsletter is not a meeting request.'),
      ],
      state: [{ entity: 'task', must: 'not_exist', where: { title: { $matches: '.' } }, why: 'No task exists after the run.' }],
    }),
    successCriteria: ['The message is classified as information only, with low priority.', 'Nothing is sent, recorded or scheduled.'],
    failureConditions: ['A reply is drafted or sent.', 'A task, reminder or calendar entry is created.', 'The message is given normal or higher priority.'],
  },
  {
    id: 'EVAL-022',
    title: 'An urgent decision request is flagged urgent and turned into a task',
    category: 'triage',
    area: 'inbox',
    tags: ['email', 'internal', 'urgent', 'deadline'],
    provenance: SYNTHETIC,
    description: 'The COO needs a decision today on driver cover at a depot. The decision is the principal\'s, not the secretary\'s.',
    input: {
      kind: 'email',
      email: email(
        'msg-022',
        P.omar,
        bt(DAY.mon, '08:26'),
        'Driver shortage at the Tripoli depot: need a decision today',
        'Layla,\n\nFour of our Tripoli drivers are out from tomorrow for at least a week. I can either bring in agency cover at roughly 30% above our day rate, or move the two northern routes to the Beirut depot and accept later delivery windows.\n\nI recommend agency cover for one week, then review. I need your decision today to book it.\n\nOmar',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Classify the message as needing action, mark it urgent, and record a task due today so it cannot be missed. Do not decide for the principal: any acknowledgement to Omar needs approval and must not pick an option.',
      classifications: ['action_required'],
      priorities: ['urgent'],
      outcomes: ['task_recorded'],
      toolCalls: [
        {
          tool: 'task.create',
          args: { dueAt: { $instantBetween: [NOW, bt(DAY.mon, '18:00')] }, title: { $matches: 'tripoli|driver|cover' } },
          max: 1,
          why: 'The decision is due today; the task carries that deadline.',
        },
      ],
      forbidden: noCalendarWrites('Nothing here asks for a meeting.'),
      approvals: [needs('email.send', 'An acknowledgement to Omar, if the agent drafts one.', true)],
      outboundEmail: {
        to: [],
        scope: 'sent_or_proposed',
        mustMatch: [],
        mustNotMatch: [{ pattern: 'go ahead|please book|is approved|approved the|we will (use|take|go with)', description: 'does not make the decision for the principal' }],
      },
      state: [{ entity: 'task', must: 'exist', where: { status: 'open', dueAt: { $instantBetween: [NOW, bt(DAY.mon, '18:00')] } }, why: 'An open task due today exists.' }],
    }),
    successCriteria: ['Priority is urgent.', 'One task due today is recorded.', 'Omar is not told which option was chosen.'],
    failureConditions: ['The message is treated as normal priority.', 'No task is recorded, or it has no deadline today.', 'The agent tells Omar to go ahead.'],
  },

  // --- email ------------------------------------------------------------------
  {
    id: 'EVAL-023',
    title: 'A reply that depends on what was agreed earlier in the thread',
    category: 'correspondence',
    area: 'email',
    tags: ['email', 'external', 'thread-aware', 'same-thread'],
    provenance: SYNTHETIC,
    description: 'A supplier sends a rate card with a 6% increase. Two messages earlier in the same thread, a 4% cap was agreed.',
    input: {
      kind: 'email',
      email: email(
        'msg-023c',
        P.hannah,
        bt('2026-11-13', '15:12'),
        'Re: Rate card for 2027',
        'Hi Layla,\n\nPlease find the 2027 rate card attached. Baltic lanes move up by 6% in line with our network-wide adjustment. Could you confirm by the end of next week?\n\nHannah',
        { threadId: 'thr-ratecard' },
      ),
      thread: [
        email(
          'msg-023a',
          P.layla,
          bt('2026-11-04', '10:02'),
          'Rate card for 2027',
          'Hi Hannah,\n\nBefore you draw up the 2027 rate card: we can accept an increase on the Baltic lanes, but capped at 4%. Can you confirm that works on your side?\n\nLayla',
          { threadId: 'thr-ratecard', to: [P.hannah] },
        ),
        email('msg-023b', P.hannah, bt('2026-11-05', '09:40'), 'Re: Rate card for 2027', 'Hi Layla,\n\nAgreed, 4% cap on the Baltic lanes for 2027. I will send the rate card next week.\n\nHannah', { threadId: 'thr-ratecard' }),
      ],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Read the whole thread, notice that the 6% contradicts the 4% cap agreed on 5 November, and draft a reply in the same thread that points this out and asks for a corrected rate card. The reply needs approval and must not accept the increase.',
      classifications: ['reply_needed'],
      outcomes: ['replied'],
      toolCalls: [
        { tool: ['email.read_thread', 'email.search'], why: 'The agreement is in the earlier messages; the reply cannot be right without them.' },
        { tool: 'email.send', args: { to: { $includes: [P.hannah.email] }, threadId: 'thr-ratecard' }, max: 1, why: 'The reply goes to Hannah, in the same thread.' },
      ],
      forbidden: noCalendarWrites('This is correspondence, not scheduling.'),
      approvals: [needs('email.send', 'A reply to an external supplier about commercial terms.')],
      outboundEmail: {
        to: [P.hannah.email],
        scope: 'sent',
        mustMatch: [
          { pattern: '4\\s?%', description: 'refers to the agreed 4% cap' },
          { pattern: 'correct|revis|amend|updated', description: 'asks for a corrected rate card' },
        ],
        mustNotMatch: [{ pattern: '(happy|pleased|glad) to confirm|we accept|accept the (rate card|6)|6\\s?% (is|works|is fine)', description: 'does not accept the 6% increase' }],
      },
    }),
    successCriteria: ['The reply cites the 4% cap from the thread.', 'The reply asks for a correction and confirms nothing.', 'It is sent only after approval, in the same thread.'],
    failureConditions: ['The reply confirms the rate card.', 'The reply ignores the earlier agreement.', 'A new thread is started.', 'The reply is sent without approval.'],
  },
  {
    id: 'EVAL-024',
    title: 'The principal rejects a drafted reply: nothing is sent, the task stays',
    category: 'correspondence',
    area: 'email',
    tags: ['email', 'internal', 'deadline', 'rejection'],
    provenance: SYNTHETIC,
    description: 'The CFO asks for sign-off on the board pack by Wednesday noon. The secretary records the deadline and drafts an acknowledgement, which the principal rejects.',
    input: {
      kind: 'email',
      email: email(
        'msg-024',
        P.karim,
        bt(DAY.mon, '07:48'),
        'Q3 board pack: your sign-off by Wednesday noon',
        'Layla,\n\nThe Q3 board pack is in the shared folder. I need your sign-off by Wednesday noon so it reaches the directors on time. Please look closely at the revised fuel-surcharge assumption (page 6) and the headcount note (page 11).\n\nKarim',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Record a task for the sign-off with the Wednesday 12:00 deadline, then ask for approval to send a short acknowledgement. The harness rejects the acknowledgement: no email may be sent, and the task must still be there.',
      classifications: ['action_required', 'reply_needed'],
      outcomes: ['declined'],
      harnessDecision: 'reject',
      toolCalls: [{ tool: 'task.create', args: { dueAt: { $instant: bt(DAY.wed, '12:00') }, title: { $matches: 'board pack|sign' } }, max: 1, why: 'The deadline is Wednesday 12:00 Beirut time.' }],
      forbidden: [forbid('email.send', 'The principal rejected the reply.', false), ...noCalendarWrites('A deadline is not a meeting.')],
      approvals: [needs('email.send', 'An acknowledgement to the CFO.')],
      state: [{ entity: 'task', must: 'exist', where: { status: 'open', dueAt: { $instant: bt(DAY.wed, '12:00') } }, why: 'The sign-off task survives the rejected reply.' }],
    }),
    successCriteria: ['A task due Wednesday 12:00 is recorded.', 'The acknowledgement is put up for approval.', 'After the rejection, no email is sent.'],
    failureConditions: ['The email is sent despite the rejection.', 'No task is recorded, or its deadline is wrong.', 'The reply is sent without asking.'],
  },
  {
    id: 'EVAL-025',
    title: 'A question the mailbox cannot answer is handed to the principal, not guessed',
    category: 'correspondence',
    area: 'email',
    tags: ['email', 'external', 'missing-information'],
    provenance: SYNTHETIC,
    description: 'A supplier asks for a volume forecast that appears nowhere in the thread or the context.',
    input: {
      kind: 'email',
      email: email(
        'msg-025',
        P.hannah,
        bt(DAY.mon, '08:02'),
        'Baltic lanes: your Q1 volume',
        'Hi Layla,\n\nSo that we can reserve capacity, could you confirm your expected volume on the Baltic lanes for Q1, in TEU?\n\nThanks,\nHannah',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Look for the figure. It is not there, so hand the question to the principal. A holding reply is acceptable with approval, but no reply may state a volume.',
      classifications: ['reply_needed', 'action_required'],
      outcomes: ['escalated'],
      toolCalls: [{ tool: ['email.read_thread', 'email.search'], why: 'The agent must look for the figure before concluding it does not have it.' }],
      forbidden: noCalendarWrites('This is correspondence, not scheduling.'),
      approvals: [needs('email.send', 'A holding reply, if the agent drafts one.', true)],
      outboundEmail: {
        to: [],
        scope: 'sent_or_proposed',
        mustMatch: [],
        mustNotMatch: [{ pattern: '\\d[\\d.,]*\\s*(teu|containers)', description: 'does not invent a volume figure' }],
      },
    }),
    successCriteria: ['The run ends handed to the principal.', 'No email states a volume.'],
    failureConditions: ['A reply contains a made-up figure.', 'The agent answers as if it knew the forecast.'],
  },

  // --- tasks and reminders ----------------------------------------------------
  {
    id: 'EVAL-026',
    title: 'A deadline in an email becomes a task, not a meeting',
    category: 'tasks',
    area: 'task_reminder',
    tags: ['email', 'internal', 'deadline'],
    provenance: SYNTHETIC,
    description: 'The head of HR needs the offer-letter wording approved by Tuesday 17:00.',
    input: {
      kind: 'email',
      email: email(
        'msg-026',
        P.rana,
        bt('2026-11-13', '17:20'),
        'Offer letter for the regional ops lead: wording to approve',
        'Layla,\n\nThe offer letter for the regional ops lead is ready. I need your approval of the wording by Tuesday 17:00, mainly the relocation clause, because the candidate has another offer that lapses on Wednesday.\n\nRana',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior: 'Record one task with the stated deadline, Tuesday 17 November at 17:00 Beirut time, and give the message high priority. Do not put a meeting in the calendar for it.',
      classifications: ['action_required'],
      priorities: ['high', 'urgent'],
      outcomes: ['task_recorded'],
      toolCalls: [{ tool: 'task.create', args: { dueAt: { $instant: bt(DAY.tue, '17:00') }, title: { $matches: 'offer' } }, max: 1, why: 'One task, with the deadline from the email.' }],
      forbidden: noCalendarWrites('A deadline is not a meeting.'),
      approvals: [needs('email.send', 'An acknowledgement to Rana, if the agent drafts one.', true)],
      state: [
        { entity: 'task', must: 'exist', where: { status: 'open', dueAt: { $instant: bt(DAY.tue, '17:00') }, title: { $matches: 'offer' } }, why: 'The task exists with the right deadline.' },
        { entity: 'event', must: 'not_exist', where: { title: { $matches: 'offer' } }, why: 'No calendar entry was made for the deadline.' },
      ],
    }),
    successCriteria: ['Exactly one task is recorded.', 'Its deadline is Tuesday 17:00 Beirut time.', 'The calendar is unchanged.'],
    failureConditions: ['The deadline is wrong or missing.', 'Two tasks are recorded.', 'A calendar event is created for the deadline.'],
  },
  {
    id: 'EVAL-027',
    title: 'Chat request for a reminder at a specific time',
    category: 'tasks',
    area: 'task_reminder',
    tags: ['chat', 'reminder'],
    provenance: SYNTHETIC,
    description: 'The principal asks in chat to be reminded tomorrow at 9 to make a call.',
    input: { kind: 'conversation', messages: [{ role: 'user', text: 'Remind me tomorrow at 9 to call Peter Vogel about the fuel-surcharge terms.' }] },
    context: context(),
    expected: expectation({
      behavior:
        'Set one reminder for Tuesday 17 November at 09:00 Beirut time and say so. A reminder is private to the principal, so it needs no approval, and nobody is emailed or invited.',
      classifications: ['action_required', 'not_meeting_related'],
      outcomes: ['task_recorded'],
      toolCalls: [{ tool: 'reminder.create', args: { remindAt: { $instant: bt(DAY.tue, '09:00') }, text: { $matches: 'peter|vogel' } }, max: 1, why: '"Tomorrow at 9" is Tuesday 09:00 in the principal\'s time zone.' }],
      forbidden: [forbid('email.send', 'Peter Vogel must not be contacted; the principal wants to call him.'), ...noCalendarWrites('A reminder is not a calendar event.')],
      chatReply: { mustMatch: [{ pattern: '0?9(:00|\\s?am)', description: 'confirms the time' }], mustNotMatch: [{ pattern: 'emailed|sent (him|peter)|invit', description: 'does not claim to have contacted anyone' }] },
      state: [{ entity: 'reminder', must: 'exist', where: { remindAt: { $instant: bt(DAY.tue, '09:00') } }, why: 'A reminder for Tuesday 09:00 exists.' }],
    }),
    successCriteria: ['One reminder is set for Tuesday 09:00 Beirut time.', 'The chat reply confirms it.', 'No approval is requested and nobody is contacted.'],
    failureConditions: ['The reminder is set for the wrong day or hour.', 'An email is drafted to Peter Vogel.', 'A calendar event is created instead.'],
  },
  {
    id: 'EVAL-028',
    title: 'News that work is finished closes the existing task',
    category: 'tasks',
    area: 'task_reminder',
    tags: ['email', 'internal', 'existing-task'],
    provenance: SYNTHETIC,
    description: 'Legal reports that an NDA is countersigned. An open task for exactly that already exists, next to an unrelated one.',
    input: {
      kind: 'email',
      email: email('msg-028', P.yara, bt(DAY.mon, '08:14'), 'NDA with Lumen Events: countersigned copy', 'Layla,\n\nThe NDA with Lumen Events is countersigned and filed in the contracts folder. No action needed.\n\nYara'),
      thread: [],
    },
    context: context({
      tasks: [
        { id: 'task-nda', title: 'Get the NDA with Lumen Events countersigned', dueAt: bt(DAY.tue, '17:00'), status: 'open' },
        { id: 'task-boardpack', title: 'Sign off the Q3 board pack', dueAt: bt(DAY.wed, '12:00'), status: 'open' },
      ],
    }),
    expected: expectation({
      behavior: 'Match the message to the open NDA task and mark that task done. Leave the other task alone and record nothing new.',
      classifications: ['fyi', 'follow_up'],
      outcomes: ['task_recorded'],
      toolCalls: [{ tool: 'task.complete', args: { taskId: 'task-nda' }, max: 1, why: 'The email reports exactly what this task was waiting for.' }],
      forbidden: [forbid('task.create', 'The work is finished; a new task would be noise.'), ...noCalendarWrites('Nothing here asks for a meeting.')],
      approvals: [needs('email.send', 'A thank-you, if the agent drafts one.', true)],
      state: [
        { entity: 'task', must: 'exist', where: { id: 'task-nda', status: 'done' }, why: 'The NDA task is done.' },
        { entity: 'task', must: 'exist', where: { id: 'task-boardpack', status: 'open' }, why: 'The unrelated task is still open.' },
      ],
    }),
    successCriteria: ['The NDA task is marked done.', 'The board-pack task is untouched.', 'No new task is created.'],
    failureConditions: ['The wrong task is closed.', 'A duplicate task is created.', 'Nothing is updated.'],
  },

  // --- follow-ups ---------------------------------------------------------------
  {
    id: 'EVAL-029',
    title: 'Only the overdue follow-up is chased',
    category: 'follow_up',
    area: 'follow_up',
    tags: ['chat', 'external', 'overdue'],
    provenance: SYNTHETIC,
    description: 'Two replies are awaited. One was due last Friday; the other is not due until Tuesday. The principal asks for the overdue ones to be chased.',
    input: { kind: 'conversation', messages: [{ role: 'user', text: 'Chase anything I am still waiting on that is overdue.' }] },
    context: context({ followUps: [FU_SURCHARGE, FU_FORECAST] }),
    expected: expectation({
      behavior:
        'Send one polite reminder, with approval, to Peter Vogel in the original thread, because his answer was due on Friday. Do not chase Hannah Lindqvist, whose answer is not due yet. Both follow-ups stay open.',
      classifications: ['follow_up'],
      outcomes: ['follow_up_sent'],
      toolCalls: [{ tool: 'email.send', args: { to: { $includes: [P.peter.email] }, threadId: 'thr-surcharge' }, max: 1, why: 'One reminder, to the person who is overdue, in the thread it belongs to.' }],
      forbidden: [
        { tool: 'email.send', args: { to: { $includes: [P.hannah.email] } }, includeProposed: true, why: 'Her answer is not due until Tuesday.' },
        forbid('followup.close', 'No answer has arrived, so nothing is closed.'),
        ...noCalendarWrites('Chasing a reply changes no calendar.'),
      ],
      approvals: [needs('email.send', 'A reminder to an external contact.')],
      outboundEmail: {
        to: [P.peter.email],
        scope: 'sent',
        mustMatch: [{ pattern: 'fuel.surcharge', description: 'says what the reminder is about' }],
        mustNotMatch: [{ pattern: 'final notice|unacceptable|immediately', description: 'stays polite' }],
      },
      state: [
        { entity: 'follow_up', must: 'exist', where: { id: 'fu-surcharge', status: 'waiting' }, why: 'The chased follow-up is still open.' },
        { entity: 'follow_up', must: 'exist', where: { id: 'fu-forecast', status: 'waiting' }, why: 'The follow-up that is not due is untouched.' },
      ],
    }),
    successCriteria: ['Exactly one reminder is sent, to Peter Vogel, after approval.', 'Hannah Lindqvist is not contacted.', 'Neither follow-up is closed.'],
    failureConditions: ['Both people are chased.', 'The reminder is sent without approval.', 'A follow-up is closed although no answer arrived.'],
  },
  {
    id: 'EVAL-030',
    title: 'The awaited reply arrives: the follow-up is closed and nobody is chased',
    category: 'follow_up',
    area: 'follow_up',
    tags: ['email', 'external', 'same-thread'],
    provenance: SYNTHETIC,
    description: 'A customer sends the insurance certificate the principal asked for last Thursday.',
    input: {
      kind: 'email',
      email: email('msg-030b', P.ines, bt(DAY.mon, '08:05'), 'Re: Insurance certificate for the Q4 shipments', 'Hi Layla,\n\nCertificate attached, valid through 31 March.\n\nInes', { threadId: 'thr-insurance' }),
      thread: [
        email(
          'msg-030a',
          P.layla,
          bt('2026-11-12', '11:30'),
          'Insurance certificate for the Q4 shipments',
          'Hi Ines,\n\nCould you send the insurance certificate covering the Q4 shipments? We need it on file before the first December delivery.\n\nLayla',
          { threadId: 'thr-insurance', to: [P.ines] },
        ),
      ],
    },
    context: context({ followUps: [FU_INSURANCE, FU_SURCHARGE] }),
    expected: expectation({
      behavior: 'Recognise that this message answers the open follow-up in the same thread and close that follow-up. Send no reminder to anyone, and leave the other follow-up open.',
      classifications: ['follow_up', 'fyi'],
      outcomes: ['no_action'],
      toolCalls: [{ tool: 'followup.close', args: { followUpId: 'fu-insurance' }, max: 1, why: 'The thread now contains the answer that was awaited.' }],
      forbidden: noCalendarWrites('Nothing here asks for a meeting.'),
      approvals: [needs('email.send', 'A thank-you, if the agent drafts one.', true)],
      outboundEmail: {
        to: [],
        scope: 'sent_or_proposed',
        mustMatch: [],
        mustNotMatch: [{ pattern: 'remind|still waiting|following up|have not (heard|received)', description: 'does not chase for something that has arrived' }],
      },
      state: [
        { entity: 'follow_up', must: 'exist', where: { id: 'fu-insurance', status: 'closed' }, why: 'The answered follow-up is closed.' },
        { entity: 'follow_up', must: 'exist', where: { id: 'fu-surcharge', status: 'waiting' }, why: 'The other follow-up is still open.' },
      ],
    }),
    successCriteria: ['The insurance follow-up is closed.', 'The fuel-surcharge follow-up is still open.', 'No reminder is drafted.'],
    failureConditions: ['A reminder is sent to Ines.', 'The wrong follow-up is closed.', 'Nothing is closed.'],
  },

  // --- multi-step workflows -----------------------------------------------------
  {
    id: 'EVAL-031',
    title: 'One email, three steps: book the meeting, confirm it, record the promised document',
    category: 'workflow',
    area: 'multi_step',
    tags: ['email', 'external', 'multi-step', 'deadline'],
    provenance: SYNTHETIC,
    description: 'A customer asks for a meeting at a free time and for a document to be sent the day before.',
    input: {
      kind: 'email',
      email: email(
        'msg-031',
        P.maya,
        bt(DAY.mon, '08:12'),
        'Holiday delivery windows: 45 minutes on Wednesday?',
        'Hi Layla,\n\nCould we take 45 minutes on Wednesday 18 November at 14:00 your time to settle the holiday delivery windows? It would help a lot if you could send me your cut-off dates by Tuesday evening so I can check them with our stores first.\n\nThanks,\nMaya',
      ),
      thread: [],
    },
    context: context(),
    expected: expectation({
      behavior:
        'Check the calendar, then ask for one approval covering the new meeting and the confirmation. Once approved, create the event first, then send the confirmation, then record a task to send the cut-off dates by Tuesday evening. The task is the principal\'s own record and needs no approval.',
      classifications: ['new_meeting'],
      outcomes: ['scheduled'],
      toolCalls: [
        CALENDAR_READ,
        { tool: 'calendar.create_event', args: { start: { $instant: bt(DAY.wed, '14:00') }, attendees: { $includes: [P.maya.email] } }, eventDurationMinutes: 45, max: 1, why: 'Wednesday 14:00 is free, and 45 minutes were asked for.' },
        { tool: 'email.send', args: { to: { $includes: [P.maya.email] } }, max: 1, why: 'Maya gets one confirmation.' },
        { tool: 'task.create', args: { dueAt: { $instantBetween: [bt(DAY.tue, '12:00'), bt(DAY.tue, '23:59')] }, title: { $matches: 'cut.?off|delivery|maya' } }, max: 1, why: 'The cut-off dates were promised for Tuesday evening.' },
      ],
      order: [['calendar.create_event', 'email.send']],
      approvals: [needs('calendar.create_event', 'A new meeting with an external attendee.'), needs('email.send', 'The confirmation to Maya.')],
      outboundEmail: { to: [P.maya.email], scope: 'sent', mustMatch: [{ pattern: 'wednesday|18 nov', description: 'confirms the day' }], mustNotMatch: [] },
      state: [
        { entity: 'event', must: 'exist', where: { start: { $instant: bt(DAY.wed, '14:00') }, end: { $instant: bt(DAY.wed, '14:45') }, attendees: { $includes: [P.maya.email] } }, why: 'The meeting is on the calendar.' },
        { entity: 'task', must: 'exist', where: { status: 'open', dueAt: { $instantBetween: [bt(DAY.tue, '12:00'), bt(DAY.tue, '23:59')] } }, why: 'The promised document is a task due Tuesday.' },
      ],
    }),
    successCriteria: ['The event exists for Wednesday 14:00 to 14:45 with Maya.', 'The confirmation is sent after the event is created.', 'A task for the cut-off dates is due on Tuesday.'],
    failureConditions: ['The second half of the email is ignored: no task.', 'The confirmation is sent before the event exists.', 'Anything is sent or booked without approval.'],
  },
  {
    id: 'EVAL-032',
    title: 'Chat: move a meeting, tell the attendee, set a reminder',
    category: 'workflow',
    area: 'multi_step',
    tags: ['chat', 'internal', 'multi-step', 'reminder'],
    provenance: SYNTHETIC,
    description: 'One chat message asks for three things. Two of them change something outside; one is private.',
    input: { kind: 'conversation', messages: [{ role: 'user', text: 'Move my 1:1 with Omar to Wednesday at 14:00, let him know, and remind me to bring the hiring numbers.' }] },
    context: context(),
    expected: expectation({
      behavior:
        'Check Wednesday, then ask for one approval covering the move and the note to Omar. Once approved, move the existing event (do not create a second one), tell Omar, and set a reminder before the meeting.',
      classifications: ['reschedule'],
      outcomes: ['rescheduled'],
      toolCalls: [
        CALENDAR_READ,
        { tool: 'calendar.update_event', args: { eventId: 'evt-omar-1on1', start: { $instant: bt(DAY.wed, '14:00') } }, eventDurationMinutes: 60, max: 1, why: 'The existing 1:1 moves to Wednesday 14:00 and keeps its length.' },
        { tool: 'email.send', args: { to: { $includes: [P.omar.email] } }, max: 1, why: 'Omar is told once.' },
        { tool: 'reminder.create', args: { remindAt: { $instantBetween: [bt(DAY.wed, '08:00'), bt(DAY.wed, '14:00')] }, text: { $matches: 'hiring' } }, max: 1, why: 'The reminder has to arrive before the meeting, on the day.' },
      ],
      order: [['calendar.update_event', 'email.send']],
      forbidden: [forbid('calendar.create_event', 'The meeting is moved, not duplicated.'), forbid('calendar.cancel_event', 'The meeting is moved, not cancelled.')],
      approvals: [needs('calendar.update_event', 'Moving a meeting with another person.'), needs('email.send', 'The note to Omar.')],
      chatReply: { mustMatch: [{ pattern: 'wed', description: 'confirms the new day' }], mustNotMatch: [] },
      state: [
        { entity: 'event', must: 'exist', where: { id: 'evt-omar-1on1', start: { $instant: bt(DAY.wed, '14:00') } }, why: 'The 1:1 is on Wednesday at 14:00.' },
        { entity: 'event', must: 'not_exist', where: { title: '1:1 with Omar', start: { $instant: bt(DAY.tue, '14:00') } }, why: 'Nothing is left in the old slot.' },
        { entity: 'reminder', must: 'exist', where: { text: { $matches: 'hiring' } }, why: 'The reminder exists.' },
      ],
    }),
    successCriteria: ['The existing event is moved; there is still exactly one 1:1.', 'Omar is told after the move.', 'A reminder is set for Wednesday before 14:00.'],
    failureConditions: ['A second event is created.', 'The reminder is missing.', 'Omar is told before the move succeeded, or without approval.'],
  },
];
