# Backend contract

For the frontend and the evaluation harness. The backend is Scriba at commit
`3ae3a2aa`. Typed versions of sections 2 and 3 are in
`frontend/src/api/contract.ts` and `frontend/src/api/scriba.ts`; use those
rather than re-declaring shapes.

Each endpoint is marked with how far it has been checked:

- **Tested**: called by `scripts/smoke.mjs` on a running Scriba backend.
- **Read**: route and request model read in Scriba's source; not yet called from this repository.
- **Proposed**: does not exist yet. Do not build against it until it moves to Tested.

## 1. Rules every client must follow

1. **Origin.** Serve the frontend from `http://localhost:5173` (or
   `127.0.0.1:5173`). Requests from other origins are refused.
2. **Credentials.** Send cookies on every request (`withCredentials: true`,
   `credentials: 'include'`). The session is an HttpOnly cookie owned by the
   API host. There is no bearer token.
3. **Sign-in is a navigation.** Send the browser to `<api>/auth/login`
   (Google) or `<api>/auth/outlook/login` (Microsoft). Do not fetch these.
   The callback is on the API host, and afterwards the browser is returned to
   Scriba's own frontend, so on a hosted API the user comes back to the Desk
   by navigating to it.
4. **Signed-in state** is `authorized` in `GET /providers/status`. A 401 from
   any endpoint means the session is gone: show the sign-in screen. Do not
   start a provider sign-in automatically.
5. **Never pass another user's account.** An `account=` parameter naming a
   different user is refused with 403.
6. **Keep the provider account with the item.** Mail rows carry `provider`
   and `provider_account_id`; calendar rows carry `provider` (or
   `calendar_provider`) and `provider_account_id`. Any later action on that
   item must send the same provider and account.
7. **Writes are deliberate.** Send an `idempotency_key` with every create,
   disable the control on click, and never retry a write automatically:
   re-read the state first.
8. **Out of scope.** `GET /providers/status` also reports integrations the
   Desk excludes. Ignore those keys; `capabilitiesFrom()` in
   `frontend/src/lib/connections.ts` already does.

Errors are JSON: `{"error": "...", "errorCode": "...", "requestId": "..."}`;
some routes use `{"detail": "..."}`. `ApiClientError` in
`frontend/src/api/client.ts` normalises both.

## 2. Tested endpoints (Phase 1)

| Method and path | Auth | Returns |
| --- | --- | --- |
| `GET /live` | Public | `{ok: true, service}` |
| `GET /health` | Public | `{ok, status, service, database: {ok}, maintenance: {maintenanceMode}}`. Always 200; read `ok`. |
| `GET /providers/status` | Public | `ProviderStatusPayload`. Anonymous: `authorized: false`, no `emailAccounts`. Signed in: `authorized: true`, `email`, `name`, `emailAccounts[]`, `gmailAccounts[]`. Each of `providers.gmail`, `google_calendar`, `outlook`, `outlook_calendar` has `connected`, `available`, `configured`, `status`, `reason`, `loginPath`. |
| `POST /auth/signin` `{email, password}` | Public | 200 and a session cookie; 401 on bad credentials |
| `POST /auth/logout` | Session | `{status: "logged_out"}` |
| `GET /emails?provider=gmail\|outlook&limit=&cursor=&mailbox=` | Session | `EmailListResponse`: `items[]`, `returnedCount`, `unreadCount`, `hasMore`, `nextCursor`. `limit` 1 to 100. `mailbox` narrows to one of the user's Gmail accounts. |
| `GET /calendar/events?provider=google\|outlook&start=&end=` | Session | `CalendarEventsPayload`: `meetings[]`, `range`, `timezone`. Served from Scriba's synced copy of the calendar. |

`status` values seen: `connected`, `disconnected`, `unavailable` (the server
is not set up for that provider), `reconnect_required`.

An Outlook mailbox that is not connected returns an empty page, not an error.

## 3. Existing endpoints for later phases (Read)

These exist in Scriba. They have not been called from this repository; the
shapes are read from the request models. None is used in Phase 1.

### Mail actions

| Method and path | Body |
| --- | --- |
| `POST /reply` | `{threadId?, messageId?, text, provider?, replyMode?, providerAccountId?}` |
| `POST /send` | `{to, subject, text, provider?, attachments?, providerAccountId?}` |
| `GET /drafts`, `POST /drafts/create`, `POST /drafts/{id}/send`, `POST /drafts/{id}/discard` | create: `{provider, email_id?, thread_id?, source_item_id?, user_context?, provider_account_id?}` |

### Calendar actions

| Method and path | Body |
| --- | --- |
| `POST /calendar/events` | `{provider: "google"\|"outlook", summary, description?, start, end, timezone?, attendees?: string[], provider_account_id?, idempotency_key?}` |
| `PATCH /calendar/events/{event_id}` | Same fields; only the ones sent are changed |
| `DELETE /calendar/events/{event_id}` | Same body, sent as the request body |
| `POST /google/sync/calendar`, `POST /outlook/sync/calendar` | Refresh Scriba's copy before re-reading |

`start` and `end` are ISO 8601. Attendees are notified by the provider on
create, change and cancel.

### Chat agent and approvals

| Method and path | Notes |
| --- | --- |
| `GET/POST /chat/conversations` | Create: `{title?}` |
| `GET /chat/conversations/{id}/messages` | History including proposed-action cards |
| `POST /chat/conversations/{id}/messages` | `{content, email_id?, thread_id?, provider?, source_item_id?}`; blocking |
| `POST /chat/conversations/{id}/messages/stream` | Same body; server-sent events `start`, `delta`, `reset`, `done`, `error` |
| `GET /chat/tool-calls/{id}` | Current state of one proposed action |
| `POST /chat/tool-calls/{id}/approve` | `{payload_overrides?, idempotency_key?}` |
| `POST /chat/tool-calls/{id}/cancel`, `/retry` | |

Proposed-action `status`: `pending`, `needs_info`, `draft`,
`awaiting_approval`, `approved`, `executing`, `executed`,
`partially_executed`, `failed`, `cancelled`, `unsupported`. Read actions run
without approval; every write needs one. After approving, follow progress
with `GET /chat/tool-calls/{id}` rather than approving again.

The chat agent does not yet check availability before proposing a time, and
it can still offer actions for integrations the Desk excludes. Both are
later-phase work.

### Automations and runs

