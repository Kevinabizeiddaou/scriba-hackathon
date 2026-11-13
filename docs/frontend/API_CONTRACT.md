# Scriba Executive Desk: API contract

**Version 1.1.0. First frozen at 1.0.0 on 13 November 2026.**

This is the interface between the Executive Desk frontend and evaluation harness (Role 2) and the Scriba backend (Role 1). The frontend, the HTTP adapter, the reference server and the test suite are built against exactly this document.

"Frozen" means the frontend side no longer changes it informally. It has not yet been confirmed against the real backend: the points Role 1 must confirm are in [handoff/ASSUMPTIONS.md](handoff/ASSUMPTIONS.md). A change after this point goes through the change log at the end of this file, with a version bump.

| Where | What |
| --- | --- |
| [`src/api/types.ts`](../src/api/types.ts) | The same contract as TypeScript types. The source of truth if this text and the code ever disagree. |
| [`src/api/validate.ts`](../src/api/validate.ts) | The runtime checks the client applies to every response |
| [API_EXAMPLES.md](API_EXAMPLES.md) | Real JSON for every type, generated from the mock |
| [`src/api/reference/referenceServer.ts`](../src/api/reference/referenceServer.ts) | A working server for this contract (scripted, not an agent). Run it with `npm run contract:server`. |
| [handoff/BACKEND_REQUIREMENTS.md](handoff/BACKEND_REQUIREMENTS.md) | The same requirements as a checklist for the backend |

The words MUST, MUST NOT and SHOULD are used in their usual specification sense.

## 1. Versioning

- The contract has a semantic version, `CONTRACT_VERSION` in `types.ts`.
  - **Major**: a breaking change (a field removed or renamed, a status added to an enum the client switches on, a changed meaning).
  - **Minor**: something added that old clients can ignore (a new optional endpoint, a new field).
  - **Patch**: wording only.
- The major version is in the URL: the base path ends in `/v1`.
- The client sends `X-Executive-Desk-Contract: 1.1.0` on every request. The server MUST send the header on every response, with the version it implements.
- `GET /meta` returns `contractVersion`. The client refuses to continue when the major number differs from its own (`unsupported_contract_version`) and accepts any minor or patch.
- A server that receives a request for a different major version SHOULD answer 400 `unsupported_contract_version`.
- A server MAY add fields the contract does not list. The client ignores them. A server MUST NOT omit a listed field.

## 2. Conventions

- Base URL: `{origin}/api/executive-desk/v1`. JSON request and response bodies, UTF-8.
- Timestamps are RFC 3339 with an explicit offset: `2026-11-17T11:00:00+02:00` or `2026-11-17T09:00:00Z`. A timestamp without an offset is invalid. The client rejects it and the evaluation fails it; neither guesses a zone.
- Within one run, all action timestamps come from the same clock. The evaluation does not compare an action timestamp with an approval timestamp, so those may come from different clocks.
- Ids are opaque strings, unique within their type.
- A nullable field is always present with the value `null`. It is never left out.
- Text fields (`subject`, `bodyText`, `summary`, `text`) are plain text. The frontend never renders HTML from the backend.

## 3. Handshake: `GET /meta`

The first request a client makes. It tells the client what is behind the URL.

```json
{
  "contractVersion": "1.1.0",
  "service": "scriba-backend",
  "agent": "real",
  "sandbox": true,
  "principal": { "name": "...", "email": "...", "timezone": "Asia/Beirut" },
  "simulatedNow": null,
  "capabilities": { "evaluation": true, "faultInjection": true, "chat": true, "tokenUsage": true }
}
```

| Field | Meaning | Effect on the client |
| --- | --- | --- |
| `contractVersion` | Version the server implements | Major mismatch stops the client |
| `service` | Display name | Shown in the sidebar and stored in reports |
| `agent` | `real` when a model-driven agent produces the runs; `scripted` for a stand-in | Everything from a `scripted` service is labelled simulated and never shown as an evaluation result |
| `sandbox` | True when the service cannot reach real mailboxes or calendars | The evaluation runner refuses to run against `sandbox: false` |
| `principal` | Whose desk this is, with an IANA time zone | All times are displayed in this zone |
| `simulatedNow` | The service's fixed clock, or null when it runs on real time | Shown as "Simulated clock" |
| `capabilities.evaluation` | `POST /evaluation/runs` exists | Without it the runner reports `evaluation_unsupported` |
| `capabilities.faultInjection` | Evaluation runs honour `context.faults` | Without it EVAL-017 and EVAL-018 are skipped, with the reason recorded |
| `capabilities.chat` | The conversation endpoints exist | |
| `capabilities.tokenUsage` | Runs report `usage` | Without it there is no cost per run |
| `capabilities.idempotentPosts` | Optional. True when the server honours `Idempotency-Key` as section 7.1 describes | Only then does the client repeat a `POST` after a lost response. Absent or false: a `POST` is sent once |

