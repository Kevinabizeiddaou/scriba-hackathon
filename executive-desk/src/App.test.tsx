import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { App } from './App';
import { setApi } from './api';
import type { EvaluationTarget } from './api/client';
import { MockExecutiveDesk } from './api/mock/mockAdapter';
import { EVALUATION_CASES } from './evaluation/fixtures';
import { SYNTHETIC_CASE_SET } from './evaluation/fixtures';
import { runEvaluation } from './evaluation/runner';
import { PROBES } from './evaluation/selfTest';
import { asLiveTarget, usageOf } from './test/liveTarget';
import { evaluationSession } from './evaluation/session';

let desk: MockExecutiveDesk;

async function open(hash: string) {
  window.location.hash = hash;
  const view = render(<App />);
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

describe('app shell', () => {
  it('shows the four sections, marks the current one, and says the data is mock data', async () => {
    await open('#/inbox');
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0];
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual([
      'Secretary Chat',
      expect.stringContaining('Request Inbox'),
      expect.stringContaining('Approval Center'),
      'Evaluation',
    ]);
    expect(within(nav).getByRole('link', { name: /Request Inbox/ })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: /Secretary Chat/ })).not.toHaveAttribute('aria-current');
    expect(screen.getByText(/Scripted agent\. No real email is sent and no calendar is changed/)).toBeInTheDocument();
    await waitFor(() => expect(within(nav).getByLabelText('4 new requests')).toBeInTheDocument());
    expect(within(nav).getByLabelText('4 approvals waiting')).toBeInTheDocument();
  });

  it('falls back to the inbox for an unknown address', async () => {
    await open('#/nowhere');
    expect(await screen.findByRole('heading', { level: 1, name: 'Request Inbox' })).toBeInTheDocument();
  });
});

