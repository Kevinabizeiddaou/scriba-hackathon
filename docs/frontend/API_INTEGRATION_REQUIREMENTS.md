# API integration requirements

What the Executive Desk frontend needs from the Scriba backend, screen by screen, set against what the backend has today.

"Backend today" is taken from Role 1's `docs/BACKEND_CONTRACT.md` on the `main` branch (Scriba at commit `3ae3a2aa`), using its own three labels:

- **Tested**: Role 1's smoke script has called it on a running backend.
- **Read**: it exists in Scriba and was read from source. Not yet called.
- **Proposed**: it does not exist yet.
- **None**: that document does not mention anything for it.

This document does not define endpoint behaviour. Where the backend has nothing, the row says what data the screen needs and leaves the shape to Role 1. Nothing in the frontend calls an endpoint that is not Tested, and today nothing in the frontend calls the real backend at all: see [FEATURE_STATUS.md](FEATURE_STATUS.md).

## 1. Rules the frontend follows

These come from section 1 of Role 1's contract. The frontend code already behaves this way.

| Rule | In the frontend |
| --- | --- |
| The session is Scriba's HttpOnly cookie. There is no bearer token. | `HttpExecutiveDesk` sends `credentials: 'include'` and no `Authorization` header. No token is stored anywhere. |
| Sign-in is a navigation to Scriba, not a fetch. | No sign-in screen exists yet. On a 401 the app says the Scriba session has ended and to sign in again. It never starts a provider sign-in by itself. |
| The frontend must be served from `http://localhost:5173`. | Against Scriba, run `npm run dev -- --port 5173`. The default port 5183 is for the mock only. |
| A write is never retried automatically. | A `POST` is sent once unless the backend states that it handles idempotency keys (`capabilities.idempotentPosts`). Buttons are disabled while a write is in flight. |
| Keep the provider and account with each item. | `InboxEmail` and `AgendaEvent` carry `provider` and `account`. Later actions on an item must send them back. |
| Ignore integrations the Desk excludes. | Only Gmail, Outlook Mail, Google Calendar and Outlook Calendar appear anywhere in the frontend. |

## 2. What each screen needs

The view models are in [`src/api/workspace.ts`](../src/api/workspace.ts) and [`src/api/types.ts`](../src/api/types.ts). They describe what the screens render. They are not a proposal for backend shapes: the mapping belongs in the frontend API layer.

### Accounts and overview

| Screen need | View model | Backend today | Gap |
| --- | --- | --- | --- |
| Which of the four accounts are connected | `ConnectedAccount` | **Tested** `GET /providers/status` | Mapping not written. Needs `providers.gmail`, `outlook`, `google_calendar`, `outlook_calendar` and `emailAccounts[]`. |
| Who is signed in | `DeskMeta.principal` | **Tested** `GET /providers/status` (`authorized`, `email`, `name`) | The principal's time zone and working hours are not in that payload. The calendar payload has a `timezone`. Working hours: none. |
| Overview counts | built in the frontend from the lists below | none needed | None, once the lists below are connected. |

### Email

| Screen need | View model | Backend today | Gap |
| --- | --- | --- | --- |
| Gmail and Outlook messages in one list | `InboxEmail` | **Tested** `GET /emails?provider=gmail\|outlook&limit=&cursor=&mailbox=` | Mapping not written. Two calls, merged and sorted in the frontend. |
| The messages of a thread | `InboxEmail.thread` | **None** | An endpoint that returns a thread's messages, oldest first, with who sent each. |
| Category and priority per message | `InboxEmail.category`, `priority`, `flags` | **None** | Triage output per message. |
| Summary and extracted action items | `InboxEmail.summary`, `actionItems` | **None** | Per message. |
| A reply draft | `ReplyDraft` | **Read** `POST /drafts/create`, `GET /drafts`, `POST /drafts/{id}/send`, `/discard` | The response shape is not documented. The screen needs the draft's recipients, subject and body, why it was drafted that way, and its state. |
| Sending a draft only after approval | `ReplyDraft.state`, `ApprovalRequest` | **Read** `POST /drafts/{id}/send`; **Read** chat tool-call approval | How a draft relates to an approval is open: is sending a draft itself the approved action, or does it go through a proposed action? |
| Pending and completed actions per email | `InboxEmail.status` | **Read** proposed-action statuses | No way to ask "what is pending for this email". |

