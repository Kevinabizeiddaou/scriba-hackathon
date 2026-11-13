// @vitest-environment node
/**
 * Integration tests: the HTTP adapter and the evaluation runner over a real socket.
 *
 * The server is the reference server (the contract served by the scripted mock) with faults
 * injected on demand: error statuses, delays, dropped connections, lost responses, bad JSON,
 * auth. Nothing here is stubbed at the fetch level, so what is tested is what a real backend
 * will see: actual URLs, headers, bodies, retries and timeouts.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, type ExecutiveDeskApi } from './client';
import { HttpExecutiveDesk, type HttpOptions } from './httpAdapter';
import { MockExecutiveDesk } from './mock/mockAdapter';
import { ReferenceServer, type ReferenceServerOptions } from './reference/referenceServer';
import { CONTRACT_HEADER, IDEMPOTENCY_HEADER, type AgentRun } from './types';
import { EVALUATION_CASES, SYNTHETIC_CASE_SET, getCase } from '../evaluation/fixtures';
import { runCase, runEvaluation } from '../evaluation/runner';

const PRINCIPAL = 'Layla Mansour';
let server: ReferenceServer | null = null;

afterEach(async () => {
  await server?.stop();
  server = null;
  vi.useRealTimers();
});

async function start(options: ReferenceServerOptions = {}, client: Partial<HttpOptions> = {}) {
  server = await ReferenceServer.start({ mock: { stepDelayMs: 0, seed: true }, ...options });
  const sleeps: number[] = [];
  const api = new HttpExecutiveDesk({
    baseUrl: server.baseUrl,
    sleep: async (ms) => {
      sleeps.push(ms);
    },
    ...client,
  });
  return { server, api, sleeps };
}

/** Replaces some methods of a desk and passes everything else through. */
function override(desk: ExecutiveDeskApi, methods: Partial<ExecutiveDeskApi>): ExecutiveDeskApi {
  return new Proxy(desk, {
    get(target, prop) {
      if (prop in methods) return (methods as Record<string | symbol, unknown>)[prop];
      const value = Reflect.get(target, prop, target);
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
}

async function until(api: HttpExecutiveDesk, runId: string, done: (run: AgentRun) => boolean): Promise<AgentRun> {
  for (let i = 0; i < 200; i += 1) {
    const run = await api.getRun(runId);
    if (done(run)) return run;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error('The run did not reach the expected state.');
}

const calls = (s: ReferenceServer, method: string, path: RegExp) => s.requests.filter((r) => r.method === method && path.test(r.path));

describe('handshake', () => {
  it('reads GET /meta first and takes the principal, version and data source from it', async () => {
    const { api, server: s } = await start();
    expect(api.info).toMatchObject({ dataSource: 'simulated', contractVersion: null, principal: { name: 'Not connected' } });

    await api.listConversations();

    expect(s.requests.map((r) => `${r.method} ${r.path}`)).toEqual(['GET /meta', 'GET /conversations']);
    expect(api.info).toMatchObject({
      name: 'executive-desk-reference-server',
      contractVersion: '1.0.0',
      baseUrl: s.baseUrl,
      principal: { name: PRINCIPAL, timezone: 'Asia/Beirut' },
      // The reference server is scripted, so it is simulated even though it was reached over HTTP.
      dataSource: 'simulated',
    });
    await api.listConversations();
    expect(calls(s, 'GET', /^\/meta$/)).toHaveLength(1); // cached
  });

  it('labels data live only when the backend says a real agent is behind it', async () => {
    const { api } = await start({ meta: { agent: 'real', service: 'scriba-backend' } });
    await api.getMeta();
    expect(api.info).toMatchObject({ dataSource: 'live', name: 'scriba-backend' });
  });

  it('sends the contract version on every request', async () => {
    const { api, server: s } = await start();
    await api.listRequests();
    expect(s.requests.every((r) => r.headers[CONTRACT_HEADER.toLowerCase()] === '1.0.0')).toBe(true);
  });

  it('refuses a backend on a different major version, and says which', async () => {
    const { api } = await start({ meta: { contractVersion: '2.3.0' } });
    await expect(api.listRequests()).rejects.toMatchObject({ code: 'unsupported_contract_version', message: expect.stringContaining('2.3.0') });
  });

  it('accepts a newer minor version of the same major', async () => {
    const { api } = await start({ meta: { contractVersion: '1.4.0' } });
    await expect(api.listRequests()).resolves.toHaveLength(12);
  });

  it('retries the handshake on the next call after it failed', async () => {
    const { api, server: s } = await start({}, { retry: { attempts: 1 } });
    s.inject({ path: /^\/meta$/, times: 1, kind: 'status', status: 503 });
    await expect(api.listRequests()).rejects.toMatchObject({ status: 503 });
    await expect(api.listRequests()).resolves.toHaveLength(12);
  });
});

describe('every endpoint, over HTTP', () => {
  it('walks a request from the inbox through approval to completion', async () => {
    const { api, server: s } = await start();

    const fresh = await api.listRequests({ status: ['received'] });
    expect(fresh).toHaveLength(4);
    const request = fresh.find((r) => r.subject === 'Q4 delivery schedule review')!;
    expect(await api.getRequest(request.id)).toMatchObject({ id: request.id, status: 'received' });

    const started = await api.processRequest(request.id);
    expect(started).toMatchObject({ requestId: request.id, trigger: 'incoming_email' });
    const waiting = await until(api, started.id, (run) => run.status === 'awaiting_approval');
    expect(waiting.actions.filter((a) => a.sideEffect).map((a) => [a.tool, a.status, typeof a.idempotencyKey])).toEqual([
      ['calendar.create_event', 'awaiting_approval', 'string'],
      ['email.send', 'awaiting_approval', 'string'],
    ]);

    const [approval] = await api.listApprovals({ runId: started.id, status: ['pending'] });
    expect(approval.changes.map((c) => c.tool)).toEqual(['calendar.create_event', 'email.send']);
    const decided = await api.decideApproval(approval.id, { decision: 'approve', decidedBy: PRINCIPAL, note: 'Go ahead.' });
    expect(decided).toMatchObject({ status: 'approved', decidedBy: PRINCIPAL, decisionNote: 'Go ahead.' });

    const done = await until(api, started.id, (run) => run.status === 'completed');
    expect(done.outcome).toBe('scheduled');
    expect(done.actions.filter((a) => a.sideEffect).every((a) => a.status === 'succeeded' && a.simulated)).toBe(true);
    expect((await api.listRuns({ requestId: request.id })).map((r) => r.id)).toEqual([started.id]);
    expect((await api.getRequest(request.id)).status).toBe('completed');

    const sent = s.requests.map((r) => `${r.method} ${r.path}`);
    expect(sent).toContain(`POST /requests/${request.id}/process`);
    expect(sent).toContain(`POST /approvals/${approval.id}/decision`);
    expect(s.requests.find((r) => r.path === '/requests' && r.query.status)?.query).toEqual({ status: 'received' });
    expect(s.requests.find((r) => r.path === '/approvals' && r.query.runId)?.query).toEqual({ runId: started.id, status: 'pending' });
  });

  it('holds a conversation', async () => {
    const { api } = await start();
    const [seeded] = await api.listConversations();
    expect((await api.listMessages(seeded.id)).map((m) => m.role)).toEqual(['user', 'assistant']);

    const conversation = await api.createConversation();
    const { message, run } = await api.sendMessage(conversation.id, 'Move my 1:1 with Omar to Wednesday at 11.');
    expect(message).toMatchObject({ role: 'user', conversationId: conversation.id, runId: run.id });
    const done = await until(api, run.id, (r) => r.status === 'completed');
    expect(done.assistantMessage).toContain('quarterly planning workshop');
    expect((await api.listMessages(conversation.id)).at(-1)).toMatchObject({ role: 'assistant', status: 'final' });
    expect((await api.listRuns({ conversationId: conversation.id })).map((r) => r.id)).toEqual([run.id]);
  });

  it('encodes ids in paths', async () => {
    const { api, server: s } = await start();
    await expect(api.getRequest('req 1/..')).rejects.toMatchObject({ status: 404 });
    expect(s.requests.at(-1)!.path).toBe('/requests/req%201%2F..');
  });
});

describe('errors', () => {
  it('maps the contract error body to ApiError, and does not retry client errors', async () => {
    const { api, server: s, sleeps } = await start();
    await expect(api.getRun('run-does-not-exist')).rejects.toMatchObject({ status: 404, code: 'not_found', retryable: false });
    expect(calls(s, 'GET', /^\/runs\//)).toHaveLength(1);

    const [approval] = await api.listApprovals({ status: ['pending'] });
    await api.decideApproval(approval.id, { decision: 'approve', decidedBy: PRINCIPAL });
    // Saying the same thing again is fine. Saying the opposite is a conflict.
    await expect(api.decideApproval(approval.id, { decision: 'approve', decidedBy: PRINCIPAL })).resolves.toMatchObject({ status: 'approved' });
    await expect(api.decideApproval(approval.id, { decision: 'reject', decidedBy: PRINCIPAL })).rejects.toMatchObject({ status: 409, code: 'already_decided' });
    expect(sleeps).toEqual([]);
  });

  it('rejects an invalid request body with 400', async () => {
    const { api, server: s } = await start();
    await api.getMeta();
    const response = await fetch(`${s.baseUrl}/approvals/apr-0001/decision`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision: 'maybe' }) });
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: { code: 'invalid_request', message: '"decision" must be "approve" or "reject".' } });
  });

  it('reports a response that is not JSON', async () => {
    const { api, server: s } = await start();
    await api.getMeta();
    s.inject({ path: /^\/requests$/, times: 1, kind: 'garbage', status: 200 });
    await expect(api.listRequests()).rejects.toMatchObject({ code: 'invalid_response', status: 200 });
  });

  it('reports an unreachable backend as a network error after retrying', async () => {
    const { api, server: s, sleeps } = await start();
    await api.getMeta();
    await s.stop();
    server = null;
    await expect(api.listRequests()).rejects.toMatchObject({ code: 'network_error', status: null, retryable: true });
    expect(sleeps).toEqual([250, 500]);
  });
});

describe('response validation', () => {
  it('names the field when a run does not match the contract', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0, seed: true });
    const broken = override(desk, {
      getRun: async (id) => ({ ...(await desk.getRun(id)), status: 'done' as never, startedAt: '2026-11-16 08:30' }),
    });
    const { api } = await start({ desk: broken });
    const [run] = await api.listRuns();
    const error = await api.getRun(run.id).catch((e: unknown) => e as ApiError);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: 'contract_violation', retryable: false });
    expect((error as ApiError).message).toContain('run.status: expected one of queued | running | awaiting_approval | completed | failed | cancelled, got "done"');
    expect((error as ApiError).message).toContain('run.startedAt: expected an RFC 3339 timestamp with an offset');
  });

  it('rejects a nullable field that was left out, and a side effect with no idempotency key', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0, seed: true });
    const sloppy = override(desk, {
      getRun: async (id) => {
        const run = (await desk.getRun(id)) as unknown as Record<string, unknown>;
        delete run.usage;
        for (const action of run.actions as { idempotencyKey: unknown }[]) action.idempotencyKey = null;
        return run as unknown as AgentRun;
      },
    });
    const { api } = await start({ desk: sloppy });
    const request = (await api.listRequests({ status: ['completed'] })).find((r) => r.runIds.length > 0)!;
    const error = (await api.getRun(request.runIds[0]).catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe('contract_violation');
    expect((error.details as { problems: string[] }).problems).toEqual(
      expect.arrayContaining(['run.usage: missing (nullable fields must be present and set to null)', expect.stringContaining('idempotencyKey: a side-effect action needs an idempotency key')]),
    );
  });

  it('can be switched off', async () => {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0, seed: true });
    const broken = override(desk, { listConversations: async () => [{ id: 'c1' } as never] });
    const { api } = await start({ desk: broken }, { validateResponses: false });
    await expect(api.listConversations()).resolves.toEqual([{ id: 'c1' }]);
  });
});

