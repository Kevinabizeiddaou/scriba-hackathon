/**
 * Runtime checks on what a backend returns.
 *
 * TypeScript types vanish at runtime, so a backend that sends "done" where the contract says
 * "completed" would otherwise surface as a blank screen or a silently wrong score. These
 * validators cover the fields the UI and the scorer actually read, and report every problem
 * with its JSON path, so a contract mismatch is found at the adapter boundary and named.
 * They do not reject unknown extra fields: a backend may add its own.
 */
import {
  ACTION_STATUSES,
  APPROVAL_EXECUTION_STATUSES,
  APPROVAL_STATUSES,
  REQUEST_CLASSIFICATIONS,
  REQUEST_FLAGS,
  REQUEST_PRIORITIES,
  REQUEST_STATUSES,
  RUN_OUTCOMES,
  RUN_STATUSES,
  SIDE_EFFECT_TOOLS,
} from './types';
import { isInstant } from '../lib/time';

type Obj = Record<string, unknown>;
type Check = (value: unknown, path: string, problems: string[]) => void;

const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);
const show = (v: unknown) => (v === undefined ? 'missing' : JSON.stringify(v)?.slice(0, 60));

const str: Check = (v, p, out) => {
  if (typeof v !== 'string') out.push(`${p}: expected a string, got ${show(v)}`);
};
const bool: Check = (v, p, out) => {
  if (typeof v !== 'boolean') out.push(`${p}: expected true or false, got ${show(v)}`);
};
const num: Check = (v, p, out) => {
  if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) out.push(`${p}: expected a non-negative number, got ${show(v)}`);
};
const instant: Check = (v, p, out) => {
  if (!isInstant(v)) out.push(`${p}: expected an RFC 3339 timestamp with an offset, got ${show(v)}`);
};
const oneOf =
  (allowed: readonly string[]): Check =>
  (v, p, out) => {
    if (typeof v !== 'string' || !allowed.includes(v)) out.push(`${p}: expected one of ${allowed.join(' | ')}, got ${show(v)}`);
  };
const nullable =
  (inner: Check): Check =>
  (v, p, out) => {
    if (v === undefined) out.push(`${p}: missing (nullable fields must be present and set to null)`);
    else if (v !== null) inner(v, p, out);
  };
const arrayOf =
  (inner: Check): Check =>
  (v, p, out) => {
    if (!Array.isArray(v)) out.push(`${p}: expected an array, got ${show(v)}`);
    else v.forEach((item, i) => inner(item, `${p}[${i}]`, out));
  };
const shape =
  (fields: Record<string, Check>): Check =>
  (v, p, out) => {
    if (!isObj(v)) out.push(`${p}: expected an object, got ${show(v)}`);
    else for (const [key, check] of Object.entries(fields)) check(v[key], `${p}.${key}`, out);
  };

const participant = shape({ name: str, email: str });
const slot = shape({ start: instant, end: instant });
const runError = shape({ code: str, message: str, source: oneOf(['tool', 'model', 'backend']), retryable: bool });
const eventDraft = shape({ title: str, start: instant, end: instant, timezone: str, attendees: arrayOf(participant) });

const extracted = shape({
  title: nullable(str),
  attendees: arrayOf(participant),
  durationMinutes: nullable(num),
  requestedWindows: arrayOf(slot),
  requesterTimezone: nullable(str),
  referencedEventId: nullable(str),
  missingFields: arrayOf(str),
});

const triage = shape({
  classification: oneOf(REQUEST_CLASSIFICATIONS),
  priority: oneOf(REQUEST_PRIORITIES),
  flags: arrayOf(oneOf(REQUEST_FLAGS)),
  extracted: nullable(extracted),
});

const usage = shape({
  models: arrayOf(shape({ model: str, calls: num, inputTokens: num, outputTokens: num, cachedInputTokens: nullable(num) })),
  estimatedCostUsd: nullable(num),
});

const action: Check = (v, p, out) => {
  shape({
    id: str,
    runId: str,
    sequence: num,
    tool: str,
    status: oneOf(ACTION_STATUSES),
    summary: str,
    startedAt: nullable(instant),
    finishedAt: nullable(instant),
    durationMs: nullable(num),
    approvalId: nullable(str),
    idempotencyKey: nullable(str),
    error: nullable(runError),
    simulated: bool,
  })(v, p, out);
  if (isObj(v)) {
    if (!isObj(v.input)) out.push(`${p}.input: expected an object, got ${show(v.input)}`);
    if (v.output !== null && !isObj(v.output)) out.push(`${p}.output: expected an object or null, got ${show(v.output)}`);
    // Canonical names are checked after aliasing, by the adapter.
    if ((SIDE_EFFECT_TOOLS as readonly string[]).includes(String(v.tool)) && v.status !== 'planned' && typeof v.idempotencyKey !== 'string') {
      out.push(`${p}.idempotencyKey: a side-effect action needs an idempotency key`);
    }
  }
};

