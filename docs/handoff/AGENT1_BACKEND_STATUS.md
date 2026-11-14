# Agent 1 status: backend, orchestration, safety

Written 14 November 2026 on branch `agent1/autonomous-engine`, which contains
`main` at `2d70a29` (pull requests 1 to 6 merged). For Agent 2 and the project
lead. The contract is [../BACKEND_CONTRACT.md](../BACKEND_CONTRACT.md),
sections 6 to 11; this report says what stands behind it.

**Nothing here is a result about a real agent.** No real model, mailbox or
calendar was used. No external write was made or is possible. Nothing in
ScribaAssist/Scriba was changed: it was read from a clone with push disabled.

## 1. Where things are

| | |
| --- | --- |
| `main` | `2d70a29` |
| This branch | `agent1/autonomous-engine`, pushed. **Not merged; no pull request opened** (this environment has no GitHub CLI). The description to paste is [PR_AGENT1_AUTONOMOUS_ENGINE.md](PR_AGENT1_AUTONOMOUS_ENGINE.md) |
| Merged earlier | PR 1 (`agent1/backend`), 2 (`agent1/chat-workflow`), 4 (`agent1/intake-loop`), 3 and 5 (Agent 2) |
| `agent1/next` | Named in the directive. It does not exist on the remote and no local copy was found, so there was nothing to preserve |
| Overlay version | 0.3.0 |

**Do not merge this branch on its own.** Three of Agent 2's pinned
compatibility tests fail against it, by design (section 5). It should land
together with Agent 2's mapping update.

## 2. What works now

"Scriba app" means: Scriba's real application, routes, card validation,
approve, retry and cancel paths at `3ae3a2a`, with chat storage in memory and
providers replaced by an isolated world. "HTTP" means: seen through real
requests against `backend/dev/seeded_desk_server.py --demo`.

| Capability | Where | Evidence |
| --- | --- | --- |
| Mail becomes a run with no client open | `worker.py` | Unit, Scriba app, HTTP |
| One run per message across polls, threads and restarts | `claims.py` | Unit (3 stores, 12-thread race, restart on a file store) |
| Run lifecycle, with separate evidence for decisions, reads, proposals, approvals, executions, verifications | `lifecycle.py`, `workflow.py` | Unit, Scriba app |
| Run list rows carry `state`, `lifecycle`, `next`, `held.reason`, `actionCounts` | `workflow.list_runs` | Unit, HTTP |
| Booking, then a confirmation only after the event exists | `workflow.py` | Scriba app, HTTP |
| Reschedule: the original event is moved, never a second one. Organizer and sender checked | `workflow._plan_change` + Scriba's `chat_calendar_edit` | Scriba app (Google and Outlook) |
| Cancellation of the one event the sender is on | same | Scriba app, HTTP |
| Reply offering only times verified free on every calendar | `workflow._offer` | Unit, Scriba app |
| Task with a written deadline; no second task for the same thing | `workflow._plan_task` | Unit, Scriba app |
| Follow-ups: waiting, satisfied by the awaited reply, overdue with a PROPOSED reminder, closed | `workflow._track_follow_ups` | Unit, HTTP |
| Real mail and calendar writes held in the server | `execution.py`, `readiness.py` | Scriba app |
| Approved actions executed against an isolated world; tripwire on real provider clients | `sandbox.py`, `execution.py` | Scriba app |
| Unknown outcome stays unknown; a retry reads back first and does not repeat | `execution._reconcile` | Scriba app |
| Failure between event and confirmation: partial, escalated, nothing undone | `lifecycle.derive` | Scriba app |
| Double and concurrent approvals book once | Scriba's claim, under the gate | Scriba app (6 threads) |
| `/desk/eval/v1` | `eval_api.py` | Scriba app; Agent 2's own runner over HTTP: 20 executed, 0 skipped, no contract violation |
| Per-run model usage and cost from Scriba's telemetry and price table | `gateway.model_usage` | Scripted only |
| Bounded model step | `agent.py` | Scripted only, off by default |