### Calendar

| Screen need | View model | Backend today | Gap |
| --- | --- | --- | --- |
| Google and Outlook events for a day or week | `AgendaEvent` | **Tested** `GET /calendar/events?provider=google\|outlook&start=&end=` | Mapping not written. Two calls, merged in the frontend. Served from Scriba's synced copy, so the screen should say when it was last synced if that is available. |
| Conflicts between the two calendars | `AgendaEvent.conflictsWith` | **Proposed** `POST /desk/slots/check` | Computed in the frontend from the events for now. A calendar that cannot be read must not be shown as free. |
| Slots the secretary proposes | `AgendaEvent.kind = 'proposed'` | **Proposed** `GET /desk/availability` | Proposed slots need to be attached to the approval that offers them. |
| Meeting preparation | `MeetingPrep` | **None** | Related mail, open tasks and notes per event. |

### Tasks, reminders and follow-ups

| Screen need | View model | Backend today | Gap |
| --- | --- | --- | --- |
| Tasks with deadlines, found in mail or added by hand | `WorkTask` | **None** for the Desk | A task store, and task extraction from mail. |
| Reminders | `Reminder` | **None** for the Desk | A reminder store. |
| Replies the principal is waiting for, with overdue state | `FollowUp` | **None** | Tracking of sent mail that expects an answer, with an expected-by time. |
| Drafting a reminder for an overdue reply | `ApprovalRequest` | **Read** mail and approval endpoints | Same open point as reply drafts. |

### Chat and approvals

| Screen need | View model | Backend today | Gap |
| --- | --- | --- | --- |
| Conversations and messages | `Conversation`, `ConversationMessage` | **Read** `GET/POST /chat/conversations`, `GET/POST .../messages`, `.../messages/stream` | Mapping not written. The frontend polls today; the stream is not consumed. |
| What the agent did for a message | `AgentRun`, `AgentAction` | **Read** proposed-action cards in the message history | The steps the agent took before proposing (what it read) are not documented as available. |
| Everything waiting for a decision, across conversations | `ApprovalRequest[]` | **Read** `GET /chat/tool-calls/{id}` (one at a time) | No list of pending proposed actions is documented. The Approval Center needs one. |
| Approve or reject | `decideApproval` | **Read** `POST /chat/tool-calls/{id}/approve`, `/cancel` | See the status mapping below. |
| Several changes behind one approval | `ApprovalRequest.changes[]` | **Read** one tool call per proposed action | Open: can related actions be grouped, or does the frontend group them? |
| Progress and result per step | `executionSteps()` | **Read** `executing`, `executed`, `partially_executed`, `failed` | `partially_executed` needs to say which parts ran. |
| Trying again after a failure | new proposal, new approval | **Read** `POST /chat/tool-calls/{id}/retry` | Open: does a retry run at once, or wait for approval again? The frontend assumes nothing runs without a fresh approval. |
| Editing a proposal before approving | not built | **Read** `payload_overrides` on approve | Not built. An edit would be recorded as a human intervention. |

Proposed mapping of Scriba's proposed-action status to the frontend's approval state. It is not implemented, and Role 1 should correct it:

| Scriba status | Approval status | Execution status | Shown as |
| --- | --- | --- | --- |
| `pending`, `needs_info`, `draft` | none yet | | The agent is still preparing; no card |
| `awaiting_approval` | `pending` | `not_started` | Card with Approve and Reject |
| `approved`, `executing` | `approved` | `executing` | Card with progress |
| `executed` | `approved` | `executed` | Card with results |
| `partially_executed` | `approved` | `failed` | Card with per-step results and the recovery block |
| `failed` | `approved` | `failed` | Card with the recovery block |
| `cancelled` | `rejected` | `not_started` | "Nothing was sent" |
| `unsupported` | none | | A plain message that this cannot be done |

