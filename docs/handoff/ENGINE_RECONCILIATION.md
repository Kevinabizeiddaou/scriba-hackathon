# Engine reconciliation: contract, typed client, and the defects two labs found

Written 14 November 2026 on branch `agent1/engine-reconciliation`, cut from
`agent1/autonomous-engine` at `33137c8`. For the project lead, the frontend
owner and whoever continues the engine.

**Nothing here is a result about a model, a mailbox or a calendar.** Every run
was in an isolated sandbox world, rules only or with a scripted reading. No
external write was made or is possible. ScribaAssist/Scriba was read from a
clone with push disabled and not changed.

Overlay version: **0.3.1**. Contract: [../BACKEND_CONTRACT.md](../BACKEND_CONTRACT.md).
What the frontend should do with it: [AGENT2_INTEGRATION_HANDOFF.md](AGENT2_INTEGRATION_HANDOFF.md).

## 1. What this branch is, and is not

| | |
| --- | --- |
| Base | `agent1/autonomous-engine` at `33137c8` (which contains `main` at `2d70a29`) |
| Not included | Pull request 7 (`agent2/frontend-excellence`, `298b7d6`). It was not merged, rebased or edited. Its tests were run against this branch's typed client (section 6) |
| Read, not merged | `agent3/autonomy-quality` (`82d2b5a`) and `agent4/office-simulation` (`e65a63e`): their findings are the source of most of section 3 |
| Changed | `backend/desk_overlay/` (execution, lifecycle, plans, planning, reading, triage, workflow), `backend/eval/scenarios.py`, backend tests, `frontend/src/api/desk.ts` (types only, additive), the contract, this folder |
| Not changed | Any frontend screen or test. `main` |

## 2. Contract reconciliation

Compared: what the backend sends (real responses, in tests), `frontend/src/api/desk.ts`,
what the frontend of pull request 7 reads (`frontend/src/live/runPlan.ts`,
`runLifecycle.ts`, `deskHolds.ts`, `deskRuns.ts` there),
`docs/BACKEND_CONTRACT.md`, and `docs/AGENT2_FRONTEND_HANDOFF.md` sections 7,
7a and 8 on that branch.

| Topic | Mismatch found | Now |
| --- | --- | --- |
| Execution plan | `DeskRun.plan` was sent and in the contract, absent from the typed client; the frontend read it as untyped data | `DeskPlan`, `DeskPlanIntent`, `DeskPlanStep` declared |
| Run steps | `steps[].state` values (`ready`, `waiting`, `blocked`, or a card status) undeclared | `DeskPlanStepState`. `blocked` now also covers a dependency whose verification failed |
| Verification evidence | `verification`, `execution` and `decisions[]` carried fields the types omitted (`toolCallId`, `tool`, `simulated`, `recovered`, `objectId`, `code`, `assistantActionId`) | Declared |
| Assumptions, missing information | In the plan, undeclared; `held.missing[]` undeclared | Declared on `DeskPlan` and `DeskRunHeld` |
| Confidence and provenance | `intents[].confidence` (null from rules), `evidence`, `source`, `plan.planner`, `plan.unsupported[]` undeclared | Declared, with what null means |
| Approval states | An action's state had to be derived from `status` + `held` + `verified` + `outcomeUnknown` + `errorCode`. The frontend did that derivation itself | `action.lifecycle` (twelve named states) and `action.final`, sent by the backend and declared |
| Retry states | What a retry does was prose in the contract | `action.retry: {mode, attempts, sameEffect}` or null |
| Partial execution | `PARTIALLY_COMPLETED` (run) was declared; the action state was not | `PARTIALLY_EXECUTED` |
| Interrupted execution | `error_code: "interrupted"` undeclared; indistinguishable from a plain failure without reading the output | `INTERRUPTED`, and `DeskRevisedCardCode` |
| Blocked dependencies | `blocked` undeclared; a step could be `ready` after a dependency that executed but failed verification | Declared; engine fixed (section 3, E3) |
| Stage names | The client declared `CLASSIFIED`, `CONTEXT_GATHERING`, `AWAITING_REPLY`; the backend sends `UNDERSTANDING`, `INVESTIGATING`, `WAITING_FOR_RESPONSE`, and `HELD` | `DeskRunStage` is what is sent. The old type is kept so existing code compiles |
| Held reasons | `intent_unclear`, `details_missing` undeclared | `DeskHeldReasonRevised`, plus the new `conflicting_instructions` |
| Edits at approval | `decisions[].edited` existed; the edited action itself was nowhere, and `input` silently stayed as proposed | `action.edited` and `action.effectiveInput` |
| Other | `plan` timeline kind, `stepId`, `held`, `attempts`, `outside_working_hours`, `proposal_changed`, `received_at`, `toolCallId` on a follow-up | Declared |

**Kept in step by a test.** `backend/tests/integration/test_typed_client_with_scriba.py`
produces real runs (a two-step plan, an edit, an unknown outcome, a rejection)
and fails when the backend sends a field, action state, run stage, evidence
kind, held reason or card code that `desk.ts` does not declare.

