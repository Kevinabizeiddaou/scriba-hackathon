# Agent 2 frontend handoff

Written 14 November 2026 for Agent 1 and the project lead. It replaces the earlier version of this
file; the polish pass that version described is merged (section 9).

Nothing in this document is a result about the product's agent. No real model, mailbox or calendar
was used. Everything seen in a browser ran against an isolated sandbox world.

## 1. Where the work is

| | |
| --- | --- |
| Branch | `agent2/frontend-excellence` |
| Started from | `b1c8543` |
| Pull request | https://github.com/Kevinabizeiddaou/scriba-hackathon/pull/7 "Frontend Excellence — Executive Secretary Experience", base `main`. Open, not merged |
| Backend it was built against | `agent1/autonomous-engine` at `e86f449` (Desk overlay 0.3.0), read-only, run locally with `python backend/dev/seeded_desk_server.py --demo` |

Two things happened outside this work that a reader should know:

- **Pull request 6 was merged into `main`** (`2d70a29`) while this was in progress. It carried the
  three polish commits up to `b1c8543`. Agent 2 did not merge it. The new commits are on the same
  branch, on top of `b1c8543`, and need a new pull request.
- **`frontend/src/api/desk.ts` on this branch is Agent 1's file**, taken byte for byte from
  `agent1/autonomous-engine` at `e86f449` (`git checkout origin/agent1/autonomous-engine --
  frontend/src/api/desk.ts`). It is not edited. It was taken because the screens need the 0.3 types
  and the `fetchDeskWorker`, `fetchDeskFollowUps` and `closeDeskFollowUp` functions, and the rule is
  not to write a second client. When Agent 1's branch merges, the file is identical and there is
  nothing to resolve; if Agent 1 changes it first, theirs wins.

No file under `backend/` and not `docs/BACKEND_CONTRACT.md` is changed.

- **Agent 1's branch moved during this work**, from `e86f449` to `0282558`, and the contract on it
  changed. Everything in this document was built and verified against `e86f449`. What changed, and
  what the frontend does about it, is section 7a. **The backend at `0282558` has not been run
  against this frontend.**

## 2. What was built

Everything below reads overlay 0.3 when the backend has it and falls back to the 0.2 behaviour when
it does not. Nothing is shown that the server did not report.

**Run lifecycle** (`frontend/src/live/runLifecycle.ts`). The fourteen stages of contract section 6,
each with the name shown to the user, who has the next move, and the list of the work queue it
belongs to:

| Server stage | Shown as | Queue list |
| --- | --- | --- |
| `RECEIVED` | Incoming | In progress |
| `CLASSIFIED` | Understanding | In progress |
| `CONTEXT_GATHERING` | Investigating | In progress |
| `PLANNING` | Planning | In progress |
| `AWAITING_APPROVAL` | Awaiting approval | Awaiting your approval, or Needs your input when every card is held |
| `EXECUTING` | Executing | In progress |
| `VERIFYING` | Verifying | In progress; Did not finish when `outcomeUnknown` |
| `COMPLETED` | Completed | Completed; No action needed when nothing was proposed |
| `AWAITING_REPLY` | Awaiting reply | Awaiting a reply (new list) |
| `NEEDS_CLARIFICATION` | Needs clarification | Needs your input |
| `ESCALATED` | Escalated to you | Needs your input |
| `PARTIALLY_COMPLETED` | Partially completed | Did not finish |
| `FAILED` | Failed | Did not finish |
| `CANCELLED` | Cancelled | Cancelled |

Two more are understood from the revised contract (section 7a): the three renamed stages, as
aliases, and `HELD`, shown as "Held" under Needs your input.

A stage this frontend does not know is shown as "Stage not recognised" with its raw value, sorted
under "State not recognised", and never treated as finished.

**Reusable components** (`frontend/src/live/RunParts.tsx`, `frontend/src/components/EvaluationResult.tsx`):

| Component | Shows |
| --- | --- |
| `RunStatus` | The stage a run rests in |
| `RunProgress` | The path of a run with the time the server recorded for each stage. A stage passed without a recorded event is drawn as "not recorded", not as done |
| `RunTimeline` | The server's own events (`timeline[]`): time, kind, summary, and a few fields of `data`. A failed read is marked |
| `ExecutionStep` | One action's record: why, when proposed, each decision (including an approval the gate held), the execution with duration and error, and the verification |
| `VerificationEvidence` | Verified with its method, not verified, or outcome unknown. Never green without `verified: true` |
| `FollowUpItem` | One awaited reply with its state, dates and run |
| `AgentActivity` | The background worker's status from `GET /desk/worker` |
| `SandboxTag` | Marks anything that ran in an isolated provider world |
| `EvaluationResultPanel` | One evaluation report under the name of what produced it |

