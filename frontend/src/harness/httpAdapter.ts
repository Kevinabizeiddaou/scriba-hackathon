/**
 * HTTP implementation of ExecutiveDeskApi, for Role 1's backend.
 *
 * This file is the only place that knows URLs, headers and transport behaviour. It follows
 * docs/API_CONTRACT.md (contract v1): handshake on GET /meta, Scriba's existing cookie session
 * for authentication, an Idempotency-Key on every POST, a timeout on every request, bounded
 * retries on reads (and on writes only when the backend says it replays repeated keys), and
 * runtime validation of what comes back.
 *
 * There is no token handling here on purpose. Scriba signs users in with an HttpOnly session
 * cookie owned by the API host; the browser sends it when `credentials` is "include".
 *
 * It is exercised over real HTTP against the reference server (src/harness/httpAdapter.integration.test.ts).
 * It has not been run against the real Scriba backend.
 */
import { ApiError, type ApiInfo, type ExecutiveDeskApi } from './client';
import {
  CONTRACT_HEADER,
  CONTRACT_VERSION,
  IDEMPOTENCY_HEADER,
  TOOL_NAMES,
  isSideEffectTool,
  type AgentRun,
  type ApprovalDecisionInput,
  type ApprovalRequest,
  type ApprovalStatus,
  type Conversation,
  type ConversationMessage,
  type DeskMeta,
  type EvaluationRunInput,
  type RequestStatus,
  type SecretaryRequest,
  type ToolName,
} from './types';
import { validate } from './validate';

export interface RetryPolicy {
  /** Total tries per request, the first one included. */
  attempts: number;
  /** Delay before the second try; doubles each time. */
  baseDelayMs: number;
  maxDelayMs: number;
}

export interface HttpOptions {
  /** For example "http://localhost:8000/api/executive-desk/v1". No trailing slash. */
  baseUrl: string;
  /**
   * Whether the browser sends the session cookie. "include" is right for a backend on another
   * origin, which is how Scriba is deployed. Defaults to "include".
   */
  credentials?: RequestCredentials;
  /**
   * For clients that are not browsers (the evaluation CLI): the value of the Cookie header of
   * an existing Scriba session. A browser ignores this and uses its own cookie jar.
   */
  sessionCookie?: () => string | null;
  /**
   * For clients that are not browsers: the Origin header to send. Scriba accepts credentialed
   * requests only from the Desk's origin, and a browser sets this itself.
   */
  origin?: string;
  /** Maps the backend's tool names onto the canonical ones in types.ts. */
  toolAliases?: Record<string, ToolName>;
  /** How often subscribers are told to refetch. */
  pollIntervalMs?: number;
  /** Per-request timeout. */
  timeoutMs?: number;
  retry?: Partial<RetryPolicy>;
  /** Set to false to skip runtime validation of responses. */
  validateResponses?: boolean;
  fetchImpl?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
  newIdempotencyKey?: () => string;
}

/**
 * Backend tool name -> canonical tool name. Empty until Role 1 confirms the real names.
 * Example entry: 'gmail_send_message': 'email.send'.
 */
export const DEFAULT_TOOL_ALIASES: Record<string, ToolName> = {};

export const DEFAULT_RETRY: RetryPolicy = { attempts: 3, baseDelayMs: 250, maxDelayMs: 4_000 };
export const DEFAULT_TIMEOUT_MS = 15_000;

/** Statuses that mean "try again later", for any method. */
const RETRYABLE_STATUS = new Set([429, 502, 503, 504]);

const UNKNOWN_PRINCIPAL = { name: 'Not connected', email: '', timezone: 'UTC' };

function uuid(): string {
  return globalThis.crypto.randomUUID();
}

