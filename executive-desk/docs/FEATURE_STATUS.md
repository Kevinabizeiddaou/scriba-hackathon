# Feature status

<!-- Generated from src/lib/featureStatus.ts by `npm run docs:generate`. Do not edit by hand. -->

What the Executive Desk frontend can do today, and what each part needs before it shows real data. The same list is shown on the Overview screen.

| Status | Meaning | Features |
| --- | --- | --- |
| Implemented and connected | Runs against the real Scriba backend | 0 |
| Implemented with mock data | The screen works on labelled mock data. The backend capability exists; the mapping in the frontend API layer is not written | 8 |
| Waiting for backend contract | The screen works on labelled mock data. There is no backend contract to connect it to yet | 13 |
| Not implemented | Not built | 2 |

Nothing is connected to the real backend yet. Every screen runs on the in-memory mock, which is labelled as mock data on every page and cannot send email or change a calendar.

"Backend today" quotes Role 1's `docs/BACKEND_CONTRACT.md` on `main`. **Tested** means Role 1's smoke script has called the endpoint. **Read** means it exists in Scriba and was read from source. **Proposed** and **None** mean it does not exist yet. Nothing here invents an endpoint: where the backend has none, the frontend waits.

## Workspace

| Feature | Status | Backend today | Needed to connect |
| --- | --- | --- | --- |
| Executive overview | Implemented with mock data | None as one endpoint; it is a composition of the items below | The inbox, calendar, task and approval sources below |
| Connected accounts (Gmail, Outlook, Google Calendar, Outlook Calendar) | Implemented with mock data | Tested: GET /providers/status | Map ProviderStatusPayload to the account list; cookie session |
| Activity and execution history | Waiting for backend contract | None for the Desk. Scriba has automation run history (Read) | A history source for approvals and executed actions |
| Sign-in | Not implemented | Exists: Scriba session cookie, sign-in by navigating to /auth/login | A sign-in screen that navigates to Scriba. No new authentication is built here. |

## Email

| Feature | Status | Backend today | Needed to connect |
| --- | --- | --- | --- |
| Unified Gmail and Outlook inbox | Implemented with mock data | Tested: GET /emails?provider=gmail|outlook | Map EmailListResponse; keep provider and account with each item |
| Thread view | Waiting for backend contract | None documented | An endpoint that returns the messages of a thread |
| Priority and classification | Waiting for backend contract | None | Triage output per message: category and priority |
| Summaries and extracted action items | Waiting for backend contract | None | Summary and action items per message |
| Reply drafts | Waiting for backend contract | Read: POST /drafts/create, POST /drafts/{id}/send | Draft content and state in the frontend shape; sending only after approval |
| Pending and completed email actions | Waiting for backend contract | Read: chat tool-call statuses | Action state per email |

## Calendar

| Feature | Status | Backend today | Needed to connect |
| --- | --- | --- | --- |
| Unified Google and Outlook calendar, day and week | Implemented with mock data | Tested: GET /calendar/events?provider=google|outlook | Map CalendarEventsPayload; calendar source per event |
| Conflict visualisation | Implemented with mock data | Proposed: POST /desk/slots/check | Computed in the frontend from the events today; the backend check when it exists |
| Proposed meeting slots | Waiting for backend contract | Proposed: GET /desk/availability | Availability across both calendars; slots attached to proposals |
| Meeting preparation view | Waiting for backend contract | None | Related mail, open tasks and notes per event |

## Tasks and follow-ups

| Feature | Status | Backend today | Needed to connect |
| --- | --- | --- | --- |
| Extracted tasks and deadlines | Waiting for backend contract | None documented for the Desk | A task store and task extraction |
| Reminders | Waiting for backend contract | None documented for the Desk | A reminder store |
| Follow-up tracking and overdue indicators | Waiting for backend contract | None | Tracking of sent mail that is waiting for a reply |

## Chat and approvals

| Feature | Status | Backend today | Needed to connect |
| --- | --- | --- | --- |
| Secretary chat | Implemented with mock data | Read: /chat/conversations, messages (blocking or server-sent events) | Map chat messages; the agent run behind a message |
| Approval and rejection cards, multi-step previews | Implemented with mock data | Read: /chat/tool-calls/{id}, approve, cancel, retry | Map proposed-action states to approval states; one tool call per change |
| Execution progress and results | Implemented with mock data | Read: tool-call status incl. executing, executed, partially_executed, failed | Map to execution status; decide how partially_executed is shown |
| Editing a proposal before approving | Not implemented | Read: approve accepts payload_overrides | An edit control; an edit counts as a human intervention |

## Evaluation

| Feature | Status | Backend today | Needed to connect |
| --- | --- | --- | --- |
| Twenty-case suite, scorer, runner, reports | Waiting for backend contract | None: no sandbox or evaluation endpoint | A sandbox mode and an evaluation entry point (docs/handoff/BACKEND_REQUIREMENTS.md, group C) |
| Results against the real agent | Waiting for backend contract | None | The above. No real result exists yet. |

See [API_INTEGRATION_REQUIREMENTS.md](API_INTEGRATION_REQUIREMENTS.md) for the data each screen needs, field by field.