The approval summary is the existing action card (`ToolCallCard`); it was extended, not duplicated.

**Screens.**

- **Work queue**: each run shows its stage and a compact progress rail; rows beyond the detail limit
  show the stage from the list row. The Intake panel shows the worker's status when the backend
  reports one, and the old "no background worker" sentence when it does not. When the worker
  reports a new pass the run list is read again. The timer option is hidden while the worker runs.
- **Run detail**: "Where this run stands" with the rail, the stage's meaning, the reason and the
  compensation message; the server's record of the run; each action's record under its card; cards
  with one `idempotencyKey` shown as one effect with a count; follow-ups of the run with "Stop
  waiting"; held reasons added in 0.3, with the target meeting and the candidates; who started the
  run; model use (null is shown as "no model call was recorded", not as zero); a warning when
  `flags` has `prompt_injection_suspected`.
- **Overview**: the worker's status, how many picked-up requests sit in each list, and "Replies
  awaited" from `GET /desk/follow-ups`. A finished run and its own action are listed once.
- **Approval center and every action card**: the execution gate. With `executionMode: "sandbox"` a
  mail or calendar action can be approved; the button reads "Approve in sandbox" and a note says
  nothing real is sent. With `held`, or on a backend that does not say, approval stays off as
  before. The notice lists the readiness checks of `externalWrites.checks`. Three new hold codes are
  explained: `external_writes_disabled`, `outcome_unknown`, `sandbox_world_gone`.
- **Follow-up workspace** (Tasks and follow-ups, third tab): the live list, grouped overdue,
  waiting, answered, closed, with counts and "Read the mailboxes again". An overdue reminder is
  described as proposed, never as sent.
- **Evaluation**: three kinds kept apart: mock, scripted-model, real-model. A report from a backend
  that ran with no model can be imported; it gets its own panel and never reaches the headline
  numbers or a snapshot. A mock report is still refused.

**Not changed this round: secretary chat.** The brief asked for chat to show what the secretary
understood, plans and has done. The backend's chat is unchanged and its evaluation routes say
`capabilities.chat: false`, so no new chat workflow is claimed. The earlier labels and the
several-actions summary stand.

## 3. Files changed since `b1c8543`

New: `frontend/src/live/runLifecycle.ts`, `RunParts.tsx`, `LiveFollowUps.tsx`,
`runLifecycle.test.tsx`; `frontend/src/components/EvaluationResult.tsx`;
`frontend/src/evaluation/provenance.ts`; `docs/frontend/evaluation/` (one report and a note);
`docs/frontend/screenshots/overlay-0.3-sandbox/` (12 images and a note).

Changed: `frontend/src/live/deskRuns.ts`, `LiveRunDetail.tsx`, `LiveWorkQueuePage.tsx`,
`LiveOverviewPage.tsx`, `LiveWorkPages.tsx`, `ToolCallCard.tsx`, `deskHolds.ts`, `writePolicy.ts`,
`liveLogic.test.ts`; `frontend/src/pages/TasksPage.tsx`, `EvaluationPage.tsx`;
`frontend/src/components/AppShell.tsx`; `frontend/src/evaluation/session.ts`;
`frontend/src/lib/featureStatus.ts` and its test; `frontend/src/App.test.tsx`;
`docs/frontend/FEATURE_STATUS.md`; this file.

Taken unchanged from Agent 1: `frontend/src/api/desk.ts`.

## 4. Test results

Run on this branch, 14 November 2026.

| What | Result |
| --- | --- |
| Frontend tests | 427 passed in 22 files (at `b1c8543`: 383 in 21) |
| Type check | Clean |
| Production build | Clean; largest script 277 kB, no chunk over 500 kB |
| Harness self-test | Passed |
| Mutation check on the new tests | 19 planted defects, 19 caught |
| Browser, live mode on overlay 0.3 in the sandbox, 1440 / 768 / 375 px | 13 screens at each width (39 page loads): no horizontal overflow, no failed request, no console error |
| Approvals through the screens, in the sandbox | Three approved: a booking (the run then proposed its confirmation), a reply offering times (executed, verified by read-back, follow-up opened, stage `AWAITING_REPLY`), a task (stage `COMPLETED`). No request failed |
| 20-case suite on `/desk/eval/v1` | Ran. See section 6 |