export class HttpExecutiveDesk implements ExecutiveDeskApi {
  private current: ApiInfo;
  private metaPromise: Promise<DeskMeta> | null = null;
  private readonly listeners = new Set<() => void>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private readonly fetchImpl: typeof fetch;
  private readonly aliases: Record<string, ToolName>;
  private readonly retry: RetryPolicy;
  private readonly timeoutMs: number;
  private readonly sleep: (ms: number) => Promise<void>;
  /** From GET /meta. Until the backend says it replays repeated keys, a write is never sent twice. */
  private writesAreIdempotent = false;

  constructor(private readonly options: HttpOptions) {
    this.current = {
      name: 'Scriba backend',
      // Until GET /meta has answered we do not know what is behind the URL. "simulated" is the
      // safe label: nothing is ever shown as a real result on the strength of a guess.
      dataSource: 'simulated',
      baseUrl: options.baseUrl,
      principal: UNKNOWN_PRINCIPAL,
      simulatedNow: null,
      suggestedPrompts: [],
      contractVersion: null,
    };
    this.fetchImpl = options.fetchImpl ?? ((...args) => fetch(...args));
    this.aliases = { ...DEFAULT_TOOL_ALIASES, ...options.toolAliases };
    this.retry = { ...DEFAULT_RETRY, ...options.retry };
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.sleep = options.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  }

  get info(): ApiInfo {
    return this.current;
  }

  /** GET /meta. Cached after the first success; a failure is not cached, so the next call retries. */
  getMeta(): Promise<DeskMeta> {
    if (!this.metaPromise) {
      this.metaPromise = this.loadMeta().catch((error) => {
        this.metaPromise = null;
        throw error;
      });
    }
    return this.metaPromise;
  }

  async listRequests(filter?: { status?: RequestStatus[] }): Promise<SecretaryRequest[]> {
    return this.checked(await this.get('/requests', { status: filter?.status?.join(',') }), validate.requests);
  }

  async getRequest(id: string): Promise<SecretaryRequest> {
    return this.checked(await this.get(`/requests/${encodeURIComponent(id)}`), validate.request);
  }

  async processRequest(id: string): Promise<AgentRun> {
    return this.run(await this.post(`/requests/${encodeURIComponent(id)}/process`, {}));
  }

  async getRun(id: string): Promise<AgentRun> {
    return this.run(await this.get(`/runs/${encodeURIComponent(id)}`));
  }

  async listRuns(filter?: { requestId?: string; conversationId?: string }): Promise<AgentRun[]> {
    const runs = await this.get<unknown>('/runs', { requestId: filter?.requestId, conversationId: filter?.conversationId });
    if (!Array.isArray(runs)) throw this.violation(['runs: expected an array']);
    return runs.map((run) => this.run(run));
  }

  async listApprovals(filter?: { status?: ApprovalStatus[]; runId?: string }): Promise<ApprovalRequest[]> {
    const approvals = await this.get<unknown>('/approvals', { status: filter?.status?.join(','), runId: filter?.runId });
    if (!Array.isArray(approvals)) throw this.violation(['approvals: expected an array']);
    return approvals.map((approval) => this.approval(approval));
  }

  async decideApproval(id: string, input: ApprovalDecisionInput): Promise<ApprovalRequest> {
    return this.approval(await this.post(`/approvals/${encodeURIComponent(id)}/decision`, { ...input, note: input.note ?? null }));
  }

  async listConversations(): Promise<Conversation[]> {
    return this.checked(await this.get('/conversations'), validate.conversations);
  }

  async createConversation(): Promise<Conversation> {
    return this.checked(await this.post('/conversations', {}), validate.conversation);
  }

  async listMessages(conversationId: string): Promise<ConversationMessage[]> {
    return this.checked(await this.get(`/conversations/${encodeURIComponent(conversationId)}/messages`), validate.messages);
  }

  async sendMessage(conversationId: string, text: string): Promise<{ message: ConversationMessage; run: AgentRun }> {
    const result = await this.post<{ message: ConversationMessage; run: unknown }>(`/conversations/${encodeURIComponent(conversationId)}/messages`, { text });
    const run = this.run(result?.run);
    return this.checked({ message: result.message, run }, validate.messageAndRun);
  }

