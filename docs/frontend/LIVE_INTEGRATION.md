# Live integration

How the Executive Desk frontend is connected to Scriba, what was verified and how, and what
the backend still has to provide. Written for the backend owner and for anyone reviewing the
frontend.

The backend's own contract is [../BACKEND_CONTRACT.md](../BACKEND_CONTRACT.md). This document
does not restate it; it says what the frontend does with it.

## 1. One application, two data modes

`frontend/` is the only application. `executive-desk/` no longer exists: its screens,
components, mock, evaluation harness, fixtures and documents were moved into `frontend/` and
`docs/frontend/` with their history.

| Mode | How to start | Data |
| --- | --- | --- |
| Live (default) | `npm run dev` | Scriba's API through the session cookie |
| Demo | `npm run dev:demo` | The in-memory mock with fictional people; labelled as mock data on every screen |
| Contract | `VITE_API_MODE=http VITE_API_BASE_URL=... npm run dev` | The predecessor's contract-v1 adapter, for the reference server (`npm run dev:reference`) |

Live and demo are never mixed. A live request that fails is shown as a failure, with a way to
try again. Nothing falls back to mock data.

Authentication is Scriba's and only Scriba's: the HttpOnly session cookie, read through
`GET /providers/status`. Requests send credentials. There is no token and no second sign-in. A
401 from any request returns the user to the sign-in screen, where they choose how to sign in.

## 2. Where the code is

| Path | What it is | Owner |
| --- | --- | --- |
| `frontend/src/api/`, `lib/apiBase.ts`, `lib/connections.ts`, `hooks/useProviderStatus.ts` | The typed clients for Scriba and the Desk overlay | Backend. Not edited by the frontend work |
| `frontend/src/live/scribaApi.ts` | Clients for the Scriba endpoints the workspace also needs: chat, action cards, tasks, reminders, notifications, drafts | Frontend |
| `frontend/src/live/mappers.ts` | The mapping layer: backend responses to view models. Pure and unit-tested | Frontend |
| `frontend/src/live/liveDesk.ts` | `ScribaWorkspace`, the live data source for the inbox, calendar and tasks screens | Frontend |
| `frontend/src/live/workQueue.ts`, `describeAction.ts`, `writePolicy.ts` | Work stages, what an action card says, which approvals are allowed | Frontend |
| `frontend/src/live/Live*.tsx`, `ToolCallCard.tsx` | The live overview, chat, approval center, activity and message detail | Frontend |
| `frontend/src/pages/`, `components/` | The screens shared by live and demo, and the demo-only screens | Frontend |
| `frontend/src/harness/` | The predecessor's contract-v1 API: types, mock, HTTP adapter, reference server | Frontend |
| `frontend/src/evaluation/` | The suites, scorer, runner and reports | Frontend |

## 3. Endpoints in use

"Seeded" means exercised in a browser against Scriba's seeded backend with the Desk overlay
(section 7). "Unit" means covered only by tests with the client functions replaced.

| Screen | Endpoint | Verified |
| --- | --- | --- |
| Session | `GET /providers/status`, `POST /auth/logout` | Seeded |
| Sign-in form | `POST /auth/signin` | Unit. Google and Microsoft sign-in are navigations to Scriba |
| Overview | `GET /desk/briefing`, `GET /desk/inbox`, `GET /desk/connections`, `GET /desk/health` | Seeded |
| Inbox | `GET /desk/inbox?provider=all&limit=50` | Seeded |
| Message detail | `GET /desk/inbox/item` | Seeded: triage, reply-from account, thread. The calendar section needs a meeting request and connected calendars: Unit |
| Reply draft | `POST /drafts/create` with the overlay's `draftRequest`, `GET /drafts`, `POST /drafts/{id}/discard` | Unit. Needs a model |
| Calendar | `GET /calendar/events?provider=google\|outlook&start=&end=` | Seeded for "no calendar connected"; events and a failed provider: Unit |
| Tasks | `GET /tasks?order=actionable`, `POST /tasks/{id}/complete` | Seeded (list). Completing: Unit |
| Reminders | `GET /reminders/upcoming`, `POST /reminders/{id}/cancel` | Seeded (empty list). Cancelling: Unit |
| Chat | `GET` and `POST /chat/conversations`, `GET .../messages`, `POST .../messages/stream`, `POST .../messages` as fallback | Seeded: a new conversation, a streamed turn, the stored reply |
| Approvals, activity | The action cards in `GET .../messages`; `POST /chat/tool-calls/{id}/approve`, `/cancel` | Seeded: one task approved (the task then existed in `GET /tasks`), one cancelled |
| Retry | `POST /chat/tool-calls/{id}/retry` | Unit |

