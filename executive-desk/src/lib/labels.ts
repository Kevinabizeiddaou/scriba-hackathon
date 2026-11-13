/** Display labels and tones for every status in the contract. Status is never shown by colour alone. */
import type {
  ActionStatus,
  ApprovalExecutionStatus,
  ApprovalStatus,
  RequestClassification,
  RequestFlag,
  RequestPriority,
  RequestStatus,
  RunOutcome,
  RunStatus,
  ToolName,
  Verdict,
} from '../api/types';

export type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'accent';

export const TONE_CLASS: Record<Tone, string> = {
  neutral: 'bg-white/[0.07] text-soft',
  ok: 'bg-ok/[0.13] text-ok',
  warn: 'bg-warn/[0.14] text-warn',
  danger: 'bg-danger/[0.14] text-danger',
  info: 'bg-info/[0.14] text-info',
  accent: 'bg-accent/[0.14] text-accent',
};

interface Label {
  label: string;
  tone: Tone;
}

export const REQUEST_STATUS: Record<RequestStatus, Label> = {
  received: { label: 'New', tone: 'accent' },
  processing: { label: 'Working', tone: 'info' },
  awaiting_approval: { label: 'Needs approval', tone: 'warn' },
  awaiting_reply: { label: 'Waiting for reply', tone: 'info' },
  completed: { label: 'Done', tone: 'ok' },
  escalated: { label: 'Needs you', tone: 'danger' },
  declined: { label: 'Rejected', tone: 'neutral' },
  failed: { label: 'Failed', tone: 'danger' },
};

export const RUN_STATUS: Record<RunStatus, Label> = {
  queued: { label: 'Queued', tone: 'neutral' },
  running: { label: 'Working', tone: 'info' },
  awaiting_approval: { label: 'Waiting for approval', tone: 'warn' },
  completed: { label: 'Finished', tone: 'ok' },
  failed: { label: 'Failed', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
};

export const ACTION_STATUS: Record<ActionStatus, Label> = {
  planned: { label: 'Planned', tone: 'neutral' },
  awaiting_approval: { label: 'Waiting for approval', tone: 'warn' },
  running: { label: 'Running', tone: 'info' },
  succeeded: { label: 'Done', tone: 'ok' },
  failed: { label: 'Failed', tone: 'danger' },
  rejected: { label: 'Not run (rejected)', tone: 'neutral' },
  skipped: { label: 'Not run', tone: 'neutral' },
};

export const APPROVAL_STATUS: Record<ApprovalStatus, Label> = {
  pending: { label: 'Waiting for you', tone: 'warn' },
  approved: { label: 'Approved', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'neutral' },
  expired: { label: 'Expired', tone: 'neutral' },
};

export const EXECUTION_STATUS: Record<ApprovalExecutionStatus, Label> = {
  not_started: { label: 'Not executed', tone: 'neutral' },
  executing: { label: 'Executing', tone: 'info' },
  executed: { label: 'Executed', tone: 'ok' },
  failed: { label: 'Execution failed', tone: 'danger' },
};

export const OUTCOME: Record<RunOutcome, string> = {
  scheduled: 'Meeting scheduled',
  rescheduled: 'Meeting moved',
  cancelled_meeting: 'Meeting cancelled',
  alternatives_proposed: 'Alternatives offered',
  clarification_requested: 'Clarification requested',
  no_action: 'No action needed',
  escalated: 'Handed to you',
  declined: 'Proposal rejected',
};

export const CLASSIFICATION: Record<RequestClassification, string> = {
  new_meeting: 'New meeting',
  reschedule: 'Reschedule',
  cancellation: 'Cancellation',
  availability_query: 'Availability question',
  unclear: 'Unclear',
  not_meeting_related: 'Not about a meeting',
};

export const PRIORITY: Record<RequestPriority, Label> = {
  urgent: { label: 'Urgent', tone: 'danger' },
  high: { label: 'High', tone: 'warn' },
  normal: { label: 'Normal', tone: 'neutral' },
  low: { label: 'Low', tone: 'neutral' },
};

export const FLAG: Record<RequestFlag, Label> = {
  prompt_injection_suspected: { label: 'Suspected prompt injection', tone: 'danger' },
  duplicate: { label: 'Duplicate', tone: 'info' },
  timezone_ambiguous: { label: 'Time zone unclear', tone: 'warn' },
  unverified_sender: { label: 'Unverified sender', tone: 'warn' },
  outside_working_hours: { label: 'Outside working hours', tone: 'warn' },
};

export const VERDICT: Record<Verdict, Label> = {
  pass: { label: 'Pass', tone: 'ok' },
  fail: { label: 'Fail', tone: 'danger' },
  error: { label: 'Error', tone: 'warn' },
  skipped: { label: 'Skipped', tone: 'neutral' },
};

export const TOOL_LABEL: Record<ToolName, string> = {
  'email.read_thread': 'Read email thread',
  'email.search': 'Search email',
  'email.send': 'Send email',
  'calendar.list_events': 'Read calendar',
  'calendar.find_free_slots': 'Find free slots',
  'calendar.create_event': 'Create event',
  'calendar.update_event': 'Move event',
  'calendar.cancel_event': 'Cancel event',
  'approval.request': 'Ask for approval',
  'audit.record': 'Record in log',
};

export function usd(value: number): string {
  return value < 1 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

export function percent(value: number): string {
  return `${(value * 100).toFixed(value === 1 || value === 0 ? 0 : 1)}%`;
}
