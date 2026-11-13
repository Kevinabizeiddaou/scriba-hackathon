/**
 * Reference HTTP server for the Executive Desk contract.
 *
 * It serves every endpoint in docs/API_CONTRACT.md over real HTTP, backed by the scripted
 * mock. It exists for two reasons:
 *   1. integration tests: the HTTP adapter and the evaluation runner are exercised over a
 *      real socket, with faults (errors, delays, dropped connections) injected on demand;
 *   2. a worked example for Role 1 of what the contract looks like on the wire.
 *
 * It is not a backend. There is no agent behind it, only hand-written scripts, and it says
 * so in GET /meta (`agent: "scripted"`), which makes every client label its data as simulated.
 * Node only: never import this from browser code.
 */
import { createHash } from 'node:crypto';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { ApiError, type ExecutiveDeskApi } from '../client';
import { MockExecutiveDesk, type MockOptions } from '../mock/mockAdapter';
import {
  CONTRACT_HEADER,
  CONTRACT_VERSION,
  IDEMPOTENCY_HEADER,
  type ApprovalStatus,
  type DeskMeta,
  type RequestStatus,
} from '../types';

export interface ReferenceServerOptions {
  port?: number;
  host?: string;
  /** Defaults to /api/executive-desk/v1. */
  basePath?: string;
  /** When set, every request must carry `Authorization: Bearer <token>`. */
  token?: string | null;
  /** Value of Access-Control-Allow-Origin. */
  allowOrigin?: string;
  mock?: MockOptions;
  /** Serve a different implementation of the interface instead of a fresh mock. */
  desk?: ExecutiveDeskApi;
  /** Overrides for GET /meta, for tests that need an incompatible or unusual server. */
  meta?: Partial<DeskMeta>;
}

export interface RecordedRequest {
  method: string;
  /** Path below the base path, for example "/runs/run-0001". */
  path: string;
  query: Record<string, string>;
  headers: Record<string, string>;
  body: unknown;
}

/** A failure to inject. The first matching fault with uses left wins. */
export interface InjectedFault {
  method?: string;
  /** Matched against the path below the base path. */
  path?: RegExp;
  /** How many matching requests it affects. */
  times: number;
  /**
   * status:        answer with an error status instead of handling the request
   * drop:          close the connection before handling the request
   * delay:         wait, then handle the request normally
   * garbage:       answer with HTML instead of JSON
   * lose_response: handle the request, then close the connection without answering
   *                (the case idempotency keys exist for)
   */
  kind: 'status' | 'drop' | 'delay' | 'garbage' | 'lose_response';
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
  delayMs?: number;
}

interface Stored {
  fingerprint: string;
  status: number;
  body: unknown;
}

class HttpProblem extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

const list = (value: string | undefined) => (value ? value.split(',').map((s) => s.trim()).filter(Boolean) : undefined);

export class ReferenceServer {
  /** Every request received, oldest first. */
  readonly requests: RecordedRequest[] = [];
  readonly desk: ExecutiveDeskApi;
  private readonly faults: InjectedFault[] = [];
  private readonly idempotency = new Map<string, Stored>();
  private readonly basePath: string;
  private server!: Server;

  private constructor(private readonly options: ReferenceServerOptions) {
    this.basePath = (options.basePath ?? '/api/executive-desk/v1').replace(/\/$/, '');
    this.desk = options.desk ?? new MockExecutiveDesk({ stepDelayMs: 0, seed: true, ...options.mock });
  }

  static async start(options: ReferenceServerOptions = {}): Promise<ReferenceServer> {
    const instance = new ReferenceServer(options);
    instance.server = createServer((req, res) => void instance.handle(req, res));
    await new Promise<void>((resolve, reject) => {
      instance.server.once('error', reject);
      instance.server.listen(options.port ?? 0, options.host ?? '127.0.0.1', resolve);
    });
    return instance;
  }

  get port(): number {
    return (this.server.address() as AddressInfo).port;
  }

  get baseUrl(): string {
    return `http://${this.options.host ?? '127.0.0.1'}:${this.port}${this.basePath}`;
  }

  inject(fault: InjectedFault): void {
    this.faults.push({ ...fault });
  }

