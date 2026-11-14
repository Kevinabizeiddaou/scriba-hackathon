# Agent 1 status: backend, orchestration, safety

> **Overlay 0.4 (later on 14 November).** This report describes 0.3. What 0.4
> added (instructions in chat, finishing existing tasks, repeated requests,
> memory read from records, follow-ups as records, unplaced mail handed over)
> is in the contract's section 12; the measurement and the remaining limits
> are in [EVAL_COMPARISON_0_4.md](EVAL_COMPARISON_0_4.md); every frontend
> change is in [AGENT2_INTEGRATION_0_4.md](AGENT2_INTEGRATION_0_4.md).
> With a real model in the sandbox: Agent 2's visible suite 18 of 20 and
> hold-out 18 of 20 (11 and 10 at `8cff1f4`), no unsafe run. Backend tests:
> 739 passed.

Written 14 November 2026 on branch `agent1/autonomous-engine`, which contains
`main` at `2d70a29` (pull requests 1 to 6 merged). For Agent 2 and the project
lead. The contract is [../BACKEND_CONTRACT.md](../BACKEND_CONTRACT.md),
sections 6 to 11; this report says what stands behind it.

**Update, later on 14 November:** a real model (`gpt-6-luna`) has now been run
through the sandbox. Its results are in [EVAL_CONFIGURED_MODEL.md](EVAL_CONFIGURED_MODEL.md)
and summarised in section 4.3; the rest of this report predates that run.

**Update, branch `agent1/engine-reconciliation` (overlay 0.3.1):** the typed
client now declares everything the backend sends and a test keeps it so;
every action has an explicit lifecycle; twelve defects found by the quality
lab, the office simulation and new scenarios are fixed; the backend scenarios
went from 24 to 38. That work is described in
[ENGINE_RECONCILIATION.md](ENGINE_RECONCILIATION.md) and
[AGENT2_INTEGRATION_HANDOFF.md](AGENT2_INTEGRATION_HANDOFF.md). The rest of
this report describes the base it was cut from.

No real mailbox or
calendar was used. No external write was made or is possible. Nothing in
ScribaAssist/Scriba was changed: it was read from a clone with push disabled.

## 1. Where things are

| | |
| --- | --- |
| `main` | `2d70a29` |
| This branch | `agent1/autonomous-engine`, pushed. **Not merged.** No pull request is open: this environment has no GitHub sign-in. The text to paste is [PR_AGENT1_AUTONOMOUS_ENGINE.md](PR_AGENT1_AUTONOMOUS_ENGINE.md) |
| Overlay version | 0.3.0 |

**Do not merge this branch on its own.** Three of Agent 2's pinned
compatibility tests fail against it, by design (section 5).

## 2. What works now

"Scriba app" means Scriba's real application, routes, card validation,
approve, retry and cancel paths at `3ae3a2a`, with chat storage in memory and
providers replaced by an isolated world. "HTTP" means seen through real
requests against `backend/dev/seeded_desk_server.py --demo`.

| Capability | Where | Evidence |
| --- | --- | --- |
| Mail becomes a run with no client open | `worker.py` | Unit, Scriba app, HTTP |
| One run per message across polls, threads and restarts | `claims.py` | Unit (3 stores, 12-thread race, restart on a file store) |
| Lifecycle with separate evidence for plan, decisions, reads, proposals, approvals, executions, verifications | `lifecycle.py`, `workflow.py` | Unit, Scriba app |
| **A typed plan per run**: intents with confidence and evidence, facts, assumptions, missing details, steps with dependencies | `plans.py` | Unit |
| **Dependent steps**: a step is proposed only after what it depends on took effect, and is blocked if that failed or was rejected | `plans.step_states`, `workflow.advance` | Unit, Scriba app |
| **Several requests in one message**, each planned by the same checked code | `understanding.py`, `workflow._plan_from_intents` | Scripted model only |
| Booking, then confirmation only after the event exists; both zones stated when they differ | `workflow.py` | Scriba app, HTTP |
| Reschedule moves the original event; cancellation cancels the one the sender is on | `workflow._plan_change` + Scriba's `chat_calendar_edit` | Scriba app |
| A repeated request for a booked meeting is recognised; a time outside working hours is flagged | `workflow.py` | Unit, scenarios |
| Replies offering only verified free times; tasks with written deadlines; follow-ups | `workflow.py` | Unit, Scriba app, HTTP |
| Real mail and calendar writes held in the server | `execution.py`, `readiness.py` | Scriba app |
| Sandbox execution with a tripwire on real provider clients | `sandbox.py`, `execution.py` | Scriba app |
| **An approval is bound to the proposed action**; a card changed behind it is held | `execution._binding_changed` | Scriba app |
| **A retry runs what the person approved**, their edit included | `execution.py` | Scriba app |
| Unknown outcome stays unknown; a retry reads back first | `execution._reconcile` | Scriba app |
| **Actions left in flight by a stopped process are settled by a read-back, never re-run** | `execution.recover_stale`, worker | Scriba app |
| **A failed verification escalates**; a run held by a guard is `HELD` | `lifecycle.derive` | Unit, Scriba app |
| `/desk/eval/v1` | `eval_api.py` | Scriba app; Agent 2's runner over HTTP |
| Per-run model usage and cost from Scriba's telemetry and price table | `gateway.model_usage` | Scripted only |
| Bounded model step (reply, task, reminder) | `agent.py` | Scripted only, off by default |

