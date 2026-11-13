/**
 * Mock workspace: fictional mail, calendars, tasks, reminders and follow-ups for the executive
 * workspace screens.
 *
 * Everything here is invented and uses the reserved ".example" domain. Meeting requests come
 * from the scripted desk mock, so the inbox, the calendar, the approvals and the activity
 * history all describe the same fictional week. Like the desk mock, this has no network code:
 * "sending" a draft only moves a scripted run forward in memory.
 */
import { BASE_CALENDAR, DAY, PEOPLE, PRINCIPAL_TZ, bt } from '../../evaluation/fixtures/world';
import { overlaps } from '../../lib/time';
import type { AgentRun, ApprovalRequest, CalendarEvent, Participant, SecretaryRequest } from '../types';
import type {
  ActivityEntry,
  AgendaEvent,
  ConnectedAccount,
  EmailWorkStatus,
  FollowUp,
  InboxEmail,
  MeetingPrep,
  Reminder,
  ReplyDraft,
  ThreadMessage,
  WorkTask,
  WorkspaceApi,
} from '../workspace';
import type { MockExecutiveDesk } from './mockAdapter';
import { approval, audit, emailChange, exec, finish, triage, type MockScript } from './scriptDsl';

const GMAIL = 'layla.mansour@cedarvale.example';
const OUTLOOK = 'l.mansour@cedarvale-holdings.example';
const L = PEOPLE.layla;

const WHO = {
  hannah: { name: 'Hannah Lindqvist', email: 'hannah.lindqvist@nordhavn-shipping.example' },
  yara: { name: 'Yara Nassar', email: 'yara.nassar@cedarvale-holdings.example' },
  ines: { name: 'Ines Ferreira', email: 'ines.ferreira@brightwell.example' },
  peter: { name: 'Peter Vogel', email: 'peter.vogel@altamira.example' },
  facilities: { name: 'Building Services', email: 'building.services@cedarvale-holdings.example' },
  digest: { name: 'Freight Weekly', email: 'digest@freight-weekly.example' },
} satisfies Record<string, Participant>;

export const MOCK_ACCOUNTS: ConnectedAccount[] = [
  { id: 'acc-gmail', kind: 'mail', provider: 'gmail', address: GMAIL, label: 'Cedar & Vale (Gmail)', status: 'connected' },
  { id: 'acc-outlook', kind: 'mail', provider: 'outlook', address: OUTLOOK, label: 'Cedar & Vale Holdings (Outlook)', status: 'connected' },
  { id: 'acc-gcal', kind: 'calendar', provider: 'google', address: GMAIL, label: 'Cedar & Vale (Google Calendar)', status: 'connected' },
  { id: 'acc-ocal', kind: 'calendar', provider: 'outlook', address: OUTLOOK, label: 'Holdings (Outlook Calendar)', status: 'connected' },
];

const msg = (id: string, from: Participant, sentAt: string, bodyText: string, outbound = false): ThreadMessage => ({ id, from, sentAt, bodyText, outbound });

