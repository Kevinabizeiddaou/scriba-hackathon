# Integration handoff: Role 2 to Role 1

Role 2 has finished the frontend, the mock API, the twenty evaluation cases and the evaluation runner. Everything runs today on scripted mock data. Connecting it to the real Scriba backend needs the endpoints below and answers to the questions in section 4.

This workspace was built without reading Scriba's backend code. The contract is a proposal written from the product description, so expect to adjust it. Section 5 says where each kind of adjustment goes.

## 1. What exists

| Piece | Where | State |
| --- | --- | --- |
| Four screens: Secretary Chat, Request Inbox, Approval Center, Evaluation Dashboard | `src/pages`, `src/components` | Working on the mock adapter |
| Typed contract | `src/api/types.ts`, documented in `docs/API_CONTRACT.md` | Draft, unconfirmed |
| Client interface | `src/api/client.ts` (`ExecutiveDeskApi`) | Stable from the UI's side |
| Mock adapter | `src/api/mock/` | Scripted, no network, every side effect simulated |
| HTTP adapter | `src/api/httpAdapter.ts` | Written and unit-tested against a stubbed `fetch`. Never run against a real server. |
| Twenty cases | `src/evaluation/fixtures`, `fixtures/evaluation-cases.json`, `docs/TEST_CASES.md` | Complete, synthetic |
| Evaluation runner and CLI | `src/evaluation`, `scripts/eval.ts` | Verified against the mock only (self-test: 20 reference scripts pass, 12 planted defects caught) |

No real evaluation has been run. There is no pass rate, cost or latency figure yet, and the dashboard shows placeholders until there is.

## 2. Connecting the backend

1. Serve the endpoints in section 3 under one base URL and allow the dev origin `http://localhost:5183` (CORS), or put both behind one proxy.
2. Start the frontend against it:

   ```bash
   VITE_API_MODE=http VITE_API_BASE_URL=http://localhost:8000/api/executive-desk VITE_PRINCIPAL_NAME="..." VITE_PRINCIPAL_EMAIL="..." VITE_PRINCIPAL_TIMEZONE="Asia/Beirut" npm run dev
   ```

3. Run the evaluation from the command line:

   ```bash
   npm run eval -- --base-url http://localhost:8000/api/executive-desk --token-env DESK_TOKEN --label "Friday first run"
   ```

   Add `--snapshot friday` (or `saturday`, `sunday`) to freeze the day's summary into `eval-results/snapshots/`, and `--pricing prices.json` if the backend reports tokens but not cost.

Nothing outside `src/api/httpAdapter.ts` and `src/api/index.ts` should need to change.

## 3. Required endpoints

Paths, payloads and response shapes are in `docs/API_CONTRACT.md`; JSON examples are in `docs/API_EXAMPLES.md`.

Minimum for the evaluation runner (do these first):

| Endpoint | Purpose |
| --- | --- |
| `POST /evaluation/runs` | Start one case in sandbox mode. Body carries the email or chat input, the calendar, the clock and any faults. |
| `GET /runs/{id}` | Poll the run until `completed`, `failed` or `cancelled`. |
| `GET /approvals?runId=&status=pending` | Find approvals the run is waiting on. |
| `POST /approvals/{id}/decision` | The harness approves or rejects, acting as the human. |

For the product screens, in addition:

| Endpoint | Screen |
| --- | --- |
| `GET /requests`, `GET /requests/{id}`, `POST /requests/{id}/process` | Request Inbox |
| `GET /runs?requestId=&conversationId=` | Inbox, Chat, Approvals |
| `GET /approvals` | Approval Center |
| `GET /conversations`, `POST /conversations`, `GET /conversations/{id}/messages`, `POST /conversations/{id}/messages` | Secretary Chat |

State transitions the UI relies on:

- Request: `received -> processing -> awaiting_approval -> processing -> completed | awaiting_reply | escalated | failed`, or `-> declined` after a rejection.
- Run: `queued -> running -> (awaiting_approval -> running)* -> completed | failed | cancelled`.
- Action: writes are registered as `awaiting_approval` when the approval is created, then `running -> succeeded | failed`, or `rejected` / `skipped`.
- Approval: `pending -> approved | rejected | expired`; execution `not_started -> executing -> executed | failed`.

## 4. Assumptions Role 1 must confirm

Each of these is built into the frontend or the scorer. Where the real backend differs, say so and the adjustment goes where the last column says.