## 3. What is missing or unproven

1. **One real model, one run per case.** `gpt-6-luna` was run through the
   sandbox (section 4.3). In every automated test `DESK_UNDERSTANDING=model`,
   `DESK_AGENT=on` and Scriba's time extraction are still scripted.
2. **Durable claims are not proven on Postgres.** The receipt-ledger adapter
   is tested against a stand-in with the ledger's outcomes.
3. **The worker reads the newest inbox page**, not Scriba's trigger cursor.
4. **Chat-started work is not driven by the Desk** (3 of the harness's 20 cases).
5. **Rule-based reading is brittle to wording** (section 4).
6. Not built: closing an existing task from news that work is done; a reply
   that needs facts from the thread without a model.
7. On a real backend the Desk reads the subject and the snippet, not the body.
8. Recovery on a real provider cannot read back: the card becomes
   `outcome_unknown` and waits for the person.
9. **Live providers:** nothing was read from or written to one.

## 4. Evaluation: three measurements, never mixed

### 4.1 The backend's own scenarios

24 scenarios (`backend/eval/scenarios.py`): reworded requests, ambiguity,
several intents, contradictory times, a sender on no meeting, time zones,
conflicts, a duplicate, provider failure, partial execution, an injected
recipient, text addressed to the assistant, an unreadable calendar. Full
table: [EVAL_BACKEND_SCENARIOS.md](EVAL_BACKEND_SCENARIOS.md).

| | Rules only | Scripted model | Configured model |
| --- | --- | --- | --- |
| Intent correct | 21 of 24 | 23 of 24 | not run |
| Plan and tools correct | 21 of 24 | 24 of 24 | not run |
| Outcome correct | 21 of 24 | 24 of 24 | not run |
| Everything correct | 20 of 24 | 23 of 24 | not run |
| Unsafe runs | 0 | 0 | not run |
| Approval compliant | 24 of 24 | 24 of 24 | not run |
| Executed actions verified | 24 of 24 | 24 of 24 | not run |
| Median latency | 21 ms | 33 ms | not run |
| Cost per run | not measurable | not measurable | not run |

- **Rules only**: the Desk with no model.
- **Scripted model**: the understanding step is handed the answer a careful
  reader would give. It measures everything BEHIND the model. It is an upper
  bound for this pipeline, not a model's score.
- **Configured model**: measured later with `gpt-6-luna`: 22 of 24 fully
  correct, 0 unsafe. See section 4.3; the column above is as first written.
- Latency is the pipeline's own time in a sandbox with no model call.
- I wrote these scenarios and the rules; the rules-only figure is therefore
  optimistic. The held-out figure below is the honest one for the rules.
- The one scenario not fully correct with a scripted model (S20) is my
  expectation list not allowing the category the run reported; I left the
  expectation as written.

### 4.2 The harness's twenty cases (Agent 2's runner, rules only, labelled simulated)

| Suite | First run | After fixing general causes found in that run |
| --- | --- | --- |
| `desk-v1` | 4 as expected | 10 as expected, 7 not, 3 errors (the chat cases) |
| `desk-holdout-v1` (reworded; I have not read its texts) | not run | **5 as expected**, 12 not, 3 errors |

Re-run on the final code of this branch: unchanged. The gap between 10 and 5 is
the finding: the rules recognise the wording they were improved on.

### 4.3 With a real model (`gpt-6-luna`, one run per case, sandbox only)

Full account: [EVAL_CONFIGURED_MODEL.md](EVAL_CONFIGURED_MODEL.md).

| | Rules only | Scripted model | Configured model |
| --- | --- | --- | --- |
| Backend scenarios, everything correct | 20 of 24 | 23 of 24 | 22 of 24 |
| Backend scenarios, unsafe runs | 0 | 0 | 0 |
| `desk-v1` (Agent 2's runner) | 10 of 20 | n/a | 11 of 20 |
| `desk-holdout-v1` (reworded) | 5 of 20 | n/a | 10 of 20 |

Figures are the run on the final code. The model closes the gap on unseen
wording and barely raises the ceiling: the remaining failures are things the
engine does not do (chat-started cases, replies that need thread facts,
completing a task, a second request beside a booking, recognising a duplicate).
Six defects the real model exposed are fixed with tests, among them a reworded
prompt injection that was not flagged and a meeting booked at a time whose zone
("IST") was ambiguous; that second one was the only unsafe run of the day.

## 5. Exact frontend integration requirements

This branch does not edit frontend files beyond `frontend/src/api/desk.ts`,
which was widened before the rule "Agent 2 owns all frontend files" was set;
the changes made after it are listed here for Agent 2 to apply instead.

**Three pinned tests fail on this branch** (`frontend/src/live/deskRuns.test.ts`),
each because the backend now does what was asked:

| Pinned test | Why it fails | What it needs |
| --- | --- | --- |
| "reads only list fields the backend emits" | `GET /desk/runs` rows carry `state` | Drop the per-run reads; use `DeskRunRow` |
| "agrees ... on what counts as done" | `_DONE` is `("executed",)`; a partly executed action is `partial` and not `verified` | Update the pin |
| "knows every reason a meeting request can be held for" | New reasons | A label for each (below) |

**Types to change in `frontend/src/api/desk.ts`** (the file currently has the
first-draft names):

```ts
export type DeskLifecycleStage =
  | 'RECEIVED' | 'UNDERSTANDING' | 'INVESTIGATING' | 'PLANNING'
  | 'AWAITING_APPROVAL' | 'EXECUTING' | 'VERIFYING' | 'COMPLETED'
  | 'WAITING_FOR_RESPONSE' | 'NEEDS_CLARIFICATION' | 'HELD' | 'ESCALATED'
  | 'PARTIALLY_COMPLETED' | 'FAILED' | 'CANCELLED'
// replaces CLASSIFIED, CONTEXT_GATHERING, AWAITING_REPLY; HELD is new

export type DeskEvidenceKind = /* existing */ | 'plan'

export type DeskHeldReasonV3 = /* existing */ | 'intent_unclear'
export type DeskGateHoldCode = /* existing */ | 'proposal_changed'

export interface DeskPlanStep {
  id: string; tool: string; purpose: DeskActionPurpose | 'reply' | null
  dependsOn: string[]; deferred: boolean; requiresApproval: true; external: boolean
  expected: string; onFailure: string
  /** A Scriba card status once proposed; else 'ready' | 'waiting' | 'blocked'. */
  state: string; toolCallId: number | null
}
export interface DeskPlan {
  version: 1
  message: { provider: MailProvider; provider_account_id: string | null; email_id: string; thread_id: string | null }
  planner: 'rules' | 'rules+model' | 'model+rules' | 'rules+agent'
  intents: Array<{ type: string; confidence: number | null; evidence: string[]; missing: string[]; source: 'rules' | 'model' }>
  unsupported: Array<{ type: string; why: string }>
  facts: string[]; assumptions: string[]; missing: string[]; tools: string[]
  steps: DeskPlanStep[]; approvals: number; escalation: string[]
}
// DeskRun gains:      plan?: DeskPlan | null
// DeskRun.flags gains 'outside_working_hours'
// DeskAction gains:   stepId?: string | null; held?: boolean; attempts?: number
// DeskRunHeld gains:  missing?: string[]
// DeskWorkerStatus gains: recovered?: number
```

**Labels needed** for `held.reason`: `event_not_found`, `event_ambiguous`
(`held.candidates[]`), `not_organizer`, `calendar_lookup_failed`,
`already_scheduled`, `task_exists`, `untrusted_instructions`,
`intent_unclear` (`held.missing[]`). `change_request` is no longer sent.
For `output.error_code`: `external_writes_disabled`, `proposal_changed`,
`outcome_unknown`, `sandbox_world_gone`, `reply_target_missing`.

**Behaviour that changed under existing screens:**

- A busy or unread meeting time now produces a `send_email` card
  (`purpose: "offer_times"` or `"clarify"`) beside `held`; `next` has no
  `draft_reply` for such a run.
- The confirmation is proposed by the backend as soon as its prerequisite
  executes. `next: ["advance"]` is rare; calling advance stays safe.
- With `health.executionMode === "sandbox"` an approve of a mail or calendar
  card executes, simulated. The rule "mail and calendar approvals stay
  disabled unless `externalWrites.enabled`" should also allow that case and
  show `simulated`.
- `lifecycle.stage === "HELD"` means no card of the run can be approved as it
  stands; show the card's hold explanation, not an Approve button.
- A retry after an edited approve failed re-applies the person's edit.

Answers to `LIVE_INTEGRATION.md` 9.1: `draft_email_reply` stores a draft in
Scriba (it does not send) and is held like a send while writes are off.
Retry executes at once in Scriba; for an unknown outcome the Desk reads back
or asks first.

For the lead: contract 1.1.0 says tasks and reminders need no approval; the
product asks for one. Evaluation worlds run them automatically and say so in
`meta.desk.internalWrites`. Which is the product's rule?

## 6. Tests and results (14 November 2026, Windows 11, Python 3.13, Node 22)

| What | Result |
| --- | --- |
| Backend, with integration on the real Scriba app at `3ae3a2a` | 590 passed, 24 skipped (the configured-model scenarios). `main` had 196 |
| Backend unit and route tests | 402 passed |
| Outbound-connection guard | On for every backend test |
| Mutation check on the safety guards | 38 planted in two passes: 36 caught at once, 2 survived the first pass and now have tests ([MUTATION_CHECK.md](MUTATION_CHECK.md)) |
| Every `/desk` route against the contract | 22 implemented, 22 documented, none missing either way |
| API smoke on the seeded demo backend (`--desk-demo`) | 33 of 33 on the final code, with zero model requests logged |
| Frontend type check and build | Clean; passes |
| Frontend tests | 380 passed, 3 failed: the pinned tests of section 5 |
| Secret scan | No secret found in tracked files |

Not run: anything with a live mailbox, a live calendar, or a Postgres
database. A real model was run in the sandbox only (section 4.3).

## 7. One incident, fixed

Scriba's test harness sets a placeholder model key. My first demo server
therefore attempted 8 model calls to the provider. All were refused (401);
the bodies were synthetic demo emails, with no user data. Since then the Desk
makes no model call unless a model is really configured (`DESK_MODEL`, and a
placeholder key never counts), the dev backend defaults to `DESK_MODEL=off`,
and the test suite fails any test that connects to another host.

## 8. Remaining security risks

- **Scriba's own retry ignores an edit made at approval.** The Desk's gate now
  re-applies it for Desk runs; plain Scriba chat cards outside the Desk scope
  keep Scriba's behaviour.
- **The approval binding covers cards the Desk proposed.** A card proposed in
  chat has no recorded digest and is not bound.
- **Injection detection is pattern-based.** It stops the wording it knows.
  The structural defences do not depend on it: a model cannot choose a
  recipient or approve, a recipient that did not come from the user or the
  From header is held, and an intent must quote the message.
- **A model's quoted evidence can be real and still misread.** Every action
  still passes the availability checks and a human approval.
- **Sandbox isolation is enforced at named provider entry points** and at the
  executor. A provider client added to Scriba later is not covered until it
  is added to the tripwire list.
- **External writes** stay off: the list of verified Scriba revisions is
  empty, in code.

## 9. Blocking issues

- No model credential, so no real-agent result exists.
- This branch and the frontend must land together.

## 10. Three highest-impact improvements

1. **Run a real model through the sandbox**: `DESK_MODEL=on
   DESK_UNDERSTANDING=model DESK_AGENT=on` on the dev backend, then Agent 2's
   runner on both suites and the 24 scenarios. It fills the third column.
2. **Move the worker onto Scriba's trigger cursor and prove the receipt
   ledger on a throwaway Postgres.**
3. **Drive chat-started work through the Desk**, which unblocks the three
   conversation cases.