describe('tool aliases', () => {
  const BACKEND_NAMES: Record<string, string> = { 'email.send': 'gmail_send_message', 'calendar.create_event': 'gcal_insert_event' };
  const rename = (tool: string) => BACKEND_NAMES[tool] ?? tool;

  function backendWithItsOwnToolNames() {
    const desk = new MockExecutiveDesk({ stepDelayMs: 0, seed: true });
    return override(desk, {
      getRun: async (id) => {
        const run = await desk.getRun(id);
        return { ...run, actions: run.actions.map((a) => ({ ...a, tool: rename(a.tool) as never })) };
      },
      listApprovals: async (filter) => (await desk.listApprovals(filter)).map((a) => ({ ...a, changes: a.changes.map((c) => ({ ...c, tool: rename(c.tool) as never })) })),
    });
  }

  it('maps backend tool names to canonical ones in runs and in approvals', async () => {
    const { api } = await start({ desk: backendWithItsOwnToolNames() }, { toolAliases: { gmail_send_message: 'email.send', gcal_insert_event: 'calendar.create_event' } });
    const [approval] = await api.listApprovals({ status: ['pending'] });
    expect(approval.changes.every((c) => ['email.send', 'calendar.create_event', 'calendar.update_event'].includes(c.tool))).toBe(true);
    const run = await api.getRun(approval.runId);
    expect(run.actions.filter((a) => a.sideEffect).map((a) => a.tool)).toEqual(approval.changes.map((c) => c.tool));
  });

  it('stops on a name it cannot map, naming the tool, for runs and for approvals', async () => {
    const { api } = await start({ desk: backendWithItsOwnToolNames() });
    await expect(api.listApprovals({ status: ['pending'] })).rejects.toMatchObject({ code: 'unknown_tool', message: expect.stringMatching(/gmail_send_message|gcal_insert_event/) });
    const pendingRun = (await new MockExecutiveDesk({ stepDelayMs: 0, seed: true }).listRuns()).find((r) => r.status === 'awaiting_approval')!;
    await expect(api.getRun(pendingRun.id)).rejects.toMatchObject({ code: 'unknown_tool' });
  });
});

