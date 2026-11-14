/**
 * What the executive workspace screens need to show: mail across Gmail and Outlook, a unified
 * calendar, tasks, reminders, follow-ups and an activity history.
 *
 * These are view models, not a backend contract. They say what the screens display; they do not
 * say which endpoint supplies it. The backend for most of this does not exist yet (see
 * docs/FEATURE_STATUS.md and Role 1's docs/BACKEND_CONTRACT.md on main), so today the only
 * implementation is a mock with fictional data, and in HTTP mode the screens say they are
 * waiting for the backend contract instead of inventing behaviour.
 */
import type { Triage } from '../api/desk';
import type { ISODateTime, Participant, RequestFlag, RequestPriority } from './types';

export type MailProvider = 'gmail' | 'outlook';
export type CalendarProvider = 'google' | 'outlook';

export interface ConnectedAccount {
  id: string;
  kind: 'mail' | 'calendar';
  provider: MailProvider | CalendarProvider;
  address: string;
  label: string;
  /** unavailable: the server is not set up for this provider, so it cannot be connected from the Desk. */
  status: 'connected' | 'disconnected' | 'reconnect_required' | 'unavailable';
  /** Live only: the backend's machine-readable reason, when it gives one. */
  reason?: string | null;
  /** Live only: backend path that starts or repairs the connection. A navigation, never a fetch. */
  loginPath?: string;
}

export type EmailCategory = 'meeting' | 'action_required' | 'reply_needed' | 'follow_up' | 'fyi' | 'low_priority';
/** untracked: the backend does not record where this message stands in the secretary's work (live data today). */
export type EmailWorkStatus = 'new' | 'in_progress' | 'needs_approval' | 'waiting' | 'needs_you' | 'done' | 'untracked';

export interface ThreadMessage {
  id: string;
  from: Participant;
  sentAt: ISODateTime;
  bodyText: string;
  /** True for a message sent from the principal's mailbox. */
  outbound: boolean;
}

export interface ReplyDraft {
  to: string[];
  subject: string;
  bodyText: string;
  /** Why the secretary wrote it this way: what in the thread it relies on. */
  rationale: string;
  state: 'drafted' | 'awaiting_approval' | 'sent' | 'rejected';
  approvalId: string | null;
}

export interface InboxEmail {
  id: string;
  provider: MailProvider;
  /** The mailbox it arrived in. Any later action on the item must use the same provider and account. */
  account: string;
  threadId: string;
  from: Participant;
  subject: string;
  receivedAt: ISODateTime;
  unread: boolean;
  category: EmailCategory;
  priority: RequestPriority;
  /** Two or three sentences written by the secretary, or the provider's snippet (see summaryKind). */
  summary: string;
  /** snippet: `summary` is the mail provider's preview text, not something the secretary wrote. Absent means secretary. */
  summaryKind?: 'secretary' | 'snippet';
  actionItems: string[];
  status: EmailWorkStatus;
  flags: RequestFlag[];
  /** Set for meeting requests, which are handled by the scheduling flow (SecretaryRequest). */
  requestId: string | null;
  /** Oldest first. The last entry is the message that arrived. */
  thread: ThreadMessage[];
  draft: ReplyDraft | null;
  taskIds: string[];
  followUpId: string | null;
  /**
   * Live only: what is needed to read or act on this message again. Any action must be sent to
   * the same provider and provider account the message arrived in.
   */
  source?: {
    messageId: string;
    providerAccountId: string | null;
    replySupported: boolean;
    /** The backend's rule-based triage, unmodified. */
    triage: Triage;
  };
}

export interface AgendaEvent {
  id: string;
  title: string;
  start: ISODateTime;
  end: ISODateTime;
  provider: CalendarProvider;
  /** Display name of the calendar it lives on. */
  calendar: string;
  attendees: Participant[];
  location: string | null;
  /**
   * event:    on the calendar now.
   * proposed: a slot the secretary has proposed and that is waiting for approval or for the
   *           requester's answer. It is not on any calendar yet.
   */
  kind: 'event' | 'proposed';
  /** Ids of other events on any connected calendar that overlap this one. */
  conflictsWith: string[];
  approvalId: string | null;
  allDay?: boolean;
  /** Live only: the provider's event id and account, needed for any later change to this event. */
  source?: { eventId: string | null; providerAccountId: string | null; joinUrl: string | null };
}

export interface MeetingPrep {
  eventId: string;
  purpose: string;
  attendees: { person: Participant; note: string }[];
  talkingPoints: string[];
  relatedEmailIds: string[];
  openTaskIds: string[];
  lastContact: string | null;
}