The new tests cover: every lifecycle stage; partial completion; failed execution; approval required
and an approval the gate held; verification pending, verified with its method, and unknown outcome;
an unknown stage and an unknown follow-up state; two cards with one identity; the four follow-up
states; list rows of 0.3; the worker's statuses; the execution gate in sandbox, held and unreported
modes; report provenance and the import rules.

Not seen in a browser, because the demo world did not produce them in this session: a partly
completed run, a failed execution, an unknown outcome, an overdue or answered follow-up, an
ambiguous change request. They are covered by tests on the shapes in `desk.ts`.

One process fault to record: commit `819f906` was made while one new test was failing, because the
check before it was piped and did not stop the commit. The next commit fixes the test. Every number
above is from runs whose exit code was read directly.

## 5. Compatibility with overlay 0.3: what was checked

| Area | Finding |
| --- | --- |
| Run states | `state` is unchanged. A partly executed action now makes the run `partial`, which removes the old mismatch where such a run read as `completed`. The frontend's fallback for that case is kept for overlay 0.2 |
| Run ids | Integers, not consecutive (11, 22, 32, 69, 84, 101 in the demo). The frontend only requires an integer |
| Tool-call ids | `actions[].toolCallId` is the chat tool-call id: the approve path on the action is `/chat/tool-calls/{id}/approve` and approving through it worked. This answers question 1 of the previous handoff, and the overview now drops an action when its run is listed |
| Approval states | A held approval comes back `needs_info` with `external_writes_disabled`, and the decision is recorded with `result: "held"`. Both are shown |
| Partial execution | `PARTIALLY_COMPLETED` with `compensation`. Shown with the message; nothing is offered that would undo an action |
| Failed execution | A timeout is `failed` with `outcomeUnknown`, stage `VERIFYING`. Shown as "outcome unknown", sorted under "Did not finish", with the instruction to look first |
| Follow-up states | `waiting`, `overdue`, `satisfied`, `closed`. All four have words; any other value is shown as unrecognised |
| Evaluation endpoints | `/desk/eval/v1` answered the runner's five calls with contract 1.1.0. `meta.agent` is `scripted`, so the report is simulated, as it should be |
| Error responses | 401, 403, 404 and the gate's `needs_info` behave as the contract says. See discrepancy 6 for 409 |
| Retry | In a sandbox a retry after an unknown outcome reads the world back. Not exercised in a browser. See question 3 |

## 6. Evaluation: the first run against the sandbox routes

`npm run eval -- --scriba-url http://localhost:8788 --signin --suite desk` against overlay 0.3.0
with no model (`meta.desk.planner: "rules"`). The report is
`docs/frontend/evaluation/rules-only-sandbox-overlay-0.3.0.simulated.json`.

| | |
| --- | --- |
| Executed | 20 of 20 |
| Passed | 10 |
| Failed | 7 |
| Could not be scored | 3, all `conversation_input_unsupported` (cases that start from a chat turn) |
| Safety violations | 0 |
| Mandatory approvals | 12; no rescue, no unexpected approval request |
| Latency, tokens, cost | Not reported: no model call |

This is the Desk's rules running real code in a sandbox. It is **not** an agent result and is
labelled simulated everywhere. By area: inbox 1 of 3, email 1 of 3, scheduling 4 of 5, tasks and
reminders 1 of 3, follow-ups 1 of 2, multi-step 0 of 2, security and failure 2 of 2.

The seven failures, for Agent 1:

| Case | Failed checks |
| --- | --- |
| EVAL-015 The same request is sent again | `outcome` |
| EVAL-022 An urgent decision request is flagged urgent and turned into a task | `classification`, `priority`, `outcome`, `tool:0`, `state:0` |
| EVAL-023 A reply that depends on what was agreed earlier in the thread | `outcome`, `tool:1`, `approvals_expected`, `email:to`, `email:must:0` |
| EVAL-024 The principal rejects a drafted reply: nothing is sent, the task stays | `outcome`, `approvals_expected` |
| EVAL-008 Time given in US Eastern time | `email:must:0` |
| EVAL-028 News that work is finished closes the existing task | `outcome`, `tool:0`, `state:0` (no `task.complete`) |
| EVAL-031 One email, three steps: book the meeting, confirm it, record the promised document | `tool:3`, `state:1` (the task for the promised document is not created) |

## 7. Discrepancies between the contract, the typed client and what the backend sent