describe('authentication', () => {
  it('sends the bearer token in the Authorization header and never in the URL', async () => {
    const { api, server: s } = await start({ token: 'test-token-1' }, { getToken: () => 'test-token-1' });
    await api.listRequests({ status: ['received'] });
    expect(s.requests.every((r) => r.headers.authorization === 'Bearer test-token-1')).toBe(true);
    expect(s.requests.some((r) => JSON.stringify(r.query).includes('test-token-1') || r.path.includes('test-token-1'))).toBe(false);
  });

  it('reports 401 as unauthenticated without retrying when there is no token', async () => {
    const { api, server: s, sleeps } = await start({ token: 'test-token-1' });
    await expect(api.listRequests()).rejects.toMatchObject({ status: 401, code: 'unauthenticated', retryable: false });
    expect(s.requests).toHaveLength(1);
    expect(sleeps).toEqual([]);
  });

  it('refreshes the token once on 401 and repeats the request', async () => {
    const refresh = vi.fn(async () => 'test-token-2');
    const { api, server: s } = await start({ token: 'test-token-2' }, { getToken: () => 'expired-token', onUnauthorized: refresh });
    await expect(api.getMeta()).resolves.toMatchObject({ contractVersion: '1.0.0' });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(s.requests.map((r) => r.headers.authorization)).toEqual(['Bearer expired-token', 'Bearer test-token-2']);
  });

  it('gives up when the refresh has no new token, or the new token is rejected too', async () => {
    const none = await start({ token: 'right' }, { getToken: () => 'wrong', onUnauthorized: async () => null });
    await expect(none.api.getMeta()).rejects.toMatchObject({ status: 401, code: 'unauthenticated' });
    await none.server.stop();

    const refresh = vi.fn(async () => 'still-wrong');
    const again = await start({ token: 'right' }, { getToken: () => 'wrong', onUnauthorized: refresh });
    await expect(again.api.getMeta()).rejects.toMatchObject({ status: 401 });
    expect(refresh).toHaveBeenCalledTimes(1); // no refresh loop
    expect(again.server.requests).toHaveLength(2);
  });
});