## 4. Authentication

Scriba signs people in with an HttpOnly session cookie that belongs to the API host. The Executive Desk uses that session and adds nothing to it: no bearer token, no token storage, no sign-in system of its own. This follows Role 1's `docs/BACKEND_CONTRACT.md` (section 1) on the `main` branch.

- The browser sends the cookie on every request, including `GET /meta`. The adapter makes every request with `credentials: 'include'` and sets no `Authorization` header.
- Signing in is a navigation to Scriba's own sign-in page, not a request made by this frontend. This frontend has no sign-in screen yet; see [FEATURE_STATUS.md](FEATURE_STATUS.md).
- No session, or an expired one: 401 with code `unauthenticated`. The client does not retry and does not start a sign-in by itself. It tells the person that the Scriba session has ended and to sign in again.
- A valid session without permission: 403 with code `forbidden`.
- The backend SHOULD derive the acting person from the session. When it does, it records that identity on approval decisions and ignores `decidedBy` in the request body (see section 8).
- Cross-origin use needs CORS with credentials: name the frontend origin exactly (a wildcard is not allowed with credentials), send `Access-Control-Allow-Credentials: true`, allow the headers `Content-Type`, `Idempotency-Key` and `X-Executive-Desk-Contract`, and expose `X-Executive-Desk-Contract` and `Retry-After`. Scriba accepts the origin `http://localhost:5173` only, so against Scriba the frontend is served from that port.
- The evaluation CLI is not a browser. It reads a session cookie from an environment variable named with `--cookie-env NAME` and sends it as the `Cookie` header. The value is never passed as an argument, printed, or written to a report. `POST /evaluation/runs` MUST be unavailable outside sandbox mode, whatever the session.

## 5. Endpoints

| # | Method and path | Request | Success | Response body |
| --- | --- | --- | --- | --- |
| 1 | `GET /meta` | | 200 | `DeskMeta` |
| 2 | `GET /requests?status=a,b` | | 200 | `SecretaryRequest[]`, newest first |
| 3 | `GET /requests/{id}` | | 200 | `SecretaryRequest` |
| 4 | `POST /requests/{id}/process` | `{}` | 200 or 202 | `AgentRun` (the run that was started) |
| 5 | `GET /runs/{id}` | | 200 | `AgentRun` |
| 6 | `GET /runs?requestId=&conversationId=` | | 200 | `AgentRun[]`, newest first |
| 7 | `GET /approvals?status=a,b&runId=` | | 200 | `ApprovalRequest[]`, newest first |
| 8 | `POST /approvals/{id}/decision` | `ApprovalDecisionInput` | 200 | `ApprovalRequest` |
| 9 | `GET /conversations` | | 200 | `Conversation[]`, most recently updated first |
| 10 | `POST /conversations` | `{}` | 200 or 201 | `Conversation` |
| 11 | `GET /conversations/{id}/messages` | | 200 | `ConversationMessage[]`, oldest first |
| 12 | `POST /conversations/{id}/messages` | `{ "text": string }` | 200 or 202 | `{ "message": ConversationMessage, "run": AgentRun }` |
| 13 | `POST /evaluation/runs` | `EvaluationRunInput` | 200 or 202 | `AgentRun` |

Rules that apply to all of them:

- Query filters are exact. `GET /approvals?runId=X` MUST return only approvals whose `runId` is `X`. The evaluation runner checks this, never acts on an approval from another run, and fails the case (`approvals_scoped`) if one is returned.
- Runs are asynchronous. A `POST` that starts a run (4, 12, 13) returns promptly with the run in `queued` or `running`. It MUST NOT block until the run needs approval or finishes. The client polls `GET /runs/{id}`: the UI every 2 seconds, the evaluation runner every 500 ms.
- The evaluation runner needs only 1, 5, 7, 8 and 13.

