/**
 * Chooses the API implementation. This is the only switch between mock and real data.
 *
 *   VITE_API_MODE=mock   (default)  in-memory scripted adapter, no network
 *   VITE_API_MODE=http              Role 1's backend at VITE_API_BASE_URL
 */
import type { ExecutiveDeskApi } from './client';
import { HttpExecutiveDesk } from './httpAdapter';
import { MockExecutiveDesk } from './mock/mockAdapter';
import { PRINCIPAL } from '../evaluation/fixtures/world';

let instance: ExecutiveDeskApi | null = null;

export function createApi(env: Record<string, string | undefined>): ExecutiveDeskApi {
  if (env.VITE_API_MODE === 'http') {
    if (!env.VITE_API_BASE_URL) throw new Error('VITE_API_MODE=http needs VITE_API_BASE_URL.');
    // The principal, the contract version and whether the agent is real all come from GET /meta.
    // Authentication is Scriba's own session cookie, sent by the browser. Nothing is stored here.
    return new HttpExecutiveDesk({ baseUrl: env.VITE_API_BASE_URL.replace(/\/$/, ''), credentials: 'include' });
  }
  return new MockExecutiveDesk({ stepDelayMs: 700, seed: true });
}

export function getApi(): ExecutiveDeskApi {
  if (!instance) instance = createApi(import.meta.env as Record<string, string | undefined>);
  return instance;
}

/** For tests: swap in a specific implementation. */
export function setApi(api: ExecutiveDeskApi | null): void {
  instance = api;
}

export { PRINCIPAL as MOCK_PRINCIPAL };
export type { ExecutiveDeskApi } from './client';