### Activity

| Screen need | View model | Backend today | Gap |
| --- | --- | --- | --- |
| What was read, proposed, decided and executed, newest first | `ActivityEntry` | **None** for the Desk. **Read** automation run history, which Role 1 says not to build on yet | A history source for approvals and executed actions. |

### Evaluation

| Need | Backend today | Gap |
| --- | --- | --- |
| Start one case with a given inbox message or chat turn, calendar, tasks and awaited replies | **None** | A sandbox entry point. The request body is described in [API_CONTRACT.md](API_CONTRACT.md), section 11, as a starting point. |
| Guarantee that nothing real is touched | **None** | A sandbox mode in which every write is simulated and marked as such. |
| The trace of a run: tool calls with inputs, results, order and approval links | **Read** proposed-action cards | The scorer needs every tool call, including reads, with its input. |
| Simulated tool failures | **None** | Needed for the failure case. Without it that case is skipped and reported as skipped. |
| Token counts per run | **None** | Needed for cost per run. Without it the cost stays empty. |

Until these exist, the suite runs only against the scripted mock, and those results are labelled simulated and never shown as agent performance.

## 3. Two ways to connect, and a suggestion

1. **Map Scriba's existing endpoints in the frontend API layer.** A class that implements `WorkspaceApi` by calling `GET /providers/status`, `GET /emails` and `GET /calendar/events`. This works today for the three Tested endpoints and needs no backend change. It would move "Connected accounts", "Unified inbox" and "Unified calendar" to connected.
2. **Scriba serves the Desk contract.** Endpoints under `/api/executive-desk/v1` as in [API_CONTRACT.md](API_CONTRACT.md). This is what the agent, approval and evaluation screens were built against, and what the HTTP adapter and its 39 integration tests cover.

Suggested: option 1 for the read-only screens now, and an agreed shape for the agent, approvals and evaluation before anything is built on either side. This is a decision for the project lead and Role 1, not something the frontend has acted on.

Role 1's branch has its own `frontend/` with typed shapes for the Tested endpoints (`frontend/src/api/contract.ts`, `scriba.ts`, `client.ts`) and asks that they be reused rather than re-declared. Option 1 should import those types once the two frontends live in one tree. How the two frontends are combined is also the project lead's decision.

## 4. Open questions for Role 1

1. Is there, or will there be, a list of proposed actions that are waiting for approval, across conversations?
2. Does `POST /chat/tool-calls/{id}/retry` execute at once, or does the retried action wait for approval again?
3. What does `partially_executed` report about which parts ran?
4. Can related proposed actions (move a meeting and tell the attendee) be approved together, and is their order guaranteed?
5. What do `POST /drafts/create` and `GET /drafts` return, and is sending a draft subject to the same approval as other writes?
6. Is there an endpoint for the messages of a thread?
7. Where do triage results (category, priority), summaries and action items come from, and when are they computed?
8. Is a task store, a reminder store or follow-up tracking planned for the Desk, or should the first version leave those screens out?
9. Where do the principal's time zone and working hours come from?
10. Will there be a sandbox mode and a way to start an evaluation case, and will runs report token counts?
11. Does the backend honour an idempotency key on writes such that a repeated request is safe? The frontend repeats a write only if the answer is yes.

## 5. What the frontend will not do

- Build its own authentication, or use bearer tokens.
- Register new Google Cloud or Microsoft Graph applications.
- Add Slack, Teams, Drive, OneDrive, Jira or desktop automation.
- Call an endpoint that is Read or Proposed before Role 1 marks it Tested.
- Show mock or scripted results as real ones. Every mock screen says it is mock data.
