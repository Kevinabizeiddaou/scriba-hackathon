/**
 * HTTP implementation of ExecutiveDeskApi, for Role 1's backend.
 *
 * This file is the only place that knows URLs. Paths and payloads follow
 * docs/API_CONTRACT.md. Where the real backend differs, change it here (or map
 * the response in `normalizeRun`) and nothing else in the app needs to move.
 *
 * It has not been exercised against a real server yet; src/api/httpAdapter.test.ts
 * covers it against a stubbed fetch.
 */
import { ApiError, type ApiInfo, type ExecutiveDeskApi } from './client';
import {
  TOOL_NAMES,
  isSideEffectTool,
  type AgentRun,
  type ApprovalDecisionInput,
  type ApprovalRequest,
  type ApprovalStatus,
  type Conversation,
  type ConversationMessage,
  type EvaluationRunInput,
  type RequestStatus,
  type SecretaryRequest,
  type ToolName,
} from './types';

export interface HttpOptions {
  /** For example "http://localhost:8000/api/executive-desk". No trailing slash. */
  baseUrl: string;
  principal: ApiInfo['principal'];
  /** Returns a bearer token, or null to send no Authorization header. Never hard-code a token. */
  getToken?: () => string | null;
  /** Maps the backend's tool names onto the canonical ones in types.ts. */
  toolAliases?: Record<string, ToolName>;
  /** How often subscribers are told to refetch. */
  pollIntervalMs?: number;
  fetchImpl?: typeof fetch;
}

/**
 * Backend tool name -> canonical tool name. Empty until Role 1 confirms the real names.
 * Example entry: 'gmail_send_message': 'email.send'.
 */
export const DEFAULT_TOOL_ALIASES: Record<string, ToolName> = {};

export class HttpExecutiveDesk implements ExecutiveDeskApi {
  readonly info: ApiInfo;
  private readonly listeners = new Set<() => void>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private readonly fetchImpl: typeof fetch;
  private readonly aliases: Record<string, ToolName>;

  constructor(private readonly options: HttpOptions) {
    this.info = {
      name: 'Scriba backend',
      dataSource: 'live',
      baseUrl: options.baseUrl,
      principal: options.principal,
      simulatedNow: null,
    };
    this.fetchImpl = options.fetchImpl ?? ((...args) => fetch(...args));
    this.aliases = { ...DEFAULT_TOOL_ALIASES, ...options.toolAliases };
  }

  listRequests(filter?: { status?: RequestStatus[] }): Promise<SecretaryRequest[]> {
    return this.get('/requests', { status: filter?.status?.join(',') });
  }

  getRequest(id: string): Promise<SecretaryRequest> {
    return this.get(`/requests/${encodeURIComponent(id)}`);
  }

  async processRequest(id: string): Promise<AgentRun> {
    return this.normalizeRun(await this.post(`/requests/${encodeURIComponent(id)}/process`, {}));
  }

  async getRun(id: string): Promise<AgentRun> {
    return this.normalizeRun(await this.get(`/runs/${encodeURIComponent(id)}`));
  }

  async listRuns(filter?: { requestId?: string; conversationId?: string }): Promise<AgentRun[]> {
    const runs = await this.get<AgentRun[]>('/runs', { requestId: filter?.requestId, conversationId: filter?.conversationId });
    return runs.map((run) => this.normalizeRun(run));
  }

  listApprovals(filter?: { status?: ApprovalStatus[]; runId?: string }): Promise<ApprovalRequest[]> {
    return this.get('/approvals', { status: filter?.status?.join(','), runId: filter?.runId });
  }

  decideApproval(id: string, input: ApprovalDecisionInput): Promise<ApprovalRequest> {
    return this.post(`/approvals/${encodeURIComponent(id)}/decision`, input);
  }

  listConversations(): Promise<Conversation[]> {
    return this.get('/conversations');
  }

  createConversation(): Promise<Conversation> {
    return this.post('/conversations', {});
  }

  listMessages(conversationId: string): Promise<ConversationMessage[]> {
    return this.get(`/conversations/${encodeURIComponent(conversationId)}/messages`);
  }

  async sendMessage(conversationId: string, text: string): Promise<{ message: ConversationMessage; run: AgentRun }> {
    const result = await this.post<{ message: ConversationMessage; run: AgentRun }>(
      `/conversations/${encodeURIComponent(conversationId)}/messages`,
      { text },
    );
    return { message: result.message, run: this.normalizeRun(result.run) };
  }

  async startEvaluationRun(input: EvaluationRunInput): Promise<AgentRun> {
    return this.normalizeRun(await this.post('/evaluation/runs', input));
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    if (!this.timer) {
      this.timer = setInterval(() => {
        for (const l of this.listeners) l();
      }, this.options.pollIntervalMs ?? 2_000);
    }
    return () => {
      this.listeners.delete(listener);
      if (this.listeners.size === 0 && this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }
    };
  }

  // --- internals ------------------------------------------------------------------

  /** Renames backend tool names to canonical ones and fills `sideEffect` from the canonical list. */
  private normalizeRun(run: AgentRun): AgentRun {
    return {
      ...run,
      actions: run.actions.map((action) => {
        const tool = (this.aliases[action.tool as string] ?? action.tool) as ToolName;
        if (!(TOOL_NAMES as readonly string[]).includes(tool)) {
          throw new ApiError(
            `Run ${run.id} uses a tool the frontend does not know: "${action.tool}". Add it to toolAliases in httpAdapter.ts.`,
            null,
            'unknown_tool',
          );
        }
        return { ...action, tool, sideEffect: isSideEffectTool(tool) };
      }),
    };
  }

  private get<T>(path: string, query: Record<string, string | undefined> = {}): Promise<T> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) if (value) params.set(key, value);
    const qs = params.toString();
    return this.request<T>('GET', qs ? `${path}?${qs}` : path);
  }

  private post<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>('POST', path, body);
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const token = this.options.getToken?.();
    if (token) headers.Authorization = `Bearer ${token}`;

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.options.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (cause) {
      throw new ApiError(`Could not reach the backend: ${cause instanceof Error ? cause.message : String(cause)}`, null, 'network_error');
    }

    const text = await response.text();
    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        throw new ApiError(`The backend returned a non-JSON response (HTTP ${response.status}).`, response.status, 'invalid_response');
      }
    }
    if (!response.ok) {
      // Error body per the contract: { "error": { "code": string, "message": string } }
      const error = (payload as { error?: { code?: string; message?: string } } | null)?.error;
      throw new ApiError(error?.message ?? `HTTP ${response.status}`, response.status, error?.code ?? `http_${response.status}`);
    }
    return payload as T;
  }
}
