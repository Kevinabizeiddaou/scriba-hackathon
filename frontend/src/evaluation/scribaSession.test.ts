import { describe, expect, it, vi } from 'vitest';
import { DESK_ORIGIN, ScribaSessionError, cookieHeaderFrom, probeEvaluationSupport, signInToScriba } from './scribaSession';

const response = (status: number, setCookie: string[] = [], body: unknown = {}) => {
  const headers = new Headers({ 'content-type': 'application/json' });
  for (const cookie of setCookie) headers.append('set-cookie', cookie);
  return new Response(JSON.stringify(body), { status, headers });
};

describe('Scriba session for the evaluation CLI', () => {
  it('signs in with the Desk origin and keeps only the cookie pairs', async () => {
    const fetchImpl = vi.fn(async () => response(200, ['scriba_session=abc123; Path=/; HttpOnly; SameSite=Lax', 'csrf=xyz; Path=/']));
    const cookie = await signInToScriba({ apiRoot: 'http://localhost:8788/', email: 'someone@example.test', password: 'not-a-real-password', fetchImpl });
    expect(cookie).toBe('scriba_session=abc123; csrf=xyz');
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://localhost:8788/auth/signin');
    expect((init.headers as Record<string, string>).Origin).toBe(DESK_ORIGIN);
    expect(init.method).toBe('POST');
  });

  it('reports a wrong password as a 401 and does not try again', async () => {
    const fetchImpl = vi.fn(async () => response(401));
    await expect(signInToScriba({ apiRoot: 'http://localhost:8788', email: 'a@example.test', password: 'x', fetchImpl })).rejects.toMatchObject({ name: 'ScribaSessionError', status: 401 });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not accept a sign-in that set no cookie', async () => {
    await expect(signInToScriba({ apiRoot: 'http://localhost:8788', email: 'a@example.test', password: 'x', fetchImpl: async () => response(200) })).rejects.toBeInstanceOf(ScribaSessionError);
  });

  it('reads several Set-Cookie headers and ignores an emptied cookie', () => {
    expect(cookieHeaderFrom(response(200, ['a=1; Path=/', 'gone=; Max-Age=0', 'b=2; HttpOnly']))).toBe('a=1; b=2');
  });

  it('says a backend without evaluation routes cannot be evaluated, after reading only', async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push(`${init?.method} ${String(url)}`);
      return String(url).endsWith('/desk/health') ? response(200, [], { ok: true }) : response(404);
    }) as unknown as typeof fetch;
    const support = await probeEvaluationSupport({ apiRoot: 'http://localhost:8788', cookie: 'scriba_session=abc', fetchImpl });
    expect(support).toMatchObject({ supported: false, reason: 'no_routes' });
    expect(calls).toEqual(['GET http://localhost:8788/desk/health', 'GET http://localhost:8788/desk/eval/v1/meta']);
  });

  it('tells apart no session, no overlay and an unreachable backend', async () => {
    const at = (status: number) => (async () => response(status)) as unknown as typeof fetch;
    expect(await probeEvaluationSupport({ apiRoot: 'http://x.test', cookie: null, fetchImpl: at(401) })).toMatchObject({ supported: false, reason: 'unauthenticated' });
    expect(await probeEvaluationSupport({ apiRoot: 'http://x.test', cookie: 'c=1', fetchImpl: at(404) })).toMatchObject({ supported: false, reason: 'no_overlay' });
    const down = (async () => {
      throw new Error('connect ECONNREFUSED');
    }) as unknown as typeof fetch;
    expect(await probeEvaluationSupport({ apiRoot: 'http://x.test', cookie: 'c=1', fetchImpl: down })).toMatchObject({ supported: false, reason: 'unreachable' });
    expect(await probeEvaluationSupport({ apiRoot: 'http://x.test', cookie: 'c=1', fetchImpl: at(200) })).toEqual({ supported: true });
  });
});
