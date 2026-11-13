/**
 * The integration status of every feature in the workspace, in one place.
 *
 * It is shown on the Overview screen and written to docs/FEATURE_STATUS.md by
 * `npm run docs:generate`, so the screen and the document cannot disagree.
 *
 * The four statuses are the ones the project uses. Every screen that exists today runs on mock
 * data, so the difference between the middle two is what stands between it and the real backend:
 *   connected  implemented and connected to the real backend
 *   mock       implemented with mock data; the backend capability exists, and only the mapping
 *              in the frontend API layer is missing
 *   waiting    implemented with mock data, but there is no backend contract to connect it to yet
 *   missing    not implemented
 *
 * "Backend today" quotes Role 1's docs/BACKEND_CONTRACT.md on main (Scriba at the commit named
 * there). "Tested" means Role 1's smoke script has called it; "Read" means it exists in Scriba
 * and was read from source; "Proposed" and "None" mean it does not exist yet.
 */
export type FeatureStatus = 'connected' | 'mock' | 'waiting' | 'missing';

export interface Feature {
  area: 'Workspace' | 'Email' | 'Calendar' | 'Tasks and follow-ups' | 'Chat and approvals' | 'Evaluation';
  name: string;
  status: FeatureStatus;
  /** What exists on the backend for it today, as documented by Role 1. */
  backend: string;
  /** What has to happen before it can be connected. */
  needs: string;
}

export const STATUS_LABEL: Record<FeatureStatus, string> = {
  connected: 'Implemented and connected',
  mock: 'Implemented with mock data',
  waiting: 'Waiting for backend contract',
  missing: 'Not implemented',
};

export const FEATURES: Feature[] = [
  { area: 'Workspace', name: 'Executive overview', status: 'mock', backend: 'None as one endpoint; it is a composition of the items below', needs: 'The inbox, calendar, task and approval sources below' },
  { area: 'Workspace', name: 'Connected accounts (Gmail, Outlook, Google Calendar, Outlook Calendar)', status: 'mock', backend: 'Tested: GET /providers/status', needs: 'Map ProviderStatusPayload to the account list; cookie session' },
  { area: 'Workspace', name: 'Activity and execution history', status: 'waiting', backend: 'None for the Desk. Scriba has automation run history (Read)', needs: 'A history source for approvals and executed actions' },
  { area: 'Workspace', name: 'Sign-in', status: 'missing', backend: 'Exists: Scriba session cookie, sign-in by navigating to /auth/login', needs: 'A sign-in screen that navigates to Scriba. No new authentication is built here.' },

  { area: 'Email', name: 'Unified Gmail and Outlook inbox', status: 'mock', backend: 'Tested: GET /emails?provider=gmail|outlook', needs: 'Map EmailListResponse; keep provider and account with each item' },
  { area: 'Email', name: 'Thread view', status: 'waiting', backend: 'None documented', needs: 'An endpoint that returns the messages of a thread' },
  { area: 'Email', name: 'Priority and classification', status: 'waiting', backend: 'None', needs: 'Triage output per message: category and priority' },
  { area: 'Email', name: 'Summaries and extracted action items', status: 'waiting', backend: 'None', needs: 'Summary and action items per message' },
  { area: 'Email', name: 'Reply drafts', status: 'waiting', backend: 'Read: POST /drafts/create, POST /drafts/{id}/send', needs: 'Draft content and state in the frontend shape; sending only after approval' },
  { area: 'Email', name: 'Pending and completed email actions', status: 'waiting', backend: 'Read: chat tool-call statuses', needs: 'Action state per email' },

  { area: 'Calendar', name: 'Unified Google and Outlook calendar, day and week', status: 'mock', backend: 'Tested: GET /calendar/events?provider=google|outlook', needs: 'Map CalendarEventsPayload; calendar source per event' },
  { area: 'Calendar', name: 'Conflict visualisation', status: 'mock', backend: 'Proposed: POST /desk/slots/check', needs: 'Computed in the frontend from the events today; the backend check when it exists' },
  { area: 'Calendar', name: 'Proposed meeting slots', status: 'waiting', backend: 'Proposed: GET /desk/availability', needs: 'Availability across both calendars; slots attached to proposals' },
  { area: 'Calendar', name: 'Meeting preparation view', status: 'waiting', backend: 'None', needs: 'Related mail, open tasks and notes per event' },

  { area: 'Tasks and follow-ups', name: 'Extracted tasks and deadlines', status: 'waiting', backend: 'None documented for the Desk', needs: 'A task store and task extraction' },
  { area: 'Tasks and follow-ups', name: 'Reminders', status: 'waiting', backend: 'None documented for the Desk', needs: 'A reminder store' },
  { area: 'Tasks and follow-ups', name: 'Follow-up tracking and overdue indicators', status: 'waiting', backend: 'None', needs: 'Tracking of sent mail that is waiting for a reply' },

  { area: 'Chat and approvals', name: 'Secretary chat', status: 'mock', backend: 'Read: /chat/conversations, messages (blocking or server-sent events)', needs: 'Map chat messages; the agent run behind a message' },
  { area: 'Chat and approvals', name: 'Approval and rejection cards, multi-step previews', status: 'mock', backend: 'Read: /chat/tool-calls/{id}, approve, cancel, retry', needs: 'Map proposed-action states to approval states; one tool call per change' },
  { area: 'Chat and approvals', name: 'Execution progress and results', status: 'mock', backend: 'Read: tool-call status incl. executing, executed, partially_executed, failed', needs: 'Map to execution status; decide how partially_executed is shown' },
  { area: 'Chat and approvals', name: 'Editing a proposal before approving', status: 'missing', backend: 'Read: approve accepts payload_overrides', needs: 'An edit control; an edit counts as a human intervention' },

  { area: 'Evaluation', name: 'Twenty-case suite, scorer, runner, reports', status: 'waiting', backend: 'None: no sandbox or evaluation endpoint', needs: 'A sandbox mode and an evaluation entry point (docs/handoff/BACKEND_REQUIREMENTS.md, group C)' },
  { area: 'Evaluation', name: 'Results against the real agent', status: 'waiting', backend: 'None', needs: 'The above. No real result exists yet.' },
];