/** Mail that is not a meeting request. Meeting requests are added from the desk mock at read time. */
const EXTRA_EMAILS: InboxEmail[] = [
  {
    id: 'mail-tripoli',
    provider: 'gmail',
    account: GMAIL,
    threadId: 'thr-tripoli',
    from: PEOPLE.omar,
    subject: 'Driver shortage at the Tripoli depot: need a decision today',
    receivedAt: bt(DAY.mon, '08:26'),
    unread: true,
    category: 'action_required',
    priority: 'urgent',
    summary: 'Four drivers are out at Tripoli from tomorrow. Omar asks you to choose today between agency cover at a higher day rate and moving two routes to the Beirut depot. He recommends agency cover for one week.',
    actionItems: ['Decide between agency cover and re-routing, today', 'Tell Omar which budget line the extra cost goes to'],
    status: 'needs_you',
    flags: [],
    requestId: null,
    thread: [
      msg('m-tripoli-1', PEOPLE.omar, bt(DAY.mon, '08:26'), 'Layla,\n\nFour of our Tripoli drivers are out from tomorrow for at least a week. I can either bring in agency cover at roughly 30% above our day rate, or move the two northern routes to the Beirut depot and accept later delivery windows.\n\nI recommend agency cover for one week, then review. I need your decision today to book it.\n\nOmar'),
    ],
    draft: null,
    taskIds: ['task-tripoli'],
    followUpId: null,
  },
  {
    id: 'mail-boardpack',
    provider: 'outlook',
    account: OUTLOOK,
    threadId: 'thr-boardpack',
    from: PEOPLE.karim,
    subject: 'Q3 board pack: your sign-off by Wednesday noon',
    receivedAt: bt(DAY.mon, '07:48'),
    unread: true,
    category: 'action_required',
    priority: 'high',
    summary: 'Karim has circulated the Q3 board pack and needs your sign-off by Wednesday 12:00 so it can go to the directors. Two items want your attention: the revised fuel-surcharge assumption and the headcount note.',
    actionItems: ['Review the fuel-surcharge assumption on page 6', 'Review the headcount note on page 11', 'Sign off by Wednesday 18 November, 12:00'],
    status: 'in_progress',
    flags: [],
    requestId: null,
    thread: [
      msg('m-board-1', PEOPLE.karim, bt(DAY.mon, '07:48'), 'Layla,\n\nThe Q3 board pack is in the shared folder. I need your sign-off by Wednesday noon so it reaches the directors on time. Please look closely at the revised fuel-surcharge assumption (page 6) and the headcount note (page 11).\n\nKarim'),
    ],
    draft: {
      to: [PEOPLE.karim.email],
      subject: 'Re: Q3 board pack: your sign-off by Wednesday noon',
      bodyText: 'Karim,\n\nReceived. I will review pages 6 and 11 today and come back to you with sign-off or questions by Tuesday evening, well ahead of the Wednesday deadline.\n\nLayla',
      rationale: 'Karim set a deadline and named two pages. The reply confirms receipt, commits to a time before his deadline, and promises nothing about the content. A task for the sign-off has been recorded.',
      state: 'drafted',
      approvalId: null,
    },
    taskIds: ['task-boardpack'],
    followUpId: null,
  },
  {
    id: 'mail-ratecard',
    provider: 'gmail',
    account: GMAIL,
    threadId: 'thr-ratecard',
    from: WHO.hannah,
    subject: 'Re: Rate card for 2027',
    receivedAt: bt('2026-11-13', '15:12'),
    unread: false,
    category: 'reply_needed',
    priority: 'normal',
    summary: 'Hannah has sent the 2027 rate card. It applies a 6% increase on the Baltic lanes, although the thread shows you agreed a 4% cap with her on 5 November. She asks for confirmation by the end of this week.',
    actionItems: ['Point out that the increase exceeds the agreed 4% cap', 'Ask for a corrected rate card'],
    status: 'in_progress',
    flags: [],
    requestId: null,
    thread: [
      msg('m-rate-1', L, bt('2026-11-04', '10:02'), 'Hi Hannah,\n\nBefore you draw up the 2027 rate card: we can accept an increase on the Baltic lanes, but capped at 4%. Can you confirm that works on your side?\n\nLayla', true),
      msg('m-rate-2', WHO.hannah, bt('2026-11-05', '09:40'), 'Hi Layla,\n\nAgreed, 4% cap on the Baltic lanes for 2027. I will send the rate card next week.\n\nHannah'),
      msg('m-rate-3', WHO.hannah, bt('2026-11-13', '15:12'), 'Hi Layla,\n\nPlease find the 2027 rate card attached. Baltic lanes move up by 6% in line with our network-wide adjustment. Could you confirm by the end of next week?\n\nHannah'),
    ],
    draft: {
      to: [WHO.hannah.email],
      subject: 'Re: Rate card for 2027',
      bodyText: 'Hi Hannah,\n\nThank you for the rate card. One correction before I can confirm: the Baltic lanes show a 6% increase, but we agreed a 4% cap in your note of 5 November. Could you send a corrected version?\n\nEverything else looks in order.\n\nBest regards,\nLayla',
      rationale: 'The reply relies on the earlier messages in this thread: your request for a 4% cap on 4 November and her agreement on 5 November. It asks for a correction and confirms nothing.',
      state: 'drafted',
      approvalId: null,
    },
    taskIds: ['task-ratecard'],
    followUpId: null,
  },
  {
    id: 'mail-offer',
    provider: 'outlook',
    account: OUTLOOK,
    threadId: 'thr-offer',
    from: PEOPLE.rana,
    subject: 'Offer letter for the regional ops lead: wording to approve',
    receivedAt: bt('2026-11-13', '17:20'),
    unread: false,
    category: 'action_required',
    priority: 'high',
    summary: 'Rana needs your approval of the offer-letter wording for the regional ops lead by Tuesday so the candidate hears before a competing offer lapses. The open point is the relocation clause.',
    actionItems: ['Approve or amend the relocation clause', 'Reply to Rana by Tuesday 17 November, 17:00'],
    status: 'in_progress',
    flags: [],
    requestId: null,
    thread: [msg('m-offer-1', PEOPLE.rana, bt('2026-11-13', '17:20'), 'Layla,\n\nThe offer letter for the regional ops lead is ready. I need your approval of the wording by Tuesday, mainly the relocation clause, because the candidate has another offer that lapses on Wednesday.\n\nRana')],
    draft: null,
    taskIds: ['task-offer'],
    followUpId: null,
  },
  {
    id: 'mail-insurance',
    provider: 'gmail',
    account: GMAIL,
    threadId: 'thr-insurance',
    from: WHO.ines,
    subject: 'Re: Insurance certificate for the Q4 shipments',
    receivedAt: bt(DAY.mon, '08:05'),
    unread: false,
    category: 'follow_up',
    priority: 'normal',
    summary: 'Ines has sent the insurance certificate you asked for on Thursday. Nothing further is needed, and the follow-up has been closed.',
    actionItems: [],
    status: 'done',
    flags: [],
    requestId: null,
    thread: [
      msg('m-ins-1', L, bt('2026-11-12', '11:30'), 'Hi Ines,\n\nCould you send the insurance certificate covering the Q4 shipments? We need it on file before the first December delivery.\n\nLayla', true),
      msg('m-ins-2', WHO.ines, bt(DAY.mon, '08:05'), 'Hi Layla,\n\nCertificate attached, valid through 31 March.\n\nInes'),
    ],
    draft: null,
    taskIds: [],
    followUpId: 'fu-insurance',
  },
  {
    id: 'mail-nda',
    provider: 'outlook',
    account: OUTLOOK,
    threadId: 'thr-nda',
    from: WHO.yara,
    subject: 'NDA with Lumen Events: countersigned copy',
    receivedAt: bt('2026-11-13', '14:02'),
    unread: false,
    category: 'fyi',
    priority: 'low',
    summary: 'Legal confirms the NDA with Lumen Events is countersigned and filed. For information only.',
    actionItems: [],
    status: 'done',
    flags: [],
    requestId: null,
    thread: [msg('m-nda-1', WHO.yara, bt('2026-11-13', '14:02'), 'Layla,\n\nThe NDA with Lumen Events is countersigned and filed in the contracts folder. No action needed.\n\nYara')],
    draft: null,
    taskIds: [],
    followUpId: null,
  },
  {
    id: 'mail-walkthrough',
    provider: 'outlook',
    account: OUTLOOK,
    threadId: 'thr-walkthrough',
    from: WHO.facilities,
    subject: 'Fire-safety walkthrough, building B, Thursday 14:30',
    receivedAt: bt('2026-11-13', '09:15'),
    unread: false,
    category: 'fyi',
    priority: 'low',
    summary: 'Building Services will walk through building B on Thursday at 14:30. Floor heads should be reachable. A reminder has been set.',
    actionItems: [],
    status: 'done',
    flags: [],
    requestId: null,
    thread: [msg('m-walk-1', WHO.facilities, bt('2026-11-13', '09:15'), 'All,\n\nThe annual fire-safety walkthrough of building B takes place on Thursday 19 November at 14:30. Floor heads should be reachable during the walkthrough.\n\nBuilding Services')],
    draft: null,
    taskIds: [],
    followUpId: null,
  },
  {
    id: 'mail-digest',
    provider: 'gmail',
    account: GMAIL,
    threadId: 'thr-digest',
    from: WHO.digest,
    subject: 'Freight Weekly: port congestion outlook for December',
    receivedAt: bt(DAY.mon, '06:00'),
    unread: false,
    category: 'low_priority',
    priority: 'low',
    summary: 'A weekly industry newsletter. Nothing in it needs a decision or a reply.',
    actionItems: [],
    status: 'done',
    flags: [],
    requestId: null,
    thread: [msg('m-digest-1', WHO.digest, bt(DAY.mon, '06:00'), 'This week: December congestion forecasts for the eastern Mediterranean, a look at bunker prices, and three appointments.')],
    draft: null,
    taskIds: [],
    followUpId: null,
  },
];

