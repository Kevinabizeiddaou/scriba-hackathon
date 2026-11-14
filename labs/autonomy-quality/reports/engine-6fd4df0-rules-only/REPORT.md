# Autonomy Quality Lab: engine-6fd4df0-rules-only

**These are results of the RULES-ONLY engine in an isolated sandbox. They say nothing about a model.**

Traceability: backend `6fd4df0f6a47` · runner `1.0.0` · seed `20270308` · model `none` · mode `rules_only+isolated_sandbox`
Run 2026-11-14T12:02:32Z to 2026-11-14T12:08:03Z, 1 pass(es), contract 1.1.0, overlay 0.5.0, Scriba `3ae3a2aa` (read-only).

## What kind of evidence this is

| Class | Measured here | Note |
| --- | --- | --- |
| rules only | yes | The Desk with no model: rule-based reading only. |
| scripted model | **no** | NOT MEASURED by this lab. A scripted model exists only inside the backend's own tests (an in-process stub); it cannot be reached over HTTP. See the baseline report for Agent 1's figure, re-run and verified. |
| real model | **no** | NOT MEASURED: the backend reports no configured model (meta.agent = scripted, desk.model.configured = false). |
| isolated provider sandbox | yes | Every mail and calendar effect was applied to a per-case SandboxWorld. All results are simulated: none is a provider success. |
| live provider | **no** | NOT MEASURED, by design: the lab never calls a live provider and the backend's external writes are disabled in code. |

## Headline

| Measure | Value | Over |
| --- | --- | --- |
| Complete job success rate | **70.8%** | 291 cases, none excluded |
| ...excluding inputs the backend cannot take at all | 70.8% | 291 cases |
| Completed or safely handed to the person | 88.3% | 291 |
| Correct intent | 68.7% | 278 |
| Correct final state | 74.2% | 287 |
| Safety violations | **0** (0.0%) | 291 |
| False successes (filed as done, job not done) | **13** (4.5%) | 291 |
| Mandatory approvals | 199 (0.8058 per completed job) | |
| Human rescues | 4 (0.0194 per completed job) | |
| Latency, median / p90 / p95 / max | 78 ms / 2.65 s / 2.89 s / 6.06 s | lab wall clock, approvals included |
| Cost per run | NOT MEASURED: no run reported model usage (no model call was made) | |
| Repeated-run consistency | run with --repeat 2 or more to measure consistency |  cases x 1 |

Verdicts: completed 206, failed 34, safe_handoff 51.

A mandatory approval is not a failure of autonomy; it is counted on its own line. A rescue is anything else the lab had to do for the engine (a retry, an advance).

## Quality gates

| Gate | Status | Checks evaluated | Violations | Cases |
| --- | --- | --- | --- | --- |
| Zero unauthorized external effects | PASS | 1170 | 0 |  |
| Zero cross-account data leaks | PASS | 570 | 0 |  |
| Zero false confirmation of a failed action | PASS | 280 | 0 |  |
| Zero duplicate effects from repeated intake in the sandbox | PASS | 298 | 0 |  |
| Correct approval enforcement | PASS | 869 | 0 |  |
| Correct handling of unknown provider outcomes | PASS | 10 | 0 |  |
| Zero incorrect external actions (approved, but not what the request called for) (lab-defined) | PASS | 573 | 0 |  |

Advisory thresholds (reported, never blocking):

| Measure | Target | Value | Status |
| --- | --- | --- | --- |
| Complete job success rate | >= 0.8 | 70.8% | below target |
| Completed or safely handed over | >= 0.95 | 88.3% | below target |
| Correct intent rate | >= 0.9 | 68.7% | below target |
| False success rate | <= 0.02 | 4.5% | above target |
| Human rescues per completed job | <= 0.05 | 1.9% | met |
| Median latency (ms) | <= 8000 | 78.5 | met |
| 95th percentile latency (ms) | <= 30000 | 2889 | met |
| Cost per run (USD) | <= 0.05 | not measured | not measured |
| Repeated-run consistency | >= 1.0 | not measured | not measured |

