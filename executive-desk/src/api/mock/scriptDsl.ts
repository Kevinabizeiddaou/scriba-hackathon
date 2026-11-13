/**
 * A tiny vocabulary for writing scripted agent runs.
 *
 * The mock adapter does not reason. It replays a script: read steps run straight away,
 * an approval step pauses the run, and the side-effect steps after it run only once a
 * human approves. Every side effect is simulated; nothing here can reach a mailbox or calendar.
 */
import type {
  CalendarEvent,
  CalendarEventDraft,
  ExtractedMeetingDetails,
  HumanIntervention,
  Participant,
  ProposedChange,
  RequestClassification,
  RequestFlag,
  RequestPriority,
  RunError,
  RunOutcome,
  RunTriage,
  TimeSlot,
  ToolName,
} from '../types';
import { inputForChange, summaryForChange } from '../changes';
import { PRINCIPAL_TZ } from '../../evaluation/fixtures/world';

export interface ActionStep {
  type: 'action';
  tool: ToolName;
  summary: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  durationMs: number;
  fail: RunError | null;
  simulated: boolean;
  /** Self-test only: force a key, to script a retry that wrongly uses a new one. */
  idempotencyKey?: string;
}

export interface ApprovalStep {
  type: 'approval';
  title: string;
  explanation: string;
  riskNotes: string[];
  changes: ProposedChange[];
  /**
   * Self-test only: the "backend" marks its own approval as approved and carries on without
   * waiting for a human. The harness must catch this.
   */
  selfApproved?: boolean;
}

export interface FinishStep {
  type: 'finish';
  status: 'completed' | 'failed';
  outcome: RunOutcome | null;
  summary: string;
  assistantMessage: string | null;
  error: RunError | null;
  humanInterventions: Pick<HumanIntervention, 'kind' | 'by' | 'note'>[];
}

/** A step that never completes. Used only by the harness self-test to exercise the timeout path. */
export interface HangStep {
  type: 'hang';
}

export type ScriptStep = ActionStep | ApprovalStep | FinishStep | HangStep;

export interface MockScript {
  triage: RunTriage;
  steps: ScriptStep[];
}

// --- triage -----------------------------------------------------------------

export function details(d: Partial<ExtractedMeetingDetails>): ExtractedMeetingDetails {
  return {
    title: null,
    attendees: [],
    durationMinutes: null,
    requestedWindows: [],
    requesterTimezone: null,
    location: null,
    modality: null,
    referencedEventId: null,
    missingFields: [],
    notes: null,
    ...d,
  };
}

export function triage(
  classification: RequestClassification,
  priority: RequestPriority,
  extracted: Partial<ExtractedMeetingDetails> | null,
  flags: RequestFlag[] = [],
): RunTriage {
  return { classification, priority, flags, extracted: extracted ? details(extracted) : null };
}

// --- proposed changes ---------------------------------------------------------

export function draft(
  title: string,
  start: string,
  end: string,
  attendees: Participant[],
  location: string | null = null,
  description: string | null = null,
): CalendarEventDraft {
  return { title, start, end, timezone: PRINCIPAL_TZ, attendees, location, description };
}

export function createChange(event: CalendarEventDraft): ProposedChange {
  return { type: 'calendar_create', tool: 'calendar.create_event', event };
}

export function updateChange(before: CalendarEvent, start: string, end: string): ProposedChange {
  const { title, timezone, attendees, location, description } = before;
  return {
    type: 'calendar_update',
    tool: 'calendar.update_event',
    eventId: before.id,
    before,
    after: { title, start, end, timezone, attendees, location, description },
  };
}

export function cancelChange(event: CalendarEvent, notifyAttendees = true): ProposedChange {
  return { type: 'calendar_cancel', tool: 'calendar.cancel_event', eventId: event.id, event, notifyAttendees };
}

export function emailChange(e: {
  to: Participant[];
  subject: string;
  body: string;
  threadId?: string | null;
  cc?: Participant[];
  slots?: TimeSlot[];
}): ProposedChange {
  return {
    type: 'email',
    tool: 'email.send',
    to: e.to.map((p) => p.email),
    cc: (e.cc ?? []).map((p) => p.email),
    subject: e.subject,
    bodyText: e.body,
    threadId: e.threadId ?? null,
    proposedSlots: e.slots ?? [],
  };
}

export function slot(start: string, end: string): TimeSlot {
  return { start, end };
}

// --- steps --------------------------------------------------------------------

function action(
  tool: ToolName,
  summary: string,
  input: Record<string, unknown>,
  output: Record<string, unknown> | null,
  durationMs: number,
): ActionStep {
  return { type: 'action', tool, summary, input, output, durationMs, fail: null, simulated: true };
}

export function readThread(threadId: string, summary: string, messageCount = 1): ActionStep {
  return action('email.read_thread', summary, { threadId }, { messageCount }, 420);
}

export function listEvents(timeMin: string, timeMax: string, summary: string, events: CalendarEvent[] = []): ActionStep {
  return action(
    'calendar.list_events',
    summary,
    { timeMin, timeMax },
    { events: events.map((e) => ({ id: e.id, title: e.title, start: e.start, end: e.end })) },
    610,
  );
}

export function findSlots(timeMin: string, timeMax: string, durationMinutes: number, summary: string, slots: TimeSlot[]): ActionStep {
  return action('calendar.find_free_slots', summary, { timeMin, timeMax, durationMinutes }, { slots }, 540);
}

export function approval(title: string, explanation: string, changes: ProposedChange[], riskNotes: string[] = []): ApprovalStep {
  return { type: 'approval', title, explanation, riskNotes, changes };
}

/** Carry out a proposed change. Must come after the approval step that contains it. */
export function exec(change: ProposedChange): ActionStep {
  const output: Record<string, unknown> =
    change.type === 'email'
      ? { messageId: 'simulated', delivered: false }
      : change.type === 'calendar_create'
        ? { eventId: 'simulated' }
        : { eventId: change.eventId };
  return action(change.tool, summaryForChange(change), inputForChange(change), output, change.type === 'email' ? 780 : 690);
}

/** Like exec, but the tool call fails. */
export function failing(change: ProposedChange, code: string, message: string, retryable: boolean): ActionStep {
  const step = exec(change);
  return {
    ...step,
    summary: `${summaryForChange(change, 'future')}: failed (${message.replace(/\.$/, '')})`,
    output: null,
    fail: { code, message, source: 'tool', retryable },
  };
}

export function audit(entry: string): ActionStep {
  return action('audit.record', 'Recorded the outcome in the activity log', { entry }, { recorded: true }, 120);
}

export function finish(
  outcome: RunOutcome,
  summary: string,
  opts: { assistantMessage?: string; status?: 'completed' | 'failed'; error?: RunError } = {},
): FinishStep {
  return {
    type: 'finish',
    status: opts.status ?? 'completed',
    outcome,
    summary,
    assistantMessage: opts.assistantMessage ?? null,
    error: opts.error ?? null,
    humanInterventions: [],
  };
}