## 3. What is missing or unproven

1. **No real model has been run.** There is no model credential in this
   environment. Time extraction, a model-written reply and the bounded model
   step are scripted in every test. To run them: start the dev backend with
   `DESK_MODEL=on DESK_AGENT=on` and a real key; `meta.agent` then reports
   `real` and the runner's report is no longer labelled simulated.
2. **Durable claims are not proven on Postgres.** `ScribaReceiptClaims` calls
   Scriba's `claim_action_receipt` / `finish_action_receipt`; it is tested
   against a stand-in that returns the ledger's outcomes. The SQLite store is
   proven across a restart and a 12-thread race.
3. **The worker reads the newest inbox page.** It does not yet use Scriba's
   per-user trigger cursor (`db.list_trigger_candidates`), so a burst of more
   than one page between ticks can be missed until a later tick or a manual
   sweep. Its "not inbound" filter depends on labels a row carries.
4. **Chat-started work is not driven by the Desk.** `/desk/eval/v1` refuses
   `input.kind: "conversation"` (3 of the 20 cases).
5. **Not built:** closing an existing task from news that work is done
   (`task.complete`); a reply that needs facts from the thread without a
   model; a meeting plus a promised document without the model step.
6. **Message bodies.** On a real backend the Desk reads the subject and the
   snippet. A sandbox row carries the full body.
7. **Follow-ups and evidence are stored as messages on the run's Scriba
   conversation.** Listing follow-ups reads up to 50 runs.
8. **Live providers:** nothing was read from or written to one.

## 4. Evaluation, as it stands

Run with Agent 2's runner against the dev backend, rules only (no model), so
every number below is labelled **simulated** by the harness and says nothing
about the product's agent.

| Suite | First run | After fixing general causes found in that run |
| --- | --- | --- |
| `desk-v1` (20 cases) | 4 as expected | 10 as expected, 7 not, 3 errors (the chat cases) |
| `desk-holdout-v1` (the same cases reworded) | not run | **5 as expected**, 12 not, 3 errors |

The gap between 10 and 5 is the finding: the rule-based reading recognises
the wording it was improved on and does not generalise. I did not read the
held-out texts and did not tune on them. Closing the gap is a model's job,
not more patterns.

Causes fixed after the first run, each with its own tests in other wording
(`tests/test_reading.py`): a request to meet that never says "meeting"; a
cancellation stated as news; a time range; a time in a named zone; "move X
to Y" naming both times; a request repeated for a meeting already booked; a
decision needed by a time; more ways of addressing the assistant.

## 5. Contract changes Agent 2 needs to adopt

`frontend/src/api/desk.ts` is updated; every 0.3 field is optional, so the
frontend compiles unchanged (typecheck clean, build passes, 369 tests pass).
Three pinned tests in `frontend/src/live/deskRuns.test.ts` fail, each because
the backend now does what was asked:

| Pinned test | Why it fails now | What it needs |
| --- | --- | --- |
| "reads only list fields the backend emits" | `GET /desk/runs` rows now carry `state` | Drop the per-run detail reads; use `DeskRunRow` |
| "agrees ... on what counts as done" | `_DONE` is `("executed",)`; a partly executed action is `partial` and not `verified` | Update the pin; `groupOf` can trust `state` |
| "knows every reason a meeting request can be held for" | New reasons: `event_not_found`, `event_ambiguous`, `not_organizer`, `calendar_lookup_failed`, `already_scheduled`, `task_exists`, `untrusted_instructions`. `change_request` is no longer sent | A label per reason; then widen `DeskRunHeld.reason` to `DeskHeldReason` |