describe('request inbox', () => {
  it('lists every request and filters by status', async () => {
    const user = userEvent.setup();
    await open('#/inbox');
    const list = screen.getByRole('region', { name: 'Requests' });
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(12));

    await user.click(within(list).getByRole('button', { name: /^New/ }));
    const fresh = within(list).getAllByRole('listitem');
    expect(fresh).toHaveLength(4);
    for (const row of fresh) expect(within(row).getByText('New')).toBeInTheDocument();
    expect(within(list).getByRole('button', { name: /^New/ })).toHaveAttribute('aria-pressed', 'true');

    await user.click(within(list).getByRole('button', { name: /^Needs you/ }));
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(within(list).getByText('Signing prep')).toBeInTheDocument();
  });

  it('shows classification, priority, extracted details, status and history for a handled request', async () => {
    await open('#/inbox/req-009');
    const detail = await screen.findByRole('article', { name: 'Request: Regional ops review' });
    expect(within(detail).getByText('Waiting for reply')).toBeInTheDocument();
    expect(within(detail).getAllByText('New meeting')).toHaveLength(2); // the chip and the status step
    expect(within(detail).getByText('Normal priority')).toBeInTheDocument();
    expect(within(detail).getByText('Outside working hours')).toBeInTheDocument();

    const extracted = within(detail).getByRole('region', { name: 'Extracted meeting details' });
    expect(within(extracted).getByText('Regional ops review: Straits Cargo')).toBeInTheDocument();
    expect(within(extracted).getByText('60 minutes')).toBeInTheDocument();
    // 9:00am Singapore time shown in the principal's zone
    expect(within(extracted).getByText('Thu 19 Nov, 03:00 to 04:00')).toBeInTheDocument();
    expect(within(extracted).getByText('Asia/Singapore')).toBeInTheDocument();

    const status = within(detail).getByRole('region', { name: 'Processing status' });
    expect(within(status).getByText('Approved by Layla Mansour')).toBeInTheDocument();
    expect(within(status).getByText('Alternatives offered')).toBeInTheDocument();

    const history = within(detail).getByRole('region', { name: 'History' });
    expect(within(history).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('Received'),
      expect.stringContaining('Processing started'),
      expect.stringContaining('Classified'),
      expect.stringContaining('Approval requested'),
      expect.stringContaining('Approved'),
      expect.stringContaining('Finished'),
    ]);
  });

  it('processes a new request and ends up waiting for approval, with a link to it', async () => {
    const user = userEvent.setup();
    await open('#/inbox/req-004');
    const detail = await screen.findByRole('article', { name: 'Request: Q4 delivery schedule review' });
    expect(within(detail).getByText(/Nothing extracted yet/)).toBeInTheDocument();
    expect(within(detail).queryByRole('link', { name: 'Review approval' })).not.toBeInTheDocument();

    await user.click(within(detail).getByRole('button', { name: 'Process request' }));
    await settle();

    await waitFor(() => expect(within(detail).getByText('Needs approval')).toBeInTheDocument());
    expect(within(detail).queryByRole('button', { name: 'Process request' })).not.toBeInTheDocument();
    const activity = within(detail).getByRole('region', { name: 'Agent activity' });
    expect(within(activity).getByText(/Checked Wednesday afternoon/)).toBeInTheDocument();
    expect(within(activity).getAllByText('Waiting for approval').length).toBeGreaterThanOrEqual(2);

    const [approval] = await desk.listApprovals({ runId: (await desk.listRuns({ requestId: 'req-004' }))[0].id });
    expect(within(detail).getByRole('link', { name: 'Review approval' })).toHaveAttribute('href', `#/approvals/${approval.id}`);
  });

  it('flags the injected email after processing and proposes nothing', async () => {
    const user = userEvent.setup();
    await open('#/inbox/req-019');
    const detail = await screen.findByRole('article', { name: 'Request: Product demo next week' });
    await user.click(within(detail).getByRole('button', { name: 'Process request' }));
    await settle();
    await waitFor(() => expect(within(detail).getByText('Suspected prompt injection')).toBeInTheDocument());
    expect(within(detail).getByText('Needs you')).toBeInTheDocument();
    expect(within(detail).queryByRole('link', { name: 'Review approval' })).not.toBeInTheDocument();
    expect(await desk.listApprovals({ status: ['pending'] })).toHaveLength(4);
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
    expect(await screen.findByText('What should Scriba arrange?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    await user.type(screen.getByLabelText('Message Scriba'), '   {Enter}');
    expect((await desk.listRuns()).filter((r) => r.trigger === 'chat_message')).toHaveLength(1);
  });

  it('does not start a second run with Enter while one is still working', async () => {
    const user = userEvent.setup();
    const slow = new MockExecutiveDesk({ stepDelayMs: 150, seed: false });
    setApi(slow);
    desk = slow;
    window.location.hash = '#/chat';
    render(<App />);
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

  it('runs the harness self-test without filling in the headline numbers', async () => {
    const user = userEvent.setup();
    await open('#/evaluation');
    await user.click(screen.getByRole('button', { name: 'Run harness self-test' }));
    const panel = await screen.findByRole('region', { name: 'Harness self-test result' }, { timeout: 15_000 });
    expect(within(panel).getByText('Harness behaves as specified')).toBeInTheDocument();
    expect(within(panel).getByText('20 of 20')).toBeInTheDocument();
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
  }, 20_000);

  it('shows real numbers from a live report and saves a day snapshot from it', async () => {
    const report = await runEvaluation(live(new MockExecutiveDesk({ stepDelayMs: 0, seed: false })), EVALUATION_CASES, { pollIntervalMs: 1, label: 'Saturday noon', caseSet: SYNTHETIC_CASE_SET });
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
  }, 20_000);

  it('will not save a report that left cases out as a day snapshot', async () => {
    const partial = await runEvaluation(live(new MockExecutiveDesk({ stepDelayMs: 0, seed: false })), EVALUATION_CASES, { pollIntervalMs: 1, caseSet: SYNTHETIC_CASE_SET, skip: { 'EVAL-018': 'Fault injection not ready.' } });
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
    await screen.findByRole('region', { name: 'Harness self-test result' }, { timeout: 15_000 });
    view.unmount();
    await open('#/evaluation');
    expect(screen.getByRole('region', { name: 'Harness self-test result' })).toBeInTheDocument();
  }, 20_000);

  it('does not show a measured duration for a scripted run', async () => {
    const user = userEvent.setup();
    await open('#/evaluation');
    await user.click(screen.getByRole('button', { name: 'Run harness self-test' }));
    await screen.findByRole('region', { name: 'Harness self-test result' }, { timeout: 15_000 });
    await user.click(screen.getByRole('button', { name: 'Show details for EVAL-001' }));
    const panel = document.getElementById('case-panel-EVAL-001')!;
    expect(within(panel).getByText(/Not measured: a scripted run does no real work/)).toBeInTheDocument();
    expect(within(panel).queryByText(/ms measured| s measured/)).not.toBeInTheDocument();
  }, 20_000);

  it('ignores a simulated report left in storage', async () => {
    const simulated = await runEvaluation(new MockExecutiveDesk({ stepDelayMs: 0, seed: false }), EVALUATION_CASES.slice(0, 2), { pollIntervalMs: 1 });
    localStorage.setItem('executive-desk.eval.lastLiveReport', JSON.stringify(simulated));
    await open('#/evaluation');
    expect(screen.getByText('No real evaluation has been run yet.')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Headline results' })).getByLabelText('Pass rate: no data yet')).toBeInTheDocument();
  });
});
