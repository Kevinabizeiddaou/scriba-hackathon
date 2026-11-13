# Backend endpoint requirements

What Role 1's backend has to provide for the Executive Desk frontend and the evaluation runner to work against it. Each line is a requirement from [API_CONTRACT.md](../API_CONTRACT.md) v1.0.0, with the section it comes from and how this side verifies it. "Runner" means a failure shows up in `npm run eval`; "adapter" means the HTTP adapter rejects the response with a named error.

Build order that gets the evaluation running soonest: group A, then B, then C. Group D is needed only for the product screens.

## A. Handshake and transport

| # | Requirement | Contract | Verified by |
| --- | --- | --- | --- |
| A1 | Serve everything under one base URL ending in `/api/executive-desk/v1`. | 2 | adapter |
| A2 | `GET /meta` returns `contractVersion` (1.x), `service`, `agent`, `sandbox`, `principal` with an IANA `timezone`, `simulatedNow`, and all four `capabilities`. | 3 | adapter: `contract_violation` names any missing field; `unsupported_contract_version` on another major |
| A3 | `agent` is `"real"` only when a model-driven agent produces the runs. | 3 | Decides whether results are labelled live. Cannot be verified from outside. |
| A4 | `sandbox` is `true` only when no real mailbox or calendar can be reached. | 3 | runner refuses `sandbox: false` (`not_sandbox`) |
| A5 | Send `X-Executive-Desk-Contract` on every response. | 1 | integration test against the reference server; not enforced on the real backend |
| A6 | Authenticate with Scriba's existing session cookie. No bearer token. 401 `unauthenticated` without a valid session, 403 `forbidden` without permission. | 4 | adapter maps both; on 401 the UI says the Scriba session has ended; never retried |
| A7 | For browser use, CORS with credentials: name the frontend origin exactly, send `Access-Control-Allow-Credentials: true`, and allow the headers `Content-Type`, `Idempotency-Key`, `X-Executive-Desk-Contract`. Scriba accepts `http://localhost:5173`. | 4 | integration test against the reference server; browser console on the real backend |
| A8 | Errors use `{ "error": { "code", "message" } }` with the codes in the contract table. | 6 | adapter |
| A9 | Honour `Idempotency-Key` on every POST: same key and same request returns the stored response without acting again; same key and a different request returns 422. Keep keys 24 hours. Say so with `capabilities.idempotentPosts: true` in `/meta`. | 7.1 | Until the backend says so, the client sends each POST exactly once and never repeats it. The reference server shows the behaviour; `httpAdapter.integration.test.ts` tests it. |
| A10 | Return 429, 502, 503 or 504 for temporary conditions (with `Retry-After` on 429), not 500. | 6, 7.2 | The adapter retries the first four and not 500 |
| A11 | Timestamps are RFC 3339 with an offset, everywhere. | 2 | adapter (`contract_violation`), runner (`timestamps_valid`) |
| A12 | Nullable fields are present as `null`, never omitted. | 2 | adapter (`contract_violation`) |

## B. Runs and approvals (needed by the evaluation runner)

