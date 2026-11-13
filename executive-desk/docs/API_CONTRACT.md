# Scriba Executive Desk: API contract

Version 0.1, draft. Proposed by the frontend (Role 2). Nothing here has been confirmed against the real backend yet; the items Role 1 needs to confirm are listed in [INTEGRATION_HANDOFF.md](INTEGRATION_HANDOFF.md).

The TypeScript source of truth is [`src/api/types.ts`](../src/api/types.ts). Full JSON examples of every type are in [API_EXAMPLES.md](API_EXAMPLES.md), generated from the mock adapter.

## Conventions

- Base path: `{baseUrl}`, for example `http://localhost:8000/api/executive-desk`. JSON in, JSON out.
- Timestamps are RFC 3339 with an explicit offset: `2026-11-17T11:00:00+02:00`. A timestamp without an offset is treated as invalid, never guessed.
- Ids are opaque strings.
- A nullable field is always present with the value `null`. Fields are never omitted.
- Auth: `Authorization: Bearer <token>` when a token is configured. The session mechanism is Role 1's decision.
- Errors: a non-2xx status with this body. `code` is a stable machine string.

```json
{ "error": { "code": "already_decided", "message": "This approval was already approved." } }
```

## Endpoints

| Method | Path | Request body | Response | Used by |
| --- | --- | --- | --- | --- |
| GET | `/requests?status=a,b` | | `SecretaryRequest[]`, newest first | Inbox, nav badge |
| GET | `/requests/{id}` | | `SecretaryRequest` | Inbox |
| POST | `/requests/{id}/process` | `{}` | `AgentRun` (the run that was started) | Inbox |
| GET | `/runs/{id}` | | `AgentRun` | everywhere, evaluation |
| GET | `/runs?requestId=&conversationId=` | | `AgentRun[]`, newest first | Inbox, Chat, Approvals |
| GET | `/approvals?status=a,b&runId=` | | `ApprovalRequest[]`, newest first | Approvals, Chat, evaluation |
| POST | `/approvals/{id}/decision` | `ApprovalDecisionInput` | `ApprovalRequest` | Approvals, Chat, evaluation |
| GET | `/conversations` | | `Conversation[]`, most recently updated first | Chat |
| POST | `/conversations` | `{}` | `Conversation` | Chat |
| GET | `/conversations/{id}/messages` | | `ConversationMessage[]`, oldest first | Chat |
| POST | `/conversations/{id}/messages` | `{ "text": string }` | `{ "message": ConversationMessage, "run": AgentRun }` | Chat |
| POST | `/evaluation/runs` | `EvaluationRunInput` | `AgentRun` | evaluation |

The evaluation harness needs only four of these: `POST /evaluation/runs`, `GET /runs/{id}`, `GET /approvals`, `POST /approvals/{id}/decision`.

Runs are asynchronous. A `POST` that starts a run returns immediately with the run in `queued` or `running`; the client polls `GET /runs/{id}`. The frontend polls every 2 seconds; the harness every 500 ms. Push (SSE or WebSocket) can replace polling later behind `ExecutiveDeskApi.subscribe` without touching the screens.

`POST /approvals/{id}/decision` on an approval that is not `pending` returns 409 `already_decided`. `POST /requests/{id}/process` on a request that is `processing` or `awaiting_approval` returns 409 `already_processing`.

## SecretaryRequest

An incoming meeting-related request.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | |
| `source` | `"email"` \| `"chat"` | |
| `receivedAt` | timestamp | |
| `from` | `{ name, email }` | |
| `subject`, `bodyText` | string | Plain text. The frontend never renders HTML from email. |
| `threadId` | string \| null | |
| `classification` | `new_meeting` \| `reschedule` \| `cancellation` \| `availability_query` \| `unclear` \| `not_meeting_related` \| null | null until triaged |
| `priority` | `urgent` \| `high` \| `normal` \| `low` \| null | null until triaged |
| `status` | see state machine below | |
| `flags` | array of `prompt_injection_suspected`, `duplicate`, `timezone_ambiguous`, `unverified_sender`, `outside_working_hours` | |
| `extracted` | `ExtractedMeetingDetails` \| null | `title`, `attendees[]`, `durationMinutes`, `requestedWindows[]` (absolute instants), `requesterTimezone` (IANA), `location`, `modality`, `referencedEventId`, `missingFields[]`, `notes` |
| `runIds` | string[] | most recent first |
| `duplicateOfRequestId` | string \| null | |
| `history` | `{ at, actor: "agent" \| "human" \| "system", event, detail }[]` | oldest first |

Status transitions:

```
received -> processing -> awaiting_approval -> processing -> completed
                |                |                 |-> awaiting_reply   (clarification or alternatives sent)
                |                |                 |-> escalated        (handed to a human)
                |                |                 |-> failed
                |                |-> declined                           (approval rejected)
                |-> completed | awaiting_reply | escalated | failed     (no approval needed)
```

## AgentRun

One execution of the agent, started by an email, a chat message or the evaluation harness.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | |
| `trigger` | `incoming_email` \| `chat_message` \| `evaluation` | |
| `requestId`, `conversationId` | string \| null | which inbox request or chat it belongs to |
| `status` | `queued` \| `running` \| `awaiting_approval` \| `completed` \| `failed` \| `cancelled` | the last three are final |
| `outcome` | `scheduled` \| `rescheduled` \| `cancelled_meeting` \| `alternatives_proposed` \| `clarification_requested` \| `no_action` \| `escalated` \| `declined` \| null | set when the run is final |
| `triage` | `{ classification, priority, flags, extracted }` \| null | set as soon as the agent has read the request |
| `summary` | string \| null | one or two sentences for a human |
| `assistantMessage` | string \| null | the reply shown in chat |
| `actions` | `AgentAction[]` | in order |
| `approvalIds` | string[] | |
| `startedAt`, `finishedAt`, `durationMs` | timestamp, timestamp \| null, number \| null | |
| `usage` | `TokenUsage` \| null | `{ model, inputTokens, outputTokens, cachedInputTokens, estimatedCostUsd }`, summed over every model call in the run. `inputTokens` counts uncached input only. `estimatedCostUsd` is null unless the backend computes cost itself. |
| `error` | `{ code, message, source: "tool" \| "model" \| "backend", retryable }` \| null | |
| `humanInterventions` | `{ at, kind, by, note }[]` | `kind` is `approval` (a mandatory decision), `edit`, `rescue` or `takeover`. Everything except `approval` counts as a rescue in the evaluation. |

Status transitions: `queued -> running -> (awaiting_approval -> running)* -> completed | failed | cancelled`.

## AgentAction

One tool call inside a run.

| Field | Type | Notes |
| --- | --- | --- |
| `id`, `runId`, `sequence` | string, string, number | |
| `tool` | canonical tool name | see the table below |
| `sideEffect` | boolean | true for the four write tools |
| `status` | `planned` \| `awaiting_approval` \| `running` \| `succeeded` \| `failed` \| `rejected` \| `skipped` | |
| `summary` | string | one line a non-technical reader understands |
| `input` | object | canonical shape per tool, below |
| `output` | object \| null | free-form |
| `startedAt`, `finishedAt`, `durationMs` | timestamp \| null, timestamp \| null, number \| null | |
| `approvalId` | string \| null | required on every side-effect action |
| `error` | run error object \| null | |
| `simulated` | boolean | true when no real email or calendar change was made |

Status transitions: `planned -> running -> succeeded | failed` for reads; `awaiting_approval -> running -> succeeded | failed`, or `awaiting_approval -> rejected | skipped`, for writes. A retry is a new action, not a status change on the failed one.

Canonical tools and the `input` keys the evaluation reads:

| Tool | Side effect | Input |
| --- | --- | --- |
| `email.read_thread` | no | `threadId` |
| `email.search` | no | `query` |
| `email.send` | yes | `to: string[]`, `cc: string[]`, `subject`, `bodyText`, `threadId`, `proposedSlots: { start, end }[]` |
| `calendar.list_events` | no | `timeMin`, `timeMax` |
| `calendar.find_free_slots` | no | `timeMin`, `timeMax`, `durationMinutes` |
| `calendar.create_event` | yes | `title`, `start`, `end`, `timezone`, `attendees: string[]` (emails), `location`, `description` |
| `calendar.update_event` | yes | `eventId`, plus the new `title`, `start`, `end`, `timezone`, `attendees`, `location` |
| `calendar.cancel_event` | yes | `eventId`, `notifyAttendees` |
| `approval.request` | no | `approvalId` |
| `audit.record` | no | `entry` |

The backend may use other tool names. Map them in `toolAliases` in `src/api/httpAdapter.ts`; an unmapped name stops the client with a clear error instead of being silently ignored.

When an email offers time options, `email.send.proposedSlots` must list them as instants. The evaluation checks those slots against the calendar; it does not parse times out of prose.

## ApprovalRequest

What a human sees before anything is sent or changed.

| Field | Type | Notes |
| --- | --- | --- |
| `id`, `runId` | string | |
| `requestId`, `conversationId` | string \| null | where it came from |
| `title` | string | short and imperative: "Book intro call with Sofia Marchetti" |
| `explanation` | string | why the agent proposes this, in plain language |
| `riskNotes` | string[] | anything the approver should double-check |
| `changes` | `ProposedChange[]` | one or more, executed in order after approval |
| `status` | `pending` \| `approved` \| `rejected` \| `expired` | |
| `createdAt`, `decidedAt`, `decidedBy`, `decisionNote` | timestamp, then nullable | |
| `execution` | `{ status: "not_started" \| "executing" \| "executed" \| "failed", finishedAt, error, simulated }` | |