  async startEvaluationRun(input: EvaluationRunInput): Promise<AgentRun> {
    return this.run(await this.post('/evaluation/runs', input));
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    if (!this.timer) {
      this.timer = setInterval(() => this.emit(), this.options.pollIntervalMs ?? 2_000);
    }
    return () => {
      this.listeners.delete(listener);
      if (this.listeners.size === 0 && this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }
    };
  }

  // --- handshake ------------------------------------------------------------------

  private async loadMeta(): Promise<DeskMeta> {
    const meta = await this.request<DeskMeta>('GET', '/meta', undefined, true);
    const problems = validate.meta(meta);
    if (problems.length > 0) throw this.violation(problems);
    if (meta.contractVersion.split('.')[0] !== CONTRACT_VERSION.split('.')[0]) {
      throw new ApiError(
        `The backend speaks contract ${meta.contractVersion}; this frontend needs ${CONTRACT_VERSION.split('.')[0]}.x.`,
        null,
        'unsupported_contract_version',
      );
    }
    this.writesAreIdempotent = meta.capabilities.idempotentPosts === true;
    this.current = {
      name: meta.service,
      // Only a real agent produces live data. A scripted stand-in is simulated, whatever the transport.
      dataSource: meta.agent === 'real' ? 'live' : 'simulated',
      baseUrl: this.options.baseUrl,
      principal: meta.principal,
      simulatedNow: meta.simulatedNow,
      suggestedPrompts: [],
      contractVersion: meta.contractVersion,
    };
    this.emit();
    return meta;
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }

  // --- response handling ------------------------------------------------------------

  private violation(problems: string[]): ApiError {
    const shown = problems.slice(0, 6).join('; ');
    const more = problems.length > 6 ? ` (and ${problems.length - 6} more)` : '';
    return new ApiError(`The backend response does not match the contract: ${shown}${more}`, null, 'contract_violation', false, { problems });
  }

  private checked<T>(value: unknown, check: (value: unknown) => string[]): T {
    if (this.options.validateResponses !== false) {
      const problems = check(value);
      if (problems.length > 0) throw this.violation(problems);
    }
    return value as T;
  }

  /** Maps a backend tool name onto the canonical one, or stops with an error that names it. */
  private canonical(tool: unknown, where: string): ToolName {
    const mapped = this.aliases[tool as string] ?? tool;
    if (typeof mapped !== 'string' || !(TOOL_NAMES as readonly string[]).includes(mapped)) {
      throw new ApiError(`${where} uses a tool the frontend does not know: "${String(tool)}". Add it to toolAliases in httpAdapter.ts.`, null, 'unknown_tool');
    }
    return mapped as ToolName;
  }

  /** Renames backend tool names to canonical ones, fills `sideEffect` from the canonical list, then validates. */
  private run(value: unknown): AgentRun {
    const raw = value as AgentRun | null;
    if (!raw || typeof raw !== 'object' || !Array.isArray(raw.actions)) throw this.violation(['run: expected an object with an actions array']);
    const normalized: AgentRun = {
      ...raw,
      actions: raw.actions.map((action) => {
        const tool = this.canonical(action?.tool, `Run ${raw.id}`);
        return { ...action, tool, sideEffect: isSideEffectTool(tool) };
      }),
    };
    return this.checked(normalized, validate.run);
  }

  /** Same renaming for the changes inside an approval, so runs and approvals speak one vocabulary. */
  private approval(value: unknown): ApprovalRequest {
    const raw = value as ApprovalRequest | null;
    if (!raw || typeof raw !== 'object' || !Array.isArray(raw.changes)) throw this.violation(['approval: expected an object with a changes array']);
    const normalized = { ...raw, changes: raw.changes.map((change) => ({ ...change, tool: this.canonical(change?.tool, `Approval ${raw.id}`) })) } as ApprovalRequest;
    return this.checked(normalized, validate.approval);
  }

  // --- transport ------------------------------------------------------------------