  clearFaults(): void {
    this.faults.length = 0;
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve) => {
      this.server.close(() => resolve());
      this.server.closeAllConnections();
    });
  }

  // --- request handling ---------------------------------------------------------------

  private meta(): DeskMeta {
    const { principal, simulatedNow } = this.desk.info;
    return {
      contractVersion: CONTRACT_VERSION,
      service: 'executive-desk-reference-server',
      agent: 'scripted',
      sandbox: true,
      principal,
      simulatedNow,
      capabilities: { evaluation: true, faultInjection: true, chat: true, tokenUsage: false },
      ...this.options.meta,
    };
  }

  private cors(res: ServerResponse): void {
    res.setHeader('Access-Control-Allow-Origin', this.options.allowOrigin ?? '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', `Authorization, Content-Type, ${IDEMPOTENCY_HEADER}, ${CONTRACT_HEADER}`);
    res.setHeader('Access-Control-Expose-Headers', `${CONTRACT_HEADER}, Retry-After`);
    res.setHeader(CONTRACT_HEADER, this.options.meta?.contractVersion ?? CONTRACT_VERSION);
  }

  private send(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}): void {
    const payload = body === undefined ? '' : JSON.stringify(body);
    res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', ...headers });
    res.end(payload);
  }

  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    this.cors(res);
    const url = new URL(req.url ?? '/', 'http://reference.local');
    const method = req.method ?? 'GET';

    if (method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }

    let body: unknown;
    try {
      const chunks: Buffer[] = [];
      for await (const chunk of req) chunks.push(chunk as Buffer);
      const text = Buffer.concat(chunks).toString('utf8');
      body = text ? JSON.parse(text) : undefined;
    } catch {
      this.send(res, 400, { error: { code: 'invalid_request', message: 'The request body is not valid JSON.' } });
      return;
    }

    const path = url.pathname.startsWith(this.basePath) ? url.pathname.slice(this.basePath.length) || '/' : null;
    const recorded: RecordedRequest = {
      method,
      path: path ?? url.pathname,
      query: Object.fromEntries(url.searchParams),
      headers: Object.fromEntries(Object.entries(req.headers).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : (v ?? '')])),
      body,
    };
    this.requests.push(recorded);

    const fault = this.faults.find((f) => f.times > 0 && (!f.method || f.method === method) && (!f.path || f.path.test(recorded.path)));
    if (fault) {
      fault.times -= 1;
      if (fault.kind === 'drop') {
        req.socket.destroy();
        return;
      }
      if (fault.kind === 'garbage') {
        res.writeHead(fault.status ?? 200, { 'Content-Type': 'text/html' });
        res.end('<html><body>Bad gateway</body></html>');
        return;
      }
      if (fault.kind === 'status') {
        this.send(res, fault.status ?? 503, fault.body ?? { error: { code: 'upstream_unavailable', message: 'Injected failure.' } }, fault.headers);
        return;
      }
      if (fault.kind === 'delay') {
        await new Promise((resolve) => setTimeout(resolve, fault.delayMs ?? 0));
        if (res.destroyed) return;
      }
    }
    const loseResponse = fault?.kind === 'lose_response';

    try {
      if (path === null) throw new HttpProblem(404, 'not_found', `Nothing is served outside ${this.basePath}.`);

      if (this.options.token) {
        const header = recorded.headers.authorization ?? '';
        if (!header.startsWith('Bearer ')) throw new HttpProblem(401, 'unauthenticated', 'Send an Authorization: Bearer token.');
        if (header.slice(7) !== this.options.token) throw new HttpProblem(401, 'unauthenticated', 'The bearer token is not valid.');
      }

      const wanted = recorded.headers[CONTRACT_HEADER.toLowerCase()];
      if (wanted && wanted.split('.')[0] !== CONTRACT_VERSION.split('.')[0]) {
        throw new HttpProblem(400, 'unsupported_contract_version', `This server speaks contract ${CONTRACT_VERSION}; the client asked for ${wanted}.`);
      }

      // Idempotent replay: the same key with the same request returns the first answer again.
      const key = method === 'POST' ? recorded.headers[IDEMPOTENCY_HEADER.toLowerCase()] : undefined;
      const fingerprint = createHash('sha256').update(`${method} ${recorded.path} ${JSON.stringify(body ?? null)}`).digest('hex');
      if (key) {
        const stored = this.idempotency.get(key);
        if (stored) {
          if (stored.fingerprint !== fingerprint) throw new HttpProblem(422, 'idempotency_key_reused', 'This Idempotency-Key was already used for a different request.');
          this.send(res, stored.status, stored.body, { 'Idempotent-Replay': 'true' });
          return;
        }
      }

      const { status, body: result } = await this.route(method, path, recorded);
      if (key) this.idempotency.set(key, { fingerprint, status, body: result });
      if (loseResponse) {
        req.socket.destroy(); // the work is done, but the client never hears about it
        return;
      }
      this.send(res, status, result);
    } catch (cause) {
      if (cause instanceof HttpProblem) this.send(res, cause.status, { error: { code: cause.code, message: cause.message } });
      else if (cause instanceof ApiError) this.send(res, cause.status ?? 500, { error: { code: cause.code, message: cause.message } });
      else this.send(res, 500, { error: { code: 'internal_error', message: cause instanceof Error ? cause.message : String(cause) } });
    }
  }

  private async route(method: string, path: string, request: RecordedRequest): Promise<{ status: number; body: unknown }> {
    const { query } = request;
    const body = (request.body ?? {}) as Record<string, unknown>;
    const ok = (value: unknown, status = 200) => ({ status, body: value });
    const match = (pattern: RegExp) => pattern.exec(path)?.slice(1).map(decodeURIComponent);
    let m: string[] | undefined;

    if (method === 'GET') {
      if (path === '/meta') return ok(this.meta());
      if (path === '/requests') return ok(await this.desk.listRequests({ status: list(query.status) as RequestStatus[] | undefined }));
      if ((m = match(/^\/requests\/([^/]+)$/))) return ok(await this.desk.getRequest(m[0]));
      if (path === '/runs') return ok(await this.desk.listRuns({ requestId: query.requestId, conversationId: query.conversationId }));
      if ((m = match(/^\/runs\/([^/]+)$/))) return ok(await this.desk.getRun(m[0]));
      if (path === '/approvals') return ok(await this.desk.listApprovals({ status: list(query.status) as ApprovalStatus[] | undefined, runId: query.runId }));
      if (path === '/conversations') return ok(await this.desk.listConversations());
      if ((m = match(/^\/conversations\/([^/]+)\/messages$/))) return ok(await this.desk.listMessages(m[0]));
    }

    if (method === 'POST') {
      if ((m = match(/^\/requests\/([^/]+)\/process$/))) return ok(await this.desk.processRequest(m[0]), 202);
      if ((m = match(/^\/approvals\/([^/]+)\/decision$/))) {
        if (body.decision !== 'approve' && body.decision !== 'reject') throw new HttpProblem(400, 'invalid_request', '"decision" must be "approve" or "reject".');
        if (typeof body.decidedBy !== 'string' || !body.decidedBy) throw new HttpProblem(400, 'invalid_request', '"decidedBy" is required.');
        return ok(await this.desk.decideApproval(m[0], { decision: body.decision, decidedBy: body.decidedBy, note: typeof body.note === 'string' ? body.note : null }));
      }
      if (path === '/conversations') return ok(await this.desk.createConversation(), 201);
      if ((m = match(/^\/conversations\/([^/]+)\/messages$/))) {
        if (typeof body.text !== 'string') throw new HttpProblem(400, 'invalid_request', '"text" is required.');
        return ok(await this.desk.sendMessage(m[0], body.text), 202);
      }
      if (path === '/evaluation/runs') {
        if (typeof body.caseId !== 'string' || body.mode !== 'sandbox' || !body.input || !body.context) {
          throw new HttpProblem(400, 'invalid_request', 'An evaluation run needs caseId, input, context and mode "sandbox".');
        }
        return ok(await this.desk.startEvaluationRun(body as never), 202);
      }
    }

    throw new HttpProblem(404, 'not_found', `No route for ${method} ${path}.`);
  }
}
