/**
 * In-memory implementation of ExecutiveDeskApi.
 *
 * It replays hand-written scripts (src/api/mock/scripts.ts). It makes no network calls,
 * holds no credentials, and has no code path that can send an email or change a calendar:
 * every side-effect action it records carries `simulated: true`.
 */
import { ApiError, type ApiInfo, type ExecutiveDeskApi } from '../client';
import { inputForChange, summaryForChange } from '../changes';
import {
  isSideEffectTool,
  type AgentAction,
  type AgentRun,
  type ApprovalDecisionInput,
  type ApprovalRequest,
  type ApprovalStatus,
  type Conversation,
  type ConversationMessage,
  type EvaluationRunInput,
  type RequestStatus,
  type RunOutcome,
  type SecretaryRequest,
  type ToolName,
} from '../types';
import { EVALUATION_CASES } from '../../evaluation/fixtures';
import { NOW, PRINCIPAL } from '../../evaluation/fixtures/world';
import { scriptForChat } from './chatIntents';
import type { ActionStep, ApprovalStep, FinishStep, MockScript } from './scriptDsl';
import { MOCK_SCRIPTS } from './scripts';

export interface MockOptions {
  /** Real-time pause between script steps, so the UI can show progress. 0 runs scripts as fast as possible. */
  stepDelayMs?: number;
  /** Fill the inbox, approvals and chat with demo data. */
  seed?: boolean;
  /** Override the script for a case. Used by the harness self-test to inject deliberately wrong runs. */
  scriptFor?: (caseId: string) => MockScript | undefined;
}

interface Playback {
  script: MockScript;
  cursor: number;
  /** Approval that gates the side-effect steps currently being replayed. */
  gate: string | null;
}

/** How each seeded inbox request should look when the app opens. */
const SEED_PLAN: { caseId: string; state: 'received' | 'processed' | 'approved' }[] = [
  { caseId: 'EVAL-008', state: 'approved' },
  { caseId: 'EVAL-009', state: 'approved' },
  { caseId: 'EVAL-016', state: 'approved' },
  { caseId: 'EVAL-017', state: 'approved' },
  { caseId: 'EVAL-018', state: 'approved' },
  { caseId: 'EVAL-001', state: 'processed' },
  { caseId: 'EVAL-003', state: 'processed' },
  { caseId: 'EVAL-011', state: 'processed' },
  { caseId: 'EVAL-004', state: 'received' },
  { caseId: 'EVAL-005', state: 'received' },
  { caseId: 'EVAL-014', state: 'received' },
  { caseId: 'EVAL-019', state: 'received' },
];

const OUTCOME_TO_REQUEST_STATUS: Record<RunOutcome, RequestStatus> = {
  scheduled: 'completed',
  rescheduled: 'completed',
  cancelled_meeting: 'completed',
  no_action: 'completed',
  alternatives_proposed: 'awaiting_reply',
  clarification_requested: 'awaiting_reply',
  escalated: 'escalated',
  declined: 'declined',
};

