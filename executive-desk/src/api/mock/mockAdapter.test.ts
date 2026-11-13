import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../client';
import { isSideEffectTool } from '../types';
import { MockExecutiveDesk } from './mockAdapter';

const PRINCIPAL = 'Layla Mansour';

afterEach(() => vi.unstubAllGlobals());

describe('MockExecutiveDesk', () => {
  it('never touches the network, even through a full approve-and-execute flow', async () => {
    const fetchSpy = vi.fn(() => Promise.reject(new Error('network is off limits')));
    vi.stubGlobal('fetch', fetchSpy);
    vi.stubGlobal('XMLHttpRequest', vi.fn(() => { throw new Error('network is off limits'); }));

    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const [pending] = await desk.listApprovals({ status: ['pending'] });
    await desk.decideApproval(pending.id, { decision: 'approve', decidedBy: PRINCIPAL });
    await desk.whenIdle();
    const conversation = await desk.createConversation();
    await desk.sendMessage(conversation.id, "What's on my calendar today?");
    await desk.whenIdle();

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('marks every side-effect action as simulated', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const runs = await desk.listRuns();
    const sideEffects = runs.flatMap((r) => r.actions).filter((a) => isSideEffectTool(a.tool));
    expect(sideEffects.length).toBeGreaterThan(5);
    expect(sideEffects.every((a) => a.simulated)).toBe(true);
    const approvals = await desk.listApprovals();
    expect(approvals.every((a) => a.execution.simulated)).toBe(true);
  });

  it('seeds an inbox that shows every stage of the flow', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const requests = await desk.listRequests();
    expect(requests).toHaveLength(12);
    const statuses = new Set(requests.map((r) => r.status));
    expect(statuses).toEqual(new Set(['received', 'awaiting_approval', 'awaiting_reply', 'completed', 'escalated']));
    // newest first
    const times = requests.map((r) => Date.parse(r.receivedAt));
    expect(times).toEqual([...times].sort((a, b) => b - a));
    // untouched requests have not been triaged
    for (const r of requests.filter((x) => x.status === 'received')) {
      expect(r).toMatchObject({ classification: null, priority: null, extracted: null, runIds: [] });
    }
  });

  it('walks a request from inbox to executed approval, with matching state on every object', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const request = (await desk.listRequests()).find((r) => r.subject === 'Q4 delivery schedule review')!;
    expect(request.status).toBe('received');

    const started = await desk.processRequest(request.id);
    expect(started).toMatchObject({ status: 'running', requestId: request.id, trigger: 'incoming_email' });
    await desk.whenIdle();

    const waiting = await desk.getRun(started.id);
    expect(waiting.status).toBe('awaiting_approval');
    expect(waiting.actions.map((a) => [a.tool, a.status])).toEqual([
      ['calendar.list_events', 'succeeded'],
      ['approval.request', 'succeeded'],
      ['calendar.create_event', 'awaiting_approval'],
      ['email.send', 'awaiting_approval'],
    ]);
    expect(await desk.getRequest(request.id)).toMatchObject({ status: 'awaiting_approval', classification: 'new_meeting', priority: 'normal' });

    const [approval] = await desk.listApprovals({ runId: started.id });
    expect(approval).toMatchObject({ status: 'pending', requestId: request.id, execution: { status: 'not_started' } });
    expect(approval.changes.map((c) => c.type)).toEqual(['calendar_create', 'email']);
    expect(waiting.actions.filter((a) => a.sideEffect).every((a) => a.approvalId === approval.id)).toBe(true);

    const decided = await desk.decideApproval(approval.id, { decision: 'approve', decidedBy: PRINCIPAL, note: 'Looks right.' });
    expect(decided).toMatchObject({ status: 'approved', decidedBy: PRINCIPAL, decisionNote: 'Looks right.', execution: { status: 'executing' } });
    await desk.whenIdle();

    const done = await desk.getRun(started.id);
    expect(done).toMatchObject({ status: 'completed', outcome: 'scheduled', usage: null });
    expect(done.actions.filter((a) => a.sideEffect).map((a) => a.status)).toEqual(['succeeded', 'succeeded']);
    expect(done.humanInterventions).toEqual([expect.objectContaining({ kind: 'approval', by: PRINCIPAL })]);
    expect((await desk.listApprovals({ runId: started.id }))[0].execution).toMatchObject({ status: 'executed', simulated: true });

    const finished = await desk.getRequest(request.id);
    expect(finished.status).toBe('completed');
    expect(finished.history.map((h) => h.event)).toEqual(['Received', 'Processing started', 'Classified', 'Approval requested', 'Approved', 'Finished']);
  });

  it('executes nothing after a rejection', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const approval = (await desk.listApprovals({ status: ['pending'] })).find((a) => a.title.includes('Sofia'))!;
    await desk.decideApproval(approval.id, { decision: 'reject', decidedBy: PRINCIPAL, note: 'Not this week.' });
    await desk.whenIdle();

    const run = await desk.getRun(approval.runId);
    expect(run).toMatchObject({ status: 'completed', outcome: 'declined' });
    expect(run.actions.filter((a) => a.sideEffect).map((a) => a.status)).toEqual(['rejected', 'rejected']);
    const after = (await desk.listApprovals({ runId: run.id }))[0];
    expect(after).toMatchObject({ status: 'rejected', decisionNote: 'Not this week.', execution: { status: 'not_started' } });
    expect((await desk.getRequest(approval.requestId!)).status).toBe('declined');
  });

  it('refuses a second decision on the same approval', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const [approval] = await desk.listApprovals({ status: ['pending'] });
    await desk.decideApproval(approval.id, { decision: 'approve', decidedBy: PRINCIPAL });
    await expect(desk.decideApproval(approval.id, { decision: 'reject', decidedBy: PRINCIPAL })).rejects.toMatchObject({ status: 409, code: 'already_decided' });
  });

  it('refuses to start a second run while one is in progress', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const waiting = (await desk.listRequests({ status: ['awaiting_approval'] }))[0];
    await expect(desk.processRequest(waiting.id)).rejects.toBeInstanceOf(ApiError);
  });

  it('shows a failed execution honestly: failed approval, escalated request, no confirmation sent', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const request = (await desk.listRequests({ status: ['escalated'] }))[0];
    expect(request.subject).toBe('Signing prep');
    const run = await desk.getRun(request.runIds[0]);
    expect(run).toMatchObject({ status: 'failed', outcome: 'escalated', error: { code: 'calendar_error' } });
    expect(run.actions.filter((a) => a.tool === 'calendar.create_event').map((a) => a.status)).toEqual(['failed', 'failed', 'failed']);
    expect(run.actions.find((a) => a.tool === 'email.send')!.status).toBe('skipped');
    expect((await desk.listApprovals({ runId: run.id }))[0].execution.status).toBe('failed');
  });

  it('answers a chat message that needs approval in two parts: the ask, then the result', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const conversation = await desk.createConversation();
    const { message, run } = await desk.sendMessage(conversation.id, 'Find 45 minutes this week for me, Omar and Rana to go over the Q1 hiring plan.');
    expect(message).toMatchObject({ role: 'user', runId: run.id });
    await desk.whenIdle();

    let thread = await desk.listMessages(conversation.id);
    expect(thread.map((m) => [m.role, m.status])).toEqual([['user', 'final'], ['assistant', 'final']]);
    expect(thread[1].runId).toBe(run.id);
    expect(thread[1].text).toContain('Approve below');

    const [approval] = await desk.listApprovals({ runId: run.id });
    expect(approval.conversationId).toBe(conversation.id);
    await desk.decideApproval(approval.id, { decision: 'approve', decidedBy: PRINCIPAL });
    await desk.whenIdle();

    thread = await desk.listMessages(conversation.id);
    expect(thread).toHaveLength(3);
    expect(thread[2]).toMatchObject({ role: 'assistant', status: 'final' });
    expect(thread[2].text).toContain('Wed 18 Nov');
    const [listed] = (await desk.listConversations()).filter((c) => c.id === conversation.id);
    expect(listed.title).toContain('Find 45 minutes');
    expect(listed.lastMessagePreview).toContain('Wed 18 Nov');
  });

  it('says so plainly when a chat message has no scripted answer', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const conversation = await desk.createConversation();
    await desk.sendMessage(conversation.id, 'Write me a poem about logistics.');
    await desk.whenIdle();
    const thread = await desk.listMessages(conversation.id);
    expect(thread[1].text).toContain('mock adapter');
    await expect(desk.sendMessage(conversation.id, '   ')).rejects.toMatchObject({ code: 'empty_message' });
  });

  it('returns copies, so callers cannot change stored state', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    const [first] = await desk.listRequests();
    first.subject = 'tampered';
    first.history.length = 0;
    const again = await desk.getRequest(first.id);
    expect(again.subject).not.toBe('tampered');
    expect(again.history.length).toBeGreaterThan(0);
  });

  it('notifies subscribers on change and stops after unsubscribe', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0 });
    await desk.whenIdle();
    const listener = vi.fn();
    const unsubscribe = desk.subscribe(listener);
    await desk.createConversation();
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    await desk.createConversation();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