- **Semantic robustness corpus**: 170 run, 99 completed, 47 handed over, 24 failed, 0 unsafe, 0 unsupported, 0 lab errors.
- **Metamorphic members**: 70 run, 58 completed, 4 handed over, 8 failed, 0 unsafe, 0 unsupported, 0 lab errors.
- **Adversarial cases**: 38 run, 36 completed, 0 handed over, 2 failed, 0 unsafe, 0 unsupported, 0 lab errors.
- **Product-route scenarios**: 13 run, 13 completed, 0 handed over, 0 failed, 0 unsafe, 0 unsupported, 0 lab errors.

## Success by workflow category (semantic corpus)

| Category | Cases | Completed | Handed over | Failed | Unsafe | Other | False success | Intent correct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cancellation | 8 | 3 (37.5%) | 3 | 2 | 0 | 0 | 1 | 3 |
| chat | 4 | 3 (75.0%) | 1 | 0 | 0 | 0 | 0 | 3 |
| conflicting_instructions | 7 | 6 (85.7%) | 1 | 0 | 0 | 0 | 0 | 6 |
| daylight_saving | 6 | 2 (33.3%) | 4 | 0 | 0 | 0 | 0 | 2 |
| deadline_reminder | 9 | 6 (66.7%) | 3 | 0 | 0 | 0 | 0 | 6 |
| direct_meeting | 10 | 3 (30.0%) | 5 | 2 | 0 | 0 | 0 | 5 |
| escalation | 8 | 7 (87.5%) | 0 | 1 | 0 | 0 | 0 | 1 |
| follow_up | 7 | 6 (85.7%) | 0 | 1 | 0 | 0 | 0 | 7 |
| implied_by_thread | 7 | 3 (42.9%) | 4 | 0 | 0 | 0 | 0 | 2 |
| indirect_meeting | 9 | 2 (22.2%) | 6 | 1 | 0 | 0 | 0 | 3 |
| language | 9 | 2 (22.2%) | 4 | 3 | 0 | 0 | 2 | 3 |
| multi_people | 8 | 5 (62.5%) | 1 | 2 | 0 | 0 | 1 | 6 |
| multi_request | 8 | 3 (37.5%) | 0 | 5 | 0 | 0 | 2 | 6 |
| no_action | 10 | 9 (90.0%) | 0 | 1 | 0 | 0 | 0 | 9 |
| relative_date | 8 | 4 (50.0%) | 2 | 2 | 0 | 0 | 0 | 4 |
| reply_drafting | 8 | 6 (75.0%) | 0 | 2 | 0 | 0 | 1 | 6 |
| requires_no | 8 | 7 (87.5%) | 0 | 1 | 0 | 0 | 0 | 5 |
| reschedule | 9 | 4 (44.4%) | 4 | 1 | 0 | 0 | 0 | 2 |
| task_extraction | 9 | 1 (11.1%) | 8 | 0 | 0 | 0 | 0 | 2 |
| timezone | 9 | 8 (88.9%) | 1 | 0 | 0 | 0 | 0 | 5 |
| unclear_time | 9 | 9 (100.0%) | 0 | 0 | 0 | 0 | 0 | 6 |

By language (a measurement, not a statement of support):

| Language | Cases | Completed | Handed over | Failed | Unsafe |
| --- | --- | --- | --- | --- | --- |
| ar | 3 | 0 | 1 | 2 | 0 |
| ar-Latn | 1 | 0 | 0 | 1 | 0 |
| en | 159 | 97 | 41 | 21 | 0 |
| fr | 6 | 1 | 5 | 0 | 0 |
| mixed | 1 | 1 | 0 | 0 | 0 |

## Metamorphic relations

26 of 36 relations hold; 10 are broken.

| Relation | Relations | Hold | Broken | Follow-up cases | Follow-ups breaking it |
| --- | --- | --- | --- | --- | --- |
| MR1_reword | 8 | 2 | 6 | 24 | 7 |
| MR2_irrelevant_history | 5 | 1 | 4 | 15 | 7 |
| MR3_conflict_added | 4 | 4 | 0 | 4 | 0 |
| MR6_calendar_unreadable | 3 | 3 | 0 | 3 | 0 |
| MR7_rejection | 5 | 5 | 0 | 5 | 0 |
| MR8_recipient_changed | 3 | 3 | 0 | 3 | 0 |
| MR9_uncertain_provider | 3 | 3 | 0 | 3 | 0 |
| MR10_second_action | 3 | 3 | 0 | 3 | 0 |
| MR11_sender_changed | 1 | 1 | 0 | 1 | 0 |
| MR12_time_changed | 1 | 1 | 0 | 1 | 0 |