None of these blocks the screens; each is handled defensively. They are listed so the types and the
contract can be made to agree.

1. **`DeskFollowUp` has no `toolCallId`**, but follow-ups carry one (`"toolCallId": 116`). It would
   let a follow-up link to the card that opened it.
2. **`DeskRun.email` has no `received_at`**, but runs carry it.
3. **Evidence objects carry fields the types omit**: `verification`, `execution` and `decisions[]`
   each include `toolCallId` and `tool`; `execution` includes `assistantActionId`; `verification`
   includes `simulated`.
4. **`DeskRunHeld.reason` is declared with the five 0.2 reasons only**, while 0.3 sends seven more.
   The comment says the type stays narrow until the screens have a label for each. They now do
   (`HELD_REASON` in `deskRuns.ts`), so the type can be widened to `DeskHeldReason`.
5. **`DeskRunHeld.slots` and `.calendars` are declared required.** The frontend no longer assumes
   they are present for the 0.3 reasons, which are not about finding a time. The contract does not
   say whether they are sent for those.
6. **`POST /desk/intake` can answer 409** when another worker is taking the same message in. The
   frontend shows it as a generic failure. It should say "already being picked up" and read the
   run list again; that needs the response body's shape, which the contract does not give.
7. **Stage events stop at `PLANNING`.** `timeline[]` has `kind: "stage"` events for the first four
   stages. For the later ones the rail takes the first `proposal`, `execution` and `verification`
   event as the time. If stage events will be written for those too, the rail will prefer them.
8. **`health.writes` and the sidebar.** On a backend older than 0.3 `executionMode` is absent and
   the frontend treats that as "approval of mail and calendar actions is off", as before.

## 7a. The contract changed while this was being built

`docs/BACKEND_CONTRACT.md` at `0282558` differs from the `e86f449` this frontend was built on. The
typed client `frontend/src/api/desk.ts` did not change between the two, so on Agent 1's own branch
the contract and the client now disagree.

| Change in the contract at `0282558` | In `desk.ts` | What this frontend does |
| --- | --- | --- |
| Stage `CLASSIFIED` is now `UNDERSTANDING`, `CONTEXT_GATHERING` is `INVESTIGATING`, `AWAITING_REPLY` is `WAITING_FOR_RESPONSE`. The contract says the first names "were never merged and are not sent" | Still the first names | Accepts both spellings and treats them as the same stage (`STAGE_ALIASES` in `runLifecycle.ts`), with tests. Without this, every such run would show as "Stage not recognised" |
| New stage `HELD`: every open card is held by a guard; `lifecycle.reason` is the first card's `errorCode` | Not declared | Shown as "Held", sorted under "Needs your input", with the reason. Tested on the shape the contract describes; not seen from a backend |
| `AWAITING_APPROVAL` now means at least one card can be approved | n/a | Already how the queue splits "Awaiting your approval" from "Needs your input" |
| `ESCALATED` also when an executed action's verification failed (`reason: "verification_failed"`) | n/a | Shown as escalated with the reason. No dedicated wording yet |
| New held reasons `intent_unclear`, `details_missing`, with `held.missing[]` | Not declared | Falls back to the server's `held.message`. No dedicated wording, and `missing[]` is not listed yet |
| New hold code `proposal_changed`: the stored action is no longer what was proposed | Not declared | Shown as an unknown reason code: the card offers no way to approve past it, which is what the contract asks. No dedicated wording yet |
| New `DeskRun.plan` (intents, facts, assumptions, missing, steps with dependencies) | Not declared | **Not shown.** This is the largest gap: the run detail should show the plan and it does not |
| New flag `outside_working_hours` | Not declared | Not shown as a flag; the card's `reason` carries the sentence |
| An approval is bound to what was proposed; an edit by the person is recorded; a retry runs the action as approved | n/a | Nothing sends edits, so nothing conflicts. `decisions[].edited` is displayed when present |
| Recovery after an interruption: `error_code: "interrupted"`, `output.recovered`, `worker.recovered` | Not declared | Not shown |

None of the last six rows is implemented against a guess. They wait for the typed client to
declare the shapes.

## 8. Exact questions for Agent 1

0. **Which stage names does the backend send today: the ones in `desk.ts` or the ones in the
   contract?** And will `desk.ts` be updated to the contract (stage names, `HELD`, `plan`,
   `proposal_changed`, `intent_unclear`, `details_missing`, `outside_working_hours`,
   `interrupted`)? The frontend's next step, showing the plan on the run detail, waits on that.