Not called: `POST /send`, `POST /reply`, `POST /drafts/{id}/send`, `POST`, `PATCH` and `DELETE`
on `/calendar/events`, and `POST /desk/slots/check` and `GET /desk/availability` (the chat
agent's tools and the message detail cover the same ground; a standalone availability screen is
a next step).

## 4. Mapping rules

1. **Identity is carried, never rebuilt.** A message keeps `provider`, `provider_account_id`
   and the mailbox it arrived in; the Desk's id for it is `<provider>:<message id>`. The message
   detail is read with that same provider and mailbox. A calendar event keeps its provider,
   event id and account.
2. **Nothing is invented.** The backend returns the provider's preview, not a summary: the view
   model marks it as a snippet and the screen does not call it a summary. Scriba has no work
   status per message, so none is shown. An attendee with no name is shown by address.
3. **Server state wins.** Every status on an action card is the server's. After approve, cancel
   or retry the Desk re-reads; it never advances a status itself. While a card is `approved` or
   `executing` it is polled.
4. **Partial reads are stated.** When one mailbox or one calendar could not be read, the screen
   names it and says the list or the numbers are incomplete. An unknown count is a dash, never a
   zero. A calendar that could not be read is never presented as free time.
5. **Times.** A timestamp with an offset is shown in the user's Scriba time zone, taken from the
   briefing or the calendar response (the browser's zone until one arrives). A time on an action
   card without an offset is shown as written, with the zone the card states.

## 5. Approvals and the write policy

Approving a card on Scriba executes it. The Desk therefore separates three kinds of action
(`writePolicy.ts`):

| Kind | Tools | Approval in the Desk |
| --- | --- | --- |
| Inside Scriba | `create_task`, `create_reminder` | Allowed |
| Reaches outside | `send_email`, `draft_email_reply`, `create_calendar_event`, `update_calendar_event`, `cancel_calendar_event` | **Disabled** until the backend reports `externalWrites.enabled: true` on `GET /desk/health` |
| Not part of the Desk, or unknown | Slack, Teams, Jira, file tools, anything unrecognised | Never. Can be cancelled |

No backend sets `externalWrites` today, so on every current backend mail and calendar approvals
are off. The card is still shown in full: what will happen, the recipients, the account, the
calendar change, the reason the agent gave, and the availability finding when the backend
attaches one. Cancelling is always allowed.

**Retry.** On Scriba a retry of a failed action executes at once: it does not return the card
for a second approval (`app/chat_service.py`, `retry_tool_call`; a calendar change is re-read
and re-validated first). The Desk does not pretend otherwise. The control is "Retry…", which
opens a confirmation that says the action runs immediately, and warns when part of the first
attempt has an unknown outcome and might already have happened. A retry is gated by the same
write policy as an approval.

**Idempotency.** Approve sends `idempotency_key: chat-tc-<id>`, the key Scriba's own client
uses, so a repeated request cannot run the action twice. The Desk never repeats a write on its
own. In chat, once the stream has opened the server has the message: if the connection drops the
conversation is re-read and the message is not sent again.

**Booking despite a conflict.** With the Desk chat scope (branch `agent1/chat-workflow`, not on
`main`) a calendar card held for a conflict or an unreadable calendar arrives as `needs_info`
with `output.availability`. The Desk shows the finding and offers an explicit "book anyway"
checkbox that sends `payload_overrides.desk_availability_override: true`. It is reachable only
when external writes are enabled. Unit-tested against the shape in that branch; not run.

## 6. Work stages

The target pipeline is Received, Classified, Planning, Awaiting approval, Executing, Verifying,
then Completed, Awaiting reply, Escalated or Failed. The Desk shows only what the backend
reports:

| Stage | Source | Shown |
| --- | --- | --- |
| Classified | Triage on every row of `GET /desk/inbox` | Yes |
| Planning | Action status `pending`, `draft` | Yes |
| Needs information | `needs_info` | Yes |
| Awaiting approval | `awaiting_approval` | Yes |
| Executing | `approved`, `executing` | Yes |
| Completed | `executed` | Yes |
| Partly completed | `partially_executed`, with each part's result | Yes |
| Failed | `failed` | Yes |
| Cancelled, not supported | `cancelled`, `unsupported` | Yes |
| Received | Mail is triaged in the read that returns it | No |
| Verifying | No separate verification step is reported | No |
| Awaiting reply | Scriba does not track awaited replies | No |
| Escalated | No escalation record | No |

A status the frontend does not know is shown as planning, never as finished.

## 7. What was verified

**Seeded backend.** Scriba at `3ae3a2aa` run by `backend/dev/seeded_desk_server.py`: the real
FastAPI application with in-memory storage, no database, no provider network and no model.
Frontend on `http://localhost:5173`. Checked in Chrome on 2026-11-14:

- The session was accepted and the overview loaded: 50 messages arrived, classified by rules,
  2 actions awaiting approval, 2 completed, the four connections with their real states.
- Inbox: 50 Gmail messages; the unavailable Outlook mailbox did not raise a false warning.
  A message detail showed triage, the reply-from account and the thread.
- Calendar: no calendar connected, stated as such.
- Tasks: the seeded tasks listed. Follow-ups: stated as not available.
- Chat: a new conversation was created and a turn streamed; the stored reply was Scriba's own
  "AI service is failing" message, because the seeded backend has no model.
- Approval center: one task approved (status became `executed` and the task appeared in
  `GET /tasks`), one cancelled (`cancelled`). Both statuses came from the server.
- Layout at 375, 792 and 1422 pixels wide: no horizontal overflow on any live screen; the
  navigation switches to the bottom bar below the large breakpoint.

On this machine the seeded backend answered `/desk/*` in 10 to 16 seconds, because it retries
its absent database on each request. The screens show a loading state for that time.

Screenshots could not be captured in this session, so the mock screenshots in `screenshots/`
are still the only images. They show demo mode.

**Not verified.** Any live Gmail, Outlook or calendar. Any model: no real agent turn, plan,
draft or approval of an agent-proposed action has been seen. Calendar events from two providers.
Executing, partially executed and failed actions from a real backend. External writes.

## 8. Evaluation

Kept as they were: the twenty-case desk suite, the scheduling regression suite, the scorer, the
runner, the mock, the reference server, the HTTP adapter tests, the reports and the generated
case documents.

Results are kept in four kinds, and the Evaluation screen says which exist:

| Kind | What it proves | State |
| --- | --- | --- |
| Mock and reference | The scorer and runner behave as specified | Exists: `npm run eval`, or the self-test on the Evaluation screen |
| Seeded integration | The overlay and the frontend work on Scriba's seeded backend | Section 7, and the backend's own tests. Not an agent result: no pass rate |
| Real-model sandbox | How the real agent does on the twenty cases | **None** |
| Live provider | The agent acting on real accounts | **None.** The suite never sends real mail or changes a real calendar |

No agent pass rate, cost or latency exists. None is shown.

**The runner and Scriba's session.** The command-line runner now signs in the way Scriba
requires and asks before it sends anything:

```bash
EVAL_EMAIL=... EVAL_PASSWORD=... npm run eval -- --scriba-url http://localhost:8788 --signin
```

It signs in with `POST /auth/signin`, keeps the session cookie in memory, sends the Desk origin
(`http://localhost:5173`) that Scriba requires, and reads `GET /desk/health` and
`GET /desk/eval/v1/meta`. On today's backend the second is 404 and the runner stops with that
reason: no case is posted. Credentials come from the environment and are never written or
printed.

## 9. Backend requirements

In priority order. Items 1 and 2 unblock the product; item 3 unblocks evaluation.

### 1. Report that external writes are safe (unblocks mail and calendar approvals)

`GET /desk/health` adds:

```json
"externalWrites": { "enabled": true, "revision": "<commit or tag of the safety fixes>" }
```

Set it only on a backend that contains the verified fixes for sending and calendar writes
(reply target and thread, sending mailbox, recipient provenance, approve and retry idempotency,
duplicate calendar events, Outlook create idempotency, a closed validator). Absent or anything
other than `true` means off. The frontend needs no change when it appears.

Please also confirm two things the frontend currently has to assume:

- `draft_email_reply`: does approving it send the reply, or store a draft? It is treated as a
  send.
- Retry: is immediate execution the intended behaviour for mail? If a retry should come back
  for approval instead, the frontend's confirmation step can go.

### 2. A work-queue listing (unblocks a complete approval center and activity)

There is no way to list actions across conversations, so the Desk reads the twelve most recent
conversations and says so when there are more. Proposed:

```
GET /desk/work?status=&limit=&cursor=
```

returning, newest first, each action with: its tool-call fields as today, the conversation id
and title, the assistant text and user request that led to it, `expires_at` when an approval
can expire, and, once automations create work, the source email (`provider`,
`provider_account_id`, message id) and the trigger. The same shape would carry the missing
stages when they exist: `received`, `verifying`, `awaiting_reply`, `escalated`.

### 3. Sandbox evaluation routes (unblocks real-model results)

The smallest safe contract is the five calls the runner makes (`EvaluationTarget` in
`frontend/src/harness/client.ts`), mounted under `/desk/eval/v1`:

| Call | Purpose |
| --- | --- |
| `GET /meta` | `contractVersion`, `agent: "real"\|"scripted"`, `sandbox`, `principal`, `capabilities` |
| `POST /evaluation/runs` `{caseId, input, context, mode: "sandbox"}` | Start one case. `context` carries the calendar, the clock and any faults |
| `GET /runs/{id}` | The run with its action trace, triage, outcome and token usage |
| `GET /approvals?runId=` | The approvals of that run only |
| `POST /approvals/{id}/decision` | The harness approves or rejects |

Safety conditions, all checked by the runner or stated where they cannot be:

- The routes exist only when `sandbox` is true. In sandbox mode no real mailbox or calendar is
  reachable: tool implementations are swapped, and every side-effect action is marked
  `simulated: true`. The runner refuses a backend that reports `sandbox: false`.
- The same agent runs as in production: prompts, model and tool selection. Only the tools'
  effects are replaced. Otherwise the results do not describe the product.
- Cases do not share state. The approval gate is unchanged.
- Authentication is the Scriba session, like every other route.

The full field-level contract is [API_CONTRACT.md](API_CONTRACT.md); the requirement list with
how each is verified is [handoff/BACKEND_REQUIREMENTS.md](handoff/BACKEND_REQUIREMENTS.md),
groups A to C. Group D of that list (requests, runs and conversations for the product screens)
is **no longer needed**: the product screens run on Scriba's own endpoints.

### 4. Smaller items

- Message bodies and older thread messages in `GET /desk/inbox/item` (today: previews of the
  recent inbox).
- The user's time zone in `GET /desk/connections`, so times are right before the first calendar
  or briefing response.
- Paging for `GET /desk/inbox` beyond the newest 50.
- A way to reopen a completed task, or confirmation that `/tasks/{id}/restore` does it.
- Tracking of awaited replies, for the follow-ups screen.