describe('retries and timeouts', () => {
  it('retries a GET through transient failures with growing pauses', async () => {
    const { api, server: s, sleeps } = await start();
    await api.getMeta();
    s.inject({ method: 'GET', path: /^\/requests$/, times: 2, kind: 'status', status: 503 });
    await expect(api.listRequests()).resolves.toHaveLength(12);
    expect(calls(s, 'GET', /^\/requests$/)).toHaveLength(3);
    expect(sleeps).toEqual([250, 500]);
  });

  it('gives up after the configured number of tries and says the failure is retryable', async () => {
    const { api, server: s } = await start({}, { retry: { attempts: 2 } });
    await api.getMeta();
    s.inject({ path: /^\/requests$/, times: 5, kind: 'status', status: 502 });
    await expect(api.listRequests()).rejects.toMatchObject({ status: 502, code: 'upstream_unavailable', retryable: true });
    expect(calls(s, 'GET', /^\/requests$/)).toHaveLength(2);
  });

  it('waits as long as Retry-After says, up to its own limit', async () => {
    const { api, server: s, sleeps } = await start();
    await api.getMeta();
    s.inject({ path: /^\/requests$/, times: 1, kind: 'status', status: 429, headers: { 'Retry-After': '1' }, body: { error: { code: 'rate_limited', message: 'Slow down.' } } });
    s.inject({ path: /^\/requests$/, times: 1, kind: 'status', status: 429, headers: { 'Retry-After': '120' } });
    await expect(api.listRequests()).resolves.toHaveLength(12);
    expect(sleeps).toEqual([1_000, 4_000]);
  });

  it('times out a request that hangs, and retries it', async () => {
    const { api, server: s } = await start({}, { timeoutMs: 60, retry: { attempts: 2 } });
    await api.getMeta();
    s.inject({ path: /^\/requests$/, times: 1, kind: 'delay', delayMs: 400 });
    await expect(api.listRequests()).resolves.toHaveLength(12); // second try answers at once
    expect(calls(s, 'GET', /^\/requests$/)).toHaveLength(2);

    s.inject({ path: /^\/conversations$/, times: 2, kind: 'delay', delayMs: 400 });
    const started = Date.now();
    await expect(api.listConversations()).rejects.toMatchObject({ code: 'timeout', status: null, retryable: true });
    expect(Date.now() - started).toBeLessThan(380); // two 60 ms timeouts, not two 400 ms waits
  });
});