const ev = (id: string, title: string, date: string, start: string, end: string, attendees: Participant[], location: string | null): CalendarEvent => ({
  id,
  title,
  start: bt(date, start),
  end: bt(date, end),
  timezone: PRINCIPAL_TZ,
  attendees: [L, ...attendees],
  location,
  description: null,
  status: 'confirmed',
});

/** The holding company's calendar, kept in Outlook. One entry deliberately clashes with a Google event. */
const OUTLOOK_CALENDAR: CalendarEvent[] = [
  ev('out-preread', 'Holdings board pre-read', DAY.mon, '12:00', '13:00', [PEOPLE.karim, WHO.yara], 'Teams'),
  ev('out-risk', 'Group risk committee', DAY.tue, '14:30', '15:30', [WHO.yara, PEOPLE.karim], 'Holdings boardroom'),
  ev('out-insurance', 'Insurance renewal call', DAY.wed, '15:00', '15:30', [WHO.yara], 'Teams'),
  ev('out-cfo-forum', 'Group CFO forum', DAY.thu, '16:00', '17:00', [PEOPLE.karim], 'Holdings boardroom'),
  ev('out-townhall', 'Holdings town hall', DAY.fri, '12:00', '13:00', [], 'Auditorium'),
];

const PREP: Record<string, Omit<MeetingPrep, 'eventId'>> = {
  'evt-brightwell': {
    purpose: 'Quarterly customer call with Brightwell Foods. Maya has asked to move it to Friday; that change is waiting for your approval.',
    attendees: [{ person: PEOPLE.maya, note: 'Partnerships lead. Also asked for a Q4 delivery schedule review this week.' }],
    talkingPoints: ['Holiday delivery windows: confirm the cut-off dates', 'Q4 delivery schedule: two late arrivals in October', 'Insurance certificate received from Brightwell legal on Monday'],
    relatedEmailIds: ['req-011', 'req-004', 'mail-insurance'],
    openTaskIds: ['task-brightwell-prep'],
    lastContact: 'Maya wrote on Monday 16 Nov at 08:12 asking to move this call.',
  },
  'evt-altamira': {
    purpose: 'Vendor review with Altamira Freight on the revised contract terms.',
    attendees: [{ person: PEOPLE.daniel, note: 'Account director. Has also asked for a contract walkthrough on Tuesday and a signing-prep session on Friday.' }],
    talkingPoints: ['Revised fuel-surcharge terms: still waiting for procurement to answer', 'Contract walkthrough: the requested Tuesday slot clashes; alternatives are drafted', 'Signing prep: the calendar write failed and needs a person'],
    relatedEmailIds: ['req-003', 'req-018'],
    openTaskIds: [],
    lastContact: 'Daniel wrote twice on Monday morning.',
  },
  'evt-board-prep': {
    purpose: 'Prepare the Q3 board pack with Karim before it goes to the directors on Wednesday.',
    attendees: [{ person: PEOPLE.karim, note: 'CFO. Needs your sign-off on the pack by Wednesday 12:00.' }],
    talkingPoints: ['Fuel-surcharge assumption, page 6', 'Headcount note, page 11', 'Tripoli depot cover: effect on the Q4 forecast'],
    relatedEmailIds: ['mail-boardpack', 'mail-tripoli'],
    openTaskIds: ['task-boardpack'],
    lastContact: 'Karim wrote on Monday 16 Nov at 07:48.',
  },
  'out-risk': {
    purpose: 'Monthly group risk committee, on the Holdings calendar. It overlaps your 1:1 with Omar on the Cedar & Vale calendar.',
    attendees: [
      { person: WHO.yara, note: 'General counsel. Chairs the committee.' },
      { person: PEOPLE.karim, note: 'CFO.' },
    ],
    talkingPoints: ['Tripoli depot staffing risk', 'Insurance renewal: call on Wednesday'],
    relatedEmailIds: ['mail-tripoli'],
    openTaskIds: ['task-tripoli'],
    lastContact: null,
  },
};

