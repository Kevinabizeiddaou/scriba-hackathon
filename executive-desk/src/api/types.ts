/**
 * Scriba Executive Desk: API contract, version 1.0.0 (frozen).
 *
 * This file is the single source of truth for every shape that crosses the
 * frontend/backend boundary; docs/API_CONTRACT.md is its written form. The
 * contract is frozen from the frontend side: from here on it changes only through
 * the change log in that document, with a version bump. The points Role 1 still has
 * to confirm are listed in docs/handoff/ASSUMPTIONS.md.
 *
 * Conventions
 * - All timestamps are RFC 3339 strings with an explicit offset ("2026-11-17T11:00:00+02:00").
 * - All ids are opaque strings.
 * - Nullable fields are always present and set to null; they are never omitted.
 */

export type ISODateTime = string;
export type IanaTimeZone = string;

/** Where the numbers on screen came from. "simulated" data must never be reported as agent performance. */
export type DataSource = 'simulated' | 'live';

// ---------------------------------------------------------------------------
// Versioning and handshake
// ---------------------------------------------------------------------------

/**
 * Semantic version of this contract. The major number is also in the URL (/v1).
 * Major: a breaking change. Minor: new optional fields or endpoints. Patch: wording only.
 */
export const CONTRACT_VERSION = '1.0.0';
/** Sent by the client on every request and by the server on every response. */
export const CONTRACT_HEADER = 'X-Executive-Desk-Contract';
/** Sent by the client on every POST. See "Idempotency" in docs/API_CONTRACT.md. */
export const IDEMPOTENCY_HEADER = 'Idempotency-Key';

/** GET /meta: what is behind the URL. The first call a client makes. */
export interface DeskMeta {
  contractVersion: string;
  /** Name of the service, for display and for reports. */
  service: string;
  /**
   * "real" when a model-driven agent produces the runs; "scripted" for a stand-in such as
   * the reference server. Clients label everything from a scripted service as simulated.
   */
  agent: 'real' | 'scripted';
  /** True when the service cannot reach real mailboxes or calendars. */
  sandbox: boolean;
  principal: Participant & { timezone: IanaTimeZone };
  /** The service's fixed clock when it has one (sandbox fixtures); null when it runs on real time. */
  simulatedNow: ISODateTime | null;
  capabilities: {
    /** POST /evaluation/runs is available. */
    evaluation: boolean;
    /** Evaluation runs honour CaseContext.faults. Without it, the two API-failure cases are skipped. */
    faultInjection: boolean;
    /** The conversation endpoints are available. */
    chat: boolean;
    /** Runs report token usage. Without it, cost per run cannot be computed. */
    tokenUsage: boolean;
  };
}

// ---------------------------------------------------------------------------
// People and calendar
// ---------------------------------------------------------------------------

export interface Participant {
  name: string;
  email: string;
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: ISODateTime;
  end: ISODateTime;
  timezone: IanaTimeZone;
  attendees: Participant[];
  location: string | null;
  description: string | null;
  status: 'confirmed' | 'tentative' | 'cancelled';
}

/** An event the agent proposes to create, or the new state of an event it proposes to change. */
export interface CalendarEventDraft {
  title: string;
  start: ISODateTime;
  end: ISODateTime;
  timezone: IanaTimeZone;
  attendees: Participant[];
  location: string | null;
  description: string | null;
}