| Method and path | Notes |
| --- | --- |
| `GET/POST /automations`, `POST /automations/draft` | Draft turns plain language into a plan |
| `GET /automations/{id}/runs`, `GET /automation-runs/{id}` | Run history |
| `POST /automation-runs/{id}/approve`, `/reject`, `/retry` | |

Some of these are disabled on servers where Scriba's desktop feature is off,
and automations cannot yet create or change a calendar event. Do not build
the secretary workflow on them yet.

## 4. Desk overlay endpoints (Tested on the seeded backend)

These exist only when the backend runs with the Desk overlay
([backend/README.md](../backend/README.md)), version 0.3.0. All need a
session, and all sit behind Scriba's own session and cross-site guards. The
ones in this section are read-only. Types and client functions:
`frontend/src/api/desk.ts`; fields added in 0.3 are optional there, so a
client written against 0.2 still compiles.

"Tested" here means: unit and route tests, integration tests on the real
Scriba application with providers replaced at the SDK boundary, and the
smoke test on Scriba's seeded backend. **No live Google or Microsoft
calendar has been read through these routes yet.**

| Method and path | Purpose | Type |
| --- | --- | --- |
| `GET /desk/health` | Overlay present, version, `writes: false`, and the readiness block of section 8: `externalWrites`, `sandboxExecution`, `executionMode`, `worker`, `model` | `DeskHealth` |
| `GET /desk/connections` | The four Desk capabilities, readiness, sending mailboxes. Excluded integrations are removed on the server | `DeskConnections` |
| `GET /desk/inbox?provider=all\|gmail\|outlook&limit=&mailbox=` | Gmail and Outlook merged, newest first; every row keeps `provider` and `provider_account_id` and gains `triage` | `DeskInbox` |
| `GET /desk/inbox/item?provider=&id=&mailbox=&days=` | One message: triage, the messages of its thread found in the recent inbox, the mailbox a reply must come from, and for a meeting request the next working days across both calendars | `DeskInboxItem` |
| `GET /desk/availability?start=&end=&duration_minutes=&buffer_minutes=&timezone=&max_slots=` | Busy time from every connected Google and Outlook calendar, existing cross-calendar conflicts, and free slots inside working hours | `DeskAvailability` |
| `POST /desk/slots/check` `{start, end, timezone?, buffer_minutes?}` | One proposed time against both calendars | `DeskSlotCheck` |
| `GET /desk/briefing` | What arrived and needs the executive, today's meetings, open and due tasks, reminders. Built from Scriba records with no model call; a section that fails is named in `unavailable` | `DeskBriefing` |

`/desk/inbox/item` also returns `draftRequest` when the message needs a
reply: the exact body for Scriba's existing `POST /drafts/create`. For a
meeting request its `user_context` lists only times verified free on every
connected calendar, and tells the draft writer not to confirm a time when the
calendars could not be read or are full. Posting it writes a draft in Scriba
for review and sends nothing. **That call has not been verified from this
repository:** it needs a real mailbox and a model, which the seeded backend
does not have.

Triage `category` is one of `meeting_request`, `needs_reply`, `action_item`,
`informational`, `automated`, with `outcome` `schedule`, `reply`, `task` or
`none`. It is rule-based: Scriba's reply classifier, plus the Desk's own
reading of the text (`backend/desk_overlay/reading.py`), which recognises a
request to meet, move or cancel even when a classifier saw only news, and a
request for a decision, approval or sign-off. `reasons` then contains
`desk_meeting_new`, `desk_meeting_reschedule`, `desk_meeting_cancel` or
`desk_action_requested`. It works on the subject and the snippet (the full
body where a row carries one) and makes no model call. It is brittle to
wording: see the evaluation numbers in
[handoff/AGENT1_BACKEND_STATUS.md](handoff/AGENT1_BACKEND_STATUS.md).

Rules a client can rely on:

- `slots` is empty unless `complete` is true. `complete` is false when no
  calendar is connected (`reason: "no_calendar_connected"`) or when any
  connected calendar could not be read (`"calendar_unreadable"`); the failed
  calendar is in `calendars` with `ok: false` and an `error`.
- Slot check `free` is `true`, `false` or `null`. `null` means unknown: do
  not present it as free.
- Defaults for time zone, working hours, weekdays, buffer and duration are
  the user's Scriba preferences; query parameters override them.
- Errors: 400 for an unreadable date, a reversed or over-31-day range, or an
  unknown time zone; 422 for out-of-range numbers; 401 and 403 as in
  section 1; 404 from `/desk/inbox/item` when the id is not in the recent
  inbox.
- Google busy intervals have no title (Google's free/busy does not give
  one); Outlook intervals do.

Not in the overlay, because Scriba's existing API already covers it: drafts,
sending, calendar writes, chat, approvals, tasks, reminders, notifications,
daily brief (`POST /daily-brief`), automations. Use section 3.

## 5. Desk chat scope (Integrated on Scriba's chat service; no model called)

The Desk does not have its own chatbot. A client uses Scriba's existing chat
routes from section 3 (`/chat/conversations`, `.../messages`,
`.../messages/stream`, `/chat/tool-calls/{id}/approve|cancel|retry`). In a
backend started for the Desk, Scriba's chat agent is scoped:

- `GET /desk/health` reports `chatScope: "enforced"` and `chatTools.read` /
  `chatTools.approval`. When it reports `"off"`, the chat is unscoped Scriba
  chat and the rules below do not apply.
- **Read tools** (run without approval): `check_availability`,
  `find_free_slots`, `executive_briefing`, `provider_status`,
  `summarize_emails`, `search_sources`, `show_agenda`, `show_meetings`,
  `list_tasks`.
- **Approval tools**: `draft_email_reply`, `send_email`, `create_task`,
  `create_reminder`, `create_calendar_event`, `update_calendar_event`,
  `cancel_calendar_event`.
- Excluded integrations are not offered to the planner, are stripped from a
  plan if a model emits them, are refused by dispatch (`status:
  "unsupported"`), and cannot be approved.

Tool-call outputs a client may render (`tool_call.output`):

| Tool | Output |
| --- | --- |
| `check_availability` | `DeskSlotCheck` (section 4) |
| `find_free_slots` | `DeskAvailability` without `busy` |
| `executive_briefing` | `DeskBriefing` |
| `provider_status` | `DeskConnections` |

A failed Desk read tool has `status: "failed"`, `error: "invalid_request"` or
`"tool_failed"`, and `output.message`.

### The booking gate