## 6. Errors

A non-2xx response carries this body. `code` is a stable machine string; `message` is shown to a person.

```json
{ "error": { "code": "already_decided", "message": "This approval was already rejected.", "details": {} } }
```

`details` is optional and free-form.

| Status | Code | When | Client retries? |
| --- | --- | --- | --- |
| 400 | `invalid_request` | Malformed JSON, missing or invalid field | No |
| 400 | `unsupported_contract_version` | The request names another major version | No |
| 401 | `unauthenticated` | No Scriba session, or it has expired | No. The person is told to sign in to Scriba again |
| 403 | `forbidden` | Signed in, not allowed | No |
| 404 | `not_found` | Unknown id or path | No |
| 409 | `already_decided` | A decision that contradicts the one already made | No |
| 409 | `already_processing` | `process` on a request that is `processing` or `awaiting_approval` | No |
| 422 | `idempotency_key_reused` | An `Idempotency-Key` seen before with a different request | No |
| 429 | `rate_limited` | Too many requests. SHOULD carry `Retry-After` (seconds). | Yes |
| 500 | `internal_error` | Unexpected failure | No |
| 502, 503, 504 | `upstream_unavailable` | The backend or something it depends on is temporarily down | Yes |

Codes the client produces itself, with no HTTP status:

| Code | Meaning |
| --- | --- |
| `network_error` | No response was received |
| `timeout` | No response within the request timeout |
| `invalid_response` | The response was not JSON |
| `contract_violation` | The response is JSON but does not match this contract. The message lists each offending field by path. |
| `unknown_tool` | A run or approval names a tool that is neither canonical nor mapped in `toolAliases` |
| `unsupported_contract_version` | `GET /meta` reported another major version |

A tool or model failure inside a run is not an HTTP error. `GET /runs/{id}` still returns 200, and the failure is in `AgentAction.error` or `AgentRun.error`.

## 7. Idempotency, timeouts and retries

### 7.1 Requests

- The client sends `Idempotency-Key: <uuid>` on every `POST`. One key belongs to one logical operation: every retry of that operation carries the same key.
- The server MUST remember each key with its response for at least 24 hours. When a key arrives again with the same method, path and body, the server MUST return the stored response and MUST NOT perform the operation again. It SHOULD add the header `Idempotent-Replay: true`.
- The same key with a different method, path or body: 422 `idempotency_key_reused`.
- This is what makes a retried `POST` safe. If an approval decision is processed but the response is lost, the client sends it again and the approval is still decided exactly once. The integration tests exercise this with a server that handles the request and then drops the connection.

### 7.2 Client behaviour the server can rely on

| Setting | Default | Notes |
| --- | --- | --- |
| Request timeout | 15 s | Per request, enforced with an abort |
| Tries per request | 3 | The first try and two retries |
| Pause between tries | 250 ms, then 500 ms, capped at 4 s | `Retry-After` replaces the pause when present, up to the cap |
| Retried | no response, timeout, 429, 502, 503, 504 | Always for `GET`. For `POST` only when `GET /meta` reports `capabilities.idempotentPosts: true`; the retry keeps its key. Otherwise a `POST` is sent exactly once and a failure is shown to the person, who re-reads the state before trying again. This matches Scriba's rule that a write is never retried automatically. |
| Never retried | every other 4xx, and 500 | |

### 7.3 Approval decisions

- Repeating the decision an approval already has (approve an approved one) returns 200 with the approval as it is. Nothing happens twice.
- A decision that contradicts the one already made returns 409 `already_decided`.

### 7.4 Side effects

Every side-effect action carries `idempotencyKey`: an identifier for the one real-world effect it is meant to have.

- It MUST be set on every `email.send`, `calendar.create_event`, `calendar.update_event` and `calendar.cancel_event` action, and is null on reads.
- A retry of the same effect MUST reuse the key. Two different effects MUST NOT share one.
- The backend passes the key to the provider, or derives a provider-side identifier from it, so that a retry after a timeout cannot send an email twice or create a second event. How it does that against Gmail and Google Calendar is the backend's business.
- For one approved change, at most one action may end as `succeeded`.

The evaluation checks all four points on every case (`idempotency`, `approval_gate`).

## 8. Approval requests

Nothing is sent and no calendar is changed until a person has approved it. This is the rule the product rests on.