1. **Is `no_action_proposed` with stage `ESCALATED` the only way a "needs a reply" message appears
   when the model step is off?** The frontend offers "Write a reply draft" there, which posts
   `draftRequest` to Scriba and needs a model. On a backend with `model.configured: false` should
   that button be hidden?
2. **Which action is the reminder for an overdue follow-up?** The contract says one `send_email`
   with `purpose: "nudge"` is proposed. Is it always an action of the same run, and can the
   follow-up name its tool-call id, so the follow-up row can link straight to the card?
3. **Retry after an unknown outcome on a real provider.** The client exports
   `DESK_RETRY_AFTER_UNKNOWN` and describes it as an approve body. Does `POST
   /chat/tool-calls/{id}/retry` accept `payload_overrides`, or is it sent to `/approve`? The
   frontend sends nothing of the kind today; a real provider is unreachable, so nothing depends on
   it yet.
4. **May `GET /desk/runs` rows be trusted alone?** They now carry `state`, `lifecycle`, `next`,
   `held` and `actionCounts`. The queue still reads the twenty newest runs in full for the headline
   and the next step. If a row carried the action names (or a headline), those reads could go.
5. **Does `closeDeskFollowUp` ever send anything?** The screen says it does not. Confirm.
6. **Chat cases in evaluation.** EVAL-027, 029 and 032 start from a chat turn and come back
   `conversation_input_unsupported`. Is driving Scriba's chat agent from the sandbox routes planned,
   or should the report show those three as "not applicable to this backend" rather than as errors?
7. **Edited approvals.** `decisions[].edited` exists. Which input fields may a client change on
   approve, beyond `desk_confirmed_recipients` and `desk_availability_override`? Until that is
   stated the frontend offers no editing.

## 9. Backend capabilities: mapped, and still missing

Mapped and used: `GET /desk/health` readiness block, `GET /desk/runs` row fields,
`GET /desk/runs/{id}` lifecycle, timeline, evidence, follow-ups and usage, `GET /desk/worker`,
`GET /desk/follow-ups`, `POST .../follow-ups/{id}/close`, the execution gate through Scriba's
approve route, `/desk/eval/v1` through the existing runner.

Not used yet: `GET /desk/sandbox` and `POST /desk/sandbox/deliver` (a sandbox inspector and a "send
a test message" control would be useful in the demo; not built), `worker.runs` by stage (the
overview counts from the runs it read instead).

Still missing from the backend, or not ready:

- A model-driven run through the sandbox routes. Until then there is no real-model evaluation and
  every headline number stays empty.
- Chat-turn cases on the evaluation routes (question 6).
- Summaries and action items per message, work status per message, meeting preparation: unchanged
  from `docs/frontend/FEATURE_STATUS.md`.
- Real sending. `externalWrites.enabled` is false on every backend by construction; the frontend
  has no way around it and does not look for one.

## 10. What is mock and what is connected

Connected to a real backend (overlay 0.3, sandbox world): overview, work queue, run detail,
approvals including sandbox execution, follow-ups, worker status, inbox, calendar, find a time,
tasks, reminders, chat, activity, and the scripted-model evaluation run from the command line.

Mock only, labelled on screen: demo mode (`npm run dev:demo`); the evaluation screen's reference
scripts and self-test.

Simulated but real code: everything in a sandbox world. It is marked "Sandbox" on runs, actions and
approvals, and a sandbox result is never called a real success.

## 11. Next tasks for Agent 1

0. Bring `frontend/src/api/desk.ts` in line with the contract at `0282558` (section 7a), or say
   that Agent 2 should. Then Agent 2 shows `DeskRun.plan`, `HELD`, `proposal_changed` and the new
   held reasons with their own wording.
1. Answer questions 0 to 7.
2. Widen `DeskRunHeld.reason`, and add `toolCallId` to `DeskFollowUp` and `received_at` to
   `DeskRun.email` (discrepancies 1, 2, 4).
3. Say what a 409 from `POST /desk/intake` carries (discrepancy 6).
4. Look at the seven failed cases in section 6. EVAL-022 fails on classification and priority;
   EVAL-023, 028 and 031 are missing a tool call.
5. Run one case through `/desk/eval/v1` with a model configured, so `meta.agent` is `real` and the
   first real-model report exists.
6. When `agent1/autonomous-engine` is ready to merge, merge it before or together with this branch:
   this frontend runs on overlay 0.2 as well, but the new screens only show their content on 0.3.
