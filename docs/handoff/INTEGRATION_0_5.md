# Integrated backend, overlay 0.5: what was merged and what was measured

14 November 2026. Branch `agent1/integration`, cut from `main` at `2df5550`
(frontend of pull request 7 and the visual refresh). **Every figure below was
produced on one commit, `bd4f0cc`**; the commit that adds this report changes
documents, evidence files and one dev script only.

Nothing here touched a real mailbox or calendar. External writes are off by
construction (`externalWrites.enabled: false` in every run). ScribaAssist/Scriba
was read from a clone with push disabled at `3ae3a2a` and was not changed.

## 1. What was merged

| Source | Tip | What it brought |
| --- | --- | --- |
| `main` | `2df5550` | The frontend of pull request 7 and the visual refresh; Docker files |
| `agent1/engine-reconciliation` | `f06a258` | Overlay 0.3.1: the action as approved (`effectiveInput`), the explicit action lifecycle, retry modes, nothing after an unverified step, reader guards (relative dates, offset zones, a weekday against its date, a retraction), the right meeting or none, the unknown-outcome rule on a held card, the typed-client test, 14 scenarios (S25 to S38) |
| `agent1/autonomous-engine` | `2e77414` | Overlay 0.4: instructions in chat, dependent multi-step plans, model understanding and its guards, task completion, follow-up records, memory read from records, repeated requests, unplaced mail handed over, 18 scenarios (N01 to N18) |

Six conflicts in two merges, each resolved to keep both sides:

| File | Resolution |
| --- | --- |
| `frontend/src/api/desk.ts` (main against the reconciliation) | The reconciliation's client (it declares what the backend sends), then the 0.4 and 0.5 fields added to it. The frontend on `main` compiles against it unchanged |
| `backend/desk_overlay/__init__.py` | Version `0.5.0` |
| `backend/eval/scenarios.py` | All 38 of the reconciliation and all 18 of 0.4: **56 scenarios, 56 distinct ids** |
| `backend/tests/integration/test_scenarios_with_scriba.py` | The wrong-hour check and the five asserted rule fixes of the reconciliation, with the replay, reply and outage handling of 0.4. Three sets are reported apart |
| the two generated scenario reports | Regenerated |

Agent 3's trial merge took one side of five of these and lost 14 scenarios.
Here none is lost: `backend/eval/scenarios.py` has S01 to S38 and N01 to N18.

## 2. Work that was being lost silently, and the corrections

Policy, as directed: an unknown human request is not informational by
default; a compound request is not complete while a part of it is open; a
holding reply does not satisfy a commitment. Contract: section 13.

| Class (Agent 3, trial merge) | Correction, in general terms | Where |
| --- | --- | --- |
| 7 messages from people completed with no action | "No work" has to be established: the message says so, or merely acknowledges. A sign-off "Thanks" is not that; a message that says something is still outstanding is not that; a message in a language the rules cannot read is not that. Mail is "automated" only when the classifier has a sign for it, not on a subject that merely resembles a newsletter's | `requests.py`, `triage.py` |
| 6 emails dropped a second request | The message is read sentence by sentence. A sentence that asks for separate work becomes its own task with its own deadline; the meeting's time is read from the sentences about the meeting. What is identified and not acted on is `unresolved`, and the run is `ESCALATED` (`unresolved_requests`) until the person takes it over | `requests.py`, `workflow.py`, `lifecycle.py` |
| 1 holding reply satisfied a follow-up | A reply that says it is not there yet, or promises it and gives no answer, leaves the wait open | `requests.py`, `workflow.py` |

Found while testing the integrated tree and fixed in the same branch:

| Found by | Defect | Fix |
| --- | --- | --- |
| Agent 3's lab | Footers and disclaimers became tasks; an instruction to cancel another meeting became a task | Nothing after the sign-off is read; a sentence about the calendar is never a task; a request that names an address is handed over |
| Agent 3's lab | A task recorded beside a held meeting request completed the run | It does not: the hold stands |
| Real model, S35 (unsafe) | The same work under another title was recorded twice | Tasks are compared by content; same date: `task_exists`; another date: left for the person |
| Real model, S29 | A retraction was read as a task to keep the meeting | The retraction guard stops every reader, before any is asked |
| Real model, S28 (unsafe) | "Wednesday 9 March" (a Tuesday) was booked when a model read the time | The contradiction guard applies to every reader |
| Real model, hold-out | A new meeting the model read was turned into a move of another meeting | The calendar-based "new or change" rule applies only when no model has read the message |
| Agent 4's simulation | A resend was dismissed as "in progress" though the first attempt had proposed nothing | An earlier run counts only if it has a live action |
| Agent 4's simulation | An answer listing what is "still outstanding" was taken for a holding reply | "Still" counts only with what it is still doing |

## 3. Results on `bd4f0cc`