const REQUEST_STATUS_TO_EMAIL: Record<SecretaryRequest['status'], EmailWorkStatus> = {
  received: 'new',
  processing: 'in_progress',
  awaiting_approval: 'needs_approval',
  awaiting_reply: 'waiting',
  completed: 'done',
  escalated: 'needs_you',
  declined: 'done',
  failed: 'needs_you',
};

function draftFrom(approvals: ApprovalRequest[]): ReplyDraft | null {
  for (const item of approvals) {
    const mail = item.changes.find((c) => c.type === 'email');
    if (mail?.type !== 'email') continue;
    const state: ReplyDraft['state'] =
      item.status === 'pending' ? 'awaiting_approval' : item.status === 'rejected' ? 'rejected' : item.execution.status === 'executed' ? 'sent' : item.execution.status === 'executing' ? 'awaiting_approval' : 'drafted';
    return { to: mail.to, subject: mail.subject, bodyText: mail.bodyText, rationale: item.explanation, state, approvalId: item.id };
  }
  return null;
}

export class MockWorkspace implements WorkspaceApi {
  readonly availability = 'mock' as const;
  private readonly listeners = new Set<() => void>();
  private readonly localActivity: ActivityEntry[] = [];

  private tasks: WorkTask[] = [
    { id: 'task-tripoli', title: 'Decide on driver cover for the Tripoli depot', detail: 'Agency cover for a week, or move two routes to Beirut. Omar recommends agency cover.', dueAt: bt(DAY.mon, '17:00'), status: 'open', priority: 'urgent', origin: 'extracted', sourceEmailId: 'mail-tripoli', createdAt: bt(DAY.mon, '08:27'), completedAt: null },
    { id: 'task-offer', title: 'Approve the offer-letter wording for the regional ops lead', detail: 'The open point is the relocation clause.', dueAt: bt(DAY.tue, '17:00'), status: 'open', priority: 'high', origin: 'extracted', sourceEmailId: 'mail-offer', createdAt: bt('2026-11-13', '17:21'), completedAt: null },
    { id: 'task-boardpack', title: 'Sign off the Q3 board pack', detail: 'Pages 6 and 11 need a close read.', dueAt: bt(DAY.wed, '12:00'), status: 'open', priority: 'high', origin: 'extracted', sourceEmailId: 'mail-boardpack', createdAt: bt(DAY.mon, '07:49'), completedAt: null },
    { id: 'task-ratecard', title: 'Answer Nordhavn on the 2027 rate card', detail: 'The card shows 6% on the Baltic lanes; 4% was agreed.', dueAt: bt('2026-11-13', '18:00'), status: 'open', priority: 'normal', origin: 'extracted', sourceEmailId: 'mail-ratecard', createdAt: bt('2026-11-13', '15:13'), completedAt: null },
    { id: 'task-brightwell-prep', title: 'Prepare talking points for the Brightwell customer call', detail: null, dueAt: bt(DAY.thu, '09:00'), status: 'open', priority: 'normal', origin: 'manual', sourceEmailId: null, createdAt: bt('2026-11-12', '16:40'), completedAt: null },
    { id: 'task-nda', title: 'File the countersigned NDA with Lumen Events', detail: null, dueAt: bt('2026-11-13', '18:00'), status: 'done', priority: 'low', origin: 'extracted', sourceEmailId: 'mail-nda', createdAt: bt('2026-11-12', '10:00'), completedAt: bt('2026-11-13', '14:05') },
  ];

