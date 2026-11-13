/**
 * The integration status of every feature in the workspace, in one place.
 *
 * It is written to docs/frontend/FEATURE_STATUS.md by `npm run docs:generate`, and shown on the
 * demo overview, so the screens and the document cannot disagree.
 *
 * Statuses describe the LIVE application (the default mode). Demo mode still runs every screen
 * on the labelled mock.
 *   connected   reads or writes Scriba's real API, and was exercised in a browser against
 *               Scriba's seeded backend with the Desk overlay
 *   unverified  calls the real endpoint, but no backend available here can exercise it (it needs
 *               a model or a live provider); its behaviour is covered by unit tests only
 *   waiting     there is no backend for it; the live screen says so instead of showing anything
 *   missing     not implemented
 *
 * "Seeded" is Scriba's own in-memory test backend: the real application, no database, no
 * provider network, no model. Nothing here has been verified against live Gmail, Outlook or
 * calendars, and nothing here says how well the agent performs.
 */
export type FeatureStatus = 'connected' | 'unverified' | 'waiting' | 'missing';

export interface Feature {
  area: 'Workspace' | 'Email' | 'Calendar' | 'Tasks and follow-ups' | 'Chat and approvals' | 'Automation' | 'Evaluation';
  name: string;
  status: FeatureStatus;
  /** The backend it uses today. */
  backend: string;
  /** What is still open before it is complete. */
  needs: string;
}

export const STATUS_LABEL: Record<FeatureStatus, string> = {
  connected: 'Connected, verified on the seeded backend',
  unverified: 'Connected, not verified end to end',
  waiting: 'Waiting for a backend',
  missing: 'Not implemented',
};

export const FEATURES: Feature[] = [
  { area: 'Workspace', name: 'Sign-in and session', status: 'connected', backend: 'Scriba session cookie; GET /providers/status; POST /auth/signin; POST /auth/logout', needs: 'Google and Microsoft sign-in are navigations to Scriba and were not exercised here' },
  { area: 'Workspace', name: 'Executive overview and work queue', status: 'connected', backend: 'GET /desk/briefing, GET /desk/inbox, GET /desk/connections, chat action records', needs: 'A backend work-queue listing, so the queue is not limited to recent conversations' },
  { area: 'Workspace', name: 'Connected accounts (Gmail, Outlook Mail, Google Calendar, Outlook Calendar)', status: 'connected', backend: 'GET /desk/connections', needs: 'Nothing for the Desk; reconnecting happens in Scriba' },
  { area: 'Workspace', name: 'Activity and execution history', status: 'connected', backend: 'GET /chat/conversations and their messages: every action card with its server status', needs: 'The same work-queue listing; automation runs are not included yet' },

  { area: 'Email', name: 'Unified Gmail and Outlook inbox', status: 'connected', backend: 'GET /desk/inbox', needs: 'Paging beyond the most recent 50 messages' },
  { area: 'Email', name: 'Priority and classification', status: 'connected', backend: 'GET /desk/inbox: rule-based triage on subject and preview, no model', needs: 'Triage on the full message body' },
  { area: 'Email', name: 'Thread view', status: 'connected', backend: 'GET /desk/inbox/item: the messages of the thread found in the recent inbox, as previews', needs: 'Full message bodies and older messages of the thread' },
  { area: 'Email', name: 'Summaries and extracted action items', status: 'waiting', backend: 'None: the backend returns the provider preview only', needs: 'A summary and action items per message. The live screen shows the preview and says so' },
  { area: 'Email', name: 'Reply drafts for review', status: 'unverified', backend: 'POST /drafts/create with the body from GET /desk/inbox/item; GET /drafts; POST /drafts/{id}/discard', needs: 'A backend with a model and a real mailbox to verify it. Sending a draft is not exposed' },
  { area: 'Email', name: 'Work status per message', status: 'waiting', backend: 'None: Scriba does not record where a message stands in the secretary\'s work', needs: 'A work record per message, linked to its actions' },

  { area: 'Calendar', name: 'Unified Google and Outlook calendar, day and week', status: 'connected', backend: 'GET /calendar/events per provider', needs: 'Seeded data has no connected calendar, so only the disconnected and failed states were seen in the browser; events are covered by unit tests' },
  { area: 'Calendar', name: 'Conflicts between calendars', status: 'unverified', backend: 'Computed in the frontend from the events of both providers', needs: 'Two connected calendars to verify it against' },
  { area: 'Calendar', name: 'Free time for a meeting request', status: 'unverified', backend: 'GET /desk/inbox/item: slots verified free on every connected calendar', needs: 'A meeting request and connected calendars to verify it against' },
  { area: 'Calendar', name: 'Meeting preparation view', status: 'waiting', backend: 'None', needs: 'Related mail, open tasks and notes per event' },

  { area: 'Tasks and follow-ups', name: 'Tasks', status: 'connected', backend: 'GET /tasks; POST /tasks/{id}/complete', needs: 'Reopening a completed task has no verified endpoint' },
  { area: 'Tasks and follow-ups', name: 'Reminders', status: 'connected', backend: 'GET /reminders/upcoming; POST /reminders/{id}/cancel', needs: 'Seeded data has no reminder, so cancelling one was not exercised' },
  { area: 'Tasks and follow-ups', name: 'Follow-up tracking and overdue indicators', status: 'waiting', backend: 'None: Scriba does not track sent mail that is waiting for a reply', needs: 'Tracking of awaited replies' },

  { area: 'Chat and approvals', name: 'Secretary chat with history and streaming', status: 'connected', backend: 'GET and POST /chat/conversations; GET messages; POST messages/stream (server-sent events), with the blocking POST as fallback', needs: 'A backend with a model: the seeded backend answers every turn with its own "AI service unavailable" message' },
  { area: 'Chat and approvals', name: 'Action cards and the approval center', status: 'connected', backend: 'Chat action records; POST /chat/tool-calls/{id}/approve and /cancel', needs: 'Approving and cancelling a task were exercised. Mail and calendar approvals are disabled until the backend reports its safety fixes' },
  { area: 'Chat and approvals', name: 'Execution progress, partial success and failure', status: 'unverified', backend: 'Server status on each action card, polled while it is approved or executing', needs: 'A backend that produces executing, partially executed and failed actions' },
  { area: 'Chat and approvals', name: 'Retry of a failed action', status: 'unverified', backend: 'POST /chat/tool-calls/{id}/retry, which executes at once without a second approval', needs: 'The same; the control says the retry runs immediately and asks for confirmation first' },
  { area: 'Chat and approvals', name: 'Booking despite an availability finding', status: 'unverified', backend: 'payload_overrides.desk_availability_override on approve (Desk chat scope, not yet on main)', needs: 'The chat scope merged and running; external writes enabled' },
  { area: 'Chat and approvals', name: 'Editing a proposal before approving', status: 'missing', backend: 'Approve accepts payload_overrides', needs: 'An edit control. Today an incomplete card is finished in chat' },

  { area: 'Automation', name: 'Automatic work on incoming mail', status: 'waiting', backend: 'None for the Desk. Scriba has automations, which cannot yet change a calendar', needs: 'A backend record per incoming-mail job with its stage' },
  { area: 'Automation', name: 'Work stages', status: 'connected', backend: 'Classified, planning, needs information, awaiting approval, executing, completed, partly completed, failed, cancelled: each from a server status', needs: 'Received, verifying, awaiting reply and escalated are not reported by the backend and are not shown as if they were' },

  { area: 'Evaluation', name: 'Twenty-case suite, scheduling regression suite, scorer, runner, reports', status: 'connected', backend: 'None needed: the harness runs against its scripted reference agent', needs: 'These are harness results, not agent results' },
  { area: 'Evaluation', name: 'Results against the real agent', status: 'waiting', backend: 'None: no sandbox evaluation route', needs: 'The sandbox contract in docs/frontend/LIVE_INTEGRATION.md. No real result exists' },
];