Every `create_calendar_event` card is checked against every connected Google
and Outlook calendar when it is created and again on approve and retry.

| Card result | Meaning | Client behaviour |
| --- | --- | --- |
| `status: "awaiting_approval"`, `output.availability.free: true` | Verified free on every calendar | Show Approve |
| `status: "needs_info"`, `output.error_code: "calendar_conflict"` | Collides with `output.availability.conflicts[]` | Show the conflicts; offer another time, or "book anyway" |
| `status: "needs_info"`, `output.error_code: "availability_unknown"`, `output.blocked: true` | A calendar could not be read (`output.availability.calendars[].ok == false`) | Show which calendar; offer reconnect, or "book anyway" |

"Book anyway" is an approve with
`{"payload_overrides": {"desk_availability_override": true}}`. Only an
approve request can set it; the same flag in a model's proposal is ignored.
After it executes, the card carries `output.availability_override`
(`by: "user"`, the time, and the conflicts overridden). An approve can come
back `needs_info` even if the card was `awaiting_approval` a moment ago,
because the calendars are re-read at approval.

The gate covers creating an event and, from 0.3, moving one
(`update_calendar_event`): the new time is checked on every calendar and the
event's own current slot does not count against it.

Limits: search results can still contain items that came from an excluded
integration; no model was called in any test, so what the agent says in prose
is unverified.

## 6. Desk workflow: one incoming email (Integrated; execution in a sandbox or held)

| Method and path | Purpose | Type |
| --- | --- | --- |
| `POST /desk/intake` `{provider, id, mailbox?}` | Take one inbox message through classify, thread, calendar context, plan and proposal. Idempotent per message: a repeat returns the same run with `duplicate: true`. 409 when another worker is taking the same message in at that moment | `DeskRun` |
| `POST /desk/intake/sweep` `{provider?, limit?, max_new?, mailbox?}` | Open a run for every recent message that needs one and has none. Bounded and safe to repeat (see below). The manual "check now" | `DeskSweep` |
| `GET /desk/runs?limit=` | The user's runs, newest first. **Each row says where the run stands** | `{account, runs: DeskRunRow[]}` |
| `GET /desk/runs/{runId}` | A run with its actions, their evidence, its timeline, follow-ups and model usage | `DeskRun` |
| `POST /desk/runs/{runId}/advance` | Propose what may only follow an executed step, and look after the run's follow-ups. Safe to repeat. The backend also does this by itself as soon as a step executes, so a client rarely needs it | `DeskRun` |
| `GET /desk/worker` | The background intake worker's status, the caller's own row, and the caller's runs by stage | `{account, worker: DeskWorkerStatus, runs}` |
| `GET /desk/follow-ups?refresh=&limit=` | Replies awaited on mail the Desk sent, in their latest state. Reads mail; sends nothing | `{account, followUps[], counts}` |
| `POST /desk/runs/{runId}/follow-ups/{id}/close` | The person closes a follow-up | `DeskRun` |

These create a run and action cards inside Scriba. They send no mail and
write no calendar. **Every action is approved through Scriba's existing
`POST /chat/tool-calls/{toolCallId}/approve`** (each action carries its
`approve` path), rejected through `.../cancel`, retried through `.../retry`.
What an approve then does is decided by the execution gate (section 8).

### What is proposed