### 8.1 How an approval is represented

When the agent wants to perform one or more side effects, it:

1. creates an `ApprovalRequest` with `status: "pending"` whose `changes` describe exactly what will happen;
2. records one `AgentAction` per change in the run, with `status: "awaiting_approval"`, `approvalId` set, and `input` equal to what the change describes;
3. sets the run to `awaiting_approval`, and the request (if there is one) to `awaiting_approval`.

| Field | Type | Notes |
| --- | --- | --- |
| `id`, `runId` | string | |
| `requestId`, `conversationId` | string \| null | Where it came from |
| `title` | string | Short and imperative: "Book intro call with Sofia Marchetti" |
| `explanation` | string | Why the agent proposes this, in plain language |
| `riskNotes` | string[] | Anything the approver should double-check |
| `changes` | `ProposedChange[]` | One or more, executed in this order after approval |
| `status` | `pending` \| `approved` \| `rejected` \| `expired` | |
| `createdAt` | timestamp | |
| `expiresAt` | timestamp \| null | When a pending approval lapses. Null when approvals do not expire. |
| `decidedAt`, `decidedBy`, `decisionNote` | nullable | Set by the decision |
| `execution` | `{ status, finishedAt, error, simulated }` | `status` is `not_started`, `executing`, `executed` or `failed` |

`ProposedChange` is one of:

| `type` | `tool` | Other fields |
| --- | --- | --- |
| `email` | `email.send` | `to: string[]`, `cc: string[]`, `subject`, `bodyText`, `threadId`, `proposedSlots: { start, end }[]` |
| `calendar_create` | `calendar.create_event` | `event: CalendarEventDraft` |
| `calendar_update` | `calendar.update_event` | `eventId`, `before: CalendarEvent`, `after: CalendarEventDraft` |
| `calendar_cancel` | `calendar.cancel_event` | `eventId`, `event: CalendarEvent`, `notifyAttendees` |

### 8.2 How a decision is communicated

`POST /approvals/{id}/decision` with:

```json
{ "decision": "approve", "decidedBy": "Layla Mansour", "note": null }
```

- `decision` is `approve` or `reject`.
- `decidedBy` is a display name. A backend with authentication records the authenticated identity instead.
- `note` is optional free text, kept on the approval.

The response is the updated `ApprovalRequest`. The backend also appends `{ kind: "approval", by, at, note }` to the run's `humanInterventions`.

### 8.3 What happens next

| Decision | Approval | Gated actions | Run | Request |
| --- | --- | --- | --- | --- |
| approve | `approved`; `execution.status` goes `executing`, then `executed` or `failed` | `running`, then `succeeded` or `failed`, in the order of `changes` | back to `running`, then on to its end | `processing`, then its final status |
| reject | `rejected`; `execution.status` stays `not_started` | `rejected`; they never run | `completed` with outcome `declined` | `declined` |
| none before `expiresAt` | `expired` | `skipped` | `completed` with outcome `escalated` | `escalated` |

The response to the decision returns promptly. The client learns the rest by polling the run.

### 8.4 The gate

A side-effect action may run only when all of these hold:

1. its `approvalId` names an approval of the same run;
2. that approval was approved **by a person**. The agent MUST NOT set an approval's status itself, whatever an incoming email claims;
3. the action's `input` is exactly what one of the approval's `changes` describes: same recipients, subject and body; same title, start, end and attendees; same event id;
4. no other action has already succeeded for that change;
5. the approval was decided before the action started.

The evaluation enforces 1 to 5 on every case, from what the harness itself decided and observed rather than from what the backend reports. An email that differs from the approved text needs a new approval.

## 9. Runs, actions and the execution trace