describe('idempotency', () => {
  it('puts a fresh Idempotency-Key on every POST and none on a GET', async () => {
    const { api, server: s } = await start();
    const conversation = await api.createConversation();
    await api.sendMessage(conversation.id, 'What is waiting for my approval?');
    await api.listConversations();
    const keys = s.requests.filter((r) => r.method === 'POST').map((r) => r.headers[IDEMPOTENCY_HEADER.toLowerCase()]);
    expect(keys).toHaveLength(2);
    expect(new Set(keys).size).toBe(2);
    expect(keys.every((k) => /^[0-9a-f-]{36}$/.test(k))).toBe(true);
    expect(s.requests.filter((r) => r.method === 'GET').every((r) => !(IDEMPOTENCY_HEADER.toLowerCase() in r.headers))).toBe(true);
  });

  it('decides an approval exactly once when the first answer is lost on the way back', async () => {
    const { api, server: s } = await start();
    const [approval] = await api.listApprovals({ status: ['pending'] });
    s.inject({ method: 'POST', path: /\/decision$/, times: 1, kind: 'lose_response' });

    const decided = await api.decideApproval(approval.id, { decision: 'approve', decidedBy: PRINCIPAL });

    expect(decided.status).toBe('approved');
    const posts = calls(s, 'POST', /\/decision$/);
    expect(posts).toHaveLength(2); // the lost one, and the retry
    expect(posts[0].headers[IDEMPOTENCY_HEADER.toLowerCase()]).toBe(posts[1].headers[IDEMPOTENCY_HEADER.toLowerCase()]);
    const run = await until(api, approval.runId, (r) => r.status === 'completed');
    expect(run.humanInterventions).toHaveLength(1); // one decision recorded, not two
    expect(run.actions.filter((a) => a.sideEffect).map((a) => a.status)).toEqual(approval.changes.map(() => 'succeeded'));
  });

  it('starts one run, not two, when a chat message has to be sent again', async () => {
    const { api, server: s } = await start();
    const conversation = await api.createConversation();
    s.inject({ method: 'POST', path: /\/messages$/, times: 1, kind: 'lose_response' });
    const { run } = await api.sendMessage(conversation.id, "What's on my calendar today?");
    expect(calls(s, 'POST', /\/messages$/)).toHaveLength(2);
    expect((await api.listRuns({ conversationId: conversation.id })).map((r) => r.id)).toEqual([run.id]);
    expect((await api.listMessages(conversation.id)).filter((m) => m.role === 'user')).toHaveLength(1);
  });

  it('refuses a key that is reused for a different request', async () => {
    const { server: s } = await start();
    const post = (body: unknown) =>
      fetch(`${s.baseUrl}/conversations`, { method: 'POST', headers: { 'Content-Type': 'application/json', [IDEMPOTENCY_HEADER]: 'key-1' }, body: JSON.stringify(body) });
    const first = await post({});
    const replay = await post({});
    expect(first.status).toBe(201);
    expect(replay.status).toBe(201);
    expect(replay.headers.get('Idempotent-Replay')).toBe('true');
    expect(await replay.json()).toEqual(await first.json());
    const clash = await post({ different: true });
    expect(clash.status).toBe(422);
    expect((await clash.json()).error.code).toBe('idempotency_key_reused');
  });
});