Broken relations:

- `MR1-reword-book` (Reword 'book' without changing its meaning; expected: equivalent; base verdict completed)
  - `MR1-reword-book/v1`: created: [['2027-03-09T09:00:00+00:00', '2027-03-09T09:30:00+00:00', ['kenji.watanabe@pacific-reefer.example']]] -> []; tasks: [] -> ['2027-03-09']; approvalsAsked: ['calendar.create_event', 'email.send'] -> ['email.send']
- `MR1-reword-busy` (Reword 'busy' without changing its meaning; expected: equivalent; base verdict completed)
  - `MR1-reword-busy/v1`: tasks: [] -> ['2027-03-09']
- `MR1-reword-move` (Reword 'move' without changing its meaning; expected: equivalent; base verdict completed)
  - `MR1-reword-move/v2`: moved: [['ev-gulf', '2027-03-10T12:00:00+00:00']] -> []; approvalsAsked: ['calendar.update_event', 'email.send'] -> ['email.send']
- `MR1-reword-cancel` (Reword 'cancel' without changing its meaning; expected: equivalent; base verdict completed)
  - `MR1-reword-cancel/v3`: cancelled: ['ev-marseille'] -> []; approvalsAsked: ['calendar.cancel_event', 'email.send'] -> ['email.send']
- `MR1-reword-task` (Reword 'task' without changing its meaning; expected: equivalent; base verdict completed)
  - `MR1-reword-task/v3`: tasks: ['2027-03-11'] -> []
- `MR1-reword-vague` (Reword 'vague' without changing its meaning; expected: equivalent; base verdict completed)
  - `MR1-reword-vague/v2`: mail: [[['george.mitchell@albion-shipbrokers.example'], 'thr-m-mr-base-vague']] -> []; approvalsAsked: ['email.send'] -> []
  - `MR1-reword-vague/v3`: mail: [[['george.mitchell@albion-shipbrokers.example'], 'thr-m-mr-base-vague']] -> []; approvalsAsked: ['email.send'] -> []
- `MR2-history-book` (Add irrelevant history to 'book'; expected: equivalent; base verdict completed)
  - `MR2-history-book/disclaimer`: tasks: [] -> ['', '']
  - `MR2-history-book/quoted`: created: [['2027-03-09T09:00:00+00:00', '2027-03-09T09:30:00+00:00', ['kenji.watanabe@pacific-reefer.example']]] -> []; mail: [[['kenji.watanabe@pacific-reefer.example'], 'thr-m-mr-base-book']] -> []; approvalsAsked: ['calendar.create_event', 'email.send'] -> []
- `MR2-history-move` (Add irrelevant history to 'move'; expected: equivalent; base verdict completed)
  - `MR2-history-move/disclaimer`: tasks: [] -> ['', '']
  - `MR2-history-move/quoted`: moved: [['ev-gulf', '2027-03-10T12:00:00+00:00']] -> []; mail: [[['hassan.almansoori@gulfcrane.example'], 'thr-m-mr-base-move']] -> []; approvalsAsked: ['calendar.update_event', 'email.send'] -> []
- `MR2-history-cancel` (Add irrelevant history to 'cancel'; expected: equivalent; base verdict completed)
  - `MR2-history-cancel/disclaimer`: tasks: [] -> ['', '']
  - `MR2-history-cancel/quoted`: cancelled: ['ev-marseille'] -> []; mail: [[['claire.dubois@port-marseille.example'], 'thr-m-mr-base-cancel']] -> []; approvalsAsked: ['calendar.cancel_event', 'email.send'] -> []
- `MR2-history-task` (Add irrelevant history to 'task'; expected: equivalent; base verdict completed)
  - `MR2-history-task/disclaimer`: tasks: ['2027-03-11'] -> ['', '', '2027-03-11']

## Adversarial and scenario results by category

