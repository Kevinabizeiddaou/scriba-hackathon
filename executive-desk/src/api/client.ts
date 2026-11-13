/**
 * The one interface the UI and the evaluation harness talk to.
 *
 * Two implementations exist:
 *   - MockExecutiveDesk (src/api/mock/mockAdapter.ts): in-memory, scripted, no network.
 *   - HttpExecutiveDesk (src/api/httpAdapter.ts): thin fetch wrapper over the endpoints
 *     in docs/API_CONTRACT.md, for Role 1's backend.
 *
 * UI code never imports an adapter directly; it calls getApi() from src/api/index.ts.
 * (The harness self-test is the one other place that constructs the mock.)
 */
import type {
  AgentRun,
  ApprovalDecisionInput,
  ApprovalRequest,
  ApprovalStatus,
  Conversation,
  ConversationMessage,
  DataSource,
  EvaluationRunInput,
  IanaTimeZone,
  ISODateTime,
  Participant,
  RequestStatus,
  SecretaryRequest,
} from './types';

export interface ApiInfo {
  name: string;
  dataSource: DataSource;
  baseUrl: string | null;
  /** Whose desk this is. Times in the UI are shown in this time zone. */
  principal: Participant & { timezone: IanaTimeZone };
  /** Set by the mock adapter, whose clock is frozen at the fixture date. Null for a live backend. */
  simulatedNow: ISODateTime | null;
  /** Example prompts for the chat composer. The mock lists the ones it has scripts for. */
  suggestedPrompts: string[];
}

export interface ExecutiveDeskApi {
  readonly info: ApiInfo;

  // Requests ---------------------------------------------------------------
  /** GET /requests */
  listRequests(filter?: { status?: RequestStatus[] }): Promise<SecretaryRequest[]>;
  /** GET /requests/{id} */
  getRequest(id: string): Promise<SecretaryRequest>;
  /** POST /requests/{id}/process: start (or restart) an agent run for this request. */
  processRequest(id: string): Promise<AgentRun>;

  // Runs -------------------------------------------------------------------
  /** GET /runs/{id} */
  getRun(id: string): Promise<AgentRun>;
  /** GET /runs?requestId=&conversationId= */
  listRuns(filter?: { requestId?: string; conversationId?: string }): Promise<AgentRun[]>;

  // Approvals --------------------------------------------------------------
  /** GET /approvals?status=&runId= */
  listApprovals(filter?: { status?: ApprovalStatus[]; runId?: string }): Promise<ApprovalRequest[]>;
  /** POST /approvals/{id}/decision */
  decideApproval(id: string, input: ApprovalDecisionInput): Promise<ApprovalRequest>;

  // Chat -------------------------------------------------------------------
  /** GET /conversations */
  listConversations(): Promise<Conversation[]>;
  /** POST /conversations */
  createConversation(): Promise<Conversation>;
  /** GET /conversations/{id}/messages */
  listMessages(conversationId: string): Promise<ConversationMessage[]>;
  /** POST /conversations/{id}/messages: returns the stored user message and the run it started. */
  sendMessage(conversationId: string, text: string): Promise<{ message: ConversationMessage; run: AgentRun }>;

  // Evaluation -------------------------------------------------------------
  /** POST /evaluation/runs: run one evaluation case in sandbox mode. */
  startEvaluationRun(input: EvaluationRunInput): Promise<AgentRun>;

  // Change notification ----------------------------------------------------
  /**
   * Calls `listener` whenever server state may have changed. The mock emits on every
   * mutation; the HTTP adapter polls. Returns an unsubscribe function.
   */
  subscribe(listener: () => void): () => void;
}

/** The part of the API the evaluation runner needs. Anything that implements it can be evaluated. */
export type EvaluationTarget = Pick<
  ExecutiveDeskApi,
  'info' | 'startEvaluationRun' | 'getRun' | 'listApprovals' | 'decideApproval'
>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly code: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