  private get<T>(path: string, query: Record<string, string | undefined> = {}): Promise<T> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) if (value) params.set(key, value);
    const qs = params.toString();
    return this.request<T>('GET', qs ? `${path}?${qs}` : path);
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const result = await this.request<T>('POST', path, body);
    // Something just changed on the server: tell the screens now instead of at the next poll tick.
    this.emit();
    return result;
  }

  private backoff(attempt: number, retryAfter: string | null): number {
    const seconds = retryAfter ? Number(retryAfter) : NaN;
    if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1_000, this.retry.maxDelayMs);
    return Math.min(this.retry.baseDelayMs * 2 ** (attempt - 1), this.retry.maxDelayMs);
  }

  private async request<T>(method: 'GET' | 'POST', path: string, body?: unknown, isHandshake = false): Promise<T> {
    if (!isHandshake) await this.getMeta();

    // One key for all tries of this call: a POST that timed out and is sent again must not act twice.
    const idempotencyKey = method === 'POST' ? (this.options.newIdempotencyKey ?? uuid)() : null;
    // Reads can always be repeated. A write is repeated only when the backend has said it
    // recognises a repeated key; otherwise it is tried once, and the caller re-reads the state.
    const tries = method === 'GET' || this.writesAreIdempotent ? this.retry.attempts : 1;
    const cookie = this.options.sessionCookie?.() ?? null;
    let lastError: ApiError | null = null;

    for (let attempt = 1; attempt <= tries; attempt += 1) {
      const headers: Record<string, string> = { Accept: 'application/json', [CONTRACT_HEADER]: CONTRACT_VERSION };
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (idempotencyKey) headers[IDEMPOTENCY_HEADER] = idempotencyKey;
      if (cookie) headers.Cookie = cookie;
      if (this.options.origin) headers.Origin = this.options.origin;

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      let response: Response;
      let text: string;
      try {
        response = await this.fetchImpl(`${this.options.baseUrl}${path}`, {
          method,
          headers,
          credentials: this.options.credentials ?? 'include',
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
        });
        text = await response.text();
      } catch (cause) {
        lastError = controller.signal.aborted
          ? new ApiError(`The backend did not answer ${method} ${path} within ${this.timeoutMs} ms.`, null, 'timeout', true)
          : new ApiError(`Could not reach the backend: ${cause instanceof Error ? cause.message : String(cause)}`, null, 'network_error', true);
        if (attempt < tries) {
          await this.sleep(this.backoff(attempt, null));
          continue;
        }
        throw lastError;
      } finally {
        clearTimeout(timer);
      }

      let payload: unknown = null;
      if (text) {
        try {
          payload = JSON.parse(text);
        } catch {
          lastError = new ApiError(`The backend returned a non-JSON response (HTTP ${response.status}).`, response.status, 'invalid_response', RETRYABLE_STATUS.has(response.status));
          if (RETRYABLE_STATUS.has(response.status) && attempt < tries) {
            await this.sleep(this.backoff(attempt, response.headers.get('Retry-After')));
            continue;
          }
          throw lastError;
        }
      }

      if (response.ok) return payload as T;

      // Error body per the contract: { "error": { "code", "message", "details"? } }
      const error = (payload as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
      const retryable = RETRYABLE_STATUS.has(response.status);
      // A 401 means the Scriba session is gone. There is nothing to refresh from here: the user
      // signs in to Scriba again. It is never retried and never triggers a sign-in by itself.
      lastError = new ApiError(
        response.status === 401 ? 'Your Scriba session has ended. Sign in to Scriba again, then reload this page.' : (error?.message ?? `HTTP ${response.status}`),
        response.status,
        error?.code ?? (response.status === 401 ? 'unauthenticated' : `http_${response.status}`),
        retryable,
        error?.details,
      );
      if (retryable && attempt < tries) {
        await this.sleep(this.backoff(attempt, response.headers.get('Retry-After')));
        continue;
      }
      throw lastError;
    }
    throw lastError ?? new ApiError('The request was not sent.', null, 'network_error', true);
  }
}
