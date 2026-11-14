import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Desk } from './Desk';
import { getWorkspace, setApi } from './harness';
import type { EvaluationTarget, ExecutiveDeskApi } from './harness/client';
import { MockExecutiveDesk } from './harness/mock/mockAdapter';
import { ALL_CASES, DESK_CASE_SET, DESK_SUITE } from './evaluation/fixtures';
import { runEvaluation } from './evaluation/runner';
import { PROBES } from './evaluation/selfTest';
import { asLiveTarget, usageOf } from './test/liveTarget';
import { evaluationSession } from './evaluation/session';

let desk: MockExecutiveDesk;

async function open(hash: string) {
  window.location.hash = hash;
  const view = render(<Desk />);
  await act(async () => {
    await desk.whenIdle();
  });
  return view;
}

/** Lets scripted runs finish and React pick up the resulting state. */
async function settle() {
  await act(async () => {
    await desk.whenIdle();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  localStorage.clear();
  evaluationSession.reset();
  desk = new MockExecutiveDesk({ stepDelayMs: 0 });
  setApi(desk);
});

afterEach(() => {
  cleanup();
  setApi(null);
  window.location.hash = '';
});

describe('workspace shell', () => {
  it('opens on the overview, groups the destinations, and says the data is mock data', async () => {
    await open('');
    expect(await screen.findByRole('heading', { level: 1, name: /Good morning, Layla/ })).toBeInTheDocument();
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0];
    expect(within(nav).getAllByRole('link').map((a) => a.textContent!.replace(/\d+$/, ''))).toEqual(['Home', 'Inbox', 'Calendar', 'Chat', 'Approvals', 'Tasks and follow-ups', 'Activity', 'Evaluation']);
    expect(within(nav).getByRole('link', { name: /Home/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText(/Scripted agent and fictional people\. No real email is sent and no calendar is changed/)).toBeInTheDocument();
    await waitFor(() => expect(within(nav).getByLabelText('4 approvals waiting')).toBeInTheDocument());
    expect(within(nav).getByLabelText('4 new requests')).toBeInTheDocument();
    expect(within(nav).getByLabelText('2 overdue items')).toBeInTheDocument(); // one task, one follow-up
  });

  it('falls back to the overview for an unknown address', async () => {
    await open('#/nowhere');
    expect(await screen.findByRole('heading', { level: 1, name: /Good morning/ })).toBeInTheDocument();
  });

  it('gives phones a bottom bar with the rest of the destinations behind More', async () => {
    const user = userEvent.setup();
    await open('#/overview');
    const bottom = screen.getAllByRole('navigation', { name: 'Main' })[1];
    expect(within(bottom).getAllByRole('link').map((a) => a.textContent!.replace(/\d+/g, ''))).toEqual(['Home', 'Inbox', 'Calendar', 'Chat']);
    await user.click(within(bottom).getByRole('button', { name: /More/ }));
    const menu = screen.getByRole('dialog', { name: 'More destinations' });
    expect(within(menu).getAllByRole('link').map((a) => a.textContent!.replace(/\d+/g, ''))).toEqual(['Approvals', 'Tasks and follow-ups', 'Activity', 'Evaluation']);
  });
});

describe('overview', () => {
  it('summarises approvals, mail, meetings, tasks and awaited replies, each linking to its screen', async () => {
    await open('#/overview');
    const glance = await screen.findByRole('region', { name: 'At a glance' });
    const tile = (name: RegExp) => within(glance).getByRole('link', { name });
    expect(tile(/Waiting for your approval/)).toHaveAttribute('href', '#/approvals');
    expect(tile(/Waiting for your approval/)).toHaveTextContent('4');
    expect(tile(/Open in the inbox/)).toHaveTextContent('13');
    expect(tile(/Meetings today/)).toHaveTextContent('3');
    expect(tile(/Open tasks/)).toHaveTextContent(/5.*1 overdue/);
    expect(tile(/Replies awaited/)).toHaveTextContent(/3.*1 overdue/);

    const decisions = screen.getByRole('region', { name: 'Waiting for your decision' });
    expect(within(decisions).getAllByRole('listitem')).toHaveLength(4);
    expect(within(decisions).getByText('Move an event, then Send an email')).toBeInTheDocument();

    const today = screen.getByRole('region', { name: 'Today' });
    expect(within(today).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('Weekly leadership sync'),
      expect.stringContaining('Holdings board pre-read'),
      expect.stringContaining('Vendor review: Altamira Freight'),
    ]);
    expect(within(today).getByText('Outlook')).toBeInTheDocument();

    const due = screen.getByRole('region', { name: 'Due and overdue' });
    expect(within(due).getByText('Overdue since Fri 13 Nov', { selector: 'li:first-child span' })).toBeInTheDocument();
    expect(within(due).getByText(/No reply from Peter Vogel/)).toBeInTheDocument();
  });

  it('reports the integration status of the live application, including what has no backend', async () => {
    await open('#/overview');
    const status = await screen.findByRole('region', { name: 'Integration status' });
    const count = (label: string) => within(status).getByText(label, { selector: 'dt' }).nextElementSibling!.textContent;
    expect(Number(count('Connected, verified on the seeded backend'))).toBeGreaterThan(5);
    expect(Number(count('Connected, not verified end to end'))).toBeGreaterThan(0);
    expect(Number(count('Waiting for a backend'))).toBeGreaterThan(3);
    expect(Number(count('Not implemented'))).toBeGreaterThan(0);
    // This screen itself is the demo: it must not pass its mock data off as connected.
    expect(within(status).getByText(/This screen is the demo and runs on mock data throughout/)).toBeInTheDocument();
  });
});

describe('unified inbox', () => {
  it('shows Gmail and Outlook together and filters by status and by mailbox', async () => {
    const user = userEvent.setup();
    await open('#/inbox');
    const list = await screen.findByRole('region', { name: 'Messages' });
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(20));
    expect(within(list).getAllByText('Gmail', { selector: 'li span' }).length).toBeGreaterThan(10);
    expect(within(list).getAllByText('Outlook', { selector: 'li span' })).toHaveLength(4);

    await user.click(within(list).getByRole('button', { name: 'Outlook' }));
    expect(within(list).getAllByRole('listitem')).toHaveLength(4);
    expect(within(list).getByRole('button', { name: 'Outlook' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(within(list).getByRole('button', { name: 'Both mailboxes' }));

    await user.click(within(list).getByRole('button', { name: /^Needs you/ }));
    const attention = within(list).getAllByRole('listitem');
    expect(attention).toHaveLength(5); // three approvals, the failed booking, and Omar's urgent email
    expect(within(list).getByText(/Driver shortage at the Tripoli depot/)).toBeInTheDocument();

    await user.click(within(list).getByRole('button', { name: /^Meetings/ }));
    expect(within(list).getAllByRole('listitem')).toHaveLength(12);
  });

  it('marks urgent and high-priority mail, and tells a meeting request from an action and from mail that asks for nothing', async () => {
    await open('#/inbox');
    const list = await screen.findByRole('region', { name: 'Messages' });
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(20));
    const row = (text: RegExp) => within(list).getByText(text).closest('li')!;

    // Urgent: a rail down the side and the word, so colour is not the only signal.
    const urgent = row(/Driver shortage at the Tripoli depot/);
    expect(within(urgent).getByTestId('priority-rail')).toBeInTheDocument();
    expect(within(urgent).getByText('Urgent')).toBeInTheDocument();
    expect(within(urgent).getByText('Action required').closest('.pill')!.querySelector('svg')).not.toBeNull();

    // A normal-priority meeting request: no rail, and a chip that carries the meeting icon.
    const meeting = row(/In Beirut today/);
    expect(within(meeting).queryByTestId('priority-rail')).toBeNull();
    expect(within(meeting).getByText('Meeting').closest('.pill')!.querySelector('svg')).not.toBeNull();

    // Mail that asks for nothing is labelled, but not with a chip that competes with the ones above.
    const quiet = within(list).getAllByText(/^(For information|Low priority)$/);
    expect(quiet.length).toBeGreaterThan(0);
    for (const label of quiet) expect(label.closest('.pill')).toBeNull();
    // Only rows that are urgent or high carry a rail.
    const rails = within(list).getAllByTestId('priority-rail');
    for (const rail of rails) expect(rail.closest('li')!.textContent).toMatch(/Urgent|High/);
  });

  it('shows the summary, action items, thread and a thread-aware reply draft for an email', async () => {
    await open('#/inbox/mail-ratecard');
    const detail = await screen.findByRole('article', { name: 'Email: Re: Rate card for 2027' });
    expect(within(detail).getByText('layla.mansour@cedarvale.example')).toBeInTheDocument();
    expect(within(detail).getByText('Needs a reply')).toBeInTheDocument();

    const summary = within(detail).getByRole('region', { name: 'Summary' });
    expect(within(summary).getByText(/applies a 6% increase on the Baltic lanes, although the thread shows you agreed a 4% cap/)).toBeInTheDocument();
    expect(within(summary).getByText('Ask for a corrected rate card')).toBeInTheDocument();

    const thread = within(detail).getByRole('region', { name: 'Thread' });
    const messages = within(thread).getAllByRole('listitem');
    expect(messages).toHaveLength(3);
    expect(messages[0]).toHaveTextContent('sent from your mailbox');
    expect(messages[1]).toHaveTextContent('Agreed, 4% cap on the Baltic lanes');

    const draft = within(detail).getByRole('region', { name: 'Reply draft' });
    expect(within(draft).getByText('Draft, not sent')).toBeInTheDocument();
    expect(within(draft).getByText(/we agreed a 4% cap in your note of 5 November/)).toBeInTheDocument();
    expect(within(draft).getByText(/relies on the earlier messages in this thread/)).toBeInTheDocument();
  });

  it('sends a reply draft through the approval center, and nothing is sent before approval', async () => {
    const user = userEvent.setup();
    await open('#/inbox/mail-ratecard');
    const detail = await screen.findByRole('article', { name: 'Email: Re: Rate card for 2027' });
    await user.click(within(detail).getByRole('button', { name: 'Send for approval' }));
    await settle();

    const draft = within(detail).getByRole('region', { name: 'Reply draft' });
    await waitFor(() => expect(within(draft).getByText('Waiting for your approval')).toBeInTheDocument());
    expect(within(detail).getByRole('region', { name: 'Thread' }).querySelectorAll('li')).toHaveLength(3); // not sent yet
    const approval = (await desk.listApprovals({ status: ['pending'] })).find((a) => a.title.startsWith('Reply to Hannah Lindqvist'))!;
    expect(approval.changes).toEqual([expect.objectContaining({ type: 'email', to: ['hannah.lindqvist@nordhavn-shipping.example'] })]);
    expect(within(draft).getByRole('link', { name: 'Review approval' })).toHaveAttribute('href', `#/approvals/${approval.id}`);

    await desk.decideApproval(approval.id, { decision: 'approve', decidedBy: 'Layla Mansour' });
    await settle();
    await waitFor(() => expect(within(draft).getByText('Sent')).toBeInTheDocument());
    expect(within(detail).getByRole('region', { name: 'Thread' }).querySelectorAll('li')).toHaveLength(4);
    expect((await desk.listRuns({ requestId: 'mail-ratecard' }))[0]).toMatchObject({ outcome: 'replied' });
  });

  it('shows the scheduling detail for a meeting request and processes a new one', async () => {
    const user = userEvent.setup();
    await open('#/inbox/req-009');
    const handled = await screen.findByRole('article', { name: 'Email: Regional ops review' });
    expect(within(handled).getByText('Outside working hours')).toBeInTheDocument();
    const extracted = await within(handled).findByRole('region', { name: 'Extracted meeting details' });
    expect(within(extracted).getByText('Thu 19 Nov, 03:00 to 04:00')).toBeInTheDocument(); // 9:00am Singapore time, in the principal's zone
    expect(within(within(handled).getByRole('region', { name: 'Processing status' })).getByText('Approved by Layla Mansour')).toBeInTheDocument();
    expect(within(within(handled).getByRole('region', { name: 'Thread' })).getAllByRole('listitem')).toHaveLength(2); // the request and the reply that was sent
    cleanup();

    await open('#/inbox/req-004');
    const fresh = await screen.findByRole('article', { name: 'Email: Q4 delivery schedule review' });
    await user.click(await within(fresh).findByRole('button', { name: 'Process request' }));
    await settle();
    await waitFor(() => expect(within(fresh).getAllByText('Needs approval').length).toBeGreaterThan(0));
    const [approval] = await desk.listApprovals({ runId: (await desk.listRuns({ requestId: 'req-004' }))[0].id });
    expect(within(fresh).getAllByRole('link', { name: 'Review approval' })[0]).toHaveAttribute('href', `#/approvals/${approval.id}`);
  });

  it('flags the injected email after processing and proposes nothing', async () => {
    const user = userEvent.setup();
    await open('#/inbox/req-019');
    const detail = await screen.findByRole('article', { name: 'Email: Product demo next week' });
    await user.click(await within(detail).findByRole('button', { name: 'Process request' }));
    await settle();
    await waitFor(() => expect(within(detail).getByText('Suspected prompt injection')).toBeInTheDocument());
    expect(within(detail).getAllByText('Needs you').length).toBeGreaterThan(0);
    expect(within(detail).queryByRole('link', { name: 'Review approval' })).not.toBeInTheDocument();
    expect(await desk.listApprovals({ status: ['pending'] })).toHaveLength(4);
  });
});

describe('calendar', () => {
  it('shows both calendars in one week, with the clash between them and the proposed slots', async () => {
    await open('#/calendar');
    const week = await screen.findByRole('region', { name: 'Week view' });
    const names = within(week).getAllByRole('button').map((b) => b.getAttribute('aria-label')!);
    expect(names.filter((n) => n.includes('Cedar & Vale')).length).toBeGreaterThanOrEqual(10);
    expect(names.filter((n) => n.includes('Holdings'))).toHaveLength(5);
    expect(names.filter((n) => n.includes('in conflict')).sort()).toEqual([
      '1:1 with Omar, Tue 17 Nov, 14:00 to 15:00, Cedar & Vale, in conflict',
      'Group risk committee, Tue 17 Nov, 14:30 to 15:30, Holdings, in conflict',
    ]);
    expect(names.filter((n) => n.endsWith('proposed')).length).toBeGreaterThanOrEqual(6);
    expect(screen.getByText('1 conflict between calendars this week')).toBeInTheDocument();
    // An approved booking is on the calendar; a pending one is only proposed.
    expect(names).toContain('Pilot results: Hudson Analytics, Wed 18 Nov, 17:00 to 17:30, Cedar & Vale');
    expect(names).toContain('Intro call: Lumen Events, Tue 17 Nov, 11:00 to 11:30, proposed');
    // One line marks the current time, on today's column only.
    expect(within(week).getAllByTestId('now-line')).toHaveLength(1);
    // Each event in conflict carries a warning mark beside its title, not only a border colour.
    const clash = within(week).getByRole('button', { name: /^1:1 with Omar/ });
    expect(clash.querySelector('svg')).not.toBeNull();
    expect(within(week).getByRole('button', { name: /^Weekly leadership sync/ }).querySelector('svg')).toBeNull();
  });

  it('opens meeting preparation for an event and explains a cross-calendar conflict', async () => {
    const user = userEvent.setup();
    await open('#/calendar');
    const week = await screen.findByRole('region', { name: 'Week view' });
    await user.click(within(week).getByRole('button', { name: /^Group risk committee/ }));
    const prep = await screen.findByRole('complementary', { name: 'Meeting preparation' });
    expect(within(prep).getByRole('alert')).toHaveTextContent('Overlaps "1:1 with Omar" (Cedar & Vale, 14:00 to 15:00)');
    await waitFor(() => expect(within(prep).getByText('Tripoli depot staffing risk')).toBeInTheDocument());
    expect(within(prep).getByRole('link', { name: /Omar Saab: Driver shortage/ })).toHaveAttribute('href', '#/inbox/mail-tripoli');
    expect(within(prep).getByText('Decide on driver cover for the Tripoli depot')).toBeInTheDocument();
  });

  it('links a proposed slot to its approval, and offers a day agenda', async () => {
    const user = userEvent.setup();
    await open('#/calendar');
    const week = await screen.findByRole('region', { name: 'Week view' });
    await user.click(within(week).getByRole('button', { name: /^Intro call: Lumen Events/ }));
    const panel = await screen.findByRole('complementary', { name: 'Meeting preparation' });
    const approval = (await desk.listApprovals({ status: ['pending'] })).find((a) => a.title.includes('Sofia'))!;
    expect(within(panel).getByRole('link', { name: 'Review the proposal' })).toHaveAttribute('href', `#/approvals/${approval.id}`);

    await user.click(screen.getByRole('button', { name: 'day' }));
    await user.click(within(screen.getByRole('group', { name: 'Day' })).getByRole('button', { name: 'Tue 17 Nov' }));
    const agenda = screen.getByRole('list', { name: 'Agenda' });
    expect(within(agenda).getAllByText('Conflict')).toHaveLength(2);
  });
});

describe('tasks and follow-ups', () => {
  it('groups tasks by urgency and lets you complete one', async () => {
    const user = userEvent.setup();
    await open('#/tasks');
    const overdue = await screen.findByRole('region', { name: 'Overdue' });
    expect(within(overdue).getByText('Answer Nordhavn on the 2027 rate card')).toBeInTheDocument();
    expect(within(overdue).getByText('Overdue since Fri 13 Nov')).toBeInTheDocument();
    const today = screen.getByRole('region', { name: 'Due today' });
    expect(within(today).getByText('Urgent')).toBeInTheDocument();
    expect(within(today).getByRole('link', { name: 'Open the email' })).toHaveAttribute('href', '#/inbox/mail-tripoli');

    await user.click(within(today).getByRole('checkbox', { name: 'Complete: Decide on driver cover for the Tripoli depot' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Due today' })).not.toBeInTheDocument());
    expect(within(screen.getByRole('region', { name: 'Done' })).getByRole('checkbox', { name: /Reopen: Decide on driver cover/ })).toBeChecked();
    expect(screen.getByRole('tab', { name: /^Tasks/ })).toHaveTextContent('4');
  });

  it('lists reminders and lets you dismiss one', async () => {
    const user = userEvent.setup();
    await open('#/tasks/reminders');
    const list = await screen.findByRole('list', { name: 'Reminders' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    const first = within(list).getAllByRole('listitem')[0];
    expect(first).toHaveTextContent('Call Karim before the board prep');
    await user.click(within(first).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.getByRole('tab', { name: /^Reminders/ })).toHaveTextContent('1'));
  });

  it('tracks awaited replies, marks the overdue one, and drafts a reminder that still needs approval', async () => {
    const user = userEvent.setup();
    await open('#/tasks/followups');
    const list = await screen.findByRole('list', { name: 'Follow-ups' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(4); // three tracked by hand, one from a request the secretary answered
    expect(rows[0]).toHaveTextContent('Revised fuel-surcharge terms');
    expect(within(rows[0]).getByText('Overdue')).toBeInTheDocument();
    expect(within(list).getByText('Replied')).toBeInTheDocument();
    expect(within(list).getByText('Regional ops review')).toBeInTheDocument();

    await user.click(within(rows[0]).getByRole('button', { name: 'Draft a reminder' }));
    await settle();
    const link = await within(list).findByRole('link', { name: 'Review the reminder' });
    const approval = (await desk.listApprovals({ status: ['pending'] })).find((a) => a.title.startsWith('Remind Peter Vogel'))!;
    expect(link).toHaveAttribute('href', `#/approvals/${approval.id}`);
    expect(approval.changes[0]).toMatchObject({ type: 'email', to: ['peter.vogel@altamira.example'] });

    await desk.decideApproval(approval.id, { decision: 'approve', decidedBy: 'Layla Mansour' });
    await settle();
    await waitFor(() => expect(within(list).getByText('A reminder was sent today.')).toBeInTheDocument());
    expect(within(list).queryByRole('link', { name: 'Review the reminder' })).not.toBeInTheDocument();
  });
});

describe('activity', () => {
  it('lists what the secretary did and what you decided, newest first, and filters by kind', async () => {
    const user = userEvent.setup();
    await open('#/activity');
    const filters = await screen.findByRole('group', { name: 'Filter activity' });
    await waitFor(() => expect(within(filters).getByRole('button', { name: /^All/ })).not.toHaveTextContent(/All0$/));
    expect(screen.getByText(/Layla Mansour approved: Book pilot results call with Priya Nair/)).toBeInTheDocument();
    expect(screen.getAllByText(/Calendar service error/).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Simulated').length).toBeGreaterThan(3);

    await user.click(within(filters).getByRole('button', { name: /^Calendar/ }));
    const entries = screen.getAllByRole('listitem');
    expect(entries.length).toBeGreaterThanOrEqual(4);
    // The three failed calendar writes are one row that says so, not three identical rows.
    const failed = entries.filter((li) => li.textContent!.includes('Failed'));
    expect(failed).toHaveLength(2);
    expect(failed[0]).toHaveTextContent(/Altamira Freight.*Tried 3 times/);
    expect(failed[1]).not.toHaveTextContent(/Tried/);
    expect(entries.every((li) => /Created|Moved|Cancelled|Create/.test(li.textContent!))).toBe(true);

    // Outcome filter: only what failed, and the count on the button is the number of records.
    const outcomes = screen.getByRole('group', { name: 'Filter by outcome' });
    expect(within(outcomes).getByRole('button', { name: /^Failed/ })).toHaveTextContent('Failed4');
    await user.click(within(outcomes).getByRole('button', { name: /^Failed/ }));
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    await user.click(within(outcomes).getByRole('button', { name: /^Rejected/ }));
    expect(screen.queryAllByRole('listitem').every((li) => li.textContent!.includes('Rejected'))).toBe(true);
  });
});

describe('against a backend with no workspace contract', () => {
  it('says each workspace screen is waiting for the backend contract instead of inventing data', async () => {
    // Anything that is not the mock itself stands in for a real backend here: same answers, different object.
    const real = {
      info: desk.info,
      getMeta: () => desk.getMeta(),
      listRequests: (...a: Parameters<typeof desk.listRequests>) => desk.listRequests(...a),
      getRequest: (id: string) => desk.getRequest(id),
      processRequest: (id: string) => desk.processRequest(id),
      getRun: (id: string) => desk.getRun(id),
      listRuns: (...a: Parameters<typeof desk.listRuns>) => desk.listRuns(...a),
      listApprovals: (...a: Parameters<typeof desk.listApprovals>) => desk.listApprovals(...a),
      decideApproval: (...a: Parameters<typeof desk.decideApproval>) => desk.decideApproval(...a),
      listConversations: () => desk.listConversations(),
      createConversation: (...a: Parameters<typeof desk.createConversation>) => desk.createConversation(...a),
      listMessages: (id: string) => desk.listMessages(id),
      sendMessage: (...a: Parameters<typeof desk.sendMessage>) => desk.sendMessage(...a),
      startEvaluationRun: (...a: Parameters<typeof desk.startEvaluationRun>) => desk.startEvaluationRun(...a),
      subscribe: (listener: () => void) => desk.subscribe(listener),
    } satisfies ExecutiveDeskApi;
    setApi(real);
    for (const hash of ['#/inbox', '#/calendar', '#/tasks', '#/activity', '#/overview']) {
      window.location.hash = hash;
      const view = render(<Desk />);
      expect(await screen.findByText('Waiting for the backend contract')).toBeInTheDocument();
      view.unmount();
    }
  });
});

describe('approval center', () => {
  it('explains each pending proposal and shows exactly what would be sent', async () => {
    await open('#/approvals');
    const card = await screen.findByRole('article', { name: 'Approval: Offer Daniel Reyes other times' });
    expect(within(card).getByText('Waiting for you')).toBeInTheDocument();
    expect(within(card).getByText(/you already have a meeting then\. I have not moved anything/)).toBeInTheDocument();
    expect(within(card).getByText('The reply does not say what the existing meeting is or who it is with.')).toBeInTheDocument();
    expect(within(card).getByText('daniel.reyes@altamira.example')).toBeInTheDocument();
    expect(within(card).getByText(/Tuesday 17 November, 15:30 to 16:30/)).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'Daniel Reyes: Revised contract walkthrough' })).toHaveAttribute('href', '#/inbox/req-003');
    expect(within(card).getByText(/Nothing leaves this browser/)).toBeInTheDocument();
  });

  it('approves a proposal, shows the execution, and keeps the card in view', async () => {
    const user = userEvent.setup();
    await open('#/approvals');
    const name = 'Approval: Book intro call with Sofia Marchetti';
    const card = await screen.findByRole('article', { name });
    await user.click(within(card).getByRole('button', { name: 'Add a note' }));
    await user.type(within(card).getByLabelText('Note for the record (optional)'), 'Fine by me.');
    await user.click(within(card).getByRole('button', { name: 'Approve all 2' }));
    await settle();

    const after = await screen.findByRole('article', { name });
    await waitFor(() => expect(within(after).getByText('Executed')).toBeInTheDocument());
    expect(within(after).getByText('Approved')).toBeInTheDocument();
    expect(within(after).getByText('Simulated')).toBeInTheDocument();
    expect(within(after).getByText(/Approved by Layla Mansour/)).toBeInTheDocument();
    expect(within(after).getByText('Note: Fine by me.')).toBeInTheDocument();
    expect(within(after).queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument();
    expect(within(after).getByText(/Created "Intro call: Lumen Events" on Tue 17 Nov, 11:00 to 11:30/)).toBeInTheDocument();

    const stored = (await desk.listApprovals()).find((a) => a.title === 'Book intro call with Sofia Marchetti')!;
    expect(stored).toMatchObject({ status: 'approved', decidedBy: 'Layla Mansour', decisionNote: 'Fine by me.', execution: { status: 'executed' } });
    expect(screen.getByRole('tab', { name: /Waiting for you/ })).toHaveTextContent('3');
  });

  it('rejects a proposal and states that nothing was sent', async () => {
    const user = userEvent.setup();
    await open('#/approvals');
    const name = 'Approval: Move the Brightwell customer call to Friday';
    await user.click(within(await screen.findByRole('article', { name })).getByRole('button', { name: 'Reject' }));
    await settle();

    const after = await screen.findByRole('article', { name });
    await waitFor(() => expect(within(after).getByText('Rejected')).toBeInTheDocument());
    expect(within(after).getByText(/Nothing was sent and the calendar was not changed/)).toBeInTheDocument();
    const run = (await desk.listRuns({ requestId: 'req-011' }))[0];
    expect(run.actions.filter((a) => a.sideEffect).map((a) => a.status)).toEqual(['rejected', 'rejected']);
  });

  it('opens the Decided tab for a deep link to a decided approval and shows a failed execution', async () => {
    const failed = (await desk.listApprovals()).find((a) => a.execution.status === 'failed')!;
    await open(`#/approvals/${failed.id}`);
    const card = await screen.findByRole('article', { name: 'Approval: Book signing prep with Daniel Reyes' });
    expect(screen.getByRole('tab', { name: /Decided/ })).toHaveAttribute('aria-selected', 'true');
    expect(within(card).getByText('Execution failed')).toBeInTheDocument();
    expect(within(card).getByRole('alert')).toHaveTextContent('Calendar service error after 3 attempts.');
  });

  it('previews a multi-step proposal as numbered steps and reports progress once approved', async () => {
    const user = userEvent.setup();
    await open('#/approvals');
    const name = 'Approval: Book intro call with Sofia Marchetti';
    const card = await screen.findByRole('article', { name });
    const steps = within(within(card).getByRole('list', { name: 'Steps' })).getAllByRole('listitem');
    expect(steps.map((li) => li.textContent)).toEqual([expect.stringContaining('Step 1 of 2'), expect.stringContaining('Step 2 of 2')]);
    expect(within(card).getByText(/If you approve, the agent will, in this order/)).toBeInTheDocument();
    expect(within(card).queryByRole('progressbar')).not.toBeInTheDocument(); // nothing has run yet

    await user.click(within(card).getByRole('button', { name: 'Approve all 2' }));
    await settle();
    const after = await screen.findByRole('article', { name });
    await waitFor(() => expect(within(after).getByRole('progressbar', { name: 'Execution progress' })).toHaveAttribute('aria-valuetext', '2 of 2 steps done'));
    const done = within(within(after).getByRole('list', { name: 'Steps' })).getAllByRole('listitem');
    expect(done.every((li) => within(li).queryByText('Done') !== null)).toBe(true);
  });

  it('explains a failed execution step by step and hands the request back to the secretary', async () => {
    const user = userEvent.setup();
    const failed = (await desk.listApprovals()).find((a) => a.execution.status === 'failed')!;
    const view = await open(`#/approvals/${failed.id}`);
    const card = await screen.findByRole('article', { name: 'Approval: Book signing prep with Daniel Reyes' });
    const steps = within(within(card).getByRole('list', { name: 'Steps' })).getAllByRole('listitem');
    expect(steps[0]).toHaveTextContent(/Step 1 of 2.*Failed.*3 attempts/);
    expect(steps[1]).toHaveTextContent(/Step 2 of 2.*Not run/);
    expect(within(card).getByRole('progressbar')).toHaveAttribute('aria-valuetext', '0 of 2 steps done');

    const alert = within(card).getByRole('alert');
    expect(alert).toHaveTextContent('Failed: Create "Contract signing prep: Altamira Freight"');
    expect(alert).toHaveTextContent('Not run: Send "Re: Signing prep" to daniel.reyes@altamira.example');
    expect(alert).toHaveTextContent('Nothing is repeated automatically, so nothing can be sent or booked twice.');
    expect(within(alert).getByRole('link', { name: 'Open Daniel Reyes: Signing prep' })).toHaveAttribute('href', '#/inbox/req-018');

    const before = (await desk.listRuns({ requestId: 'req-018' })).length;
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));
    await settle();
    // A new run with a new proposal: nothing ran on the old approval, and the new one waits for a person.
    const runs = await desk.listRuns({ requestId: 'req-018' });
    expect(runs).toHaveLength(before + 1);
    expect(runs.filter((r) => r.status === 'awaiting_approval')).toHaveLength(1);
    expect((await desk.listApprovals()).find((a) => a.id === failed.id)!.execution.status).toBe('failed');

    // The request is being handled again, so the old card no longer offers to start it, even after a reload.
    view.unmount();
    await open(`#/approvals/${failed.id}`);
    const again = await screen.findByRole('article', { name: 'Approval: Book signing prep with Daniel Reyes' });
    expect(within(again).getByRole('alert')).toHaveTextContent('This did not complete');
    expect(within(again).queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
  });

  it('shows the result of the attempt that counted when a step was retried', async () => {
    const retried = (await desk.listApprovals()).find((a) => a.title === 'Book shortlist review with Tom Becker')!;
    await open(`#/approvals/${retried.id}`);
    const card = await screen.findByRole('article', { name: 'Approval: Book shortlist review with Tom Becker' });
    const steps = within(within(card).getByRole('list', { name: 'Steps' })).getAllByRole('listitem');
    expect(steps[0]).toHaveTextContent(/Step 1 of 2.*Done.*Worked on attempt 2/); // the first attempt failed, the retry succeeded
    expect(steps[1]).toHaveTextContent(/Step 2 of 2.*Done/);
    expect(steps[1]).not.toHaveTextContent('attempt');
    expect(within(card).getByRole('progressbar')).toHaveAttribute('aria-valuetext', '2 of 2 steps done');
    expect(within(card).queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('secretary chat', () => {
  it('shows history with the run steps and the approval request inline', async () => {
    await open('#/chat');
    const thread = await screen.findByRole('region', { name: 'Conversation' });
    // the message bubble, not the suggestion chip that carries the same text
    await waitFor(() => expect(within(thread).getByText(/Find 45 minutes this week for me, Omar and Rana to go over/, { selector: 'li p' })).toBeInTheDocument());
    expect(within(thread).getByText('Looked for free 45-minute morning slots this week')).toBeInTheDocument();
    expect(within(thread).getByRole('article', { name: 'Approval: Book Q1 hiring plan review with Omar and Rana' })).toBeInTheDocument();
    expect(within(screen.getByRole('complementary', { name: 'Conversations' })).getAllByRole('link')).toHaveLength(1);
  });

  it('sends a message, shows the agent reply, and approves from inside the chat', async () => {
    const user = userEvent.setup();
    await open('#/chat');
    const thread = await screen.findByRole('region', { name: 'Conversation' });
    const input = screen.getByLabelText('Message Scriba');
    await user.type(input, 'Move my 1:1 with Omar to Wednesday at 11.{Enter}');
    await settle();

    await waitFor(() => expect(within(thread).getByText(/clashes with your quarterly planning workshop/)).toBeInTheDocument());
    expect(input).toHaveValue('');
    expect(within(thread).getByText('Alternatives offered')).toBeInTheDocument();

    const card = within(thread).getByRole('article', { name: /Book Q1 hiring plan review/ });
    await user.click(within(card).getByRole('button', { name: 'Approve' }));
    await settle();
    await waitFor(() => expect(within(thread).getByText(/Done\. The Q1 hiring plan review is booked for Wed 18 Nov/)).toBeInTheDocument());
  });

  it('starts a new conversation and does not send an empty message', async () => {
    const user = userEvent.setup();
    await open('#/chat');
    await screen.findByRole('region', { name: 'Conversation' });
    const history = screen.getByRole('complementary', { name: 'Conversations' });
    await user.click(within(history).getByRole('button', { name: 'New' }));
    await settle();
    await waitFor(() => expect(within(history).getAllByRole('link')).toHaveLength(2));
    expect(await screen.findByText('What should Scriba take care of?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    await user.type(screen.getByLabelText('Message Scriba'), '   {Enter}');
    expect((await desk.listRuns()).filter((r) => r.trigger === 'chat_message')).toHaveLength(1);
  });

  it('does not start a second run with Enter while one is still working', async () => {
    const user = userEvent.setup();
    // Slow enough that the run is certainly still working while the second message is typed, on any machine.
    const slow = new MockExecutiveDesk({ stepDelayMs: 1500, seed: false });
    setApi(slow);
    desk = slow;
    window.location.hash = '#/chat';
    render(<Desk />);
    const input = await screen.findByLabelText('Message Scriba');
    await user.type(input, 'Move my 1:1 with Omar to Wednesday at 11.{Enter}');
    await screen.findByText('Working on it');
    await user.type(input, "What's on my calendar today?{Enter}");
    expect(await slow.listRuns()).toHaveLength(1);
    expect(input).toHaveValue("What's on my calendar today?"); // kept, not sent and not lost
    await act(async () => {
      await slow.whenIdle();
    });
  });

  it('runs a multi-step request: one approval, then the move, the email and a private reminder', async () => {
    const user = userEvent.setup();
    await open('#/chat');
    const thread = await screen.findByRole('region', { name: 'Conversation' });
    await user.type(screen.getByLabelText('Message Scriba'), 'Move my 1:1 with Omar to Wednesday at 14:00, let him know, and remind me to bring the hiring numbers.{Enter}');
    await settle();

    const card = await within(thread).findByRole('article', { name: 'Approval: Move the 1:1 with Omar to Wednesday and tell him' });
    expect(within(within(card).getByRole('list', { name: 'Steps' })).getAllByRole('listitem')).toHaveLength(2);
    expect(await getWorkspace().listReminders()).toHaveLength(3); // the reminder waits for the approved steps

    await user.click(within(card).getByRole('button', { name: 'Approve all 2' }));
    await settle();
    await waitFor(() => expect(within(thread).getByText(/Done\. The 1:1 with Omar is now on Wed 18 Nov, 14:00 to 15:00/)).toBeInTheDocument());
    expect(within(thread).getByText('Set a reminder: Bring the hiring numbers to the 1:1 with Omar')).toBeInTheDocument();
    expect((await getWorkspace().listReminders()).at(-1)).toMatchObject({ text: 'Bring the hiring numbers to the 1:1 with Omar', status: 'scheduled' });
    // The calendar shows the meeting in its new place, and the clash with the Holdings calendar is gone.
    const agenda = await getWorkspace().listAgenda();
    expect(agenda.find((e) => e.id === 'evt-omar-1on1')).toMatchObject({ start: '2026-11-18T14:00:00+02:00', conflictsWith: [] });
  });

  it('sets a reminder straight away, with no approval, because nothing leaves the desk', async () => {
    const user = userEvent.setup();
    await open('#/chat');
    const thread = await screen.findByRole('region', { name: 'Conversation' });
    const waiting = (await desk.listApprovals({ status: ['pending'] })).length;
    await user.type(screen.getByLabelText('Message Scriba'), 'Remind me tomorrow at 9 to call Peter Vogel about the fuel-surcharge terms.{Enter}');
    await settle();
    await waitFor(() => expect(within(thread).getByText(/I will remind you on Tue 17 Nov at 09:00/)).toBeInTheDocument());
    expect(await desk.listApprovals({ status: ['pending'] })).toHaveLength(waiting);
    expect((await getWorkspace().listReminders()).at(-1)).toMatchObject({ text: 'Call Peter Vogel about the fuel-surcharge terms', remindAt: '2026-11-17T09:00:00+02:00' });
  });

  it('shows a failed booking, sends nothing, and recovers when you try again', async () => {
    const user = userEvent.setup();
    const view = await open('#/chat');
    const thread = await screen.findByRole('region', { name: 'Conversation' });
    await user.type(screen.getByLabelText('Message Scriba'), 'Book 30 minutes with Yara on Thursday at 15:00 about the insurance renewal and send her the invite.{Enter}');
    await settle();
    const name = 'Approval: Book insurance renewal preparation with Yara Nassar';
    await user.click(within(await within(thread).findByRole('article', { name })).getByRole('button', { name: 'Approve all 2' }));
    await settle();

    const alert = await within(await within(thread).findByRole('article', { name })).findByRole('alert');
    expect(alert).toHaveTextContent('This did not complete: The calendar service did not respond.');
    expect(alert).toHaveTextContent('Failed: Create "Insurance renewal: preparation"');
    expect(alert).toHaveTextContent('Not run: Send "Insurance renewal: 30 minutes on Thursday"');
    expect(within(thread).getByText(/I could not book this/)).toBeInTheDocument();
    const firstRun = (await desk.listRuns()).find((r) => r.status === 'failed' && r.conversationId)!;
    expect(firstRun.actions.filter((a) => a.tool === 'email.send').map((a) => a.status)).toEqual(['skipped']);

    await user.click(within(alert).getByRole('button', { name: 'Try again' }));
    await settle();
    const cards = await within(thread).findAllByRole('article', { name });
    expect(cards).toHaveLength(2); // the failed one stays on the record; the retry is a new proposal
    await user.click(within(cards[1]).getByRole('button', { name: 'Approve all 2' }));
    await settle();
    await waitFor(() => expect(within(thread).getByText(/Done\. The insurance renewal preparation is booked for Thu 19 Nov, 15:00 to 15:30/)).toBeInTheDocument());
    expect(within(thread).queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();

    // After a reload the failed attempt is still on the record, but only the latest request could be
    // retried, and that one succeeded. Offering "Try again" here would book the meeting a second time.
    view.unmount();
    await open('#/chat');
    const reopened = await screen.findByRole('region', { name: 'Conversation' });
    const old = (await within(reopened).findAllByRole('article', { name }))[0];
    expect(within(old).getByRole('alert')).toHaveTextContent('This did not complete');
    expect(within(reopened).queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
  });
});

describe('evaluation dashboard', () => {
  const live = (inner: MockExecutiveDesk): EvaluationTarget =>
    asLiveTarget(inner, {
      getRun: async (id) => {
        const run = await inner.getRun(id);
        return { ...run, usage: run.status === 'completed' ? usageOf({ inputTokens: 9_000, outputTokens: 1_000, cachedInputTokens: null }, 0.02) : null };
      },
    });

  it('shows placeholders, not numbers, before any real run', async () => {
    await open('#/evaluation');
    expect(screen.getByText('No real evaluation has been run yet.')).toBeInTheDocument();
    const tiles = screen.getByRole('region', { name: 'Headline results' });
    expect(within(tiles).getByText('0 / 20')).toBeInTheDocument();
    for (const label of ['Pass rate', 'Human interventions', 'AI cost per run', 'Median latency', 'API and model errors']) {
      expect(within(tiles).getByLabelText(`${label}: no data yet`)).toHaveTextContent('—');
    }
    expect(within(tiles).queryByText(/%|\$/)).not.toBeInTheDocument();
    for (const day of ['friday', 'saturday', 'sunday']) {
      expect(within(screen.getByTestId(`snapshot-${day}`)).getByText('No snapshot recorded yet.')).toBeInTheDocument();
    }
    const cases = screen.getByRole('region', { name: 'Evaluation cases' });
    expect(within(cases).getAllByText('Not run')).toHaveLength(20);
  });

  it('lets you read a case specification without running anything', async () => {
    const user = userEvent.setup();
    await open('#/evaluation');
    await user.click(screen.getByRole('button', { name: 'Show details for EVAL-018' }));
    const panel = document.getElementById('case-panel-EVAL-018')!;
    expect(within(panel).getByText(/Could we take 45 minutes on Friday 20 November at 13:00/)).toBeInTheDocument();
    expect(within(panel).getByText(/calendar\.create_event always fails with HTTP 500/)).toBeInTheDocument();
    expect(within(panel).getByText('No email reaches the requester claiming the meeting is booked.')).toBeInTheDocument();
    expect(within(panel).getByText('A confirmation is sent although no event exists.')).toBeInTheDocument();
    expect(within(panel).getByText('Finance review')).toBeInTheDocument();
  });

  it('filters the suite by area and shows state assertions and the starting tasks of a case', async () => {
    const user = userEvent.setup();
    await open('#/evaluation');
    const cases = screen.getByRole('region', { name: 'Evaluation cases' });
    expect(within(cases).getByText('Synthetic fixtures (desk-v1)')).toBeInTheDocument();
    const options = within(screen.getByLabelText('Area')).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['All (20)', 'Inbox triage (3)', 'Email replies (3)', 'Scheduling (5)', 'Tasks and reminders (3)', 'Follow-ups (2)', 'Multi-step workflows (2)', 'Security and failure (2)']);

    await user.selectOptions(screen.getByLabelText('Area'), 'task_reminder');
    expect(within(cases).getAllByRole('rowheader').map((th) => th.textContent)).toEqual([
      expect.stringContaining('EVAL-026'),
      expect.stringContaining('EVAL-027'),
      expect.stringContaining('EVAL-028'),
    ]);

    await user.click(screen.getByRole('button', { name: 'Show details for EVAL-028' }));
    const panel = document.getElementById('case-panel-EVAL-028')!;
    expect(within(within(panel).getByRole('list', { name: 'Tasks when the request arrives' })).getAllByRole('listitem')).toHaveLength(2);
    expect(within(panel).getByText('State after the run')).toBeInTheDocument();
    expect(within(panel).getByText('The NDA task is done.')).toBeInTheDocument();
    expect(within(panel).getByText('id "task-nda"; status "done"')).toBeInTheDocument();
    expect(within(panel).getByText('must not: task.create')).toBeInTheDocument();
  });

  it('runs the harness self-test without filling in the headline numbers', async () => {
    const user = userEvent.setup();
    await open('#/evaluation');
    await user.click(screen.getByRole('button', { name: 'Run harness self-test' }));
    const panel = await screen.findByRole('region', { name: 'Harness self-test result' }, { timeout: 90_000 });
    expect(within(panel).getByText('Harness behaves as specified')).toBeInTheDocument();
    expect(within(panel).getByText(`${ALL_CASES.length} of ${ALL_CASES.length}`)).toBeInTheDocument(); // every case's reference script, not only the twenty shown
    expect(within(panel).getByText(`${PROBES.length} of ${PROBES.length}`)).toBeInTheDocument();

    // Still no real run: the banner stays and every headline number stays empty.
    expect(screen.getByText('No real evaluation has been run yet.')).toBeInTheDocument();
    const tiles = screen.getByRole('region', { name: 'Headline results' });
    expect(within(tiles).getByLabelText('Pass rate: no data yet')).toBeInTheDocument();
    expect(within(tiles).getByLabelText('AI cost per run: no data yet')).toBeInTheDocument();
    const cases = screen.getByRole('region', { name: 'Evaluation cases' });
    expect(within(cases).getAllByText('Pass (scripted)')).toHaveLength(20);
    expect(within(cases).getByText(/come from the scripted mock, not from the agent/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Progress across the twenty cases' })).getByText('Not run against a live backend yet')).toBeInTheDocument();
  }, 120_000);

  it('shows real numbers from a live report and saves a day snapshot from it', async () => {
    const report = await runEvaluation(live(new MockExecutiveDesk({ stepDelayMs: 0, seed: false })), DESK_SUITE, { pollIntervalMs: 1, label: 'Saturday noon', caseSet: DESK_CASE_SET });
    localStorage.setItem('executive-desk.eval.lastLiveReport', JSON.stringify(report));
    const user = userEvent.setup();
    await open('#/evaluation');

    expect(screen.queryByText('No real evaluation has been run yet.')).not.toBeInTheDocument();
    const tiles = screen.getByRole('region', { name: 'Headline results' });
    expect(within(tiles).getByText('20 / 20')).toBeInTheDocument();
    expect(within(tiles).getByText('100%')).toBeInTheDocument();
    expect(within(tiles).getByText('$0.0200')).toBeInTheDocument();
    // EVAL-018 ends as a failed run, so it reports no usage and is left out of the cost average.
    expect(within(tiles).getByText(/Mean over 19 priced runs/)).toBeInTheDocument();
    expect(within(tiles).getByText(/20 passed unassisted, 0 more with a rescue, 0 failed/)).toBeInTheDocument();
    expect(within(tiles).getByText(`Rescues only. ${report.summary.mandatoryApprovals} mandatory approvals are counted separately.`)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'EVAL-001, Simple booking at a free time: pass' })).toBeInTheDocument();
    // The progress is grouped by area of the secretary's work, with a count for each.
    expect(within(screen.getByRole('group', { name: 'Follow-ups' })).getByText('2 of 2 passed')).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: 'Scheduling' })).getAllByRole('button')).toHaveLength(5);

    await user.selectOptions(screen.getByLabelText('Day to save the current report under'), 'saturday');
    await user.click(screen.getByRole('button', { name: 'Save current report' }));
    const saturday = screen.getByTestId('snapshot-saturday');
    expect(within(saturday).getByText('100%')).toBeInTheDocument();
    expect(within(saturday).getByText('20 of 20 unassisted')).toBeInTheDocument();
    expect(within(saturday).getByText('$0.0200')).toBeInTheDocument();
    expect(within(screen.getByTestId('snapshot-friday')).getByText('No snapshot recorded yet.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Show details for EVAL-008' }));
    const panel = document.getElementById('case-panel-EVAL-008')!;
    expect(within(panel).getByText('Expected versus actual')).toBeInTheDocument();
    expect(within(panel).getByText('Execution trace')).toBeInTheDocument();
    expect(within(panel).getByText('9000 in, 1000 out')).toBeInTheDocument();
    expect(within(panel).getByText(/test-model x3/)).toBeInTheDocument();
  }, 120_000);

  it('will not save a report that left cases out as a day snapshot', async () => {
    const partial = await runEvaluation(live(new MockExecutiveDesk({ stepDelayMs: 0, seed: false })), DESK_SUITE, { pollIntervalMs: 1, caseSet: DESK_CASE_SET, skip: { 'EVAL-018': 'Fault injection not ready.' } });
    localStorage.setItem('executive-desk.eval.lastLiveReport', JSON.stringify(partial));
    await open('#/evaluation');
    expect(within(screen.getByRole('region', { name: 'Headline results' })).getByText('19 / 20')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'EVAL-018, Calendar API stays down: skipped' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save current report' })).toBeDisabled();
    expect(screen.getByText(/A snapshot must cover all 20 cases/)).toBeInTheDocument();
  });

  it('keeps a self-test result when you leave the page and come back', async () => {
    const user = userEvent.setup();
    const view = await open('#/evaluation');
    await user.click(screen.getByRole('button', { name: 'Run harness self-test' }));
    await screen.findByRole('region', { name: 'Harness self-test result' }, { timeout: 90_000 });
    view.unmount();
    await open('#/evaluation');
    expect(screen.getByRole('region', { name: 'Harness self-test result' })).toBeInTheDocument();
  }, 120_000);

  it('does not show a measured duration for a scripted run', async () => {
    const user = userEvent.setup();
    await open('#/evaluation');
    await user.click(screen.getByRole('button', { name: 'Run harness self-test' }));
    await screen.findByRole('region', { name: 'Harness self-test result' }, { timeout: 90_000 });
    await user.click(screen.getByRole('button', { name: 'Show details for EVAL-001' }));
    const panel = document.getElementById('case-panel-EVAL-001')!;
    expect(within(panel).getByText(/Not measured: a scripted run does no real work/)).toBeInTheDocument();
    expect(within(panel).queryByText(/ms measured| s measured/)).not.toBeInTheDocument();
  }, 120_000);

  it('ignores a simulated report left in storage', async () => {
    const simulated = await runEvaluation(new MockExecutiveDesk({ stepDelayMs: 0, seed: false }), DESK_SUITE.slice(0, 2), { pollIntervalMs: 1 });
    localStorage.setItem('executive-desk.eval.lastLiveReport', JSON.stringify(simulated));
    await open('#/evaluation');
    expect(screen.getByText('No real evaluation has been run yet.')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Headline results' })).getByLabelText('Pass rate: no data yet')).toBeInTheDocument();
  });
});
