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
([backend/README.md](../backend/README.md)). All need a session, all are
read-only, and all sit behind Scriba's own session and cross-site guards.
Types and client functions: `frontend/src/api/desk.ts`.

"Tested" here means: unit and route tests, integration tests on the real
Scriba application with providers replaced at the SDK boundary, and the
smoke test on Scriba's seeded backend. **No live Google or Microsoft
calendar has been read through these routes yet.**

| Method and path | Purpose | Type |
| --- | --- | --- |
| `GET /desk/health` | Overlay present, version, `writes: false` | `DeskHealth` |
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
`none`. It is rule-based (Scriba's reply classifier plus deadline and
meeting-intent patterns) and works on the subject and snippet, not the full
body. It makes no model call.

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

Limits: the gate covers creating an event, not yet moving one; search results
can still contain items that came from an excluded integration; no model was
called in any test, so what the agent says in prose is unverified.

## 6. Desk workflow: one incoming email (Integrated; execution simulated or in-memory)

| Method and path | Purpose | Type |
| --- | --- | --- |
| `POST /desk/intake` `{provider, id, mailbox?}` | Take one inbox message through classify, thread, calendar context and proposal. Idempotent per message: a repeat returns the same run with `duplicate: true` | `DeskRun` |
| `GET /desk/runs` | The user's runs, newest first | `{account, runs[]}` |
| `GET /desk/runs/{runId}` | A run with its proposed actions and their current status | `DeskRun` |
| `POST /desk/runs/{runId}/advance` | Propose what may only follow an executed step (the confirmation reply after the event exists). Safe to repeat | `DeskRun` |

These create a run and action cards inside Scriba. They send no mail and
write no calendar. **Every action is approved through Scriba's existing
`POST /chat/tool-calls/{toolCallId}/approve`** (each action carries its
`approve` path) and rejected through `.../cancel`.

What is proposed:

| Message | Proposal |
| --- | --- |
| Actionable (deadline, no question) | One `create_task` card |
| New meeting request, requested time verified free on every calendar | One `create_calendar_event` card, attendee = the sender from the From header. After it is executed, `next` contains `"advance"`, which proposes one `send_email` reply in the original thread, from the receiving mailbox |
| Meeting request, time busy or unverifiable or not understood | No card. `held.reason` is `calendar_conflict`, `availability_unknown`, `time_not_understood`, `change_request` or `invalid_preferences`; `held.slots` are verified free times; `draftRequest` is the reply request |
| Needs a reply | No card; `draftRequest`, and `next: ["draft_reply"]` |
| Informational or automated | Nothing |

`DeskRun.state`: `awaiting_approval`, `executing`, `completed`, `partial`
(some actions executed, some failed), `failed`, `cancelled`,
`no_action_proposed`. An action's `verified` is true only when the card
executed and Scriba recorded the action (`assistantActionId`); it is never
inferred.

Readiness:

| Capability | Status |
| --- | --- |
| Classification, proposals, duplicates, isolation, run states | Tested without Scriba and on the real Scriba app |
| Task case: propose, approve through Scriba's route, executed by Scriba's engine, verified | Integrated, with in-memory storage |
| Meeting case: propose, gate at approval, event before reply | Integrated; the calendar write itself is a recording stand-in |
| Extracting the requested time from the email | Uses Scriba's model call; scripted in tests, **never run against a real model** |
| Sending the confirmation reply | Card creation tested; the send is not executed in any test |
| Anything on a live mailbox, calendar or model | Not tested |

Limits: a run starts when a client calls `/desk/intake`; nothing yet starts
runs automatically when mail arrives. Reschedule and cancel requests are
held, not proposed. One Desk process is assumed (the duplicate guard is a
process lock plus a lookup). The confirmation reply text is a fixed template
the user can edit on the card.

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
| `recipient_required`, `body_required`, `title_required`, `reminder_incomplete`, `start_required` | The action is incomplete | Let the user fill the field |
| `calendar_conflict`, `availability_unknown` | The booking gate (section 5) | As in section 5 |
| `desk_check_failed` | A Desk check itself failed. The card is held, never passed | Retry later |

Rules:

- `desk_verified_recipients`, `desk_confirmed_recipients` and
  `desk_availability_override` are honoured only on an approve request. In a
  model's proposal they are ignored.
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