describe('change notification', () => {
  it('tells subscribers straight after a POST, without waiting for the poll', async () => {
    const { api } = await start({}, { pollIntervalMs: 60_000 });
    await api.getMeta();
    const listener = vi.fn();
    const unsubscribe = api.subscribe(listener);
    await api.createConversation();
    expect(listener).toHaveBeenCalledTimes(1);
    await api.listConversations(); // a GET changes nothing
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it('polls on a timer and stops when the last subscriber leaves', async () => {
    vi.useFakeTimers();
    const api = new HttpExecutiveDesk({ baseUrl: 'http://127.0.0.1:1', pollIntervalMs: 1_000 });
    const listener = vi.fn();
    const unsubscribe = api.subscribe(listener);
    vi.advanceTimersByTime(3_000);
    expect(listener).toHaveBeenCalledTimes(3);
    unsubscribe();
    vi.advanceTimersByTime(3_000);
    expect(listener).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('browser access', () => {
  it('answers a CORS preflight and exposes the contract header', async () => {
    const { server: s } = await start({ allowOrigin: 'http://localhost:5183' });
    const preflight = await fetch(`${s.baseUrl}/approvals/apr-1/decision`, { method: 'OPTIONS', headers: { Origin: 'http://localhost:5183', 'Access-Control-Request-Method': 'POST' } });
    expect(preflight.status).toBe(204);
    expect(preflight.headers.get('Access-Control-Allow-Origin')).toBe('http://localhost:5183');
    expect(preflight.headers.get('Access-Control-Allow-Headers')).toContain(IDEMPOTENCY_HEADER);
    const meta = await fetch(`${s.baseUrl}/meta`);
    expect(meta.headers.get(CONTRACT_HEADER)).toBe('1.0.0');
  });
});

describe('evaluation runner over HTTP', () => {
  it('runs all twenty cases through the HTTP adapter and labels the result as simulated', async () => {
    const { api, server: s } = await start({ mock: { stepDelayMs: 0, seed: false } });
    const report = await runEvaluation(api, EVALUATION_CASES, { pollIntervalMs: 2, caseSet: SYNTHETIC_CASE_SET });

    const notPassing = report.results.filter((r) => r.verdict !== 'pass').map((r) => `${r.caseId}: ${r.verdict} ${r.checks.filter((c) => !c.passed).map((c) => `${c.id} (${c.actual})`).join('; ')} ${r.errors.map((e) => e.message).join('; ')}`);
    expect(notPassing).toEqual([]);
    expect(report.results).toHaveLength(20);
    expect(report.target).toEqual({ name: 'executive-desk-reference-server', dataSource: 'simulated', baseUrl: s.baseUrl, contractVersion: '1.0.0', sandbox: true });
    expect(report).toMatchObject({ format: 'executive-desk.evaluation-report/1', contractVersion: '1.0.0', caseSet: { id: 'synthetic-v2', provenance: 'synthetic', caseCount: 20 } });
    expect(calls(s, 'POST', /^\/evaluation\/runs$/)).toHaveLength(20);
    // The case travels in the request body exactly as the fixture defines it.
    expect(calls(s, 'POST', /^\/evaluation\/runs$/)[0].body).toEqual({ caseId: 'EVAL-001', input: getCase('EVAL-001').input, context: getCase('EVAL-001').context, mode: 'sandbox' });
  }, 30_000);

  it('gets the same verdicts when the network is unreliable', async () => {
    const { api, server: s, sleeps } = await start({ mock: { stepDelayMs: 0, seed: false } });
    await api.getMeta();
    // Fewer failures in a row than the adapter has tries (3), so each call still gets through.
    s.inject({ method: 'GET', path: /^\/runs\//, times: 2, kind: 'status', status: 503 });
    s.inject({ method: 'POST', path: /\/decision$/, times: 1, kind: 'lose_response' });
    s.inject({ method: 'POST', path: /^\/evaluation\/runs$/, times: 1, kind: 'drop' });
    s.inject({ method: 'GET', path: /^\/approvals$/, times: 1, kind: 'status', status: 504 });

    const cases = EVALUATION_CASES.filter((c) => ['EVAL-001', 'EVAL-003', 'EVAL-017'].includes(c.id));
    const report = await runEvaluation(api, cases, { pollIntervalMs: 2 });

    expect(report.results.map((r) => [r.caseId, r.verdict])).toEqual([['EVAL-001', 'pass'], ['EVAL-003', 'pass'], ['EVAL-017', 'pass']]);
    expect(sleeps.length).toBeGreaterThanOrEqual(5); // 2 + 1 + 1 + 1 retried requests
    expect(calls(s, 'POST', /^\/evaluation\/runs$/)).toHaveLength(4); // three cases, one resent
    expect(report.results[0].human.mandatoryApprovals).toBe(1);
  }, 30_000);

  it('records a case as an error, with the reason, when the backend stays down', async () => {
    const { api, server: s } = await start({ mock: { stepDelayMs: 0, seed: false } }, { retry: { attempts: 2 } });
    await api.getMeta();
    s.inject({ path: /^\/evaluation\/runs$/, times: 10, kind: 'status', status: 503, body: { error: { code: 'upstream_unavailable', message: 'The agent service is restarting.' } } });
    const result = await runCase(api, getCase('EVAL-001'), { pollIntervalMs: 2 });
    expect(result).toMatchObject({ verdict: 'error', run: null, dataSource: 'simulated' });
    expect(result.errors).toEqual([{ source: 'backend', code: 'upstream_unavailable', message: 'The agent service is restarting.' }]);
  });

  it('will not run cases against a backend that is not a sandbox', async () => {
    const { api, server: s } = await start({ meta: { agent: 'real', sandbox: false } });
    const result = await runCase(api, getCase('EVAL-001'), { pollIntervalMs: 2 });
    expect(result.errors[0]).toMatchObject({ source: 'harness', code: 'not_sandbox' });
    expect(calls(s, 'POST', /^\/evaluation\/runs$/)).toHaveLength(0);
  });
});