| Category | Cases | Completed | Handed over | Failed | Unsafe | Other |
| --- | --- | --- | --- | --- | --- | --- |
| MR4_repeated_message | 4 | 4 | 0 | 0 | 0 | 0 |
| MR5_receiving_mailbox | 2 | 2 | 0 | 0 | 0 | 0 |
| MR8_recipient_changed | 1 | 1 | 0 | 0 | 0 | 0 |
| MR9_uncertain_provider | 1 | 1 | 0 | 0 | 0 | 0 |
| approval_integrity | 8 | 8 | 0 | 0 | 0 | 0 |
| calendar_conflict | 1 | 1 | 0 | 0 | 0 | 0 |
| cross_account | 1 | 1 | 0 | 0 | 0 | 0 |
| forged_authority | 8 | 8 | 0 | 0 | 0 | 0 |
| injection | 11 | 10 | 0 | 1 | 0 | 0 |
| interrupted | 2 | 2 | 0 | 0 | 0 | 0 |
| organizer_identity | 2 | 2 | 0 | 0 | 0 | 0 |
| poisoned_thread | 1 | 1 | 0 | 0 | 0 | 0 |
| provider_failure | 6 | 6 | 0 | 0 | 0 | 0 |
| recipient_substitution | 3 | 2 | 0 | 1 | 0 | 0 |

## Root causes

One row per defect, not per wording. Details, reproductions and acceptance criteria: `ROOT_CAUSES.md`.

| # | Root cause | Severity | Cases | Classes |
| --- | --- | --- | --- | --- |
| 1 | A task is recorded for a message that asks nothing of the executive, or with a title that says nothing (`RC-NEEDLESS-TASK`) | false success | 8 | Incorrect entity extraction, Misleading completion claim |
| 2 | French and Arabic mail is not understood (`RC-NON-ENGLISH-NOT-READ`) | false success | 6 | Intent misunderstanding, Misleading completion claim, Incorrect time interpretation |
| 3 | With two requests in one email, the second is dropped and the run is reported complete (`RC-SECOND-REQUEST-DROPPED`) | false success | 3 | Incomplete execution, Misleading completion claim |
| 4 | A cancellation stated as news is filed as news and the meeting stays (`RC-CHANGE-READ-AS-NEWS`) | false success | 1 | Intent misunderstanding, Misleading completion claim |
| 5 | A reply that needs a fact from the thread cannot be written without a model (`RC-REPLY-NEEDS-MODEL`) | false success | 1 | Wrong tool selection, Misleading completion claim |
| 6 | A time that is written in the message is not read, and the sender is asked for it again (`RC-WRITTEN-TIME-NOT-READ`) | missed work | 8 | Incorrect time interpretation |
| 7 | A request to move or cancel a meeting is read as a request for a new one (`RC-CHANGE-READ-AS-NEW-MEETING`) | missed work | 4 | Intent misunderstanding |
| 8 | A message that mentions a meeting or a call is treated as a request for one (`RC-NON-MEETING-READ-AS-MEETING`) | missed work | 4 | Intent misunderstanding |
| 9 | A reply that only makes sense with the thread is read alone (`RC-THREAD-CONTEXT-NOT-USED`) | missed work | 3 | Intent misunderstanding, Missing context, Incorrect time interpretation |
| 10 | A cancellation worded without 'cancel' is read as a move, and the sender is asked for a new time (`RC-CANCEL-READ-AS-MOVE`) | missed work | 1 | Intent misunderstanding |
| 11 | A scheduling request in ordinary words is not recognised and is handed to the executive (`RC-SCHEDULING-NOT-RECOGNISED`) | handoff | 20 | Intent misunderstanding |
| 12 | Other jobs not done (see each trace) (`RC-OTHER-JOB-NOT-DONE`) | handoff | 18 | Intent misunderstanding, Missing context, Wrong tool selection |
| 13 | A task with its deadline is handed over as 'needs a reply' instead of recorded (`RC-TASK-HANDED-OVER`) | handoff | 8 | Intent misunderstanding |

Case by case, for everything not completed: `CASES.md`. Full traces (input, the lab's decisions, the engine's record, the office afterwards) for every case: `traces.jsonl.gz`.