export interface WorkTask {
  id: string;
  title: string;
  detail: string | null;
  dueAt: ISODateTime | null;
  status: 'open' | 'done';
  priority: RequestPriority;
  /** extracted: the secretary found it in an email. manual: the principal asked for it. */
  origin: 'extracted' | 'manual';
  sourceEmailId: string | null;
  createdAt: ISODateTime;
  completedAt: ISODateTime | null;
}

export interface Reminder {
  id: string;
  text: string;
  remindAt: ISODateTime;
  status: 'scheduled' | 'done' | 'dismissed';
  sourceEmailId: string | null;
}

export interface FollowUp {
  id: string;
  subject: string;
  waitingOn: Participant;
  sentAt: ISODateTime;
  /** When an answer was expected. After this, with no reply, the follow-up is overdue. */
  expectedBy: ISODateTime;
  status: 'waiting' | 'overdue' | 'replied' | 'closed';
  emailId: string | null;
  nudgesSent: number;
  note: string | null;
  /** A reminder email waiting in the Approval Center, if one has been drafted. */
  nudgeApprovalId: string | null;
}

export interface ActivityEntry {
  id: string;
  at: ISODateTime;
  kind: 'email' | 'calendar' | 'task' | 'approval' | 'triage' | 'follow_up' | 'system';
  actor: 'agent' | 'human' | 'system';
  title: string;
  detail: string | null;
  outcome: 'done' | 'failed' | 'pending' | 'rejected';
  /** True when nothing real happened (mock or sandbox). */
  simulated: boolean;
  link: { page: 'inbox' | 'calendar' | 'tasks' | 'approvals' | 'chat'; param: string | null } | null;
}

export interface WorkspaceApi {
  /**
   * mock:                fictional data from the in-memory mock.
   * waiting_for_backend: no backend contract exists for this yet; every method rejects with a
   *                      WorkspaceUnavailable error and the screens say so.
   * live:                Scriba's API through the session cookie. A method with no backend rejects
   *                      with WorkspaceUnavailable; a failed request rejects with its own error.
   */
  readonly availability: 'mock' | 'waiting_for_backend' | 'live';

  listAccounts(): Promise<ConnectedAccount[]>;
  listEmails(): Promise<InboxEmail[]>;
  /** Puts an email's reply draft in the Approval Center. Nothing is sent until it is approved there. */
  submitDraft(emailId: string): Promise<void>;

  /** Events and proposed slots on every connected calendar for the visible week. */
  /** `week`: the Monday-to-Monday dates to read. Without it, the week that contains now. */
  listAgenda(week?: { start: string; end: string }): Promise<AgendaEvent[]>;
  getMeetingPrep(eventId: string): Promise<MeetingPrep | null>;

  listTasks(): Promise<WorkTask[]>;
  setTaskStatus(id: string, status: WorkTask['status']): Promise<void>;
  listReminders(): Promise<Reminder[]>;
  setReminderStatus(id: string, status: Reminder['status']): Promise<void>;
  listFollowUps(): Promise<FollowUp[]>;
  /** Drafts a reminder email for an unanswered follow-up and puts it in the Approval Center. */
  draftNudge(followUpId: string): Promise<void>;

  listActivity(): Promise<ActivityEntry[]>;

  subscribe(listener: () => void): () => void;
}

export class WorkspaceUnavailable extends Error {
  /** True when the message is the whole explanation (live data), not the generic "waiting" text. */
  readonly specific: boolean;
  constructor(readonly feature: string, detail?: string) {
    super(detail ?? `${feature} is waiting for the backend contract. Nothing is shown rather than something invented.`);
    this.name = 'WorkspaceUnavailable';
    this.specific = detail !== undefined;
  }
}

/** Used whenever the app talks to a real backend: no workspace endpoint has been agreed yet. */
export class WaitingWorkspace implements WorkspaceApi {
  readonly availability = 'waiting_for_backend' as const;
  private fail(feature: string): Promise<never> {
    return Promise.reject(new WorkspaceUnavailable(feature));
  }
  listAccounts = () => this.fail('Connected accounts');
  listEmails = () => this.fail('The unified inbox');
  submitDraft = () => this.fail('Reply drafts');
  listAgenda = () => this.fail('The unified calendar');
  getMeetingPrep = () => this.fail('Meeting preparation');
  listTasks = () => this.fail('Tasks');
  setTaskStatus = () => this.fail('Tasks');
  listReminders = () => this.fail('Reminders');
  setReminderStatus = () => this.fail('Reminders');
  listFollowUps = () => this.fail('Follow-up tracking');
  draftNudge = () => this.fail('Follow-up tracking');
  listActivity = () => this.fail('Activity history');
  subscribe = () => () => {};
}