### Backend and frontend together

| Check | Result | Mode |
| --- | --- | --- |
| Backend unit and integration suites (`pytest tests`, real Scriba app at `3ae3a2a`, no network) | **869 passed**, 56 skipped (the configured-model placeholders) | No model; sandbox worlds |
| Frontend type check (`tsc --noEmit`) | Clean | |
| Frontend tests (`vitest run`) | **452 of 452** | One timing test (a 60 ms timeout in the HTTP adapter) failed once while three other jobs loaded the machine and passed on the rerun |
| Frontend build | Passes | |
| API smoke on the seeded demo backend | 33 of 33 | No model |
| Typed client against real backend responses (`test_typed_client_with_scriba.py`) | Passes: every field, state, reason and code the backend sends is declared | |

### Backend scenarios (56), by set

| Set | Rules only | Scripted model | Real model (`gpt-6-luna`) |
| --- | --- | --- | --- |
| The 24 of `8cff1f4` | 21 | 23 | 22 |
| S25 to S38 (reconciliation) | 14 of 14 | 14 of 14 | 14 of 14 |
| N01 to N18 (overlay 0.4) | 18 of 18 | 18 of 18 | 16 of 18 |
| Unsafe runs, all 56 | 0 | 0 | 0 |
| Approval compliant, verified | 56, 56 | 56, 56 | 56, 56 |

Real model: 52 calls, none failed; 51 scenarios answered by the model (the
others are the outage scenario and the ones stopped before any reader).
Not correct with the real model: S19 (a third party named in the request: on
this run the Desk handed the message over, where I expect the booking), S20
(my expectation does not allow the category reported), N06 (a correct reply
and a task read beside it), N08 (the cancellation and the task were both done;
classified as work, where I expect a cancellation). S25 to S38 had never been
run with a real model before this integration.

### The official 20 cases and the reworded hold-out (Agent 2's runner, real model, sandbox)

| Suite | `8cff1f4` | `24845c1` (0.4) | `bd4f0cc` (0.5) |
| --- | --- | --- | --- |
| `desk-v1` | 11 | 18 | **19** of 20 |
| `desk-holdout-v1` | 10 | 18 | **17** of 20 |

`bd4f0cc`: 75 model calls, none failed; 19 and 18 approvals, none
unexpected; median 6.6 s and 7.2 s per case; $0.00032 and $0.00036 per case.
One run per case. Across the five integration commits measured today the
visible suite scored 19, 19, 18, 18, 19 and the hold-out 17, 17, 17, 15, 17:
the hold-out's 18 at `24845c1` is within that spread, not a level the engine
holds. Still failing on this run: EVAL-023 in both (a correct reply went out,
and the model also read a task; the run is labelled by the task),
EVAL-015-H1 (the reworded repeat is handed over, not recognised),
EVAL-031-H1 (the three-step request ended in a question on this run).
I have not read the hold-out's texts.

### Agent 3's lab (291 items, rules only, isolated sandbox)

Their runner, unmodified, from `origin/agent3/autonomy-quality` at `f23beb2`,
against a pinned checkout of `bd4f0cc`.

| | Their trial merge (`f06a258` + `99ad291`) | `bd4f0cc` | `bd4f0cc`, seed 7 |
| --- | --- | --- | --- |
| Completed | 208 | **218** | 218 |
| Safely handed over | 49 | 54 | 54 |
| Failed | 34 | 19 | 19 |
| Unsafe | 0 | 0 | 0 |
| **False successes** | **15** | **0** | 0 |
| Completed or safely handed over | 88.3% | 93.5% | 93.5% |
| Hard gates (7) | all pass | all pass | all pass |

No case that completed on their trial merge fails here. Seed 7 changes the
senders, slots and greetings, not the sentence patterns, so its identical
tally shows independence from names and dates, not from wording; the
corrections' own tests use wording written for them.

What still fails (19) or is handed over (54), by their root cause: a written
time not read (6), a change read as a new meeting (4), a non-meeting read as
a meeting (4), a second request dropped (2), a cancellation read as a move
(1), thread context (1), non-English (1); handed over: scheduling not
recognised (20), other jobs not done (21), a task handed over (8),
non-English (3), thread context (2). These are reading limits of the rules.

### Agent 4's eight simulated workdays (rules only, isolated sandbox)

Their simulator, unmodified, from `origin/agent4/office-simulation` at
`76ae367`, seed 7, attentive executive.

| | `f06a258` (their published run) | `bd4f0cc` |
| --- | --- | --- |
| Actionable requests | 77 | 77 |
| Handled with approvals only | 54 (70.1%) | **55 (71.4%)** |
| Completed correctly | 42 | 43 |
| Left for a human | 19 | 15 |
| Partly completed | 1 | 3 |
| Incorrect: something wrong took effect | 0 | 0 |
| Safety invariant violations | 0 | 0 |
| Tasks and reminders confirmed | 7 | 11 |
| Follow-ups satisfied | 8 | 7 |
| Scenario checks passed / failed | 44 / 17 | 45 / 16 |
| Executed actions the Desk did not verify | 0 | 0 |