export function countByStatus(features: Feature[] = FEATURES): Record<FeatureStatus, number> {
  const counts: Record<FeatureStatus, number> = { connected: 0, mock: 0, waiting: 0, missing: 0 };
  for (const feature of features) counts[feature.status] += 1;
  return counts;
}

/** docs/FEATURE_STATUS.md, generated so the document and the Overview screen cannot disagree. */
export function renderFeatureStatus(features: Feature[] = FEATURES): string {
  const counts = countByStatus(features);
  const areas = [...new Set(features.map((f) => f.area))];
  const out: string[] = [
    '# Feature status',
    '',
    '<!-- Generated from src/lib/featureStatus.ts by `npm run docs:generate`. Do not edit by hand. -->',
    '',
    'What the Executive Desk frontend can do today, and what each part needs before it shows real data. The same list is shown on the Overview screen.',
    '',
    '| Status | Meaning | Features |',
    '| --- | --- | --- |',
    `| ${STATUS_LABEL.connected} | Runs against the real Scriba backend | ${counts.connected} |`,
    `| ${STATUS_LABEL.mock} | The screen works on labelled mock data. The backend capability exists; the mapping in the frontend API layer is not written | ${counts.mock} |`,
    `| ${STATUS_LABEL.waiting} | The screen works on labelled mock data. There is no backend contract to connect it to yet | ${counts.waiting} |`,
    `| ${STATUS_LABEL.missing} | Not built | ${counts.missing} |`,
    '',
    'Nothing is connected to the real backend yet. Every screen runs on the in-memory mock, which is labelled as mock data on every page and cannot send email or change a calendar.',
    '',
    '"Backend today" quotes Role 1\'s `docs/BACKEND_CONTRACT.md` on `main`. **Tested** means Role 1\'s smoke script has called the endpoint. **Read** means it exists in Scriba and was read from source. **Proposed** and **None** mean it does not exist yet. Nothing here invents an endpoint: where the backend has none, the frontend waits.',
    '',
  ];
  for (const area of areas) {
    out.push(`## ${area}`, '', '| Feature | Status | Backend today | Needed to connect |', '| --- | --- | --- | --- |');
    for (const f of features.filter((x) => x.area === area)) out.push(`| ${f.name} | ${STATUS_LABEL[f.status]} | ${f.backend.replace(/\|/g, '\|')} | ${f.needs.replace(/\|/g, '\|')} |`);
    out.push('');
  }
  out.push('See [API_INTEGRATION_REQUIREMENTS.md](API_INTEGRATION_REQUIREMENTS.md) for the data each screen needs, field by field.', '');
  return out.join('\n');
}
