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

## 4. Proposed endpoints (not implemented)

Names and shapes are a starting point for review, not a commitment.

| Method and path | Purpose | Response sketch |
| --- | --- | --- |
| `GET /desk/health` | Overlay loaded, Scriba commit, enabled capabilities | `{ok, scribaCommit, capabilities: []}` |
| `GET /desk/availability?start=&end=&duration_minutes=&attendees=` | Busy intervals and free slots across every connected Google and Microsoft calendar, inside the user's working hours | `{timezone, calendars: [{provider, account, ok, error?}], busy: [{start, end, provider, account}], slots: [{start, end}]}` |
| `POST /desk/slots/check` `{start, end}` | Is one slot free everywhere, and what does it collide with | `{free, conflicts: [{provider, account, title?, start, end}]}` |

A calendar that cannot be read must appear with `ok: false` rather than be
treated as free.