"Partly completed" is higher because a second request that is not acted on
now keeps the run open instead of being dropped. One follow-up fewer is
satisfied than on `f06a258`; I did not find which.

### Safety and mutation

`backend/dev/mutation_check.py` plants one defect at a time in a guard and
runs the suite against a pinned checkout of `bd4f0cc`: **55 planted, 55
caught, 0 missed, 0 not applied.** They cover the external-write gate and its
second layer, the isolation tripwire, unknown outcomes and their read-back,
approval binding and retry, claims, injection, availability, the reader
guards of the reconciliation, model-reading validation, and ten for overlay
0.5 (no-work, footers, unresolved requests, addresses, duplicate tasks, the
weekday guard, weak automated hints, holding replies). On the first run of
this round two of the new ten were missed; tests were added and both are
caught. Log: [integration-0.5/mutation-check.log](integration-0.5/mutation-check.log).

Safety properties measured independently by Agent 3's lab on this commit:
1,170 checks for unauthorized external effects, 570 for cross-account leaks,
280 for false confirmations, 298 for duplicate effects, 869 for approval
enforcement, 10 for unknown outcomes, 573 for incorrect external actions:
zero violations in each.

### Real-model demo of the autonomous path

`backend/dev/demo_path.py` against the seeded demo backend with
`DESK_MODEL=on DESK_UNDERSTANDING=model DESK_AGENT=on`, on `bd4f0cc`.
Transcript: [integration-0.5/demo-path.log](integration-0.5/demo-path.log).

1. Synthetic mail asking for a meeting and a document by a date is delivered
   to the sandbox mailbox. The script never calls intake.
2. **The worker picks it up** (`trigger: worker`).
3. **The model reads it**: two intents, `new_meeting` and `task`, each quoted.
4. **A checked plan**: `s1` book, `s2` task, `s3` confirmation depending on
   `s1` and waiting.
5. **A person approves** each card through Scriba's own approve route.
6. **Sandbox execution**: `calendar.create_event`, `task.create`, then, only
   after the booking took effect, `email.send`.
7. **Verification**: each action `VERIFIED` by `sandbox_readback`.
8. **Completed run**: `COMPLETED`, nothing unresolved.
9. **Follow-up**: a second message asks for a time that is now taken; times
   are offered after approval; a follow-up waits; the sender's answer arrives;
   the follow-up is `satisfied` and that run completes.

26 model calls, none failed; isolation violations: none; external writes off.

## 4. External-write safety state

Unchanged and enforced in the server: `VERIFIED_SCRIBA_REVISIONS` is empty, so
`externalWrites.enabled` is false whatever the environment says; a mail or
calendar card outside a sandbox world is held with `external_writes_disabled`;
the executor refuses a second time; tripwires on the real provider clients
count violations (zero in every run above). The mutation check plants a defect
in each of these and the suite notices.

## 5. Remaining false successes and limits

- **In Agent 3's lab: none** on `bd4f0cc` (15 on their trial merge).
- **In the backend's 56 scenarios: none unsafe**, in any mode.
- **Known ways a run can still end "done" when it is not:**
  - a request worded as a plain statement, in a message that also says "FYI"
    or "no action needed", is filed;
  - with a model on, the model can read a message as `fyi` that needs
    judgement (the prompt says what `fyi` may not be used for; that is a
    request to a model, not a guard);
  - a holding reply the wording rule does not recognise satisfies the wait.
- **The price of the policy:** more runs are handed over. On rules alone a
  message from a person that says nothing recognisable is `ESCALATED`, and a
  request beside a meeting that is not clearly separate work keeps the run
  open. Agent 4's simulation shows it as "partly completed" 3 against 1.
- **Reading is still the limit on rules alone:** 19 failed and 54 handed over
  of 291 are all reading (times, changes worded without the verb, other
  languages, threads).
- **Not run:** a live mailbox or calendar; Postgres; more than one run per
  case with the model; Agent 3's lab and Agent 4's simulation with a model
  (both are rules-only tools as written).
- **Not done from the other agents' requests:** sandbox control routes over
  HTTP (Agent 4, A), offering times on a grid near the day asked for (B4),
  the briefing additions (B8), commit and model name in `/meta` (Agent 3).

## 6. For Agent 2

[AGENT2_INTEGRATION_0_5.md](AGENT2_INTEGRATION_0_5.md).

## 7. Evidence in this folder

`integration-0.5/`: the real-model scenario report, the two harness reports,
the lab's report and gates for `bd4f0cc` (both seeds), the simulator's
combined summary, the mutation log, the demo transcript.
