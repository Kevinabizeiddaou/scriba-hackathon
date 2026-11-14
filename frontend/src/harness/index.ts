/**
 * Holds the API implementation the screens talk to.
 *
 * Demo mode (lib/mode.ts) uses the in-memory mock created here. In live mode the session gate
 * (src/live/LiveApp.tsx) installs Scriba-backed implementations with setApi() once the user is
 * signed in; nothing here ever substitutes mock data for a live backend.
 *
 * VITE_API_MODE=http still selects the predecessor's contract-v1 HTTP adapter, which is what the
 * evaluation CLI and the reference server speak. No Scriba backend serves that contract today.
 */
import type { ExecutiveDeskApi } from './client';
import { HttpExecutiveDesk } from './httpAdapter';
import type { MockExecutiveDesk } from './mock/mockAdapter';
import { WaitingWorkspace, type WorkspaceApi } from './workspace';
import { deskModeFrom } from '../lib/mode';

let instance: ExecutiveDeskApi | null = null;
let workspace: WorkspaceApi | null = null;

/**
 * The in-memory mock, when it has been loaded. It is not imported here: the live application
 * never needs it, so it stays out of the live bundle. Demo mode, the evaluation screen and the
 * tests load src/harness/mock/runtime.ts, which registers it.
 */
export interface MockRuntime {
  /** The demo data source: seeded, with scripted delays. */
  createDemo(): ExecutiveDeskApi;
  /** The mock workspace for an API that is the mock; null for any other implementation. */
  workspaceFor(api: ExecutiveDeskApi): WorkspaceApi | null;
  /** A fresh scripted reference agent for the evaluation harness. */
  createReferenceAgent(): MockExecutiveDesk;
}
let mockRuntime: MockRuntime | null = null;

export function installMockRuntime(runtime: MockRuntime): void {
  mockRuntime = runtime;
}

export function createApi(env: Record<string, string | undefined>): ExecutiveDeskApi {
  if (env.VITE_API_MODE === 'http') {
    if (!env.VITE_API_BASE_URL) throw new Error('VITE_API_MODE=http needs VITE_API_BASE_URL.');
    // The principal, the contract version and whether the agent is real all come from GET /meta.
    // Authentication is Scriba's own session cookie, sent by the browser. Nothing is stored here.
    return new HttpExecutiveDesk({ baseUrl: env.VITE_API_BASE_URL.replace(/[/]$/, ''), credentials: 'include' });
  }
  if (deskModeFrom(env) === 'live') {
    throw new Error('The live Desk is installed by the session gate after sign-in; it is never created implicitly.');
  }
  if (!mockRuntime) throw new Error('Demo mode needs the mock data layer (src/harness/mock/runtime.ts), which has not been loaded.');
  return mockRuntime.createDemo();
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
    workspace = mockRuntime?.workspaceFor(api) ?? new WaitingWorkspace();
  }
  return workspace;
}

/** Installs an implementation: the live session gate, and tests. A workspace may be supplied with it. */
export function setApi(api: ExecutiveDeskApi | null, withWorkspace: WorkspaceApi | null = null): void {
  instance = api;
  workspace = withWorkspace;
}

let evaluationApi: MockExecutiveDesk | null = null;
/**
 * The scripted reference agent the Evaluation screen runs when the Desk is live. The real
 * backend has no sandbox evaluation route, so the harness is exercised against the mock and
 * every result is labelled as a reference result, never as the real agent's.
 */
export function getReferenceAgent(): MockExecutiveDesk {
  if (!mockRuntime) throw new Error('The reference agent needs the mock data layer, which has not been loaded.');
  if (!evaluationApi) evaluationApi = mockRuntime.createReferenceAgent();
  return evaluationApi;
}

export type { ExecutiveDeskApi } from './client';