| # | Assumption | If it is wrong, change |
| --- | --- | --- |
| A1 | Every email send and every calendar create, update or cancel needs a human approval. There is no auto-send tier. | `expected.approvals` in the fixtures; the approval-gate check in `scoring.ts` |
| A2 | One approval can cover several changes, executed in order (event first, then the confirmation). If a later step fails, the approval's execution is `failed`. | `ApprovalCard`, mock scripts |
| A3 | Runs are asynchronous and can be polled with `GET /runs/{id}`. No streaming is required. | `HttpExecutiveDesk.subscribe` |
| A4 | The backend's tool calls can be mapped one-to-one onto the ten canonical tool names. | `toolAliases` in `httpAdapter.ts` |
| A5 | The backend has (or can get) a sandbox mode: injected calendar, injected clock, injected tool faults, no real Gmail or Calendar calls, `simulated: true` on side effects. | Without it the cases cannot be scored safely. EVAL-017 and EVAL-018 need fault injection and can be skipped with `--skip` until it exists. |
| A6 | Token usage is available per run: model name, uncached input, output and cached input tokens, summed over all model calls. Cost is optional. | `TokenUsage`, `pricing.ts` |
| A7 | Auth is a bearer token. | `getToken` in `src/api/index.ts` |
| A8 | All timestamps carry an offset, and the principal's IANA time zone is known. | `lib/time.ts` treats offset-less timestamps as invalid |
| A9 | The classification, outcome and flag vocabularies in `types.ts` can be produced by the agent (or mapped from Scriba's existing labels). | `normalizeRun` in `httpAdapter.ts` |
| A10 | Triage yields the `ExtractedMeetingDetails` shape, with requested windows already converted to instants. | Inbox detail view |
| A11 | When a reply offers times, `email.send.proposedSlots` lists them as instants. | `proposed_slots` check; cases 003, 005, 009 require it |
| A12 | Chat: one run per user message, with the reply in `AgentRun.assistantMessage` and in the message list. | `ChatPage` |
| A13 | The backend decides which incoming emails become requests and exposes them at `/requests`. The frontend does not read Gmail. | nothing on this side |
| A14 | The backend records human interventions on the run and distinguishes a plain approval from an edit, a retry or a takeover. | rescue counting in `runner.ts` |
| A15 | Deciding an approval twice returns 409. | error display only |
| A16 | One principal, one mailbox, one calendar. | `ApiInfo.principal` |

## 5. Open questions

1. Can a human edit a proposed email before approving it? The contract has no edit endpoint and the Approval Center has no edit control. If Scriba already supports draft editing, add `PATCH /approvals/{id}` and count an edit as an `edit` intervention.
2. Do approvals expire? The `expired` status is defined, but nothing sets it.
3. Does Scriba already distinguish "the agent asked a clarifying question" from "the agent proposed alternatives"? The cases treat them as two outcomes.
4. What does the agent do when an attendee's calendar is not visible? The cases only use the principal's calendar.
5. Which model, and does the backend know its own per-token price? That decides whether cost comes from the backend or from a price table we maintain.
6. How should a request the agent declines to handle be shown: `escalated` (as assumed here) or something else?
7. Is there an existing audit log the `audit.record` tool should map to?

## 6. Boundaries kept

- The original Scriba repository was read only for its visual theme (colours, font, radii). Nothing in it was modified, and no secrets, production data or deployment configuration were copied.
- This workspace contains no backend integration and no agent logic. The mock adapter replays hand-written scripts.
- The mock adapter has no network code. A test stubs `fetch` and asserts it is never called.
- All fixture people, companies and addresses are invented, on the reserved `.example` domain.

## 7. Checklist for the first real run

- [ ] `POST /evaluation/runs` with EVAL-001 returns a run that reaches `awaiting_approval`.
- [ ] The pending approval lists a `calendar_create` and an `email` change, and the run's side-effect actions carry its id.
- [ ] After the harness approves, the run reaches `completed` with outcome `scheduled`, and the side-effect actions have `simulated: true`.
- [ ] `npm run eval -- --base-url ... --only EVAL-001` prints PASS, or a table of expected versus actual that explains why not.
- [ ] No real email was sent and no real calendar changed during the run. Check the real mailbox and calendar by hand once.
- [ ] Run all twenty, then `--snapshot friday`.