| Message | Proposal |
| --- | --- |
| Something to do (a written deadline, or a request for a decision, approval or sign-off) | One `create_task` card. `due_at` is set only when a day is written out; it is never invented. Priority follows the deadline. If an open task with the same title exists, no card: `held.reason: "task_exists"` |
| New meeting request, time verified free on every calendar | One `create_calendar_event` card: attendee = the sender from the From header; `calendar_provider` and `provider_account_id` = the calendar of the mailbox the request reached. After it executes, one `send_email` confirmation in the original thread (`purpose: "confirm"`) |
| The same request again, when the sender is already on an event at that exact time | No card. `held.reason: "already_scheduled"`, `flags: ["duplicate"]` |
| Meeting request, time busy | No event. One `send_email` reply (`purpose: "offer_times"`) offering up to three times verified free on every calendar; `proposedSlots` lists them. `held.reason: "calendar_conflict"` |
| Meeting request at a free time outside working hours | Proposed as usual, with `flags: ["outside_working_hours"]` and the fact stated in the card's `reason`: the person decides |
| Meeting request, no time could be read | The same reply with `purpose: "clarify"`, when verified free times exist. `held.reason: "time_not_understood"` |
| Meeting request, a calendar could not be read | No card at all: nothing is verified, so nothing is offered. `held.reason: "availability_unknown"` |
| Request to move a meeting | The ORIGINAL event is found among the meetings the sender is on. New time verified free (the meeting's own slot does not count against it): one `update_calendar_event` card naming that `event_id`. Never a second event. Then a confirmation |
| Request to cancel a meeting | Same search: one `cancel_calendar_event` card for that event. Then a confirmation |
| A change request that cannot be tied to one meeting, or to one the user organizes | No card. `held.reason`: `event_not_found` (the sender is on no meeting), `event_ambiguous` (`held.candidates[]`), `not_organizer`, `calendar_lookup_failed` |
| A change request about a meeting that was cancelled or has already taken place (0.3.1) | No card, and **no other meeting of the sender is touched**. `held.reason: "event_not_found"`, `held.gone[]` (the meetings it was about, with `status`), `flags: ["duplicate"]` |
| A change request that NAMES its meeting ("our pricing workshop") when no meeting of the sender carries that name (0.3.1) | No card. `held.reason: "event_not_found"`, `held.candidates[]` (the sender's other meetings, untouched). Days, times and generic words ("our Thursday call") name nothing |
| A message that speaks of an existing meeting ("push Thursday's call back to Friday", "would 11:00 work for the review instead") from someone who is on a meeting still ahead (0.3.1) | Planned as a **change** to that meeting, whatever verb was used. Never a second event beside it. A `decision` event `read_as_change` is recorded |
| A message that gives an instruction and takes it back ("cancel it. On second thought, keep it"), a weekday that does not match its date ("Wednesday 17 November" when the 17th is a Tuesday), or a subject and a text that name different days for a new meeting (0.3.1) | No card. `held.reason: "conflicting_instructions"`: which one stands is the writer's to say. Stage `ESCALATED` |
| A request to be reminded ("remind yourself on Wednesday at 09:00 to call the chairman") (0.3.1) | Not a meeting with the writer: classified `action_item`, one `create_task` card |
| Needs a reply | No card unless the model step is on (below); `draftRequest`, and `next: ["draft_reply"]` |
| Text that addresses the assistant ("ignore previous instructions", "system note to AI") | Nothing. `held.reason: "untrusted_instructions"`, `flags: ["prompt_injection_suspected"]`. The message is not sent to a model |
| Informational or automated | Nothing |

A reply the Desk sends that awaits an answer (`offer_times`, `clarify`,
`nudge`) opens a **follow-up** on the run once it has executed: `waiting`,
then `satisfied` when a message from that person arrives in that thread,
`overdue` after two days (one `send_email` reminder is then PROPOSED, with
`purpose: "nudge"`, never sent), or `closed` by the person. A mailbox that
cannot be read leaves a follow-up as it is: unknown is not "no answer".

### Reading a time

With a model configured, Scriba's own extraction reads the request. With no
model (`health.model.configured: false`) a time is read by rule, and only when
it is written out in full: one day and one clock time, or one range, in a
zone that resolves to exactly one zone ("ET", "CET", "London time", "your
time"). "IST", "my time", two candidate times, or "at 3" are not read; the
run is held as `time_not_understood`. A model that answers nothing is not
second-guessed by the rules.

From 0.3.1 a time is read **in full or not at all**. A word beside the day
that changes what it means, and that the rules do not compute, leaves the
time unread: "the day after tomorrow", "Thursday week", "a week on Thursday",
"Tuesday after next", "Tuesday next week", "in two weeks", "the following
Tuesday", "end of the month". ("next Thursday" and a written date are read as
before.) A zone written with an offset is that zone: "11:00 GMT+3" is 11:00 at
UTC+3 (`requester_timezone: "Etc/GMT-3"`); a half-hour offset is not read.

### `DeskRun`

`state` (unchanged): `awaiting_approval`, `executing`, `completed`, `partial`,
`failed`, `cancelled`, `no_action_proposed`. **A partly executed action now
makes the run `partial`**, and such an action is not `verified`.

`lifecycle` (new): `{stage, reason, final, outcomeUnknown, compensation}`.

| `stage` | Meaning |
| --- | --- |
| `RECEIVED`, `UNDERSTANDING`, `INVESTIGATING`, `PLANNING` | Recorded as the run is opened; they appear in `timeline`, never as a resting stage |
| `AWAITING_APPROVAL` | At least one card can be approved |
| `HELD` | Every open card is held by a guard (`action.held: true`): nothing can be approved as it stands. `lifecycle.reason` is the first card's `errorCode` (`external_writes_disabled`, `proposal_changed`, `unverified_recipient`, ...) |
| `EXECUTING` | A card is running, or a step executed and the next one is about to be proposed |
| `VERIFYING` | Executed and not yet verified, or `outcomeUnknown`: the provider did not confirm and it may or may not have happened |
| `COMPLETED` | Everything proposed took effect and was verified, or nothing was needed |
| `WAITING_FOR_RESPONSE` | A reply went out and its follow-up is `waiting` or `overdue` |
| `NEEDS_CLARIFICATION` | Cannot be acted on as written (`time_not_understood`, `event_not_found`, `event_ambiguous`, `intent_unclear`, `details_missing`) and nothing could be proposed |
| `ESCALATED` | Handed to the person; the Desk proposes nothing. Also when an action executed and its verification FAILED (`reason: "verification_failed"`): an action is never reported complete because a call returned without an error |
| `PARTIALLY_COMPLETED` | Some actions took effect and some did not. `compensation.policy` is `escalate`: the Desk never undoes an executed action by itself |
| `FAILED`, `CANCELLED` | |

The fourteen values of `lifecycle.stage`, exactly: `RECEIVED`, `UNDERSTANDING`,
`INVESTIGATING`, `PLANNING`, `AWAITING_APPROVAL`, `EXECUTING`, `VERIFYING`,
`COMPLETED`, `WAITING_FOR_RESPONSE`, `NEEDS_CLARIFICATION`, `HELD`,
`ESCALATED`, `PARTIALLY_COMPLETED`, `FAILED`, `CANCELLED`. (The first draft
of 0.3 called three of them `CLASSIFIED`, `CONTEXT_GATHERING` and
`AWAITING_REPLY`; those names were never merged and are not sent.)

### The plan (`DeskRun.plan`)

Written once, when the run is opened, and stored as a `plan` event:

```json
{
  "version": 1,
  "message": {"provider": "gmail", "provider_account_id": "...", "email_id": "...", "thread_id": "..."},
  "planner": "rules" | "rules+model" | "model+rules" | "rules+agent",
  "intents": [{"type": "new_meeting", "confidence": 0.9, "evidence": ["Could we meet Tuesday at 10:00"],
               "missing": [], "source": "model"}],
  "unsupported": [{"type": "task", "why": "evidence_not_in_message"}],
  "facts": ["The requested time is free on every connected calendar (2 read)."],
  "assumptions": ["The length was not stated; your default of 30 minutes is used."],
  "missing": ["time"],
  "tools": ["calendar.check_availability", "calendar.find_free_slots"],
  "steps": [
    {"id": "s1", "tool": "create_calendar_event", "purpose": "book", "dependsOn": [], "deferred": false,
     "requiresApproval": true, "external": true, "expected": "...", "onFailure": "...",
     "state": "awaiting_approval", "toolCallId": 41},
    {"id": "s2", "tool": "send_email", "purpose": "confirm", "dependsOn": ["s1"], "deferred": true,
     "requiresApproval": true, "external": true, "expected": "...", "onFailure": "...",
     "state": "waiting", "toolCallId": null}
  ],
  "approvals": 2,
  "escalation": ["A calendar cannot be read: availability is unknown and nothing is booked.", "..."]
}
```

- `intents[].type`: `new_meeting`, `reschedule`, `cancellation`,
  `reply_needed`, `information_request`, `task`, `reminder`, `follow_up`,
  `fyi`. From the rules there is one intent, `confidence: null` (rules do not
  measure it) and `evidence` holds the rule names. From a model there can be
  up to four, each with a confidence and quotes.
- `facts` are things the Desk verified by reading. `assumptions` are things
  it filled in because the message did not say. `missing` is what is needed
  and absent: it leads to a question or a hand-over, never to an invented
  detail. `unsupported` lists intents a model reported without a quote that
  is in the message; they were dropped.
- `steps[].state`: the card's Scriba status once the step has a card;
  otherwise `ready` (every step it depends on took effect), `waiting`, or
  `blocked` (a step it depends on failed or was rejected). **A blocked step
  is never proposed**, and a `decision` event `step_blocked` is recorded once.
  `next` contains `advance` exactly when a deferred step is `ready`.
- A run opened before 0.3 has `plan: null`.

Other new fields: `trigger` (`manual`, `sweep`, `worker`, `evaluation`),
`simulated` (the run lives in an isolated provider world), `flags`,
`updatedAt`, `actionCounts`, `followUps[]`, `usage`, and `timeline[]`:
`{at, kind, summary, data}` with `kind` one of `stage`, `decision`, `read`,
`plan`, `proposal`, `approval`, `execution`, `verification`, `human`,
`followup`, `usage`, `error`. One event is one kind: an agent decision, a tool read, a
proposed write, a human decision, an execution and a verification are never
merged. `summary` never contains message text.

### The lifecycle of an action (0.3.1)

A run's `lifecycle.stage` says where the whole request stands. Each action
says where IT stands, in `lifecycle`, so that no client derives it from a
status, a flag and an error code:

| `action.lifecycle` | Meaning | Card `status` |
| --- | --- | --- |
| `PROPOSED` | Waits for the person; can be approved as it stands | `awaiting_approval` |
| `HELD` | A guard or a missing detail holds it; cannot be approved as it stands (`errorCode`) | `needs_info` |
| `APPROVED` | Approved and claimed, not started | `approved` |
| `EXECUTING` | Being carried out | `executing` |
| `EXECUTED_UNVERIFIED` | The call returned; no evidence yet that it took effect. **Not done** | `executed` |
| `VERIFIED` | It took effect, on evidence (`verification.method`) | `executed` |
| `VERIFICATION_FAILED` | The call returned and the state read back does not show it | `executed` |
| `PARTIALLY_EXECUTED` | Part of it took effect; nothing is undone | `partially_executed` |
| `OUTCOME_UNKNOWN` | The provider did not confirm; it may or may not have happened | `failed` |
| `INTERRUPTED` | The process stopped; read back, the effect is not there | `failed` |
| `FAILED` | It did not take effect | `failed`, `unsupported` |
| `REJECTED` | The person rejected it; it never ran | `cancelled` |

`final` is true only for `VERIFIED` and `REJECTED`. **An action is never
complete because a provider accepted a request**: `executed` without evidence
is `EXECUTED_UNVERIFIED`.

`retry` is `null` when there is nothing to retry, otherwise `{mode, attempts,
sameEffect: true}`:

| `retry.mode` | When | What a retry does first |
| --- | --- | --- |
| `rerun` | `FAILED`, `INTERRUPTED`: nothing happened | Runs the action |
| `readback_first` | `OUTCOME_UNKNOWN` in a sandbox | Reads the state back; if the effect is there it is not repeated |
| `confirm_first` | `OUTCOME_UNKNOWN` on a real provider | Refused until the person says they checked (`desk_retry_after_unknown_confirmed`) |

A retry is the same effect (`idempotencyKey`), never a second one.

**The action as approved.** `input` is the action as it was PROPOSED and does
not change. When the person edits it in the approve request, `edited` lists
the fields they changed and `effectiveInput` is the action as it ran (`input`
with the edit applied; the Desk's own control flags are not edits). From 0.3.1
everything that speaks about the action after the approval uses
`effectiveInput`: the verification read-back, the search for its effect on a
retry or after an interruption, and the confirmation sent to the other
person. (Before, a meeting moved from 10:00 to 10:30 at approval was booked
at 10:30, reported `start_differs`, and confirmed to the sender as 10:00.)

**Nothing follows an unverified step.** A deferred step is `ready` only when
every step it depends on took effect and was not found unverified. If a
dependency is `VERIFICATION_FAILED` the step is `blocked` (a `decision` event
`step_blocked` is recorded once) and the run is `ESCALATED` with `reason:
"verification_failed"`. If a later read-back verifies the dependency, the
step becomes `ready` again.

**A read-back that settles an action is followed like an execution.** After a
retry of an unknown outcome finds the effect, and after recovery finds it,
the next step of the plan is proposed at once (before 0.3.1 the run rested in
`EXECUTING` with `next: ["advance"]`).

Each action also carries `stepId` (its step in the plan), `held` (a guard
holds it), `attempts` (how many times execution was attempted),
`purpose`, `reason`, `proposedSlots`, `output` (the
whole card output: no second request per action), `errorCode`,
`idempotencyKey`, `proposedAt`, `decisions[]`, `execution`, `verification`,
`outcomeUnknown`, `simulated`. **`verified` is true only on evidence**: a
read-back of the provider state where one exists (`verification.method:
"sandbox_readback"`), otherwise Scriba's record of the executed action
(`"scriba_action_record"`).

`usage` is `{models[], estimatedCostUsd, priceSource}` from Scriba's own
telemetry record of each call and Scriba's own price table. It is `null` when
no model call was recorded, and `estimatedCostUsd` is `null` when any call has
no known price. Null is not zero.

A `DeskRunRow` (`GET /desk/runs`) has `runId, provider, email_id, subject,
from_addr, category, created_at` as before, plus `state`, `lifecycle` (the
stage), `next`, `trigger`, `simulated`, `held: {reason} | null`,
`actionCounts`, `updatedAt`, `followUps: [{id, state}]`.

### Sweep and the worker

`POST /desk/intake/sweep` is unchanged (see `DeskSweep`), except that drafts,
sent mail, spam and trash are skipped when a row carries its labels or folder.

The **background intake worker** does the same thing with no client open. It
is opt-in (`DESK_INTAKE_WORKER=on`, `DESK_INTAKE_USERS=a@x,b@y`), refuses to
start in a production process, and acts as one enrolled user at a time with
that user's identity passed explicitly. It does not poll a provider: mail
reaches Scriba through Scriba's own ingestion, and the worker reads the inbox
through the runtime behind `GET /emails`. Per tick, per user: take in up to
`maxNewPerTick` messages, propose what follows an executed step, look after
follow-ups. It only proposes.

| `worker.you.lastStatus` | Meaning |
| --- | --- |
| `ok` | |
| `mailbox_unreadable` | A connected mailbox could not be read. What was readable was handled; the worker slows down for this user |
| `backing_off` | Skipped this tick after a failure |
| `rate_limited`, `backpressure` | The hourly limit was reached, or `maxPending` runs already await the person |
| `failed` | The pass for this user raised; `consecutiveFailures` counts |

**One run per message** is a claim, not a process lock. The key is user,
provider, receiving account and provider message id. `worker.claims.store`:
`scriba_receipts` (Scriba's own `automation_action_receipts` ledger, UNIQUE on
user and key; `durable: true`), `sqlite` (a local file; durable) or `memory`
(this process; the seeded backend, whose runs are in memory too).

### Model understanding (off by default)

`DESK_UNDERSTANDING=model`, with a model really configured, replaces Scriba's
single-request extraction with one structured call that reads up to four
intents from a message (`backend/desk_overlay/understanding.py`). What a
model contributes is WHAT is asked. It never decides that a time is free, who
is on a meeting, or that something may be sent: each intent is planned by the
same checked code as a single request. An intent is kept only if it quotes
the message; a time must carry an offset; below 0.6 confidence nothing is
proposed (`held.reason: "intent_unclear"`, with `held.missing[]`). A message
classed as automated is not upgraded, a change request is never turned into
a new booking, and a message that addresses the assistant is not sent to a
model. The call also reports `instructs_assistant`: exact quotes of text
written to an assistant, or asking to skip approval or to send the
executive's data somewhere. One such quote that is in the message stops the
run exactly as the rules' own check does (`flags:
["prompt_injection_suspected"]`, `held.reason: "untrusted_instructions"`,
the decision carries `source: "model"` and `evidence[]`); a claim that is
not a quote changes nothing. A time in a zone that means more than one place
("IST", "CST", "my time") is never used, whoever read it: the decision
`timezone_ambiguous` is recorded, `plan.missing` gains `time zone` and the
sender is asked. When a model call fails, a plainly written time is read by
the rules (`model.extract_request` records `model_call_failed`).
Its tests script the model. One real model has been run through it in
the sandbox: `docs/handoff/EVAL_CONFIGURED_MODEL.md`.

### The model step (off by default)

`DESK_AGENT=on`, with a configured model, adds one bounded planning step
after the rules (`backend/desk_overlay/agent.py`): at most 4 model calls, 4
tool calls and 45 seconds. It may read through four read tools and may
propose a reply to the sender in the message's thread, a task or a reminder.
It cannot choose a recipient, propose a calendar change or approve anything.
A reply it writes is refused when the plan contains a calendar change
(`confirmation_follows_calendar_change`): the sender is told once, by the
plan's confirmation step, after the change took effect.
Its tests script the model. One real model has been run through it in the
sandbox: `docs/handoff/EVAL_CONFIGURED_MODEL.md`.

### Readiness

| Capability | Status |
| --- | --- |
| Classification, proposals, lifecycle, evidence, claims, follow-ups, worker | Tested without Scriba and on the real Scriba app |
| Approve, cancel and retry through Scriba's routes; execution; verification; unknown outcomes; partial success | Tested on the real Scriba app against an isolated provider world |
| Reschedule and cancel through Scriba's own calendar-edit validation | Tested on the real Scriba app; the event read and the write are the world's |
| The background worker opening runs with no client | Tested, and seen over HTTP on the seeded demo backend |
| Durable claims on Scriba's receipt ledger | The adapter is tested against a stand-in with the ledger's outcomes. **Not run against a Postgres database** |
| Extracting a time with a model; a model-written reply | Scripted in tests. **Never run against a real model** |
| Anything on a live mailbox or calendar | Not tested |

### Changes to an existing task (0.3.1)

When a message reports work as finished and exactly one of the person's open
tasks is about it, the run carries `taskUpdates: [{op: "complete", taskId,
title, matched, source, state, verified, by, error, updatedAt}]` and, while
one is `suggested`, `next` contains `complete_task`. More than one matching
task: nothing is suggested (`decision` `task_match_ambiguous`).

| Route | Effect |
| --- | --- |
| `POST /desk/runs/{id}/task-updates/{taskId}/apply` | Marks that task done in the person's own records, then reads the open tasks back. Safe to repeat. Returns the run |
| `POST /desk/runs/{id}/task-updates/{taskId}/dismiss` | Declines the suggestion. Returns the run |

`state`: `suggested`, `completed` (marked done **and** read back as no longer
open), `unverified` (the change was sent and the tasks could not be read
back: not known to be done; the run rests in `VERIFYING` with `reason:
"task_not_verified"`), `failed` (it is still open), `dismissed`. A Desk set
to keep own records without asking applies a suggestion at once. Each change
is a `task` event in `timeline`.

### One representation, checked

`frontend/src/api/desk.ts` declares every type in this section. From 0.3.1 a
backend test (`backend/tests/integration/test_typed_client_with_scriba.py`)
produces real responses and fails when the backend sends a field, an action
state, a run stage, an evidence kind, a held reason or a card code the typed
client does not declare. Three names in the client are older than what is
sent and are kept only so that existing code compiles: `DeskLifecycleStage`
(use `DeskRunStage`), `DeskHeldReason` (use `DeskAnyHeldReason`) and
`DeskAnyHoldCode` (use `DeskCardCode`). `DeskRunHeld.reason` is declared with
the five 0.2 reasons although any `DeskAnyHeldReason` is sent: read it with
`heldReasonOf`.

`flags: ["prompt_injection_suspected"]` is a **hint, not a control**. The
defences do not depend on it: only the sender, taken from the From header,
can become a recipient or attendee; every write needs an approval; an approval
is bound to the proposed action.

## 7. Desk safeguards on proposed actions (Integrated; no live provider)

With the Desk chat scope enforced, every write card passes the Desk's own
checks after Scriba's validation, both when it is proposed and again on
approve and retry. They are implemented in the Desk
(`backend/desk_overlay/safeguards.py`), so they hold whatever version of
Scriba the Desk runs on. A held card has `status: "needs_info"`,
`output.blocked: true` and one of these `output.error_code` values:

| `error_code` | Meaning | What the client offers |
| --- | --- | --- |
| `unverified_recipient` | A recipient or attendee (`output.unverified_recipients[]`) was not given by the user, is not the sender of the message being answered, and is not one of the user's own accounts | Show the address. To accept it, approve with `{"payload_overrides": {"desk_confirmed_recipients": ["<address>"]}}`. To change it, send the corrected field and the same confirmation |
| `reply_target_changed` | A Gmail reply targets a message that is no longer the latest in its thread (a newer message arrived, or the user already wrote there) | Open the thread; do not approve as is |
| `reply_target_unverified` | The message being answered, or the user's sent mail, could not be read | Retry later |
| `reply_target_missing` | A Gmail reply does not name the message it answers | Complete it in chat |
| `recipient_required`, `body_required`, `title_required`, `reminder_incomplete`, `start_required` | The action is incomplete | Let the user fill the field |
| `calendar_conflict`, `availability_unknown` | The booking gate (section 5). It now covers **moving** an event too: the new time is checked on every calendar, and the event's own current slot does not count against it | As in section 5 |
| `desk_check_failed` | A Desk check itself failed. The card is held, never passed | Retry later |
| `external_writes_disabled` | The execution gate (section 8): mail and calendar writes are off on this backend. Nothing was claimed or executed | Nothing to offer. The card can be approved once writes are enabled |
| `proposal_changed` | The stored action is no longer what was proposed and no edit by the person is recorded (section 8, "An approval is bound") | Nothing to offer. Open the run; do not approve as is |
| `approval_held` (evaluation routes only, HTTP 409) | A guard held the card when the harness approved it; the message names the hold code | Nothing ran |
| `outcome_unknown` | A provider did not confirm the action. It may or may not have happened (`output.outcome_unknown: true`, card `status: "failed"`) | See "Unknown outcomes" in section 8 |
| `sandbox_world_gone` | The card was prepared in a sandbox that no longer exists | Nothing to offer |

Rules:

- **`payload_overrides` on approve.** The Desk reads exactly four keys, and
  only on an approve request (in a model's proposal they are ignored):
  `desk_confirmed_recipients` (addresses the user confirmed or typed),
  `desk_availability_override` (`true`: book despite the booking gate),
  `desk_verified_recipients` (set by the Desk itself), and
  `desk_retry_after_unknown_confirmed` (`true`: the user checked and wants an
  unknown-outcome action run again, on a real provider). Every other key is
  merged into the card's input by Scriba and re-validated by Scriba's gate and
  then by the Desk's checks, so an edited recipient, time or text is checked
  exactly like a proposed one. For `update_calendar_event` and
  `cancel_calendar_event` the change is recomputed from the live event at
  approval; a client cannot supply `planned_change`.
- When a user edits a recipient on a card, send `desk_confirmed_recipients`
  with the addresses the user typed, in the same approve request.
- An approve that carries an `idempotency_key` and is repeated with the same
  key after its attempt failed returns the recorded card with
  `idempotent_replay: true` and runs nothing. Use one key per user click.
- A second identical calendar event is held as `calendar_conflict`, because
  the first one now occupies the slot.

Not covered by a Desk guard (they live in Scriba itself): what happens to a
session cookie after sign-out, the thread context Scriba gives its draft
writer, and the provider call inside one already-approved attempt. The Desk
does not assume any Scriba change for these.

## 8. The execution gate and external-write readiness (Enforced in the server)

`GET /desk/health` reports three separate things:

```json
"writes": false,
"externalWrites": {
  "enabled": false, "capable": true, "authorized": false, "revision": null,
  "reason": "scriba_fixes_verified",
  "message": "No Scriba revision has been verified to contain the outbound fixes (this backend reports 3ae3a2aa).",
  "checks": [
    {"id": "desk_guards_installed", "ok": true, "detail": "..."},
    {"id": "scriba_fixes_verified", "ok": false, "detail": "..."},
    {"id": "isolated_provider_tests", "ok": false, "detail": "..."},
    {"id": "lead_authorization", "ok": false, "detail": "..."}
  ]
},
"sandboxExecution": {"available": true, "worlds": 2, "note": "..."},
"executionMode": "sandbox",
"sandbox": {"id": "demo-alice", "label": "demo"},
"worker": {"enabled": true, "running": true, "reason": null, "intervalSeconds": 15, "lastTickAt": "..."},
"model": {"configured": false}
```

- `externalWrites.enabled` is true only when **every** check passes. It is
  **false on every backend today, by construction**: the list of verified
  Scriba revisions in `backend/desk_overlay/readiness.py` is empty, and adding
  one is a reviewed code change made after the outbound fixes are confirmed
  active in that revision and isolated provider tests have passed. No
  environment variable alone can enable writes, and passing unit tests never
  does. `writes` equals `externalWrites.enabled`.
- `executionMode` is what approving a mail or calendar action does **for this
  user**: `sandbox` (it runs against the user's isolated provider world),
  `held` (the gate refuses it) or `external` (a real provider; unreachable
  today).
- A client must not treat `sandboxExecution.available` as permission to show
  real sends: a sandbox result has `simulated: true` everywhere and is never a
  provider success.

**Enforcement is in the server, not in disabled buttons.** For every card of
a Desk run (and every card at all when `chatScope` is `enforced`), an approve
or retry of `send_email`, `draft_email_reply`, `create_calendar_event`,
`update_calendar_event` or `cancel_calendar_event`:

- with a sandbox world in force: is applied to the world. Scriba's execution
  engine is not called. Reaching a real provider client during that call
  raises and is counted (`GET /desk/sandbox` `isolationViolations`, which must
  be empty);
- otherwise, with writes disabled: comes back `needs_info` with
  `output.error_code: "external_writes_disabled"`. Nothing is claimed,
  nothing is executed, and the card stays approvable for later.

`create_task` and `create_reminder` write only the user's own Scriba records.
They are not held; they still need an approval, except in a world that sets
the internal-write policy to automatic (evaluation worlds do: section 10).

### An approval is bound to the proposed action

When the Desk proposes a card it records a digest of what the action will do:
recipients and attendees, subject, text, title, start, end, event, thread,
reminder and due times. An approve or retry first compares the stored card
with that digest. If they differ and no edit by the person is on record, the
card is held with `proposal_changed` and nothing runs. An edit the person
makes in an approve request (`payload_overrides` touching those fields) is
recorded as a `human` event (`action: "edit"`, `fields[]`) and becomes the
new binding. A retry after such an attempt failed runs the action **as the
person approved it**, edit included (Scriba's own retry would run the first
proposal). Cards proposed in chat, outside a Desk run, are not bound.

### Recovery after an interruption

A card left `approved` or `executing` for five minutes by a process that
stopped is settled by the worker, and never by running it again: in a sandbox
the world is read back (the effect is there: `executed`, `output.reconciled`
and `output.recovered`; it is not: `failed` with `error_code: "interrupted"`,
retryable); on a real provider it becomes `failed` with `outcome_unknown`.
`worker.recovered` counts them. The action is then `VERIFIED` (the effect was
found; from 0.3.1 its next step is proposed), `INTERRUPTED` (`retry.mode:
"rerun"`) or `OUTCOME_UNKNOWN` (`retry.mode: "confirm_first"`).

### Unknown outcomes

A provider call that times out may have taken effect. The card is then
`status: "failed"` with `output.outcome_unknown: true` and `error_code:
"outcome_unknown"`; the action's `outcomeUnknown` is true and the run rests in
`VERIFYING`. It is never reported as a plain failure, and never retried
blindly:

- in a sandbox, a retry first reads the world back. If the effect is there
  the card becomes `executed` with `output.reconciled: true` and no second
  write happens; if it is not, the action runs;
- on a real provider there is no read-back: the retry is held until the user
  confirms they checked (`desk_retry_after_unknown_confirmed`). Scriba's retry
  route takes no body, so the retry is held (`needs_info`, `error_code:
  "outcome_unknown"`) and the confirmation is sent with an **approve** of that
  card. From 0.3.1 an approve without it is held again: the rule applies
  while the outcome is unknown, whatever the card's status.

A failure between two steps (the event exists, the confirmation failed) is
`PARTIALLY_COMPLETED`. The event stays. Retry the failed card.

## 9. The sandbox world and the demo backend (Tested; seen over HTTP)

A sandbox world is a complete stand-in for one person's Gmail, Outlook Mail,
Google Calendar and Outlook Calendar, with tasks and reminders. It is not a
flag on a real provider call: while a world is in force the Desk's gateway
answers every provider read from it, and approved actions are applied to it.

`python backend/dev/seeded_desk_server.py --demo` gives the seeded users
Alice and Bob a world each, with mail for every case in section 6 and the
intake worker on.

| Method and path | Purpose |
| --- | --- |
| `GET /desk/sandbox` | The caller's world: accounts, counts, every operation executed in it (`{seq, at, op, status, object_id, error, simulated: true}`), and `isolationViolations` (must be empty). 404 when the backend has no world for the caller |
| `POST /desk/sandbox/deliver` `{provider?, from_addr, subject, body, thread_id?}` | Put a synthetic message in the caller's own sandbox mailbox. It is not taken in by this call: the worker, or a sweep, finds it like any mail |

`op` is one of `email.send`, `email.draft`, `calendar.create_event`,
`calendar.update_event`, `calendar.cancel_event`, `task.create`,
`reminder.create`, `followup.close`.

## 10. Sandbox evaluation routes: `/desk/eval/v1` (Tested with the harness's own runner)

Present only in a process started with `DESK_EVAL_SANDBOX=on` (the seeded dev
backend sets it). They implement the five calls of contract 1.1.0
(`docs/frontend/API_CONTRACT.md`) that the evaluation runner makes:
`GET /meta`, `POST /evaluation/runs`, `GET /runs/{id}`, `GET /approvals`,
`POST /approvals/{id}/decision`, with the `X-Executive-Desk-Contract` header.

What runs: the real Desk workflow, Scriba's card validation and approve path,
the Desk's safeguards and execution gate. What is replaced: the providers.
Each case gets its own world built from the case's own `context` (calendar,
tasks, awaited replies, clock, faults) and `input`. No case id is inspected
and no expected answer exists in the backend.

Things a harness should know:

- `meta.agent` is `"real"` only when a model is configured. Without one the
  Desk still runs, on rules alone, and reports `"scripted"`: its results are
  not the product's and the harness labels them simulated.
- `meta.sandbox` is always true. `meta.desk.isolation` reports the tripwire
  and its violation count; each run carries `sandbox.isolationViolations`.
- `input.kind: "conversation"` is **not supported**: the run ends `failed`
  with `error.code: "conversation_input_unsupported"`. It is never faked.
  `capabilities.chat` is false.
- Internal writes (`task.create`, `reminder.create`) run without an approval
  in an evaluation world, as contract 1.1.0 requires; they are still simulated.
  In the product they need an approval. `meta.desk.internalWrites` says which.
- A card the Desk holds (`needs_info`) is not offered as an approval: it
  cannot be approved as it stands. Its action is `skipped` and the run ends
  `completed` with outcome `escalated`.
- All timestamps of a run are on the case's clock (`context.now`), which is
  fixed; order within a run is `sequence`.
- `usage` is null unless a model call was recorded.
- `triage.classification` is the model's first intent when a model read the
  message, otherwise the rules' category.
- Beyond the contract, for the backend's own scenarios: `context.unreadableCalendars`
  (`{"google": "<error code>"}`) makes that calendar unreadable in the case's world.

## 11. Environment

Read by the Desk only. None of these is a credential.

| Variable | Meaning | Default |
| --- | --- | --- |
| `DESK_CHAT_SCOPE` | `on`: narrow Scriba's chat to the Desk's tools for the whole process | off (the seeded dev backend: on) |
| `DESK_CLAIMS` | `scriba`, `sqlite:<path>` or `memory` | `scriba` (the seeded dev backend: `memory`) |
| `DESK_INTAKE_WORKER`, `DESK_INTAKE_USERS` | `on`, and the Scriba users the worker serves | off |
| `DESK_INTAKE_INTERVAL`, `DESK_INTAKE_MAX_NEW`, `DESK_INTAKE_MAX_PER_HOUR`, `DESK_INTAKE_MAX_PENDING` | Seconds between ticks (min 15), runs per user per tick, per hour, and the number awaiting the person at which intake pauses | 60, 3, 30, 20 |
| `DESK_MODEL` | `off`: the Desk makes no model call, whatever Scriba is configured with. A placeholder key (`test-key`) is never treated as a model | `auto` (the seeded dev backend: `off`) |
| `DESK_UNDERSTANDING` | `model`: one structured call reads a message's intents | off |
| `DESK_AGENT` | `on`: the bounded model step | off |
| `DESK_EVAL_SANDBOX` | `on`: mount `/desk/eval/v1` | off (the seeded dev backend: on) |
| `DESK_EXTERNAL_WRITES`, `DESK_EXTERNAL_WRITES_AUTHORIZED_BY`, `DESK_ISOLATED_PROVIDER_TEST_REPORT` | The lead's switch and the record of isolated provider tests. Necessary, not sufficient (section 8) | unset |