`ProposedChange` is one of:

- `{ type: "email", tool: "email.send", to, cc, subject, bodyText, threadId, proposedSlots }`
- `{ type: "calendar_create", tool: "calendar.create_event", event: CalendarEventDraft }`
- `{ type: "calendar_update", tool: "calendar.update_event", eventId, before: CalendarEvent, after: CalendarEventDraft }`
- `{ type: "calendar_cancel", tool: "calendar.cancel_event", eventId, event: CalendarEvent, notifyAttendees }`

`ApprovalDecisionInput` is `{ "decision": "approve" | "reject", "decidedBy": string, "note": string | null }`.

Transitions: `pending -> approved | rejected | expired`. For an approved request, `execution.status` goes `not_started -> executing -> executed | failed`. After a rejection, the gated actions become `rejected` and the run finishes with outcome `declined`.

The rule the whole product rests on: **a side-effect action may only run when its `approvalId` points at an approval whose status is `approved`, that covers that tool, and that was decided before the action started.** The evaluation enforces this on every case.

## ConversationMessage

| Field | Type | Notes |
| --- | --- | --- |
| `id`, `conversationId` | string | |
| `role` | `user` \| `assistant` | |
| `createdAt` | timestamp | |
| `text` | string | plain text; may be empty while `status` is `streaming` |
| `runId` | string \| null | the run a user message started, or the run that produced an assistant message. The UI shows that run's steps and approvals under the message. |
| `status` | `streaming` \| `final` | |

`Conversation` is `{ id, title, createdAt, updatedAt, lastMessagePreview }`.

When a chat run needs approval, the assistant message for that run becomes `final` with the ask, and a second assistant message (with `runId: null`) reports the result after the decision.

## EvaluationCase

A synthetic scenario and what a correct agent does with it. All twenty are in [TEST_CASES.md](TEST_CASES.md) and `fixtures/evaluation-cases.json`.

| Field | Notes |
| --- | --- |
| `id`, `title`, `category`, `tags`, `description` | |
| `synthetic` | always `true` |
| `input` | `{ kind: "email", email, thread }` or `{ kind: "conversation", messages }` |
| `context` | `now` (the sandbox clock), `principal` (name, email, time zone, working hours), `calendar` (events at that moment), `faults` (tool failures to simulate) |
| `expected` | `behavior` (prose), `classifications`, `outcomes`, `runStatuses`, `toolCalls`, `forbidden`, `order`, `approvals`, `harnessDecision`, `outboundEmail`, `proposedSlots`, `chatReply`, `flags` |
| `successCriteria`, `failureConditions` | prose, for a human reviewer |

`EvaluationRunInput`, the body of `POST /evaluation/runs`, is `{ caseId, input, context, mode: "sandbox" }`. In sandbox mode the backend must:

1. use `context.calendar` as the principal's calendar and `context.now` as the current time;
2. apply `context.faults` to the named tools;
3. touch no real mailbox or calendar, and set `simulated: true` on every side-effect action;
4. keep the approval gate exactly as in production. The harness plays the human through the normal approvals endpoints.

## EvaluationResult

Produced by the harness, not by the backend.

| Field | Notes |
| --- | --- |
| `caseId`, `caseTitle`, `category`, `dataSource` | `dataSource` is `live` or `simulated` |
| `verdict` | `pass` (every check passed), `fail` (finished, at least one check failed), `error` (could not be scored: API error, model error, timeout), `skipped` |
| `checks` | `{ id, label, passed, expected, actual }[]`: the expected-versus-actual table |
| `expected`, `actual` | short summaries: classification, outcome, tools, approvals |
| `human` | `mandatoryApprovals` (expected, granted by the harness), `unexpectedApprovals` (not called for, rejected by the harness), `rescued`, `interventions` |
| `errors` | `{ source, code, message }[]`, including tool errors the agent recovered from |
| `timing` | `startedAt`, `finishedAt`, `wallClockMs` (measured by the harness), `agentReportedMs` |
| `usage`, `estimatedCostUsd`, `costSource` | cost comes from the backend if it reports one, otherwise from the price table, otherwise null |
| `run`, `approvals` | the full trace |

`EvaluationReport` wraps the results with `target`, timestamps and an `EvaluationSummary`. In the summary, `passRate` is `passedUnassisted / executed` and is null until something has been executed; `costPerRunUsd` is null until at least one run has a cost.