**Three compromises, stated.** The typed client was changed additively so
that both the frontend on `main` and pull request 7 still compile:

1. `DeskLifecycleStage` keeps the first-draft names. `DeskRunStage` is the
   real list. `DeskLifecycle.stage` is typed as either.
2. `DeskRunHeld.reason` is still declared with the five 0.2 reasons, because
   the frontend on `main` builds a `Record` over that exact type. Any
   `DeskAnyHeldReason` is sent. `heldReasonOf()` reads it honestly.
3. `DeskAnyHoldCode` is unchanged; `DeskCardCode` adds `proposal_changed` and
   `interrupted`.

Each has a one-line removal once pull request 7 is merged (handoff, section 4).

## 3. Engine defects fixed

Source: **L** = quality lab (`agent3`, `labs/autonomy-quality/docs/AGENT1_HANDOFF.md`),
**O** = office simulation (`agent4`, `hackathon/office-simulation/docs/FINDINGS.md`),
**S** = found by this branch's new scenarios.

| # | Defect | Source | Fix | Test |
| --- | --- | --- | --- | --- |
| E1 | A time edited at approval (10:00 to 10:30) was booked at 10:30, verified against 10:00 (`start_differs`, run escalated) and confirmed to the sender as 10:00 | O1 | `effective_input`: the action as approved is what is verified, searched for and confirmed | `test_a_time_edited_at_approval_is_what_is_verified_and_what_the_sender_is_told` |
| E2 | After a read-back settled an action (retry of an unknown outcome; recovery), the next step was never proposed: the run rested in `EXECUTING` | L D2 | `_follow_on` after reconcile and after recovery | two tests in `test_execution_with_scriba.py` |
| E3 | A step that executed and FAILED verification still let its confirmation be proposed | this audit | The dependent step is `blocked`; lifted if a later read-back verifies | `test_a_step_that_ran_and_cannot_be_verified_is_not_followed_by_a_confirmation` |
| E4 | "The day after tomorrow at noon" booked tomorrow; "Thursday week" booked this Thursday | L S2 | A word that moves the day and is not computed leaves the time unread | `test_reader_guards.py`, scenarios S25, S26 |
| E5 | "11:00 GMT+3" booked 11:00 GMT | L S2 | An offset beside a zone is part of the zone | S27 |
| E6 | "Wednesday 9 March" (a Tuesday) was booked on one of the two; subject and text naming different days likewise | L S3 | Held as `conflicting_instructions` | S28 |
| E7 | "Please cancel Thursday's call. On second thought, keep it" cancelled the meeting | L S4 | A retraction is held | S29 (asserted) |
| E8 | "Can we push Thursday's call back to Friday" created a second event | L S1, O3 | New or change is decided from the calendar: a message that speaks of an existing meeting, from someone on one, is a change | S30 (asserted) |
| E9 | A repeated cancellation was aimed at the sender's other meeting, one that had already taken place | O2 | A cancelled or finished meeting is never a target; a meeting named in the message and absent from the calendar is not replaced by another | S31, S32 (asserted) |
| E10 | The same, found again: with the named meeting absent, the sender's only other meeting was cancelled and the sender told | S | Same fix (`named_not_found`) | S31 |
| E12 | On a real provider, after a retry of an unknown outcome was held, a plain second approve went past the "check first" rule and would have run the action again | this audit (reading the retry path) | The rule applies while the outcome is unknown, whatever the card's status | `test_on_a_real_provider_an_unknown_outcome_is_not_run_again_until_the_person_says_they_checked` (failed before the fix). Not reachable today: real sending is off |
| E11 | "Remind yourself on Wednesday at 09:00 to call the chairman" booked a meeting with the colleague who wrote | L S5 | A request to be reminded is work to record | S38 |

Already fixed on the base by its owner before this branch: the HTTP 500 on a
held approval (L D1).

**Every action now has an explicit lifecycle** (`backend/desk_overlay/lifecycle.py`,
`ACTION_STATES`), sent as `action.lifecycle`. `executed` without evidence is
`EXECUTED_UNVERIFIED`; only `VERIFIED` and `REJECTED` are final.

## 4. Not fixed, and why

These are real and are left open, in the labs' own order.