| # | Requirement | Contract | Verified by |
| --- | --- | --- | --- |
| B1 | `GET /runs/{id}` returns the run with its full `actions` trace. Final statuses are `completed`, `failed`, `cancelled`. | 9.1 | adapter, runner |
| B2 | A run that needs a side effect creates an `ApprovalRequest`, records one `awaiting_approval` action per change with `approvalId` set, and moves to `awaiting_approval`. | 8.1 | runner |
| B3 | `GET /approvals?runId=X` returns only that run's approvals. `status=pending` filters by status. | 5 | runner: `approvals_scoped` fails the case if another run's approval is returned |
| B4 | `POST /approvals/{id}/decision` with `{ decision, decidedBy, note }` returns the updated approval promptly. Repeating the same decision returns 200; the opposite decision returns 409 `already_decided`. | 7.3, 8.2 | adapter, integration tests |
| B5 | After approval the gated actions run in the order of `changes`, and the run continues to a final status. After rejection they become `rejected`, never run, and the run completes with outcome `declined`. | 8.3 | runner |
| B6 | The agent never sets an approval's status itself. | 8.4 | runner: `approval_gate` only accepts approvals the harness decided |
| B7 | An executed side-effect action's `input` equals what the approved change describes. A different email or event needs a new approval. | 8.4 | runner: `approval_gate` |
| B8 | For one approved change, at most one action succeeds. A retry is a new action with the same `idempotencyKey`. | 7.4, 9.2 | runner: `approval_gate`, `idempotency` |
| B9 | No gated action starts before its approval is decided. | 8.4 | runner observes the run at the moment it decides |
| B10 | Every side-effect action has `idempotencyKey`; reads have `null`. | 7.4 | adapter (`contract_violation`), runner (`idempotency`) |
| B11 | `sequence` follows execution order; `startedAt` and `finishedAt` are set once an action has run. | 9.2 | runner: ordering checks |
| B12 | Tool names are canonical, or the mapping is given to Role 2 for `toolAliases`. The same names are used in run actions and approval changes. | 9.3 | adapter: `unknown_tool` names the tool |
| B13 | `triage` (classification, priority, flags, extracted details) is on the run. | 9.1 | runner: `classification`, `flags` |
| B14 | `outcome` is one of the eight values and matches what was done to the calendar. | 9.1 | runner: `outcome`, `outcome_consistent` |
| B15 | `email.send` carries `proposedSlots` as timestamps whenever the body offers times. | 9.3 | runner: `proposed_slots`; required by EVAL-003, 005 and 009 |
| B16 | `humanInterventions` records each approval as `kind: "approval"`, and any edit, retry or takeover by a person as `edit`, `rescue` or `takeover`. | 9.1 | The rescue count. Cannot be verified from outside. |
| B17 | `usage` lists tokens per model (`model`, `calls`, `inputTokens` uncached, `outputTokens`, `cachedInputTokens`), summed over the run. `estimatedCostUsd` is null unless the backend computes cost. | 9.4 | adapter; without it the cost tile stays empty |

## C. Evaluation mode

| # | Requirement | Contract | Verified by |
| --- | --- | --- | --- |
| C1 | `POST /evaluation/runs` accepts `{ caseId, input, context, mode: "sandbox" }` and returns the started run promptly. It does not block until approval. | 5, 11 | runner: per-case timeout |
| C2 | The run uses `context.calendar` as the calendar and `context.now` as the clock. | 11 | Most cases fail otherwise |
| C3 | The run touches no real mailbox or calendar, and marks side-effect actions `simulated: true`. | 11 | runner: `sandbox_only`. Also check the real mailbox by hand once. |
| C4 | The approval gate is unchanged in sandbox mode. | 11 | runner |
| C5 | The same agent runs as in production: prompts, model and tool selection. Only tool implementations are swapped. | 11 | Cannot be verified from outside. Without it the results do not describe the product. |
| C6 | `context.faults` is honoured (`fail_times`, `fail_always`), or `capabilities.faultInjection` is `false`. | 11 | runner skips EVAL-017 and EVAL-018 when false |
| C7 | The endpoint is unavailable when `sandbox` is false. | 4 | Safety. Not verified by this side. |
| C8 | Runs of different cases do not share state: one case's calendar or approvals never appear in another's. | 11 | runner: `approvals_scoped` catches approvals; calendar leakage shows as wrong verdicts |

## D. Product screens

| # | Requirement | Contract | Screen |
| --- | --- | --- | --- |
| D1 | `GET /requests?status=` and `GET /requests/{id}` return `SecretaryRequest` objects, newest first, with `history`. | 10.1 | Request Inbox |
| D2 | `POST /requests/{id}/process` starts a run and returns it; 409 `already_processing` when one is in progress. | 5, 6 | Request Inbox |
| D3 | `GET /runs?requestId=&conversationId=` filters exactly. | 5 | Inbox, Chat, Approvals |
| D4 | `GET /approvals` without filters returns all approvals, newest first. | 5 | Approval Center |
| D5 | `GET /conversations`, `POST /conversations`, `GET /conversations/{id}/messages`. | 10.2 | Secretary Chat |
| D6 | `POST /conversations/{id}/messages` with `{ text }` stores the user message, starts one run and returns both. | 10.2 | Secretary Chat |
| D7 | A chat run that needs approval posts the ask as the run's assistant message, then a second assistant message with the result. | 10.2 | Secretary Chat |
| D8 | The backend decides which incoming emails become requests. The frontend does not read Gmail. | | Request Inbox |

## Not required

- Streaming or server push. The client polls. Push can be added later behind `subscribe` without changing the screens.
- Any knowledge of the evaluation cases. Each case arrives complete in the request body.
- Cost calculation. Token counts are enough; cost is optional.