const run = shape({
  id: str,
  trigger: oneOf(['incoming_email', 'chat_message', 'evaluation']),
  requestId: nullable(str),
  conversationId: nullable(str),
  status: oneOf(RUN_STATUSES),
  outcome: nullable(oneOf(RUN_OUTCOMES)),
  triage: nullable(triage),
  summary: nullable(str),
  assistantMessage: nullable(str),
  actions: arrayOf(action),
  approvalIds: arrayOf(str),
  startedAt: instant,
  finishedAt: nullable(instant),
  durationMs: nullable(num),
  usage: nullable(usage),
  error: nullable(runError),
  humanInterventions: arrayOf(shape({ at: instant, kind: oneOf(['approval', 'edit', 'rescue', 'takeover']), by: str, note: nullable(str) })),
});

const change: Check = (v, p, out) => {
  if (!isObj(v)) {
    out.push(`${p}: expected an object, got ${show(v)}`);
    return;
  }
  switch (v.type) {
    case 'email':
      shape({ tool: oneOf(['email.send']), to: arrayOf(str), cc: arrayOf(str), subject: str, bodyText: str, threadId: nullable(str), proposedSlots: arrayOf(slot) })(v, p, out);
      break;
    case 'calendar_create':
      shape({ tool: oneOf(['calendar.create_event']), event: eventDraft })(v, p, out);
      break;
    case 'calendar_update':
      shape({ tool: oneOf(['calendar.update_event']), eventId: str, before: eventDraft, after: eventDraft })(v, p, out);
      break;
    case 'calendar_cancel':
      shape({ tool: oneOf(['calendar.cancel_event']), eventId: str, event: eventDraft, notifyAttendees: bool })(v, p, out);
      break;
    default:
      out.push(`${p}.type: expected email | calendar_create | calendar_update | calendar_cancel, got ${show(v.type)}`);
  }
};

const approval = shape({
  id: str,
  runId: str,
  requestId: nullable(str),
  conversationId: nullable(str),
  title: str,
  explanation: str,
  riskNotes: arrayOf(str),
  changes: arrayOf(change),
  status: oneOf(APPROVAL_STATUSES),
  createdAt: instant,
  expiresAt: nullable(instant),
  decidedAt: nullable(instant),
  decidedBy: nullable(str),
  decisionNote: nullable(str),
  execution: shape({ status: oneOf(APPROVAL_EXECUTION_STATUSES), finishedAt: nullable(instant), error: nullable(runError), simulated: bool }),
});

const request = shape({
  id: str,
  source: oneOf(['email', 'chat']),
  receivedAt: instant,
  from: participant,
  subject: str,
  bodyText: str,
  threadId: nullable(str),
  classification: nullable(oneOf(REQUEST_CLASSIFICATIONS)),
  priority: nullable(oneOf(REQUEST_PRIORITIES)),
  status: oneOf(REQUEST_STATUSES),
  flags: arrayOf(oneOf(REQUEST_FLAGS)),
  extracted: nullable(extracted),
  runIds: arrayOf(str),
  duplicateOfRequestId: nullable(str),
  history: arrayOf(shape({ at: instant, actor: oneOf(['agent', 'human', 'system']), event: str, detail: nullable(str) })),
});

const conversation = shape({ id: str, title: str, createdAt: instant, updatedAt: instant, lastMessagePreview: nullable(str) });

const message = shape({
  id: str,
  conversationId: str,
  role: oneOf(['user', 'assistant']),
  createdAt: instant,
  text: str,
  runId: nullable(str),
  status: oneOf(['streaming', 'final']),
});

const meta = shape({
  contractVersion: str,
  service: str,
  agent: oneOf(['real', 'scripted']),
  sandbox: bool,
  principal: shape({ name: str, email: str, timezone: str }),
  simulatedNow: nullable(instant),
  capabilities: shape({ evaluation: bool, faultInjection: bool, chat: bool, tokenUsage: bool }),
});

function run1(check: Check, label: string) {
  return (value: unknown): string[] => {
    const problems: string[] = [];
    check(value, label, problems);
    return problems;
  };
}

export const validate = {
  meta: run1(meta, 'meta'),
  request: run1(request, 'request'),
  requests: run1(arrayOf(request), 'requests'),
  run: run1(run, 'run'),
  runs: run1(arrayOf(run), 'runs'),
  approval: run1(approval, 'approval'),
  approvals: run1(arrayOf(approval), 'approvals'),
  conversation: run1(conversation, 'conversation'),
  conversations: run1(arrayOf(conversation), 'conversations'),
  messages: run1(arrayOf(message), 'messages'),
  messageAndRun: run1(shape({ message, run }), 'response'),
};