| Finding | Why not here |
| --- | --- |
| L F1 to F7: mail the rules cannot place is filed `informational`, `COMPLETED`, unseen ("`informational` must be earned") | The right change is to escalate what cannot be placed. It moves many runs from "done" to "needs you" and should be decided by the lead with the frontend owner: it changes what the work queue shows |
| L F4: a second request in one email is dropped | Needs multi-intent planning in the rules, or the model understanding step, which exists and is measured in `EVAL_CONFIGURED_MODEL.md` |
| L F5, F6: French and Arabic mail; replies that need their thread | A reader's job, not a guard's |
| L priority 4 and 5: unnecessary questions, safe hand-overs | Nothing wrong happens; cost of rules |
| O4: offered times have no lead time or grid | Not attempted |
| O5: the reminder for an overdue follow-up has no recipient | Not attempted |
| O6, O7: an awaited reply is closed only for some categories; replies awaited before the Desk never become overdue | Not attempted |
| O8: briefing lacks handled, awaited, overdue | Not attempted |
| Agent 4 request A: sandbox control over HTTP (clock, deliver, fault, tick, state) | Not attempted. `recover_stale` still compares the world's clock with the card's real `updated_at` |
| Agent 3 request: a read-only view of the case's world on the evaluation routes; commit and model name in `meta` | Not attempted |

## 5. Evaluation

`backend/eval/scenarios.py` went from 24 to **38 scenarios**. The 14 new ones
(S25 to S38): two relative dates, an offset zone, a weekday that contradicts
its date, a retraction, a reworded move, a cancellation repeated after the
meeting was cancelled, a cancellation for a meeting already held, a rejected
cancellation, a reply that cannot be sent, a duplicate task, a move the
calendar refuses, an address written in the text, a reminder. A scenario may
state `event_start_if_created`: a meeting booked or moved to any other instant
makes the run **unsafe**, not merely wrong.

Measured (`docs/handoff/EVAL_BACKEND_SCENARIOS.md`, generated):

| | Rules only | Scripted model |
| --- | --- | --- |
| Scenarios | 38 | 38 |
| Everything correct | 34 | 37 |
| Unsafe runs | 0 | 0 |
| Approval compliant | 38 | 38 |
| Executed actions verified | 38 | 38 |

On the first 24 scenarios the result is unchanged (20 and 23). **The 14 new
scenarios have not been run with a real model**, and the configured-model
report on the base (`EVAL_CONFIGURED_MODEL.md`) predates every change here.
"Scripted model" is an upper bound for the pipeline behind a model, not a
model's score.

Not covered by a scenario, because the evaluation routes cannot stage them:
retry after a failure, an interrupted workflow, a follow-up deadline, a second
provider's mailbox. The first two are covered by integration tests
(`test_execution_with_scriba.py`); the last two are not covered by anything
new on this branch.

Five scenarios are **asserted** in rules mode (S29, S30, S31, S32, S35): each
was a wrong action on a calendar or a duplicate record. The accuracy numbers
above are still only measured.

## 6. Tests

Windows 11, Python 3.13, Node 22. Scriba read-only at the commit the base used.

| What | Result |
| --- | --- |
| Backend unit tests | 440 passed (base: 403) |
| Backend integration tests, on Scriba's real application in a sandbox world | 233 passed, 38 skipped (the configured-model parameters, which need a network this suite forbids) (base: 189 passed, 24 skipped) |
| Mutation check on this branch's changes | 23 planted defects, 23 caught (22 at first; one test added) |
| Mutation check on the safety guards (`backend/dev/mutation_check.py`) | 45 planted defects, 45 caught (section 7) |
| This branch's backend over HTTP (`seeded_desk_server.py --demo`) | Started; `health.version` 0.3.1; six runs read with `lifecycle`, `final`, `retry`, `edited`; one cancellation approved through Scriba's route: `VERIFIED`, and its confirmation `PROPOSED` without a call to `advance` |
| Frontend of pull request 7 against this branch's `desk.ts` | Type check clean; 452 of 452 tests pass. Checked in a copy of the file, then restored: that branch is untouched |
| Frontend on this branch (the one on `main`) | Type check clean. 380 of 383 tests pass; the 3 that fail are the compatibility tests the base's status report already lists as failing by design (they pin overlay 0.2), and pull request 7 updates them |

Not run: anything against a real provider or a real model; the frontend in a
browser against this branch; the quality lab and the office simulation
against this branch (they would say whether their own findings are closed).

## 7. Safety guards

`backend/dev/mutation_check.py` plants one defect at a time in a guard and
runs the suite. It was run against this branch after the changes:

| | Result |
| --- | --- |
| The base's 38 mutants (approval gate, sandbox tripwires, binding, safeguards, agent limits, understanding) | 37 caught, 0 missed. 1 no longer applied, because the line it targets was rewritten here; it was re-anchored and is caught |
| 7 mutants added for this branch's guards (a step after a failed verification, the unknown-outcome rule on a held card, verification of an edited action, verified without evidence, a gone meeting as a target, a half-read day, a retraction) | 7 caught |
| Total | 45 planted, 45 caught |

The first 37 were run on a copy of the tree taken before the last fix (E12);
the 8 others on the final tree.

## 8. Next, in order

1. Run the quality lab and the office simulation against this branch.
2. Decide "`informational` must be earned" with the frontend owner, then do it.
3. Run the 38 scenarios with a real model in the sandbox.
4. Agent 4's sandbox control routes, so a demo day can be driven over HTTP.
5. After pull request 7 merges: remove the three compatibility types (handoff, section 4).