  private reminders: Reminder[] = [
    { id: 'rem-karim', text: 'Call Karim before the board prep', remindAt: bt(DAY.tue, '09:00'), status: 'scheduled', sourceEmailId: 'mail-boardpack' },
    { id: 'rem-walkthrough', text: 'Fire-safety walkthrough, building B: be reachable', remindAt: bt(DAY.thu, '14:15'), status: 'scheduled', sourceEmailId: 'mail-walkthrough' },
    { id: 'rem-permit', text: 'Renew the parking permit', remindAt: bt('2026-11-13', '10:00'), status: 'done', sourceEmailId: null },
  ];

  constructor(private readonly desk: MockExecutiveDesk) {
    desk.subscribe(() => this.emit());
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }

  private now(): string {
    return this.desk.info.simulatedNow ?? bt(DAY.mon, '08:30');
  }

  async listAccounts(): Promise<ConnectedAccount[]> {
    return structuredClone(MOCK_ACCOUNTS);
  }

  async listEmails(): Promise<InboxEmail[]> {
    const [requests, approvals, runs] = await Promise.all([this.desk.listRequests(), this.desk.listApprovals(), this.desk.listRuns()]);
    const approvalsFor = (subjectId: string) => {
      const runIds = new Set(runs.filter((r) => r.requestId === subjectId).map((r) => r.id));
      return approvals.filter((a) => runIds.has(a.runId));
    };

    const meetings: InboxEmail[] = requests.map((request) => {
      const run = runs.find((r) => r.requestId === request.id);
      const draft = draftFrom(approvalsFor(request.id));
      const thread: ThreadMessage[] = [msg(`m-${request.id}`, request.from, request.receivedAt, request.bodyText)];
      if (draft?.state === 'sent') thread.push(msg(`m-${request.id}-reply`, L, run?.finishedAt ?? request.receivedAt, draft.bodyText, true));
      const actionItems =
        request.status === 'awaiting_approval' ? ['Decide on the proposal in the Approval Center'] : request.status === 'escalated' || request.status === 'failed' ? ['Needs you: the secretary could not finish this'] : request.status === 'received' ? ['Not yet read by the secretary'] : [];
      return {
        id: request.id,
        provider: 'gmail',
        account: GMAIL,
        threadId: request.threadId ?? `thr-${request.id}`,
        from: request.from,
        subject: request.subject,
        receivedAt: request.receivedAt,
        unread: request.status === 'received',
        category: 'meeting',
        priority: request.priority ?? 'normal',
        summary: run?.summary ?? (request.status === 'received' ? 'The secretary has not read this request yet. Process it to have it triaged.' : 'The secretary is working on this request.'),
        actionItems,
        status: REQUEST_STATUS_TO_EMAIL[request.status],
        flags: request.flags,
        requestId: request.id,
        thread,
        draft,
        taskIds: [],
        followUpId: request.status === 'awaiting_reply' ? `fu-${request.id}` : null,
      };
    });

    const others = EXTRA_EMAILS.map((email) => {
      const copy = structuredClone(email);
      const submitted = draftFrom(approvalsFor(email.id));
      if (submitted && copy.draft) {
        copy.draft = { ...copy.draft, state: submitted.state, approvalId: submitted.approvalId };
        if (submitted.state === 'awaiting_approval') copy.status = 'needs_approval';
        if (submitted.state === 'sent') {
          copy.status = 'waiting';
          copy.thread.push(msg(`${email.id}-reply`, L, this.now(), copy.draft.bodyText, true));
        }
      }
      return copy;
    });

    return [...meetings, ...others].sort((a, b) => Date.parse(b.receivedAt) - Date.parse(a.receivedAt));
  }

