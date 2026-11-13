/**
 * Chooses the API implementation. This is the only switch between mock and real data.
 *
 *   VITE_API_MODE=mock   (default)  in-memory scripted adapter, no network
 *   VITE_API_MODE=http              a backend at VITE_API_BASE_URL, reached with Scriba's session cookie
 */
import type { ExecutiveDeskApi } from './client';
import { HttpExecutiveDesk } from './httpAdapter';
import { MockExecutiveDesk } from './mock/mockAdapter';
import { MockWorkspace } from './mock/workspaceMock';
import { WaitingWorkspace, type WorkspaceApi } from './workspace';
import { PRINCIPAL } from '../evaluation/fixtures/world';

let instance: ExecutiveDeskApi | null = null;
let workspace: WorkspaceApi | null = null;

export function createApi(env: Record<string, string | undefined>): ExecutiveDeskApi {
  if (env.VITE_API_MODE === 'http') {
    if (!env.VITE_API_BASE_URL) throw new Error('VITE_API_MODE=http needs VITE_API_BASE_URL.');
    // The principal, the contract version and whether the agent is real all come from GET /meta.
    // Authentication is Scriba's own session cookie, sent by the browser. Nothing is stored here.
    return new HttpExecutiveDesk({ baseUrl: env.VITE_API_BASE_URL.replace(/[/]$/, ''), credentials: 'include' });
  }
  return new MockExecutiveDesk({ stepDelayMs: 700, seed: true });
}

export function getApi(): ExecutiveDeskApi {
  if (!instance) instance = createApi(import.meta.env as Record<string, string | undefined>);
  return instance;
}

/**
 * Mail, calendar, tasks, follow-ups and activity for the workspace screens.
 * Only the mock can supply these today. Against a real backend the screens are told to wait:
 * no endpoint for them has been agreed, and nothing is invented in the meantime.
 */
export function getWorkspace(): WorkspaceApi {
  if (!workspace) {
    const api = getApi();
    workspace = api instanceof MockExecutiveDesk ? new MockWorkspace(api) : new WaitingWorkspace();
  }
  return workspace;
}

/** For tests: swap in a specific implementation. */
export function setApi(api: ExecutiveDeskApi | null): void {
  instance = api;
  workspace = null;
}

export { PRINCIPAL as MOCK_PRINCIPAL };
export type { ExecutiveDeskApi } from './client';
