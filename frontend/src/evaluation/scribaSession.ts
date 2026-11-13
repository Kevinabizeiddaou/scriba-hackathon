/**
 * Scriba session handling for the evaluation CLI.
 *
 * Scriba authenticates with an HttpOnly session cookie and accepts credentialed requests only
 * from the Desk's origin. A browser does both on its own. A command-line client has to sign in
 * with POST /auth/signin, keep the cookie the server sets, and send the Desk origin itself.
 *
 * Nothing here stores a credential or prints a cookie: the caller reads the email and password
 * from the environment, and the cookie lives in memory for the length of the run.
 */

/** The origin Scriba trusts for the Desk (docs/BACKEND_CONTRACT.md, rule 1). */
export const DESK_ORIGIN = 'http://localhost:5173';

/** Where a Scriba backend with evaluation support would mount the contract-v1 routes. */
export const EVALUATION_BASE_PATH = '/desk/eval/v1';

export class ScribaSessionError extends Error {
  constructor(message: string, readonly status: number | null) {
    super(message);
    this.name = 'ScribaSessionError';
  }
}

type Fetch = typeof fetch;

/** Name=value pairs from the Set-Cookie headers of a response, joined for a Cookie header. */
export function cookieHeaderFrom(response: Pick<Response, 'headers'>): string {
  const headers = response.headers as Headers & { getSetCookie?: () => string[] };
  const raw = typeof headers.getSetCookie === 'function' ? headers.getSetCookie() : (headers.get('set-cookie') ?? '').split(/,(?=\s*[A-Za-z0-9_.-]+=)/);
  return raw
    .map((line) => line.split(';')[0].trim())
    .filter((pair) => pair.includes('=') && !pair.endsWith('='))
    .join('; ');
}

/**
 * Signs in to Scriba and returns the value for the Cookie header.
 * A wrong password is a 401 and is reported as such; it is never retried.
 */
export async function signInToScriba(options: { apiRoot: string; email: string; password: string; origin?: string; fetchImpl?: Fetch }): Promise<string> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const root = options.apiRoot.replace(/\/+$/, '');
  let response: Response;
  try {
    response = await fetchImpl(`${root}/auth/signin`, {
      method: 'POST',
      redirect: 'manual',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', Origin: options.origin ?? DESK_ORIGIN },
      body: JSON.stringify({ email: options.email, password: options.password }),
    });
  } catch (cause) {
    throw new ScribaSessionError(`Could not reach Scriba at ${root}: ${cause instanceof Error ? cause.message : String(cause)}`, null);
  }
  if (response.status === 401) throw new ScribaSessionError('Scriba refused the sign-in: wrong email or password.', 401);
  if (!response.ok) throw new ScribaSessionError(`Scriba sign-in failed with HTTP ${response.status}.`, response.status);
  const cookie = cookieHeaderFrom(response);
  if (!cookie) throw new ScribaSessionError('Scriba accepted the sign-in but set no session cookie.', response.status);
  return cookie;
}

export type EvaluationSupport =
  | { supported: true }
  /** no_overlay: plain Scriba. no_routes: the Desk overlay is there but has no evaluation routes. */
  | { supported: false; reason: 'no_overlay' | 'no_routes' | 'unauthenticated' | 'unreachable'; detail: string };

/**
 * Asks a Scriba backend whether it can be evaluated, before any case is sent to it.
 * It only reads: GET /desk/health and GET <evaluation base>/meta.
 */
export async function probeEvaluationSupport(options: { apiRoot: string; cookie: string | null; origin?: string; basePath?: string; fetchImpl?: Fetch }): Promise<EvaluationSupport> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const root = options.apiRoot.replace(/\/+$/, '');
  const headers: Record<string, string> = { Accept: 'application/json', Origin: options.origin ?? DESK_ORIGIN };
  if (options.cookie) headers.Cookie = options.cookie;
  const get = (path: string) => fetchImpl(`${root}${path}`, { method: 'GET', headers, redirect: 'manual' });
  try {
    const health = await get('/desk/health');
    if (health.status === 401) return { supported: false, reason: 'unauthenticated', detail: 'Scriba answered 401: there is no valid session. Sign in (EVAL_EMAIL and EVAL_PASSWORD with --signin) or pass a session with --cookie-env.' };
    if (health.status === 404) return { supported: false, reason: 'no_overlay', detail: 'This backend is Scriba without the Desk overlay (GET /desk/health is 404). Start it as described in backend/README.md.' };
    const meta = await get(`${options.basePath ?? EVALUATION_BASE_PATH}/meta`);
    if (meta.status === 404) {
      return {
        supported: false,
        reason: 'no_routes',
        detail: `This backend has no sandbox evaluation routes (GET ${options.basePath ?? EVALUATION_BASE_PATH}/meta is 404), so the cases cannot run against it. Nothing was sent. The routes it needs are in docs/frontend/LIVE_INTEGRATION.md.`,
      };
    }
    return { supported: true };
  } catch (cause) {
    return { supported: false, reason: 'unreachable', detail: `Could not reach Scriba at ${root}: ${cause instanceof Error ? cause.message : String(cause)}` };
  }
}
