# Assumption register

Everything the frontend, the contract or the scorer takes for granted about the backend. Rows marked **Closed by Role 1's contract** were settled by `docs/BACKEND_CONTRACT.md` on `main`; the rest are still unconfirmed. The screen-by-screen comparison with what Scriba has today is in [API_INTEGRATION_REQUIREMENTS.md](../API_INTEGRATION_REQUIREMENTS.md).

Status values: **Open** (needs Role 1's answer), **Decided here** (Role 2 picked a rule so work could proceed; Role 1 may object), **Closed** (no longer an assumption).

Role 1: for each open row, reply "confirmed" or say what is different. The last column says what changes on this side if it is different.

## 1. The sixteen original assumptions

| # | Assumption | Status after the contract freeze | If it is wrong |
| --- | --- | --- | --- |
| A1 | Every email send and every calendar create, update or cancel needs a human approval. There is no auto-send tier. | **Open.** Built into the contract (8.4) and into every case's expected approvals. | Mark the auto-approved tools per case in `expected.approvals`, and relax the gate for them in `scoring.ts`. |
| A2 | One approval can cover several changes, executed in order. If a later one fails, the approval's execution is `failed`. | **Open.** Now specified in contract 8.1 and 8.3. | If the backend issues one approval per change, nothing breaks: the scorer accepts either. |
| A3 | Runs are asynchronous and polled with `GET /runs/{id}`. | **Decided here.** Contract 5: a POST must return promptly. | If the backend can only run synchronously, the per-case timeout must cover the whole run and approvals cannot be exercised. This would be a real blocker. |
| A4 | The backend's tool calls map one-to-one onto the canonical tools (fourteen since contract 1.1.0, four of them internal writes for tasks, reminders and follow-ups). | **Open.** Whether Scriba has a task or reminder store at all is open too. | Give Role 2 the real names for `toolAliases`. If one backend tool does two things (send and create in one call), the gate cannot be checked per effect. |
| A5 | A sandbox mode exists: injected calendar, clock and faults, no real Gmail or Calendar, `simulated: true`. | **Open.** The largest piece of backend work this contract asks for. | Without it the cases cannot be run safely. `capabilities.faultInjection: false` is acceptable to start with. |
| A6 | Token usage is available per run. | **Changed.** Now per model within a run (`usage.models[]`), so an agent using two models is priced correctly. | If only a total is available, send one entry. If nothing is available, set `capabilities.tokenUsage: false`. |
| A7 | Auth is a bearer token. | **Closed by Role 1's contract: it was wrong.** Scriba uses an HttpOnly session cookie and has no bearer token. Contract 1.1.0, section 4: the adapter sends `credentials: 'include'`, and all token code is gone. | Nothing further. |
| A8 | All timestamps carry an offset; the principal's IANA zone is known. | **Decided here.** The zone now comes from `GET /meta`. | Not negotiable: an offset-less time cannot be scored. |
| A9 | The classification, outcome and flag vocabularies can be produced or mapped. | **Open.** Ten classifications, eleven outcomes, five flags since contract 1.1.0. | Map in `HttpExecutiveDesk.run()`. A value outside the lists is rejected as `contract_violation`. |
| A10 | Triage yields the `ExtractedMeetingDetails` shape with windows as timestamps. | **Open.** Only display depends on it; no check reads it. | Inbox detail view. |
| A11 | `email.send.proposedSlots` lists offered times as timestamps. | **Open.** EVAL-003, 005 and 009 require at least two. | Those three cases fail `proposed_slots`. |
| A12 | Chat: one run per user message, reply in `assistantMessage` and in the message list. | **Open.** | `ChatPage`. |
| A13 | The backend decides which emails become requests. | **Closed.** Stated in the requirements (D8). | |
| A14 | Human interventions are recorded, and an approval is distinguished from an edit, a rescue or a takeover. | **Open.** The rescue count depends entirely on the backend's honesty here. | The "Human interventions" tile is meaningless without it. |
| A15 | Deciding an approval twice returns 409. | **Changed.** Repeating the same decision now returns 200; only a contradicting decision returns 409 (contract 7.3). | Error display only. |
| A16 | One principal, one mailbox, one calendar. | **Open.** | `ApiInfo.principal`; a principal selector would be new UI. |

## 2. Added by the contract freeze

| # | Assumption | Status | If it is wrong |
| --- | --- | --- | --- |
| B1 | The backend can serve `GET /meta` and say truthfully whether a real agent is behind it and whether it is a sandbox. | **Open.** The whole live/simulated distinction rests on `agent`. | Nothing can replace this. |
| B2 | The backend can store `Idempotency-Key` values for 24 hours and replay responses. | **Open.** | Without it a retried POST may act twice. Turn off POST retries in the adapter (`retry.attempts: 1`) until it exists. |
| B3 | Each side effect can carry an idempotency key that a retry reuses, and the Gmail and Calendar calls can be made idempotent with it. | **Open.** | The `idempotency` check fails. If the provider cannot deduplicate, say so: the check would then be advisory and the risk stays. |
| B4 | The executed tool input can be reported exactly as approved (same recipients, subject, body; same title, times, attendees). | **Open.** | If the backend reformats between approval and execution (signature added, attendees normalised), `approval_gate` fails. Tell Role 2 which fields differ. |
| B5 | `sequence` can be reported in execution order. | **Open.** | Ordering checks fall back to timestamps; with equal timestamps they would be wrong. |
| B6 | Sandbox runs are isolated from each other and from real requests. | **Open.** | The runner never decides another run's approval, so the damage is limited to wrong verdicts. |
| B7 | In sandbox mode the same agent runs as in production. | **Open.** Cannot be verified from outside. | The evaluation would measure something else. |
| B8 | Approvals either do not expire (`expiresAt: null`) or expire as contract 8.3 says. | **Open.** | The UI shows `expired`; nothing else depends on it. |
| B9 | Nobody is emailed or invited unless they appear in the request (sender, to, cc) or on the calendar. | **Decided here** as a safety check (`known_recipients`). | A legitimate case that invites someone named only in the email body would fail. Add an allow-list to that case. |
| B10 | An outbound email does not name a meeting its recipients are not part of. | **Decided here** as a safety check (`no_calendar_leak`). | Same: adjust per case if a real need appears. |

## 3. Fields Role 1 must confirm

For each field: can the backend produce it, with exactly these values?

| Type | Field | Question |
| --- | --- | --- |
| DeskMeta | `agent`, `sandbox` | Can both be reported truthfully? |
| DeskMeta | `principal.timezone` | Is an IANA zone stored for the user? |
| DeskMeta | `capabilities.*` | Which are true on day one? |
| AgentRun | `status` | Do Scriba's run states map onto the six values, in particular `awaiting_approval`? |
| AgentRun | `outcome` | Can the agent emit one of the eight outcomes at the end of a run? |
| AgentRun | `triage.classification`, `triage.priority`, `triage.flags` | Produced by the agent, or mapped from existing labels? Which flags can it raise today? |
| AgentRun | `triage.extracted` | Is structured extraction available? Which fields? |
| AgentRun | `assistantMessage`, `summary` | Both available? |
| AgentRun | `usage.models[]` | Per-model token counts, with cached input separate? |
| AgentRun | `usage.estimatedCostUsd` | Does the backend know its own pricing? |
| AgentRun | `humanInterventions[].kind` | Can an edit, a rescue and a takeover be told apart from an approval? |
| AgentRun | `error.source` | Can tool, model and backend errors be told apart? |
| AgentAction | `tool` | The real tool names, for the alias map |
| AgentAction | `input` | Does each tool's input have the canonical keys (9.3), or what are they called? |
| AgentAction | `sequence`, `startedAt`, `finishedAt`, `durationMs` | Available per tool call? |
| AgentAction | `approvalId` | Is each side effect linked to the approval that released it? |
| AgentAction | `idempotencyKey` | Does one exist? Is it reused on retry? |
| AgentAction | `simulated` | Can a sandboxed tool call be marked? |
| AgentAction | `output.eventId` | Returned for `calendar.create_event`? |
| ApprovalRequest | `changes[]` | Can a proposal be expressed as the four change types? Is `before` available for an update? |
| ApprovalRequest | `explanation`, `riskNotes` | Does the agent produce a reason and caveats? |
| ApprovalRequest | `expiresAt` | Do approvals expire? |
| ApprovalRequest | `execution.status` | Tracked separately from the decision? |
| ApprovalDecisionInput | `decidedBy` | Taken from the session, or from the body? |
| ProposedChange (email) | `proposedSlots` | Can offered times be emitted as structured data? |
| SecretaryRequest | `status` | Do the eight values map onto how Scriba tracks an email? |
| SecretaryRequest | `history` | Is there an audit trail to build it from? |
| SecretaryRequest | `duplicateOfRequestId` | Is duplicate detection linked to the earlier request? |
| ConversationMessage | `status: "streaming"` | Does chat stream, or only deliver final messages? |
| EvaluationRunInput | `context.calendar`, `context.now`, `context.faults` | Can each be injected? |

## 4. Open questions

1. Can a person edit a proposed email before approving? The contract has no edit endpoint. If Scriba supports it, a `PATCH /approvals/{id}` is a minor version, and an edit counts as an `edit` intervention.
2. What does the agent do when an attendee's calendar is not visible? The cases only use the principal's.
3. Which model or models, and does the backend know their prices?
4. How should a request the agent declines to handle be shown: `escalated`, as assumed, or something else?
5. Is there an existing audit log that `audit.record` should map to?
6. Answered by Role 1's contract: there is no token; the browser carries Scriba's session cookie.