export function countByStatus(features: Feature[] = FEATURES): Record<FeatureStatus, number> {
  const counts: Record<FeatureStatus, number> = { connected: 0, unverified: 0, waiting: 0, missing: 0 };
  for (const feature of features) counts[feature.status] += 1;
  return counts;
}

/** docs/frontend/FEATURE_STATUS.md, generated so the document and the registry cannot disagree. */
export function renderFeatureStatus(features: Feature[] = FEATURES): string {
  const counts = countByStatus(features);
  const areas = [...new Set(features.map((f) => f.area))];
  const out: string[] = [
    '# Feature status',
    '',
    '<!-- Generated from frontend/src/lib/featureStatus.ts by `npm run docs:generate`. Do not edit by hand. -->',
    '',
    'What the Executive Desk frontend does on live data (the default mode), and what each part still needs.',
    '',
    '| Status | Meaning | Features |',
    '| --- | --- | --- |',
    `| ${STATUS_LABEL.connected} | Uses Scriba's real API, and was exercised in a browser against Scriba's seeded backend with the Desk overlay | ${counts.connected} |`,
    `| ${STATUS_LABEL.unverified} | Calls the real endpoint, but needs a model or a live provider to exercise. Covered by unit tests only | ${counts.unverified} |`,
    `| ${STATUS_LABEL.waiting} | No backend exists for it. The live screen says so and shows nothing in its place | ${counts.waiting} |`,
    `| ${STATUS_LABEL.missing} | Not built | ${counts.missing} |`,
    '',
    'The seeded backend is Scriba\'s real application with in-memory storage: no database, no provider network and no model. **Nothing here has been verified against live Gmail, Outlook or calendars, and nothing here measures the agent.** Demo mode (`npm run dev:demo`) still runs every screen on the labelled mock.',
    '',
  ];
  for (const area of areas) {
    out.push(`## ${area}`, '', '| Feature | Status | Backend used | Still open |', '| --- | --- | --- | --- |');
    for (const f of features.filter((x) => x.area === area)) out.push(`| ${f.name} | ${STATUS_LABEL[f.status]} | ${f.backend.replace(/\|/g, '\\|')} | ${f.needs.replace(/\|/g, '\\|')} |`);
    out.push('');
  }
  out.push('See [LIVE_INTEGRATION.md](LIVE_INTEGRATION.md) for the endpoints, the mapping rules and the open backend requirements.', '');
  return out.join('\n');
}