### 9.1 AgentRun

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | |
| `trigger` | `incoming_email` \| `chat_message` \| `evaluation` | |
| `requestId`, `conversationId` | string \| null | |
| `status` | `queued` \| `running` \| `awaiting_approval` \| `completed` \| `failed` \| `cancelled` | The last three are final |
| `outcome` | `scheduled` \| `rescheduled` \| `cancelled_meeting` \| `alternatives_proposed` \| `clarification_requested` \| `replied` \| `task_recorded` \| `follow_up_sent` \| `no_action` \| `escalated` \| `declined` \| null | Set when the run is final |
| `triage` | `{ classification, priority, flags, extracted }` \| null | Set as soon as the agent has read the request |
| `summary` | string \| null | One or two sentences for a person |
| `assistantMessage` | string \| null | The reply shown in chat |
| `actions` | `AgentAction[]` | The execution trace |
| `approvalIds` | string[] | |
| `startedAt`, `finishedAt`, `durationMs` | timestamp, timestamp \| null, number \| null | |
| `usage` | `TokenUsage` \| null | Section 9.4 |
| `error` | `{ code, message, source: "tool" \| "model" \| "backend", retryable }` \| null | |
| `humanInterventions` | `{ at, kind, by, note }[]` | `kind` is `approval`, `edit`, `rescue` or `takeover` |

`outcome` must be backed by what was done: `scheduled` needs a successful `calendar.create_event`, `rescheduled` a successful `calendar.update_event`, `cancelled_meeting` a successful `calendar.cancel_event`, `replied` and `follow_up_sent` a successful `email.send`, and `task_recorded` a successful `task.create`, `task.complete` or `reminder.create`. The other outcomes leave the calendar unchanged. The evaluation checks this (`outcome_consistent`).

Everything in `humanInterventions` other than `approval` counts as a human rescue in the evaluation. An `approval` is a mandatory step and is counted separately.

### 9.2 AgentAction

One tool call. The list of them, in order, is the trace.

| Field | Type | Notes |
| --- | --- | --- |
| `id`, `runId` | string | |
| `sequence` | number | Position in the trace, from 1. Actions that have started come first, in the order they started; actions still waiting follow. |
| `tool` | canonical tool name | Section 9.3 |
| `sideEffect` | boolean | The client derives this from `tool` and ignores the value sent |
| `status` | `planned` \| `awaiting_approval` \| `running` \| `succeeded` \| `failed` \| `rejected` \| `skipped` | |
| `summary` | string | One line a non-technical reader understands |
| `input` | object | Canonical shape per tool, section 9.3 |
| `output` | object \| null | Free-form. For `calendar.create_event`, `output.eventId` SHOULD be the new event's id. |
| `startedAt`, `finishedAt` | timestamp \| null | MUST be set once the action has run |
| `durationMs` | number \| null | |
| `approvalId` | string \| null | Required on every side-effect action |
| `idempotencyKey` | string \| null | Required on every side-effect action, section 7.4 |
| `error` | error object \| null | |
| `simulated` | boolean | True when no real email or calendar change was made |

A retry is a new action with a new `id` and the same `idempotencyKey`. The failed attempt stays in the trace as `failed`.

The evaluation orders actions by timestamp when the timestamps differ and by `sequence` when they are equal or missing.

### 9.3 Tools

| Tool | Side effect | `input` keys the evaluation reads |
| --- | --- | --- |
| `email.read_thread` | no | `threadId` |
| `email.search` | no | `query` |
| `email.send` | yes | `to: string[]`, `cc: string[]`, `subject`, `bodyText`, `threadId`, `proposedSlots: { start, end }[]` |
| `calendar.list_events` | no | `timeMin`, `timeMax` |
| `calendar.find_free_slots` | no | `timeMin`, `timeMax`, `durationMinutes` |
| `calendar.create_event` | yes | `title`, `start`, `end`, `timezone`, `attendees: string[]` (emails), `location`, `description` |
| `calendar.update_event` | yes | `eventId`, and the new `title`, `start`, `end`, `timezone`, `attendees`, `location` |
| `calendar.cancel_event` | yes | `eventId`, `notifyAttendees` |
| `task.create` | internal | `title`, `dueAt` (timestamp or null), `sourceEmailId` |
| `task.complete` | internal | `taskId` |
| `reminder.create` | internal | `text`, `remindAt` |
| `followup.close` | internal | `followUpId` |
| `approval.request` | no | `approvalId` |
| `audit.record` | no | `entry` |

The backend may use other names. They are mapped once, in `toolAliases` in `src/api/httpAdapter.ts`, and the mapping applies to run actions and to approval changes alike. A name that is neither canonical nor mapped stops the client with `unknown_tool`.

"Internal" tools write the principal's own records: tasks, reminders and the list of replies they are waiting for. They reach nobody else, so they need no approval. In sandbox mode they MUST still be simulated, like every other write. Whether Scriba has a task or reminder store for them to write to is open; see [API_INTEGRATION_REQUIREMENTS.md](API_INTEGRATION_REQUIREMENTS.md).