Also new for the screens: `DeskGateHoldCode` (`external_writes_disabled`,
`outcome_unknown`, `sandbox_world_gone`, `reply_target_missing`);
`health.externalWrites` with `reason` and `checks`; `health.executionMode`;
`lifecycle`, `timeline`, `followUps`, `usage` on a run; `fetchDeskWorker`,
`fetchDeskFollowUps`, `closeDeskFollowUp`, `fetchDeskSandbox`,
`deliverToDeskSandbox`.

Behaviour that changed under existing screens:

- A busy or unread meeting time now produces a `send_email` card
  (`purpose: "offer_times"` or `"clarify"`) beside `held`. `next` no longer
  contains `draft_reply` for such a run.
- The confirmation reply is proposed by the backend as soon as the event
  executes. `next: ["advance"]` is rarely seen; calling advance stays safe.
- With `executionMode: "sandbox"` an approve of a mail or calendar card
  executes, simulated. The frontend's rule "mail and calendar approvals stay
  disabled unless `externalWrites.enabled`" should also allow them when
  `executionMode === "sandbox"`, showing `simulated`.

Answers to the two open questions in `LIVE_INTEGRATION.md` 9.1:
`draft_email_reply` stores a draft in Scriba (it does not send), and the Desk
holds it like a send while writes are off. Retry does execute at once in
Scriba; for a card with an unknown outcome the Desk reads back or asks first.

One point for the lead to decide: contract 1.1.0 says tasks and reminders
need no approval; the product asks for one (they are Scriba approval cards).
Evaluation worlds run them automatically so the harness can finish, and say
so in `meta.desk.internalWrites`. Which is the product's rule?

## 6. Tests and results (14 November 2026, Windows 11, Python 3.13, Node 22)

| What | Result |
| --- | --- |
| Backend unit and route tests | 375 passed |
| Backend with integration on the real Scriba app at `3ae3a2a` | 505 passed (was 196 on `main`) |
| Outbound-connection guard | On for every backend test: a test that opens a socket to another host fails |
| Mutation check on the safety guards | 30 planted: 28 caught at once, 2 survived and now have tests ([MUTATION_CHECK.md](MUTATION_CHECK.md)) |
| API smoke on the seeded demo backend (`--desk-demo`) | 33 of 33, including mail to worker to approval to sandbox execution to verified |
| Frontend type check and build | Clean; passes |
| Frontend tests | 369 passed, 3 failed (section 5) |
| Agent 2's runner against `/desk/eval/v1` | 20 executed, 0 skipped, on both suites (section 4) |
| Secret scan | No secret found in tracked files |

Not run: anything with a real model, a live mailbox, a live calendar, or a
Postgres database.

## 7. One incident, fixed

Scriba's test harness sets a placeholder model key. My first demo server
therefore attempted 8 model calls to the provider. All were refused (401);
the bodies were synthetic demo emails written for this repository, with no
user data. Since then: the Desk makes no model call unless a model is really
configured (`DESK_MODEL`, and a placeholder key never counts), the dev
backend defaults to `DESK_MODEL=off`, and the test suite fails any test that
connects to another host. The later demo runs logged zero model requests.

## 8. Blocking issues

- **No model credential**, so no real-agent result of any kind exists.
- **This branch and the frontend must land together** (section 5).
- **External writes** stay off until a Scriba revision with the outbound
  fixes is verified by isolated provider tests and the lead authorizes it.
  The list of verified revisions is empty, in code.

## 9. Three highest-impact improvements

1. **Run a real model through the sandbox.** Everything is in place: the
   evaluation routes, usage and cost capture, and the bounded step. It turns
   every "scripted" above into a measured result, and it is what the
   held-out number says is needed.
2. **Move the worker onto Scriba's trigger cursor and prove the receipt
   ledger on a throwaway Postgres.** That is the difference between "tested"
   and "durable" for autonomous intake.
3. **Drive chat-started work through the Desk** (Scriba's chat agent inside a
   sandbox world), which unblocks the three conversation cases and reminders
   asked for in chat.