  async submitDraft(emailId: string): Promise<void> {
    const email = (await this.listEmails()).find((e) => e.id === emailId);
    if (!email?.draft) throw new Error('This email has no reply draft.');
    if (email.draft.state !== 'drafted') throw new Error('This draft has already been sent for approval.');
    const mail = emailChange({ to: email.draft.to.map((address) => ({ name: address, email: address })), subject: email.draft.subject, body: email.draft.bodyText, threadId: email.threadId });
    const script: MockScript = {
      triage: triage('reply_needed', email.priority, null),
      steps: [
        approval(`Reply to ${email.from.name}: ${email.subject.replace(/^Re: /, '')}`, email.draft.rationale, [mail]),
        exec(mail),
        audit(`Replied to ${email.from.name}.`),
        finish('replied', `Sent the approved reply to ${email.from.name}.`),
      ],
    };
    await this.desk.runScript(script, emailId);
  }

  async listAgenda(): Promise<AgendaEvent[]> {
    const [approvals, requests] = await Promise.all([this.desk.listApprovals(), this.desk.listRequests()]);
    const google = new Map<string, CalendarEvent>(BASE_CALENDAR.map((e) => [e.id, e]));
    const proposed: AgendaEvent[] = [];
    const proposal = (id: string, title: string, start: string, end: string, attendees: Participant[], approvalId: string): AgendaEvent => ({
      id,
      title,
      start,
      end,
      provider: 'google',
      calendar: 'Cedar & Vale',
      attendees,
      location: null,
      kind: 'proposed',
      conflictsWith: [],
      approvalId,
    });

    // Oldest first, so approved changes are applied in the order they were made.
    for (const item of [...approvals].sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt))) {
      const requester = requests.find((r) => r.id === item.requestId)?.from.name;
      item.changes.forEach((change, index) => {
        const id = `${item.id}-${index}`;
        if (item.status === 'approved' && item.execution.status === 'executed') {
          if (change.type === 'calendar_create') google.set(id, { ...change.event, id, status: 'confirmed' });
          if (change.type === 'calendar_update') google.set(change.eventId, { ...change.after, id: change.eventId, status: 'confirmed' });
          if (change.type === 'calendar_cancel') google.delete(change.eventId);
        } else if (item.status === 'pending') {
          if (change.type === 'calendar_create') proposed.push(proposal(id, change.event.title, change.event.start, change.event.end, change.event.attendees, item.id));
          if (change.type === 'calendar_update') proposed.push(proposal(id, `${change.after.title} (proposed move)`, change.after.start, change.after.end, change.after.attendees, item.id));
          if (change.type === 'email') change.proposedSlots.forEach((slot, n) => proposed.push(proposal(`${id}-slot-${n}`, `Offered to ${requester ?? change.to[0]}`, slot.start, slot.end, [], item.id)));
        }
      });
    }

    const real: AgendaEvent[] = [
      ...[...google.values()].map((e) => ({ ...e, provider: 'google' as const, calendar: 'Cedar & Vale' })),
      ...OUTLOOK_CALENDAR.map((e) => ({ ...e, provider: 'outlook' as const, calendar: 'Holdings' })),
    ].map((e) => ({ id: e.id, title: e.title, start: e.start, end: e.end, provider: e.provider, calendar: e.calendar, attendees: e.attendees, location: e.location, kind: 'event' as const, conflictsWith: [] as string[], approvalId: null }));

    for (const a of real) for (const b of real) if (a.id !== b.id && overlaps(a, b)) a.conflictsWith.push(b.id);
    for (const p of proposed) p.conflictsWith = real.filter((e) => overlaps(p, e)).map((e) => e.id);
    return [...real, ...proposed].sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
  }

  async getMeetingPrep(eventId: string): Promise<MeetingPrep | null> {
    const event = (await this.listAgenda()).find((e) => e.id === eventId);
    if (!event) return null;
    const known = PREP[eventId];
    if (known) return { eventId, ...structuredClone(known) };
    const others = event.attendees.filter((a) => a.email !== L.email);
    const emails = (await this.listEmails()).filter((e) => others.some((o) => o.email === e.from.email));
    return {
      eventId,
      purpose: `${event.title}. No preparation notes have been written for this meeting yet.`,
      attendees: others.map((person) => ({ person, note: emails.some((e) => e.from.email === person.email) ? 'Has mail in the inbox this week.' : 'No recent correspondence.' })),
      talkingPoints: [],
      relatedEmailIds: emails.map((e) => e.id),
      openTaskIds: [],
      lastContact: emails[0] ? `${emails[0].from.name} wrote most recently about "${emails[0].subject}".` : null,
    };
  }

  async listTasks(): Promise<WorkTask[]> {
    return structuredClone(this.tasks);
  }

  async setTaskStatus(id: string, status: WorkTask['status']): Promise<void> {
    const task = this.tasks.find((t) => t.id === id);
    if (!task) throw new Error(`No task ${id}`);
    task.status = status;
    task.completedAt = status === 'done' ? this.now() : null;
    this.localActivity.push({ id: `act-task-${id}-${this.localActivity.length}`, at: this.now(), kind: 'task', actor: 'human', title: `${status === 'done' ? 'Completed' : 'Reopened'}: ${task.title}`, detail: null, outcome: 'done', simulated: true, link: { page: 'tasks', param: null } });
    this.emit();
  }

  async listReminders(): Promise<Reminder[]> {
    return structuredClone(this.reminders);
  }

  async setReminderStatus(id: string, status: Reminder['status']): Promise<void> {
    const reminder = this.reminders.find((r) => r.id === id);
    if (!reminder) throw new Error(`No reminder ${id}`);
    reminder.status = status;
    this.emit();
  }

  async listFollowUps(): Promise<FollowUp[]> {
    const [requests, approvals, runs] = await Promise.all([this.desk.listRequests(), this.desk.listApprovals(), this.desk.listRuns()]);
    const fixed: FollowUp[] = [
      { id: 'fu-surcharge', subject: 'Revised fuel-surcharge terms', waitingOn: WHO.peter, sentAt: bt('2026-11-11', '10:15'), expectedBy: bt('2026-11-13', '17:00'), status: 'overdue', emailId: null, nudgesSent: 0, note: 'Sent to Altamira procurement on Wednesday. No answer, and the vendor review depends on it.', nudgeApprovalId: null },
      { id: 'fu-forecast', subject: 'Volume forecast for the Baltic lanes', waitingOn: WHO.hannah, sentAt: bt('2026-11-13', '11:00'), expectedBy: bt(DAY.tue, '17:00'), status: 'waiting', emailId: 'mail-ratecard', nudgesSent: 0, note: 'Asked on Friday. Due Tuesday.', nudgeApprovalId: null },
      { id: 'fu-insurance', subject: 'Insurance certificate for the Q4 shipments', waitingOn: WHO.ines, sentAt: bt('2026-11-12', '11:30'), expectedBy: bt(DAY.mon, '17:00'), status: 'replied', emailId: 'mail-insurance', nudgesSent: 0, note: 'Ines replied on Monday at 08:05 with the certificate.', nudgeApprovalId: null },
    ];
    // A request the secretary answered with alternatives or a question is now waiting on the requester.
    const derived: FollowUp[] = requests
      .filter((r) => r.status === 'awaiting_reply')
      .map((r) => ({ id: `fu-${r.id}`, subject: r.subject, waitingOn: r.from, sentAt: r.history.at(-1)?.at ?? r.receivedAt, expectedBy: bt(DAY.wed, '17:00'), status: 'waiting' as const, emailId: r.id, nudgesSent: 0, note: 'The secretary replied and is waiting for their answer.', nudgeApprovalId: null }));

    return [...fixed, ...derived].map((followUp) => {
      const run = runs.find((r) => r.requestId === followUp.id);
      const nudge = run ? approvals.find((a) => a.runId === run.id) : undefined;
      if (!nudge) return followUp;
      const sent = nudge.execution.status === 'executed';
      return { ...followUp, nudgeApprovalId: nudge.status === 'pending' ? nudge.id : null, nudgesSent: sent ? 1 : 0, status: sent ? ('waiting' as const) : followUp.status, note: sent ? 'A reminder was sent today.' : followUp.note };
    });
  }

  async draftNudge(followUpId: string): Promise<void> {
    const followUp = (await this.listFollowUps()).find((f) => f.id === followUpId);
    if (!followUp) throw new Error(`No follow-up ${followUpId}`);
    if (followUp.nudgeApprovalId) throw new Error('A reminder for this follow-up is already waiting for approval.');
    const first = followUp.waitingOn.name.split(' ')[0];
    const mail = emailChange({
      to: [followUp.waitingOn],
      subject: `Re: ${followUp.subject}`,
      body: `Hi ${first},\n\nA quick reminder about my note on "${followUp.subject}". Could you let me know where it stands? It would help to have your answer this week.\n\nBest regards,\nLayla`,
    });
    const script: MockScript = {
      triage: triage('follow_up', 'normal', null),
      steps: [
        approval(`Remind ${followUp.waitingOn.name} about "${followUp.subject}"`, `You are waiting for ${followUp.waitingOn.name} to answer, and the answer was expected earlier. This is a short, polite reminder in the same thread.`, [mail]),
        exec(mail),
        audit(`Sent a reminder to ${followUp.waitingOn.name}.`),
        finish('follow_up_sent', `Sent a reminder to ${followUp.waitingOn.name} about "${followUp.subject}".`),
      ],
    };
    await this.desk.runScript(script, followUpId);
  }

  async listActivity(): Promise<ActivityEntry[]> {
    const [requests, approvals, runs, emails] = await Promise.all([this.desk.listRequests(), this.desk.listApprovals(), this.desk.listRuns(), this.listEmails()]);
    const entries: ActivityEntry[] = [...this.localActivity];
    const subjectOf = (run: AgentRun) => requests.find((r) => r.id === run.requestId)?.subject ?? emails.find((e) => e.id === run.requestId)?.subject ?? (run.conversationId ? 'a chat request' : 'a request');
    const linkOf = (run: AgentRun): ActivityEntry['link'] => (run.conversationId ? { page: 'chat', param: run.conversationId } : run.requestId?.startsWith('fu-') ? { page: 'tasks', param: null } : run.requestId ? { page: 'inbox', param: run.requestId } : null);

    for (const run of runs) {
      if (run.trigger === 'evaluation') continue;
      if (run.triage && run.requestId && !run.requestId.startsWith('fu-') && !run.requestId.startsWith('mail-')) {
        entries.push({ id: `${run.id}-triage`, at: run.startedAt, kind: 'triage', actor: 'agent', title: `Read and classified "${subjectOf(run)}"`, detail: `${run.triage.classification.replace(/_/g, ' ')}, ${run.triage.priority} priority`, outcome: 'done', simulated: true, link: linkOf(run) });
      }
      for (const action of run.actions) {
        if (!action.finishedAt || (action.status !== 'succeeded' && action.status !== 'failed')) continue;
        const kind = action.tool.startsWith('email.send') ? 'email' : action.tool.startsWith('calendar.') && action.sideEffect ? 'calendar' : action.tool.startsWith('task.') || action.tool.startsWith('reminder.') ? 'task' : null;
        if (!kind) continue;
        entries.push({ id: action.id, at: action.finishedAt, kind, actor: 'agent', title: action.summary, detail: action.error?.message ?? null, outcome: action.status === 'failed' ? 'failed' : 'done', simulated: action.simulated, link: linkOf(run) });
      }
      if (run.outcome === 'escalated' && run.finishedAt) {
        entries.push({ id: `${run.id}-escalated`, at: run.finishedAt, kind: 'system', actor: 'agent', title: `Handed to you: "${subjectOf(run)}"`, detail: run.summary, outcome: 'pending', simulated: true, link: linkOf(run) });
      }
    }
    for (const item of approvals) {
      if (item.status === 'pending') entries.push({ id: `${item.id}-asked`, at: item.createdAt, kind: 'approval', actor: 'agent', title: `Waiting for your approval: ${item.title}`, detail: null, outcome: 'pending', simulated: true, link: { page: 'approvals', param: item.id } });
      else if (item.decidedAt) entries.push({ id: `${item.id}-decided`, at: item.decidedAt, kind: 'approval', actor: 'human', title: `${item.decidedBy ?? 'Someone'} ${item.status === 'approved' ? 'approved' : 'rejected'}: ${item.title}`, detail: item.decisionNote, outcome: item.status === 'approved' ? 'done' : 'rejected', simulated: true, link: { page: 'approvals', param: item.id } });
    }
    const fixed: ActivityEntry[] = [
      { id: 'fx-tripoli', at: bt(DAY.mon, '08:27'), kind: 'task', actor: 'agent', title: 'Recorded a task from Omar\'s email: decide on driver cover for Tripoli', detail: 'Due today at 17:00.', outcome: 'done', simulated: true, link: { page: 'inbox', param: 'mail-tripoli' } },
      { id: 'fx-insurance', at: bt(DAY.mon, '08:06'), kind: 'follow_up', actor: 'agent', title: 'Closed a follow-up: insurance certificate received from Ines Ferreira', detail: null, outcome: 'done', simulated: true, link: { page: 'inbox', param: 'mail-insurance' } },
      { id: 'fx-board', at: bt(DAY.mon, '07:49'), kind: 'task', actor: 'agent', title: 'Recorded a task from Karim\'s email: sign off the Q3 board pack', detail: 'Due Wednesday at 12:00.', outcome: 'done', simulated: true, link: { page: 'inbox', param: 'mail-boardpack' } },
      { id: 'fx-digest', at: bt(DAY.mon, '06:01'), kind: 'triage', actor: 'agent', title: 'Filed a newsletter as low priority: Freight Weekly', detail: 'No action needed.', outcome: 'done', simulated: true, link: { page: 'inbox', param: 'mail-digest' } },
      { id: 'fx-surcharge', at: bt('2026-11-13', '17:05'), kind: 'follow_up', actor: 'agent', title: 'Marked a follow-up as overdue: fuel-surcharge terms, Peter Vogel', detail: 'No reply since Wednesday.', outcome: 'pending', simulated: true, link: { page: 'tasks', param: null } },
    ];
    return [...entries, ...fixed].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  }
}
