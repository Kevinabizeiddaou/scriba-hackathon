import { describe, expect, it, vi } from 'vitest';
import { HttpExecutiveDesk } from './httpAdapter';
import type { AgentRun } from './types';
import { getCase } from '../evaluation/fixtures';

const principal = { name: 'Layla Mansour', email: 'layla.mansour@cedarvale.example', timezone: 'Asia/Beirut' };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function setup(respond: (url: string, init: RequestInit) => Response | Promise<Response>, extra: Partial<ConstructorParameters<typeof HttpExecutiveDesk>[0]> = {}) {
  const fetchImpl = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => respond(String(url), init ?? {}));
  const api = new HttpExecutiveDesk({ baseUrl: 'http://backend.test/api/executive-desk', principal, fetchImpl: fetchImpl as unknown as typeof fetch, ...extra });
  return { api, fetchImpl };
}

const run = (over: Partial<AgentRun> = {}): AgentRun => ({
  id: 'run-1', trigger: 'evaluation', requestId: null, conversationId: null, status: 'running', outcome: null, triage: null, summary: null,
  assistantMessage: null, actions: [], approvalIds: [], startedAt: '2026-11-16T08:30:00+02:00', finishedAt: null, durationMs: null, usage: null,
  error: null, humanInterventions: [], ...over,
});

describe('HttpExecutiveDesk', () => {
  it('identifies itself as a live data source', () => {
    expect(setup(() => json([])).api.info).toMatchObject({ dataSource: 'live', baseUrl: 'http://backend.test/api/executive-desk', simulatedNow: null });
  });

  it('maps each method to its documented endpoint', async () => {
    const calls: string[] = [];
    const { api } = setup((url, init) => {
      calls.push(`${init.method} ${url.replace('http://backend.test/api/executive-desk', '')}`);
      if (url.includes('/messages') && init.method === 'POST') return json({ message: {}, run: run() });
      return json(url.endsWith('/runs/run-1') || init.method === 'POST' ? run() : []);
    });

    await api.listRequests({ status: ['received', 'awaiting_approval'] });
    await api.getRequest('req 1');
    await api.processRequest('req-1');
    await api.getRun('run-1');
    await api.listRuns({ requestId: 'req-1' });
    await api.listApprovals({ status: ['pending'], runId: 'run-1' });
    await api.decideApproval('apr-1', { decision: 'approve', decidedBy: 'Layla Mansour' });
    await api.listConversations();
    await api.createConversation();
    await api.listMessages('conv-1');
    await api.sendMessage('conv-1', 'hello');
    await api.startEvaluationRun({ caseId: 'EVAL-001', input: getCase('EVAL-001').input, context: getCase('EVAL-001').context, mode: 'sandbox' });

    expect(calls).toEqual([
      'GET /requests?status=received%2Cawaiting_approval',
      'GET /requests/req%201',
      'POST /requests/req-1/process',
      'GET /runs/run-1',
      'GET /runs?requestId=req-1',
      'GET /approvals?status=pending&runId=run-1',
      'POST /approvals/apr-1/decision',
      'GET /conversations',
      'POST /conversations',
      'GET /conversations/conv-1/messages',
      'POST /conversations/conv-1/messages',
      'POST /evaluation/runs',
    ]);
  });

  it('sends JSON bodies and a bearer token only when one is available', async () => {
    const seen: RequestInit[] = [];
    const withToken = setup((_url, init) => { seen.push(init); return json({}); }, { getToken: () => 'test-token' });
    await withToken.api.decideApproval('apr-1', { decision: 'reject', decidedBy: 'Layla Mansour', note: 'No.' });
    expect(seen[0].headers).toMatchObject({ Authorization: 'Bearer test-token', 'Content-Type': 'application/json' });
    expect(JSON.parse(String(seen[0].body))).toEqual({ decision: 'reject', decidedBy: 'Layla Mansour', note: 'No.' });

    const withoutToken = setup((_url, init) => { seen.push(init); return json([]); });
    await withoutToken.api.listConversations();
    expect(seen[1].headers).not.toHaveProperty('Authorization');
    expect(seen[1].body).toBeUndefined();
  });

  it('renames backend tool names to canonical ones and derives sideEffect itself', async () => {
    const backendRun = run({
      actions: [
        { id: 'a1', runId: 'run-1', sequence: 1, tool: 'gmail_send_message' as never, sideEffect: false, status: 'succeeded', summary: '', input: {}, output: null, startedAt: null, finishedAt: null, durationMs: null, approvalId: 'apr-1', error: null, simulated: true },
        { id: 'a2', runId: 'run-1', sequence: 2, tool: 'calendar.list_events', sideEffect: true, status: 'succeeded', summary: '', input: {}, output: null, startedAt: null, finishedAt: null, durationMs: null, approvalId: null, error: null, simulated: true },
      ],
    });
    const { api } = setup(() => json(backendRun), { toolAliases: { gmail_send_message: 'email.send' } });
    const result = await api.getRun('run-1');
    expect(result.actions.map((a) => [a.tool, a.sideEffect])).toEqual([['email.send', true], ['calendar.list_events', false]]);
  });

  it('stops on a tool name it cannot map, naming the tool', async () => {
    const backendRun = run({ actions: [{ id: 'a1', runId: 'run-1', sequence: 1, tool: 'mystery_tool' as never, sideEffect: true, status: 'succeeded', summary: '', input: {}, output: null, startedAt: null, finishedAt: null, durationMs: null, approvalId: null, error: null, simulated: true }] });
    const { api } = setup(() => json(backendRun));
    await expect(api.getRun('run-1')).rejects.toMatchObject({ code: 'unknown_tool', message: expect.stringContaining('mystery_tool') });
  });

  it('turns error responses, bad JSON and network failures into ApiError', async () => {
    const coded = setup(() => json({ error: { code: 'already_decided', message: 'This approval was already approved.' } }, 409));
    await expect(coded.api.decideApproval('apr-1', { decision: 'approve', decidedBy: 'x' })).rejects.toMatchObject({ status: 409, code: 'already_decided', message: 'This approval was already approved.' });

    const bare = setup(() => new Response('', { status: 502 }));
    await expect(bare.api.listRequests()).rejects.toMatchObject({ status: 502, code: 'http_502' });

    const html = setup(() => new Response('<html>oops</html>', { status: 200 }));
    await expect(html.api.listRequests()).rejects.toMatchObject({ code: 'invalid_response' });

    const down = setup(() => { throw new TypeError('fetch failed'); });
    await expect(down.api.listRequests()).rejects.toMatchObject({ status: null, code: 'network_error' });
  });

  it('polls subscribers and stops the timer when the last one leaves', () => {
    vi.useFakeTimers();
    try {
      const { api } = setup(() => json([]), { pollIntervalMs: 1_000 });
      const listener = vi.fn();
      const unsubscribe = api.subscribe(listener);
      vi.advanceTimersByTime(3_000);
      expect(listener).toHaveBeenCalledTimes(3);
      unsubscribe();
      vi.advanceTimersByTime(3_000);
      expect(listener).toHaveBeenCalledTimes(3);
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