function clone<T>(value: T): T {
  return structuredClone(value);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Formats an epoch time as a Beirut-offset timestamp. Valid for the fixture dates, when Beirut is UTC+02:00. */
function beirutIso(ms: number): string {
  return `${new Date(ms + 2 * 3_600_000).toISOString().slice(0, 19)}+02:00`;
}

export class MockExecutiveDesk implements ExecutiveDeskApi {
  readonly info: ApiInfo = {
    name: 'Mock adapter',
    dataSource: 'simulated',
    baseUrl: null,
    principal: { name: PRINCIPAL.name, email: PRINCIPAL.email, timezone: PRINCIPAL.timezone },
    simulatedNow: NOW,
  };

  private readonly requests = new Map<string, SecretaryRequest>();
  private readonly requestCase = new Map<string, string>();
  private readonly runs = new Map<string, AgentRun>();
  private readonly approvals = new Map<string, ApprovalRequest>();
  private readonly conversations = new Map<string, Conversation>();
  private readonly messages = new Map<string, ConversationMessage[]>();
  private readonly playback = new Map<string, Playback>();
  private readonly listeners = new Set<() => void>();
  private readonly scriptFor: (caseId: string) => MockScript | undefined;

  private delay: number;
  private clockMs = Date.parse(NOW);
  private counter = 0;
  private inFlight = 0;
  private idleWaiters: (() => void)[] = [];
  private readonly ready: Promise<void>;

  constructor(options: MockOptions = {}) {
    this.delay = options.stepDelayMs ?? 700;
    this.scriptFor = (caseId) => options.scriptFor?.(caseId) ?? MOCK_SCRIPTS[caseId];
    this.ready = options.seed === false ? Promise.resolve() : this.seed();
  }

  // --- public API -------------------------------------------------------------

  async listRequests(filter?: { status?: RequestStatus[] }): Promise<SecretaryRequest[]> {
    await this.ready;
    return [...this.requests.values()]
      .filter((r) => !filter?.status || filter.status.includes(r.status))
      .sort((a, b) => Date.parse(b.receivedAt) - Date.parse(a.receivedAt))
      .map(clone);
  }

  async getRequest(id: string): Promise<SecretaryRequest> {
    await this.ready;
    return clone(this.mustGet(this.requests, id, 'request'));
  }

  async processRequest(id: string): Promise<AgentRun> {
    await this.ready;
    return clone(this.startRequestRun(id));
  }

  async getRun(id: string): Promise<AgentRun> {
    await this.ready;
    return clone(this.mustGet(this.runs, id, 'run'));
  }

  async listRuns(filter?: { requestId?: string; conversationId?: string }): Promise<AgentRun[]> {
    await this.ready;
    return [...this.runs.values()]
      .filter((r) => !filter?.requestId || r.requestId === filter.requestId)
      .filter((r) => !filter?.conversationId || r.conversationId === filter.conversationId)
      .sort((a, b) => Date.parse(b.startedAt) - Date.parse(a.startedAt))
      .map(clone);
  }

  async listApprovals(filter?: { status?: ApprovalStatus[]; runId?: string }): Promise<ApprovalRequest[]> {
    await this.ready;
    return [...this.approvals.values()]
      .filter((a) => !filter?.status || filter.status.includes(a.status))
      .filter((a) => !filter?.runId || a.runId === filter.runId)
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
      .map(clone);
  }

  async decideApproval(id: string, input: ApprovalDecisionInput): Promise<ApprovalRequest> {
    await this.ready;
    return clone(this.decide(id, input));
  }

  async listConversations(): Promise<Conversation[]> {
    await this.ready;
    return [...this.conversations.values()].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)).map(clone);
  }

  async createConversation(): Promise<Conversation> {
    await this.ready;
    return clone(this.newConversation());
  }

  async listMessages(conversationId: string): Promise<ConversationMessage[]> {
    await this.ready;
    this.mustGet(this.conversations, conversationId, 'conversation');
    return clone(this.messages.get(conversationId) ?? []);
  }

  async sendMessage(conversationId: string, text: string): Promise<{ message: ConversationMessage; run: AgentRun }> {
    await this.ready;
    return clone(this.postMessage(conversationId, text));
  }

  async startEvaluationRun(input: EvaluationRunInput): Promise<AgentRun> {
    await this.ready;
    const script = this.scriptFor(input.caseId);
    if (!script) throw new ApiError(`The mock has no script for ${input.caseId}`, 404, 'unknown_case');
    const run = this.newRun('evaluation', null, null, script);
    this.schedule(run.id);
    return clone(run);
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Resolves when no scripted run is mid-step. For tests. */
  async whenIdle(): Promise<void> {
    await this.ready;
    if (this.inFlight === 0) return;
    await new Promise<void>((resolve) => this.idleWaiters.push(resolve));
  }

  // --- clock and ids ------------------------------------------------------------

  private now(): string {
    return beirutIso(this.clockMs);
  }

  private tick(ms: number): void {
    this.clockMs += ms;
  }

  private id(prefix: string): string {
    this.counter += 1;
    return `${prefix}-${String(this.counter).padStart(4, '0')}`;
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }

  private async wait(): Promise<void> {
    if (this.delay > 0) await sleep(this.delay);
  }

  private mustGet<T>(map: Map<string, T>, id: string, kind: string): T {
    const value = map.get(id);
    if (!value) throw new ApiError(`No ${kind} with id ${id}`, 404, 'not_found');
    return value;
  }

  // --- seeding ------------------------------------------------------------------

  private async seed(): Promise<void> {
    const realDelay = this.delay;
    this.delay = 0;

    const plan = SEED_PLAN.map((entry) => {
      const found = EVALUATION_CASES.find((c) => c.id === entry.caseId);
      if (!found || found.input.kind !== 'email') throw new Error(`Seed case ${entry.caseId} must be an email case`);
      return { ...entry, email: found.input.email };
    }).sort((a, b) => Date.parse(a.email.sentAt) - Date.parse(b.email.sentAt));

    for (const { caseId, state, email } of plan) {
      const requestId = `req-${caseId.slice(-3)}`;
      this.requests.set(requestId, {
        id: requestId,
        source: 'email',
        receivedAt: email.sentAt,
        from: email.from,
        subject: email.subject,
        bodyText: email.bodyText,
        threadId: email.threadId,
        classification: null,
        priority: null,
        status: 'received',
        flags: [],
        extracted: null,
        runIds: [],
        duplicateOfRequestId: null,
        history: [{ at: email.sentAt, actor: 'system', event: 'Received', detail: 'Arrived in the inbox.' }],
      });
      this.requestCase.set(requestId, caseId);
      if (state === 'received') continue;

      this.clockMs = Math.max(this.clockMs, Date.parse(email.sentAt)) + 45_000;
      const run = this.startRequestRun(requestId);
      await this.settle();
      if (state === 'approved') {
        for (const approvalId of run.approvalIds) {
          this.tick(90_000);
          this.decide(approvalId, { decision: 'approve', decidedBy: PRINCIPAL.name });
          await this.settle();
        }
      }
    }

    // One conversation with a request already in progress, so the chat screen is not empty.
    const conversation = this.newConversation();
    this.postMessage(conversation.id, 'Find 45 minutes this week for me, Omar and Rana to go over the Q1 hiring plan. Mornings preferred.');
    await this.settle();

    this.clockMs = Math.max(this.clockMs, Date.parse(NOW));
    this.delay = realDelay;
  }

  private async settle(): Promise<void> {
    if (this.inFlight === 0) return;
    await new Promise<void>((resolve) => this.idleWaiters.push(resolve));
  }

  // --- runs ---------------------------------------------------------------------

  private newRun(trigger: AgentRun['trigger'], requestId: string | null, conversationId: string | null, script: MockScript): AgentRun {
    const run: AgentRun = {
      id: this.id('run'),
      trigger,
      requestId,
      conversationId,
      status: 'running',
      outcome: null,
      triage: null,
      summary: null,
      assistantMessage: null,
      actions: [],
      approvalIds: [],
      startedAt: this.now(),
      finishedAt: null,
      durationMs: null,
      usage: null, // the mock calls no model, so there is nothing to report
      error: null,
      humanInterventions: [],
    };
    this.runs.set(run.id, run);
    this.playback.set(run.id, { script, cursor: 0, gate: null });
    return run;
  }

  private startRequestRun(requestId: string): AgentRun {
    const request = this.mustGet(this.requests, requestId, 'request');
    if (request.status === 'processing' || request.status === 'awaiting_approval') {
      throw new ApiError('This request is already being handled.', 409, 'already_processing');
    }
    const caseId = this.requestCase.get(requestId);
    const script = caseId ? this.scriptFor(caseId) : undefined;
    if (!script) throw new ApiError('The mock has no script for this request.', 404, 'unknown_case');

    const run = this.newRun('incoming_email', requestId, null, script);
    request.status = 'processing';
    request.runIds.unshift(run.id);
    this.log(request, 'agent', 'Processing started', null);
    this.emit();
    this.schedule(run.id);
    return run;
  }

  private schedule(runId: string): void {
    this.inFlight += 1;
    void this.play(runId).finally(() => {
      this.inFlight -= 1;
      if (this.inFlight === 0) {
        const waiters = this.idleWaiters;
        this.idleWaiters = [];
        for (const resolve of waiters) resolve();
      }
    });
  }

  private async play(runId: string): Promise<void> {
    const run = this.runs.get(runId);
    const pb = this.playback.get(runId);
    if (!run || !pb) return;

    if (!run.triage) {
      await this.wait();
      this.tick(900);
      run.triage = clone(pb.script.triage);
      const request = run.requestId ? this.requests.get(run.requestId) : undefined;
      if (request) {
        request.classification = run.triage.classification;
        request.priority = run.triage.priority;
        request.flags = [...run.triage.flags];
        request.extracted = clone(run.triage.extracted);
        this.log(request, 'agent', 'Classified', `${run.triage.classification.replace(/_/g, ' ')}, ${run.triage.priority} priority`);
      }
      this.emit();
    }

    while (pb.cursor < pb.script.steps.length) {
      const step = pb.script.steps[pb.cursor];
      if (step.type === 'hang') return; // deliberately never finishes
      pb.cursor += 1;
      if (step.type === 'action') {
        await this.runAction(run, pb, step);
      } else if (step.type === 'approval') {
        this.openApproval(run, pb, step);
        return;
      } else {
        this.finishRun(run, step);
        return;
      }
    }
  }

  private newAction(run: AgentRun, tool: ToolName, summary: string, input: Record<string, unknown>, approvalId: string | null): AgentAction {
    const action: AgentAction = {
      id: this.id('act'),
      runId: run.id,
      sequence: run.actions.length + 1,
      tool,
      sideEffect: isSideEffectTool(tool),
      status: 'planned',
      summary,
      input,
      output: null,
      startedAt: null,
      finishedAt: null,
      durationMs: null,
      approvalId,
      error: null,
      simulated: true,
    };
    run.actions.push(action);
    return action;
  }

  private async runAction(run: AgentRun, pb: Playback, step: ActionStep): Promise<void> {
    const sideEffect = isSideEffectTool(step.tool);
    let action = sideEffect
      ? run.actions.find((a) => a.status === 'awaiting_approval' && a.tool === step.tool && a.approvalId === pb.gate)
      : undefined;
    if (!action) action = this.newAction(run, step.tool, step.summary, step.input, sideEffect ? pb.gate : null);

    action.status = 'running';
    action.input = clone(step.input);
    action.startedAt = this.now();
    this.emit();

    await this.wait();
    this.tick(step.durationMs);
    action.finishedAt = this.now();
    action.durationMs = step.durationMs;
    action.summary = step.summary;
    action.simulated = step.simulated;
    if (step.fail) {
      action.status = 'failed';
      action.error = clone(step.fail);
    } else {
      action.status = 'succeeded';
      action.output = clone(step.output);
    }
    this.emit();
  }

  private openApproval(run: AgentRun, pb: Playback, step: ApprovalStep): void {
    this.tick(300);
    const approval: ApprovalRequest = {
      id: this.id('apr'),
      runId: run.id,
      requestId: run.requestId,
      conversationId: run.conversationId,
      title: step.title,
      explanation: step.explanation,
      riskNotes: [...step.riskNotes],
      changes: clone(step.changes),
      status: 'pending',
      createdAt: this.now(),
      decidedAt: null,
      decidedBy: null,
      decisionNote: null,
      execution: { status: 'not_started', finishedAt: null, error: null, simulated: true },
    };
    this.approvals.set(approval.id, approval);
    run.approvalIds.push(approval.id);
    pb.gate = approval.id;

    const ask = this.newAction(run, 'approval.request', `Asked for approval: ${step.title}`, { approvalId: approval.id }, null);
    ask.status = 'succeeded';
    ask.startedAt = ask.finishedAt = this.now();
    ask.durationMs = 0;
    ask.output = { approvalId: approval.id };

    for (const change of step.changes) {
      const planned = this.newAction(run, change.tool, summaryForChange(change, 'future'), inputForChange(change), approval.id);
      planned.status = 'awaiting_approval';
    }

    run.status = 'awaiting_approval';
    const request = run.requestId ? this.requests.get(run.requestId) : undefined;
    if (request) {
      request.status = 'awaiting_approval';
      this.log(request, 'agent', 'Approval requested', step.title);
    }
    this.settleChatMessage(run, `${step.explanation}\n\nApprove below and I will go ahead.`);
    this.emit();
  }

  private finishRun(run: AgentRun, step: FinishStep): void {
    for (const action of run.actions) {
      if (action.status === 'awaiting_approval' || action.status === 'planned') action.status = 'skipped';
    }
    run.status = step.status;
    run.outcome = step.outcome;
    run.summary = step.summary;
    run.assistantMessage = step.assistantMessage;
    run.error = clone(step.error);
    run.finishedAt = this.now();
    run.durationMs = Date.parse(run.finishedAt) - Date.parse(run.startedAt);
    for (const intervention of step.humanInterventions) {
      run.humanInterventions.push({ at: this.now(), ...intervention });
    }

    for (const approvalId of run.approvalIds) {
      const approval = this.approvals.get(approvalId);
      if (!approval || approval.execution.status !== 'executing') continue;
      const mine = run.actions.filter((a) => a.approvalId === approvalId);
      const failed = approval.changes.some((change) => {
        const last = mine.filter((a) => a.tool === change.tool).at(-1);
        return !last || last.status !== 'succeeded';
      });
      approval.execution.status = failed ? 'failed' : 'executed';
      approval.execution.finishedAt = this.now();
      approval.execution.error = failed ? clone(run.error) : null;
    }

    const request = run.requestId ? this.requests.get(run.requestId) : undefined;
    if (request) {
      request.status = step.outcome ? OUTCOME_TO_REQUEST_STATUS[step.outcome] : 'failed';
      this.log(request, 'agent', step.status === 'failed' ? 'Run failed' : 'Finished', step.summary);
    }
    this.settleChatMessage(run, step.assistantMessage ?? step.summary);
    this.emit();
  }

  // --- approvals ------------------------------------------------------------------

  private decide(id: string, input: ApprovalDecisionInput): ApprovalRequest {
    const approval = this.mustGet(this.approvals, id, 'approval');
    if (approval.status !== 'pending') {
      throw new ApiError(`This approval was already ${approval.status}.`, 409, 'already_decided');
    }
    const run = this.mustGet(this.runs, approval.runId, 'run');
    const request = run.requestId ? this.requests.get(run.requestId) : undefined;

    this.tick(1_000);
    approval.status = input.decision === 'approve' ? 'approved' : 'rejected';
    approval.decidedAt = this.now();
    approval.decidedBy = input.decidedBy;
    approval.decisionNote = input.note ?? null;
    run.humanInterventions.push({ at: this.now(), kind: 'approval', by: input.decidedBy, note: input.note ?? null });

    if (input.decision === 'approve') {
      approval.execution.status = 'executing';
      run.status = 'running';
      if (request) {
        request.status = 'processing';
        this.log(request, 'human', 'Approved', `${input.decidedBy} approved "${approval.title}".`);
      }
      this.emit();
      this.schedule(run.id);
      return approval;
    }

    for (const action of run.actions) {
      if (action.approvalId === id && action.status === 'awaiting_approval') action.status = 'rejected';
    }
    const pb = this.playback.get(run.id);
    if (pb) pb.cursor = pb.script.steps.length;
    const summary = 'The proposal was rejected. No email was sent and the calendar was not changed.';
    run.status = 'completed';
    run.outcome = 'declined';
    run.summary = summary;
    run.assistantMessage = run.conversationId ? 'Understood. I have not sent anything or changed your calendar.' : null;
    run.finishedAt = this.now();
    run.durationMs = Date.parse(run.finishedAt) - Date.parse(run.startedAt);
    if (request) {
      request.status = 'declined';
      this.log(request, 'human', 'Rejected', `${input.decidedBy} rejected "${approval.title}".${input.note ? ` Note: ${input.note}` : ''}`);
    }
    this.settleChatMessage(run, run.assistantMessage ?? summary);
    this.emit();
    return approval;
  }

  // --- chat -----------------------------------------------------------------------

  private newConversation(): Conversation {
    const conversation: Conversation = {
      id: this.id('conv'),
      title: 'New conversation',
      createdAt: this.now(),
      updatedAt: this.now(),
      lastMessagePreview: null,
    };
    this.conversations.set(conversation.id, conversation);
    this.messages.set(conversation.id, []);
    this.emit();
    return conversation;
  }

  private addMessage(conversationId: string, role: ConversationMessage['role'], text: string, runId: string | null, status: ConversationMessage['status']): ConversationMessage {
    const conversation = this.mustGet(this.conversations, conversationId, 'conversation');
    const message: ConversationMessage = { id: this.id('msg'), conversationId, role, createdAt: this.now(), text, runId, status };
    this.messages.get(conversationId)!.push(message);
    conversation.updatedAt = message.createdAt;
    if (text) conversation.lastMessagePreview = text.slice(0, 120);
    return message;
  }

  private postMessage(conversationId: string, text: string): { message: ConversationMessage; run: AgentRun } {
    const trimmed = text.trim();
    if (!trimmed) throw new ApiError('A message cannot be empty.', 400, 'empty_message');
    const conversation = this.mustGet(this.conversations, conversationId, 'conversation');
    const thread = this.messages.get(conversationId)!;
    if (thread.length === 0) conversation.title = trimmed.length > 48 ? `${trimmed.slice(0, 47)}…` : trimmed;

    this.tick(1_000);
    const pending = [...this.approvals.values()].filter((a) => a.status === 'pending');
    const run = this.newRun('chat_message', null, conversationId, scriptForChat(trimmed, pending));
    const message = this.addMessage(conversationId, 'user', trimmed, run.id, 'final');
    this.addMessage(conversationId, 'assistant', '', run.id, 'streaming');
    this.emit();
    this.schedule(run.id);
    return { message, run };
  }

  /** Writes the assistant's text for a chat run: fills the streaming placeholder first, then appends. */
  private settleChatMessage(run: AgentRun, text: string): void {
    if (!run.conversationId) return;
    const thread = this.messages.get(run.conversationId);
    const conversation = this.conversations.get(run.conversationId);
    if (!thread || !conversation) return;
    const placeholder = thread.find((m) => m.role === 'assistant' && m.runId === run.id && m.status === 'streaming');
    if (placeholder) {
      placeholder.text = text;
      placeholder.status = 'final';
      placeholder.createdAt = this.now();
      conversation.updatedAt = placeholder.createdAt;
      conversation.lastMessagePreview = text.slice(0, 120);
    } else {
      this.addMessage(run.conversationId, 'assistant', text, null, 'final');
    }
  }

  private log(request: SecretaryRequest, actor: 'agent' | 'human' | 'system', event: string, detail: string | null): void {
    request.history.push({ at: this.now(), actor, event, detail });
  }
}