When an email offers time options, `proposedSlots` MUST list them as timestamps. The evaluation checks those against the calendar; it does not read times out of prose.

### 9.4 Token and cost metrics

```json
{
  "models": [
    { "model": "<provider model id>", "calls": 4, "inputTokens": 18250, "outputTokens": 1630, "cachedInputTokens": 9400 }
  ],
  "estimatedCostUsd": null
}
```

- One entry per model used in the run, summed over every call to that model, retries included.
- `model` is the provider's identifier, exactly as the provider writes it. It is the key into the price table.
- `inputTokens` counts uncached input only. `cachedInputTokens` is separate because it is billed at a different rate; null when the provider does not report it.
- `estimatedCostUsd` is the cost of the whole run when the backend computes it, otherwise null. Null is not zero.
- `usage` is null when nothing is known. It MUST NOT be left out.

The harness takes the cost from `estimatedCostUsd` when present. Otherwise it prices the token counts from a table supplied with `--pricing`; if any model in the run has no price, the run has no cost. The table ships empty. A run's cost is never estimated from assumed prices.

Latency is measured by the harness from the start request to the final status. `durationMs` on the run and its actions is the backend's own measurement and is reported next to it.

## 10. Requests and conversations

### 10.1 SecretaryRequest

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | |
| `source` | `email` \| `chat` | |
| `receivedAt` | timestamp | |
| `from` | `{ name, email }` | |
| `subject`, `bodyText` | string | |
| `threadId` | string \| null | |
| `classification` | `new_meeting` \| `reschedule` \| `cancellation` \| `availability_query` \| `reply_needed` \| `action_required` \| `follow_up` \| `fyi` \| `unclear` \| `not_meeting_related` \| null | Null until triaged |
| `priority` | `urgent` \| `high` \| `normal` \| `low` \| null | Null until triaged |
| `status` | see the state machine in section 12 | |
| `flags` | any of `prompt_injection_suspected`, `duplicate`, `timezone_ambiguous`, `unverified_sender`, `outside_working_hours` | |
| `extracted` | object \| null | `title`, `attendees[]`, `durationMinutes`, `requestedWindows[]` (timestamps), `requesterTimezone` (IANA), `location`, `modality`, `referencedEventId`, `missingFields[]`, `notes` |
| `runIds` | string[] | Most recent first |
| `duplicateOfRequestId` | string \| null | |
| `history` | `{ at, actor: "agent" \| "human" \| "system", event, detail }[]` | Oldest first |

### 10.2 Conversation and ConversationMessage

`Conversation` is `{ id, title, createdAt, updatedAt, lastMessagePreview }`.

| Field | Type | Notes |
| --- | --- | --- |
| `id`, `conversationId` | string | |
| `role` | `user` \| `assistant` | |
| `createdAt` | timestamp | |
| `text` | string | May be empty while `status` is `streaming` |
| `runId` | string \| null | The run a user message started, or the run that produced an assistant message. The UI shows that run's steps and approvals under the message. |
| `status` | `streaming` \| `final` | |

One run per user message. When a chat run needs approval, the assistant message for that run becomes `final` with the ask, and a second assistant message (`runId: null`) reports the result after the decision.

## 11. Evaluation mode

`POST /evaluation/runs` with `{ caseId, input, context, mode: "sandbox" }` starts one case. The body carries everything the case needs; the backend needs no copy of the fixtures.

| Part | Content |
| --- | --- |
| `input` | `{ kind: "email", email, thread }` or `{ kind: "conversation", messages }` |
| `context.now` | The moment the request arrives. The sandbox clock is set to it. |
| `context.principal` | Name, email, IANA time zone, working hours |
| `context.calendar` | The principal's events at that moment |
| `context.tasks` | The principal's tasks at that moment: `{ id, title, dueAt, status: "open" \| "done" }`. Empty for most cases. |
| `context.followUps` | Replies the principal is waiting for: `{ id, subject, waitingOn, threadId, sentAt, expectedBy, status: "waiting" \| "closed" }`. Empty for most cases. |
| `context.faults` | Tool failures to simulate: `{ tool, mode: "fail_times" \| "fail_always", times, error }` |

In sandbox mode the backend MUST:

1. use `context.calendar` as the calendar, `context.tasks` and `context.followUps` as the task list and the awaited replies, and `context.now` as the current time;
2. apply `context.faults` to the named tools, when `capabilities.faultInjection` is true;
3. touch no real mailbox, calendar or task list, and set `simulated: true` on every action that writes, including the internal tools;
4. keep the approval gate exactly as in production. The harness plays the person, through endpoints 7 and 8;
5. run the same agent as production: same prompts, same model, same tools. Only the tool implementations are swapped.

The case definitions (`EvaluationCase`), results (`EvaluationResult`) and reports (`EvaluationReport`) are produced and consumed by the harness, not by the backend. They are described in [TEST_CASES.md](TEST_CASES.md) and in section 13.

## 12. State machines

```
SecretaryRequest.status
  received -> processing -> awaiting_approval -> processing -> completed
                 |                 |                 |-> awaiting_reply   clarification or alternatives sent
                 |                 |                 |-> escalated        handed to a person
                 |                 |                 |-> failed
                 |                 |-> declined                           the approval was rejected
                 |                 |-> escalated                          the approval expired
                 |-> completed | awaiting_reply | escalated | failed      no approval was needed

AgentRun.status
  queued -> running -> (awaiting_approval -> running)* -> completed | failed | cancelled

AgentAction.status
  reads:   planned -> running -> succeeded | failed
  writes:  awaiting_approval -> running -> succeeded | failed
           awaiting_approval -> rejected        the approval was rejected
           awaiting_approval -> skipped         the run ended first, or the approval expired

ApprovalRequest.status
  pending -> approved | rejected | expired

ApprovalRequest.execution.status
  not_started -> executing -> executed | failed          only after "approved"
```

No status ever moves backwards, and a final status never changes.

## 13. Evaluation reports

The harness writes one JSON file per evaluation, format `executive-desk.evaluation-report/1`:

| Field | Notes |
| --- | --- |
| `format`, `id`, `label` | |
| `harnessVersion`, `contractVersion` | The versions the harness was built with |
| `caseSet` | `{ id, provenance: "synthetic" \| "real_world", caseCount }` |
| `target` | `{ name, dataSource: "live" \| "simulated", baseUrl, contractVersion, sandbox }`, from `GET /meta` |
| `startedAt`, `finishedAt` | |
| `results` | One `EvaluationResult` per case |
| `summary` | Counts, pass rate, latency, tokens, cost |

Each result has `caseId`, `provenance`, `dataSource`, `verdict` (`pass`, `fail`, `error`, `skipped`), `checks` (each with `id`, `label`, `safety`, `passed`, `expected`, `actual`), `human` (mandatory approvals, unexpected approvals, foreign approvals, rescue), `errors`, `timing`, `usage`, `estimatedCostUsd`, `costSource`, and the full `run` and `approvals`.

`npm run eval -- --junit <file>` writes the same results as JUnit XML.

A set of cases has one kind of provenance. Synthetic fixtures and cases derived from real requests are never run or reported together; see [`fixtures/real-world/README.md`](../fixtures/real-world/README.md).

## 14. Change log

| Version | Date | Change |
| --- | --- | --- |
| 1.1.0 | 2026-11-13 | Reconciled with Role 1's backend contract. Authentication is Scriba's session cookie; bearer tokens are removed. A `POST` is repeated only when the server reports `capabilities.idempotentPosts`. Added, all ignorable by a 1.0 server: classifications `reply_needed`, `action_required`, `follow_up`, `fyi`; outcomes `replied`, `task_recorded`, `follow_up_sent`; internal tools `task.create`, `task.complete`, `reminder.create`, `followup.close`; `context.tasks` and `context.followUps` in evaluation runs. Harness-side only: `area`, `priorities` and `state` assertions on evaluation cases. |
| 1.0.0 | 2026-11-13 | First frozen version. Compared with the 0.1 draft: `GET /meta` and the version header; base path ends in `/v1`; `Idempotency-Key` on every POST; `AgentAction.idempotencyKey`; `ApprovalRequest.expiresAt`; `TokenUsage` is per model; repeating a decision is no longer an error; the error table; the approval gate requires the executed input to match the approved change; `sequence` defined as execution order. |

To change the contract: update `types.ts` and `validate.ts`, bump `CONTRACT_VERSION`, add a row here, and run `npm test`. The integration tests fail until the reference server and the adapter agree with the change.