export interface TimeSlot {
  start: ISODateTime;
  end: ISODateTime;
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

/**
 * Canonical tool vocabulary used in traces and in evaluation expectations.
 * The real backend may use different names; the HTTP adapter maps them through
 * `toolAliases` (see src/api/httpAdapter.ts).
 */
export const TOOL_NAMES = [
  'email.read_thread',
  'email.search',
  'email.send',
  'calendar.list_events',
  'calendar.find_free_slots',
  'calendar.create_event',
  'calendar.update_event',
  'calendar.cancel_event',
  'approval.request',
  'audit.record',
] as const;
export type ToolName = (typeof TOOL_NAMES)[number];

/** Tools that change the outside world. Every one of them needs an approved ApprovalRequest before it runs. */
export const SIDE_EFFECT_TOOLS = [
  'email.send',
  'calendar.create_event',
  'calendar.update_event',
  'calendar.cancel_event',
] as const;
export type SideEffectTool = (typeof SIDE_EFFECT_TOOLS)[number];

export function isSideEffectTool(tool: string): tool is SideEffectTool {
  return (SIDE_EFFECT_TOOLS as readonly string[]).includes(tool);
}

// ---------------------------------------------------------------------------
// SecretaryRequest
// ---------------------------------------------------------------------------

export const REQUEST_CLASSIFICATIONS = ['new_meeting', 'reschedule', 'cancellation', 'availability_query', 'unclear', 'not_meeting_related'] as const;
export type RequestClassification = (typeof REQUEST_CLASSIFICATIONS)[number];

export const REQUEST_PRIORITIES = ['urgent', 'high', 'normal', 'low'] as const;
export type RequestPriority = (typeof REQUEST_PRIORITIES)[number];

/**
 * received:          in the inbox, not yet picked up by the agent
 * processing:        an agent run is working on it
 * awaiting_approval: the agent proposed side effects and is waiting for a human decision
 * awaiting_reply:    the agent replied (clarification or alternatives) and is waiting for the requester
 * completed:         nothing further to do
 * escalated:         handed to a human; the agent will not act further
 * declined:          a human rejected the proposal
 * failed:            the run failed and nothing was handed over
 */
export const REQUEST_STATUSES = ['received', 'processing', 'awaiting_approval', 'awaiting_reply', 'completed', 'escalated', 'declined', 'failed'] as const;
export type RequestStatus = (typeof REQUEST_STATUSES)[number];

export const REQUEST_FLAGS = ['prompt_injection_suspected', 'duplicate', 'timezone_ambiguous', 'unverified_sender', 'outside_working_hours'] as const;
export type RequestFlag = (typeof REQUEST_FLAGS)[number];

export interface ExtractedMeetingDetails {
  title: string | null;
  attendees: Participant[];
  durationMinutes: number | null;
  /** Windows the requester offered, already converted to absolute instants. */
  requestedWindows: TimeSlot[];
  /** Time zone the requester wrote in, when they stated one. */
  requesterTimezone: IanaTimeZone | null;
  location: string | null;
  modality: 'in_person' | 'video' | 'phone' | null;
  /** Existing event this request refers to (reschedule and cancellation). */
  referencedEventId: string | null;
  /** Names of details the agent still needs, for example "time zone". */
  missingFields: string[];
  notes: string | null;
}

export interface RequestHistoryEntry {
  at: ISODateTime;
  actor: 'agent' | 'human' | 'system';
  event: string;
  detail: string | null;
}

export interface SecretaryRequest {
  id: string;
  source: 'email' | 'chat';
  receivedAt: ISODateTime;
  from: Participant;
  subject: string;
  bodyText: string;
  threadId: string | null;
  classification: RequestClassification | null;
  priority: RequestPriority | null;
  status: RequestStatus;
  flags: RequestFlag[];
  extracted: ExtractedMeetingDetails | null;
  /** Most recent run first. */
  runIds: string[];
  duplicateOfRequestId: string | null;
  history: RequestHistoryEntry[];
}

// ---------------------------------------------------------------------------
// AgentRun and AgentAction
// ---------------------------------------------------------------------------

export const RUN_STATUSES = ['queued', 'running', 'awaiting_approval', 'completed', 'failed', 'cancelled'] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

export const TERMINAL_RUN_STATUSES: readonly RunStatus[] = ['completed', 'failed', 'cancelled'];

export const RUN_OUTCOMES = ['scheduled', 'rescheduled', 'cancelled_meeting', 'alternatives_proposed', 'clarification_requested', 'no_action', 'escalated', 'declined'] as const;
export type RunOutcome = (typeof RUN_OUTCOMES)[number];

export interface RunError {
  /** Stable machine code, for example "calendar_unavailable" or "model_error". */
  code: string;
  message: string;
  source: 'tool' | 'model' | 'backend';
  retryable: boolean;
}

/** Tokens one model consumed during a run, summed over every call to that model. */
export interface ModelUsage {
  /** Model identifier exactly as the provider names it. It is the key into the price table. */
  model: string;
  /** Number of requests made to this model in the run. */
  calls: number;
  /** Uncached input tokens only. Cached input is counted separately because it is billed differently. */
  inputTokens: number;
  outputTokens: number;
  /** Input tokens served from a prompt cache. Null when the provider does not report it. */
  cachedInputTokens: number | null;
}

/** Token usage of one run. One entry per model, so an agent that uses two models is priced correctly. */
export interface TokenUsage {
  models: ModelUsage[];
  /** Cost of the whole run computed by the backend, when it knows its own pricing. Null means "not reported". */
  estimatedCostUsd: number | null;
}

export interface HumanIntervention {
  at: ISODateTime;
  /**
   * approval: a mandatory approve/reject decision. Expected, not a rescue.
   * edit:     a human changed the agent's proposal before approving it.
   * rescue:   a human fixed, retried or completed something the agent could not.
   * takeover: a human finished the request by hand.
   */
  kind: 'approval' | 'edit' | 'rescue' | 'takeover';
  by: string;
  note: string | null;
}

export interface RunTriage {
  classification: RequestClassification;
  priority: RequestPriority;
  flags: RequestFlag[];
  extracted: ExtractedMeetingDetails | null;
}

/** rejected: its approval was rejected, it never ran. skipped: it never ran for another reason. */
export const ACTION_STATUSES = ['planned', 'awaiting_approval', 'running', 'succeeded', 'failed', 'rejected', 'skipped'] as const;
export type ActionStatus = (typeof ACTION_STATUSES)[number];

/** Statuses that mean the tool call actually went out. */
export const EXECUTED_ACTION_STATUSES: readonly ActionStatus[] = ['running', 'succeeded', 'failed'];

export interface AgentAction {
  id: string;
  runId: string;
  /**
   * Position in the trace, starting at 1. Actions that have started come first, in the order
   * they started; actions still waiting follow. The scorer falls back to it when timestamps tie.
   */
  sequence: number;
  tool: ToolName;
  sideEffect: boolean;
  status: ActionStatus;
  /** One line a non-technical reader understands: "Checked Tuesday 17 Nov: 11:00 is free". */
  summary: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  startedAt: ISODateTime | null;
  finishedAt: ISODateTime | null;
  durationMs: number | null;
  /** Approval that gates this action. Required on every side-effect action. */
  approvalId: string | null;
  /**
   * Identifies the one real-world effect this action is meant to have. Required on every
   * side-effect action; null on reads. A retry of the same effect carries the same key, and the
   * backend passes it to the provider so that a retry can never send or create twice.
   */
  idempotencyKey: string | null;
  error: RunError | null;
  /** True when no real email or calendar change was made (mock adapter, sandbox or evaluation mode). */
  simulated: boolean;
}

export interface AgentRun {
  id: string;
  trigger: 'incoming_email' | 'chat_message' | 'evaluation';
  requestId: string | null;
  conversationId: string | null;
  status: RunStatus;
  outcome: RunOutcome | null;
  triage: RunTriage | null;
  /** What the agent did, in one or two sentences. */
  summary: string | null;
  /** The reply shown to the principal in chat, when the run was started from chat. */
  assistantMessage: string | null;
  actions: AgentAction[];
  approvalIds: string[];
  startedAt: ISODateTime;
  finishedAt: ISODateTime | null;
  durationMs: number | null;
  usage: TokenUsage | null;
  error: RunError | null;
  humanInterventions: HumanIntervention[];
}

// ---------------------------------------------------------------------------
// ApprovalRequest
// ---------------------------------------------------------------------------

export type ProposedChange =
  | {
      type: 'email';
      tool: 'email.send';
      to: string[];
      cc: string[];
      subject: string;
      bodyText: string;
      threadId: string | null;
      /** Machine-readable copy of any time options offered in the body. */
      proposedSlots: TimeSlot[];
    }
  | { type: 'calendar_create'; tool: 'calendar.create_event'; event: CalendarEventDraft }
  | {
      type: 'calendar_update';
      tool: 'calendar.update_event';
      eventId: string;
      before: CalendarEvent;
      after: CalendarEventDraft;
    }
  | {
      type: 'calendar_cancel';
      tool: 'calendar.cancel_event';
      eventId: string;
      event: CalendarEvent;
      notifyAttendees: boolean;
    };

export const APPROVAL_STATUSES = ['pending', 'approved', 'rejected', 'expired'] as const;
export type ApprovalStatus = (typeof APPROVAL_STATUSES)[number];
export const APPROVAL_EXECUTION_STATUSES = ['not_started', 'executing', 'executed', 'failed'] as const;
export type ApprovalExecutionStatus = (typeof APPROVAL_EXECUTION_STATUSES)[number];

export interface ApprovalRequest {
  id: string;
  runId: string;
  requestId: string | null;
  conversationId: string | null;
  /** Short imperative title: "Book intro call and confirm with Sofia". */
  title: string;
  /** Why the agent wants to do this, in plain language. */
  explanation: string;
  /** Anything the approver should double-check. */
  riskNotes: string[];
  /** One approval covers one or more changes that are executed together. */
  changes: ProposedChange[];
  status: ApprovalStatus;
  createdAt: ISODateTime;
  /** When a pending approval lapses into "expired". Null when approvals do not expire. */
  expiresAt: ISODateTime | null;
  decidedAt: ISODateTime | null;
  decidedBy: string | null;
  decisionNote: string | null;
  execution: {
    status: ApprovalExecutionStatus;
    finishedAt: ISODateTime | null;
    error: RunError | null;
    /** True when execution made no real email or calendar change. */
    simulated: boolean;
  };
}

export interface ApprovalDecisionInput {
  decision: 'approve' | 'reject';
  /**
   * Display name of the person deciding. A backend with authentication records the
   * authenticated identity instead and treats this as a fallback.
   */
  decidedBy: string;
  note?: string | null;
}

// ---------------------------------------------------------------------------
// Conversation
// ---------------------------------------------------------------------------

export interface Conversation {
  id: string;
  title: string;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
  lastMessagePreview: string | null;
}

export interface ConversationMessage {
  id: string;
  conversationId: string;
  role: 'user' | 'assistant';
  createdAt: ISODateTime;
  text: string;
  /**
   * Run that produced this message (assistant) or that it started (user).
   * The UI renders that run's actions and approvals as cards under the message.
   */
  runId: string | null;
  /** "streaming" while the run is still working; the text may still change. */
  status: 'streaming' | 'final';
}

// ---------------------------------------------------------------------------
// Evaluation: cases
// ---------------------------------------------------------------------------

export type CaseCategory =
  | 'straightforward'
  | 'conflict'
  | 'alternatives'
  | 'unclear'
  | 'timezone'
  | 'rescheduling'
  | 'cancellation'
  | 'duplicate'
  | 'api_failure'
  | 'prompt_injection';

export interface SampleEmail {
  id: string;
  threadId: string;
  from: Participant;
  to: Participant[];
  cc: Participant[];
  sentAt: ISODateTime;
  subject: string;
  bodyText: string;
}

export type CaseInput =
  | {
      kind: 'email';
      /** The message that triggers the run. */
      email: SampleEmail;
      /** Earlier messages in the same thread, oldest first. */
      thread: SampleEmail[];
    }
  | {
      kind: 'conversation';
      /** Chat turns from the principal, oldest first. The last one triggers the run. */
      messages: { role: 'user' | 'assistant'; text: string }[];
    };

export interface FaultInjection {
  tool: ToolName;
  /** fail_times: fail the first `times` calls, then succeed. fail_always: never succeed. */
  mode: 'fail_times' | 'fail_always';
  times: number | null;
  error: { code: string; httpStatus: number; message: string };
}

export interface CaseContext {
  /** The moment the request arrives. The sandbox clock is set to this. */
  now: ISODateTime;
  principal: Participant & {
    timezone: IanaTimeZone;
    workingHours: { days: number[]; start: string; end: string }; // days: 1 = Monday ... 7 = Sunday
  };
  /** The principal's calendar when the request arrives. */
  calendar: CalendarEvent[];
  /** Tool failures the sandbox must simulate. Empty for most cases. */
  faults: FaultInjection[];
}

/**
 * Matchers for tool arguments. A bare string, number, boolean or null means deep equality,
 * except that two RFC 3339 timestamps are compared as instants.
 */
export type ArgMatcher =
  | string
  | number
  | boolean
  | null
  | { $instant: ISODateTime }
  | { $instantBetween: [ISODateTime, ISODateTime] }
  | { $localTimeBetween: { timezone: IanaTimeZone; from: string; to: string } }
  | { $contains: string }
  | { $matches: string }
  | { $includes: string[] }
  | { $excludes: string[] }
  | { $all: ArgMatcher[] };

export interface ExpectedToolCall {
  /** One tool, or several of which any one satisfies the expectation. */
  tool: ToolName | ToolName[];
  /** Matched against the top-level keys of AgentAction.input. */
  args?: Record<string, ArgMatcher>;
  /** Action status that counts. Defaults to "succeeded". */
  status?: ActionStatus;
  /** How many matching calls must exist. Defaults to at least 1 and no upper bound. */
  min?: number;
  max?: number;
  /** For calendar writes: required length of the resulting event. */
  eventDurationMinutes?: number;
  why: string;
}

export interface ForbiddenToolCall {
  tool: ToolName;
  args?: Record<string, ArgMatcher>;
  /** When true, even proposing the call in an approval request fails the case. */
  includeProposed: boolean;
  why: string;
}

export interface ExpectedApproval {
  tool: SideEffectTool;
  /** Optional approvals may be requested or not; required ones must be. */
  optional: boolean;
  reason: string;
}

export interface TextExpectation {
  /** Case-insensitive regular expressions that must each match. */
  mustMatch: { pattern: string; description: string }[];
  /** Case-insensitive regular expressions that must not match. */
  mustNotMatch: { pattern: string; description: string }[];
}

export interface CaseExpectation {
  /** Prose description of what a good executive secretary does here. */
  behavior: string;
  /** Acceptable classifications; any one passes. */
  classifications: RequestClassification[];
  /** Acceptable outcomes; any one passes. */
  outcomes: RunOutcome[];
  /** Acceptable terminal run statuses. Normally just "completed". */
  runStatuses: RunStatus[];
  toolCalls: ExpectedToolCall[];
  /** Extra tool-call expectations that apply only when the run ends with the given outcome. */
  whenOutcome: Partial<Record<RunOutcome, { toolCalls: ExpectedToolCall[] }>>;
  forbidden: ForbiddenToolCall[];
  /** Pairs [earlier, later]: the first successful call of `earlier` must precede the first of `later`. */
  order: [ToolName, ToolName][];
  /** Side effects that need human approval. The harness plays the human and applies `harnessDecision`. */
  approvals: ExpectedApproval[];
  harnessDecision: 'approve' | 'reject';
  /**
   * Checked against the agent's outbound emails: every address in `to` must receive one,
   * every mustMatch pattern must match at least one, and no mustNotMatch pattern may match any.
   * `scope` says which emails count: only those actually sent, or also those put up for approval.
   * Quoted text from the original email is ignored when matching.
   */
  outboundEmail: (TextExpectation & { to: string[]; scope: 'sent' | 'sent_or_proposed' }) | null;
  /** When alternatives are offered: how many machine-readable slots email.send must carry. */
  proposedSlots: { min: number } | null;
  /** Checked against AgentRun.assistantMessage. */
  chatReply: TextExpectation | null;
  /** Flags the triage must raise. */
  flags: RequestFlag[];
}

/**
 * synthetic:  invented for development. Every person, company and calendar entry is made up.
 * real_world: derived from a real request. It must be anonymised, and someone must have
 *             agreed to its use; both facts are recorded here and checked when a set is loaded.
 */
export type CaseProvenance =
  | { kind: 'synthetic'; note: string }
  | { kind: 'real_world'; source: string; anonymized: true; consentReference: string };

export interface EvaluationCase {
  id: string;
  title: string;
  category: CaseCategory;
  tags: string[];
  /** Where the case comes from. Synthetic fixtures and real-world cases are never mixed in one set. */
  provenance: CaseProvenance;
  description: string;
  input: CaseInput;
  context: CaseContext;
  expected: CaseExpectation;
  successCriteria: string[];
  failureConditions: string[];
}

/** Body of POST /evaluation/runs. */
export interface EvaluationRunInput {
  caseId: string;
  input: CaseInput;
  context: CaseContext;
  /** The backend must not touch real mailboxes or calendars in this mode. */
  mode: 'sandbox';
}

// ---------------------------------------------------------------------------
// Evaluation: results
// ---------------------------------------------------------------------------

export type Verdict = 'pass' | 'fail' | 'error' | 'skipped';

export interface CheckResult {
  id: string;
  label: string;
  /**
   * True for checks that apply to every case and guard against harm (approval gate, sandbox,
   * double booking, recipients, leaks). A failed safety check fails the case even when the run
   * itself crashed or timed out.
   */
  safety: boolean;
  passed: boolean;
  expected: string;
  actual: string;
}

export interface EvaluationError {
  source: 'harness' | 'backend' | 'model' | 'tool';
  code: string;
  message: string;
}

export interface EvaluationResult {
  caseId: string;
  caseTitle: string;
  category: CaseCategory;
  /** Whether the case is a synthetic fixture or derived from a real request. */
  provenance: CaseProvenance['kind'];
  /** Whether a real agent produced the run ("live") or a scripted stand-in ("simulated"). */
  dataSource: DataSource;
  /**
   * pass:    every check passed (see `human.rescued` for whether a person helped).
   * fail:    the run finished but at least one check failed.
   * error:   the run could not be scored (API error, model error, timeout).
   * skipped: the case was not executed.
   */
  verdict: Verdict;
  checks: CheckResult[];
  expected: { classification: string; outcomes: string[]; tools: string[]; approvals: string[] };
  actual: { classification: string | null; outcome: string | null; runStatus: string | null; tools: string[]; approvals: string[] };
  human: {
    /** Approvals the case requires and the harness granted. Expected; not a rescue. */
    mandatoryApprovals: number;
    /** Approval requests the case did not call for. The harness rejects them. */
    unexpectedApprovals: number;
    /** Approvals the backend returned that belong to another run. The harness never decides these. */
    foreignApprovals: number;
    /** True when a person edited, retried or completed something for the agent. */
    rescued: boolean;
    interventions: HumanIntervention[];
  };
  errors: EvaluationError[];
  timing: {
    startedAt: ISODateTime;
    finishedAt: ISODateTime;
    /** Measured by the harness from start request to terminal status. */
    wallClockMs: number;
    /** AgentRun.durationMs as reported by the backend. */
    agentReportedMs: number | null;
  };
  usage: TokenUsage | null;
  estimatedCostUsd: number | null;
  costSource: 'backend' | 'price_table' | null;
  /** Full trace for the detail view. */
  run: AgentRun | null;
  approvals: ApprovalRequest[];
  skipReason: string | null;
}

export interface EvaluationSummary {
  total: number;
  executed: number;
  passed: number;
  /** Passed with no human rescue. This is the number the pass rate is built on. */
  passedUnassisted: number;
  failed: number;
  errored: number;
  skipped: number;
  rescued: number;
  mandatoryApprovals: number;
  unexpectedApprovals: number;
  /** passedUnassisted / executed. Null until at least one case has been executed. */
  passRate: number | null;
  latency: { medianMs: number; p95Ms: number; meanMs: number } | null;
  casesWithUsage: number;
  totalInputTokens: number | null;
  totalOutputTokens: number | null;
  casesWithCost: number;
  totalCostUsd: number | null;
  /** totalCostUsd / casesWithCost. Null until the backend reports usage and pricing is known. */
  costPerRunUsd: number | null;
}

/** Which set of cases a report covers. A snapshot must cover the whole set. */
export interface CaseSetInfo {
  id: string;
  /** Every case in a set has the same kind of provenance, so a report is about one or the other. */
  provenance: CaseProvenance['kind'];
  /** Number of cases in the full set, whether or not this report ran them all. */
  caseCount: number;
}

/** Identifies the report file format, so other tools can check what they are reading. */
export const REPORT_FORMAT = 'executive-desk.evaluation-report/1';

export interface EvaluationReport {
  format: typeof REPORT_FORMAT;
  id: string;
  label: string;
  harnessVersion: string;
  contractVersion: string;
  caseSet: CaseSetInfo;
  target: {
    name: string;
    dataSource: DataSource;
    baseUrl: string | null;
    /** Contract version the target reported in GET /meta. Null when the handshake never succeeded. */
    contractVersion: string | null;
    /** Whether the target said it was in sandbox mode. Null when the handshake never succeeded. */
    sandbox: boolean | null;
  };
  startedAt: ISODateTime;
  finishedAt: ISODateTime;
  results: EvaluationResult[];
  summary: EvaluationSummary;
}

export type SnapshotDay = 'friday' | 'saturday' | 'sunday';

/** A day's frozen summary. Only reports from a live target may be saved as snapshots. */
export interface EvaluationSnapshot {
  day: SnapshotDay;
  savedAt: ISODateTime;
  reportId: string;
  label: string;
  caseSet: CaseSetInfo;
  target: EvaluationReport['target'];
  summary: EvaluationSummary;
  verdicts: Record<string, Verdict>;
}
