# Robustness and repeatability

> **SIMULATED.** Fresh sandbox backends, a fictional office, no provider.

Seed 7, week of 2026-11-16. **26 passed, 0 failed, 1 not run.** A case that could not be run is not a pass.

## Repeatability

| Case | Result | What was observed |
| --- | --- | --- |
| the same seed gives the same initial office | pass | office specification 890a911e74c74890 twice; the sandbox world as built from it: 1f74da2c66f545e8 and 1f74da2c66f545e8 |
| replaying a complete day reproduces it | pass | 105 log entries each; fingerprints bbe9e922fb71b42a and bbe9e922fb71b42a |
| the verdicts are the same on replay | pass | 14 verdicts; differing: none |
| another seed: the same office, other arrival seconds and counterpart choices | pass | world 1f74da2c66f545e8 (same); replay 799d83e5f4ca203c (different, as expected); verdicts that changed with the seed: none |

## Repeats, duplicates, missing things

| Case | Result | What was observed |
| --- | --- | --- |
| empty inbox | pass | a worker pass over no mail opened 0 runs; runs listed: 0; the briefing answered "0 meeting requests, 0 messages need a reply, 3 meetings today, 0 tasks due today." with unavailable=[] |
| the same message taken in again | pass | first pass opened 1 run (11); POST /desk/intake again returned run 11 with duplicate=True; a second worker pass opened 0; a manual sweep opened 0; the mailbox ignored a second notification: True; runs in total: 1 |
| no model answer: the rules take over, and the run says so | pass | the run records ('model.extract_request', False, 'model_not_configured'); planner=rules; usage=None (null, not zero) |
| incomplete model results (a model that answers nothing, or half an answer) | NOT RUN | NOT RUN: no model is configured in this environment, so a real partial model answer cannot be produced. The engine's own tests script that case. |
| a duplicate email, both proposals approved | pass | first approval: executed; second approval: needs_info (calendar_conflict); meetings with the sender on the calendar: 1 |
| the request again after it was booked | pass | held: already_scheduled; actions proposed: 0; flags: ['duplicate'] |
| a calendar that is missing | pass | with one Google calendar answering not_found the run is held as availability_unknown, proposes 0 actions, and the world has 1 operations (unchanged by this request) |
| a meeting deleted before the approval | pass | approving the move of a meeting that no longer exists: needs_info (calendar_event_not_found); the run rests in HELD; confirmations proposed: 0 |
| a worker restart (in-memory claims) | pass | 5 runs before, 5 after; the first pass after the restart opened 0. (The unreliable day repeats this with claims on a file.) |
| sandbox isolation held throughout | pass | real provider clients reached: none |

## Failures the day profiles exercise

| Case | Result | What was observed |
| --- | --- | --- |
| a duplicate notification | pass | second intake of unreliable-tomas-cancel returned run 130 (duplicate=True) |
| a worker restart (claims reopened from a file) | pass | 10 runs before the restart, 10 after; the first pass opened 0 |
| an interruption in the middle of an approved action | pass | the Desk's recovery settled the stuck action without running it: True; after the executive's retry it is executed; the meeting is on the calendar 1 time(s); the run's evidence counts 3 execution records for it |
| a partial provider failure | pass | the event exists and the confirmation failed; the Desk reports the run as PARTIALLY_COMPLETED / partial, compensation escalate |
| an uncertain outcome | pass | recorded as unknown: True; settled by a read-back, not a second write: True; execution attempts recorded: 1 / recorded as unknown: True; settled by a read-back, not a second write: True; execution attempts recorded: 1 |
| safety invariants during the unreliable day | pass | violations: none |
| invalid approvals | pass | approve an action that already executed, same key: HTTP 200, card executed; approve an action that already executed, new key: HTTP 200, card executed; reject an action that already executed: HTTP 200, card executed; approve an action the executive rejected: HTTP 400, card None; approve an action that does not exist: HTTP 400, card None |
| safety invariants during the human_in_loop day | pass | violations: none |
| an unanswered follow-up | pass | 1 reminder(s) proposed in thread-yusuf-call (executed), 1 sent; the proposal had no recipient until the executive typed it in |
| an unanswered follow-up: no second reminder | pass | 1 reminder(s) exist in thread-yusuf-call |
| safety invariants during the follow_up day | pass | violations: none |

## The simulator against a broken backend

| Case | Result | What was observed |
| --- | --- | --- |
| a backend that does nothing earns nothing | pass | against a stand-in that never opens a run, the actionable requests are judged: ['missed'] |
| an unexpected backend response | pass | a 500 and a non-JSON answer were injected; the runner recorded 2 backend error(s) (GET /desk/runs?limit=200 -> 200: not JSON: b'<html>not json</html>'; POST /sim/worker/tick -> 500: {"detail": "boom"}), played all 4 steps and still produced 7 verdicts |
