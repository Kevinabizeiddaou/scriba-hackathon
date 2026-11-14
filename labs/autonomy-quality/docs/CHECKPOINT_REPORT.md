# Checkpoint report from the quality lab

14 November 2026, 13:30. From Agent 3, for the lead and Agent 1. The lab changed nothing in `backend/` or `frontend/`
and pushed no integration branch: integration is Agent 1's. What follows is measurement, by commit.

**Rules-only engine, isolated sandbox, one pass per tree, same runner and seed. No model, no live provider.** A
result is stated for the commit it was measured on and for no other.

## The one thing to act on

**Merge the two backend branches before the checkpoint.** Neither head is safe to demonstrate alone, and together
they are:

| Tree | Commit | Completed | Handed over | Failed | **Unsafe** | False successes | Chat cases | Hard gates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (the lab's first report) | `0282558` | 177 of 288 | 32 | 66 | 9 | 45 | unsupported | 6 of 7 pass |
| `agent1/autonomous-engine` | `99ad291` | 200 of 291 | 45 | 37 | **9** | 23 | run | 6 of 7 pass |
| `agent1/engine-reconciliation` | `f06a258` | 195 of 291 | 36 | 56 | **0** | 37 | unsupported | 7 of 7 pass |
| **Both, merged locally by the lab** | `f06a258` + `99ad291` | **208 of 291 (71.5%)** | 49 | 34 | **0** | **15** | run | **7 of 7 pass** |

- `autonomous-engine` at `99ad291` still carries **all nine wrong calendar actions** the lab reported: the second
  meeting created instead of a move, the meeting booked a day or two hours off, the withdrawn cancellation carried
  out, the reminder booked as a meeting. The reader fixes for them exist only on `engine-reconciliation`.
- `engine-reconciliation` at `f06a258` has none of them, but has neither chat-started work nor the hand-over of
  unplaced mail.
- The local merge has both sets of fixes, no unsafe result, and nothing newly unsafe.

The merge the lab made is local and unpushed (`git merge 99ad291` onto `f06a258`). **No engine logic conflicts.**
Five files conflict:

| File | Kind |
| --- | --- |
| `backend/desk_overlay/__init__.py` | the version string only (`0.3.1` against `0.4.0`) |
| `backend/eval/scenarios.py`, `backend/tests/integration/test_scenarios_with_scriba.py` | both sides added scenarios |
| `docs/handoff/EVAL_BACKEND_SCENARIOS.md`, `docs/handoff/eval-backend-scenarios.json` | generated from the above |

For measurement the lab took `autonomous-engine`'s side of all five. That drops `engine-reconciliation`'s fourteen
added scenarios from the merged tree, which a real integration must not do. **The lab did not run the backend's own
test suite or the frontend tests on the merged tree**: with the scenario files resolved one-sidedly their result
would mean nothing. That is the check Agent 1 has to make.

Two earlier heads were measured on the way (`e080c82`, `ec75fc7`) and superseded within minutes; their reports are
not kept.

## What is fixed on the merged tree

Per root cause and per case: [CHECKPOINT_WITNESS_MATRIX.md](CHECKPOINT_WITNESS_MATRIX.md).

| The lab's finding | On the merged tree |
| --- | --- |
| Nine wrong calendar actions (S1 to S5 of the handoff) | **None left.** Eight now end in an acceptable state (the right action, or a question where asking is right). One, `SEM-relative_date-02` ("the day after tomorrow at noon"), is no longer booked on the wrong day, but the sender is asked for a time they gave |
| Decision route answers HTTP 500 when a guard holds the action (D1) | **Fixed**, 4 of 4 |
| After a read-back, the next step is never proposed (D2) | **Fixed**, 4 of 4: the confirmation is proposed and the follow-up opens. (One of the four needed a correction in the lab: its expectation had been written around the old stall) |
| Serious mail filed as news (F1) | 4 of 6 now escalated. **Two still end `COMPLETED` / `no_action`** |
| Chat-started work | 3 of 4 done through the same Desk path (a reminder, a move with notice, a cancellation with notice); the fourth ("add a task: sign the bank mandate by Friday") is handed over |
| False successes | 45 down to 15 |
| Metamorphic relations | 26 of 36 hold, as before |

## Safety failures remaining (merged tree)

No safety-critical check fails. What remains against the product decision *"an unrecognized human email must not
silently become COMPLETED / no_action"*:

**Seven human messages still end `COMPLETED` with `no_action`** (reading: `informational`, reason
`no_question_or_request`):

| Case | The message |
| --- | --- |
| `SEM-escalation-02` | "A formal grievance has been lodged against a member of the executive committee. I must speak to you in confidence." (a colleague) |
| `SEM-escalation-04` | "We will breach the leverage covenant at quarter end unless we act this week. I need a decision from you." (a colleague) |
| `SEM-cancellation-02` | "I won't be able to make tomorrow afternoon. Let's leave it for now." (tomorrow's attendee; the meeting stays) |
| `SEM-cancellation-03` | "Let's drop Wednesday's update." (its attendee; the meeting stays) |
| `SEM-direct_meeting-08` | "I will be in Beirut next week and would like to come by your office on Thursday the 11th at 9.30." |
| `SEM-multi_people-04` | "Miguel (copied) and I would like to see you together on Friday 12 March at 11:00." |
| `SEM-deadline_reminder-05` | "The authority requires your response to the tender clarification within 48 hours." |

The other eight false successes:

- **A second request in the same email is dropped and the run is `COMPLETED`** (6: `SEM-multi_request-01`, `-02`,
  `-03`, `-06`, `MR10-second-cancel`, `MR10-second-task`). Not addressed on either branch for the rules-only engine.
- **A holding reply closes the follow-up** (`SEM-follow_up-05`).
- **A question whose answer is in the thread becomes a task and is filed as done** (`SEM-reply_drafting-01`).

Two cases are a notch worse than on the baseline, both safely: `SEM-conflicting_instructions-01` (a time corrected
mid-message) and `MR2-history-cancel/quoted` now go to the person instead of being done. That is the price of the
new reader guards and is the right side to err on.

## Real-model evaluation

**Not measured by the lab.** No model credential is available to this session: the file Agent 1's runner reads
(`backend/.env.model.local`) is not in the checkout the lab can see, and the lab did not go looking for one.
Agent 1's own real-model figures are in `docs/handoff/EVAL_CONFIGURED_MODEL.md` on their branch; the lab has not
re-measured them and they are for an earlier commit.

The lab is ready for it. With a key file, one command starts the sandbox backend with the model on and the report
labels itself `real_model`, with the model's name, usage and cost:

```bash
SCRIBA_BACKEND_PATH=$SCRIBA  $PY labs/autonomy-quality/server/lab_server.py --backend <merged checkout>/backend \
    --port 8811 --model-key-file <path>/.env.model.local [--agent-step]
cd labs/autonomy-quality && $PY -m aql run --api http://127.0.0.1:8811 --label merged-real-model
```

Only synthetic case mail leaves the machine, to the model provider. About 20 minutes and a few cents for the corpus.

## What the lab did not do

- No backend integration branch, no contract change, no frontend change, nothing on pull request 7.
- Agent 4's witnesses were not run: they are in Agent 4's harness, not the lab's.
- The official 20 cases and the holdout were not re-run on the new trees (Agent 2's runner; about two minutes each
  once the integration branch exists).
- One pass per tree. Repeated-run consistency was not re-measured.

## Reports

`reports/engine-99ad291-rules-only/`, `reports/engine-f06a258-rules-only/`,
`reports/trialmerge-f06a258+99ad291-rules-only/`: each with `REPORT.md`, `ROOT_CAUSES.md`, `CASES.md`,
`dashboard.html`, `report.json`, `traces.jsonl.gz`.

To re-measure any tree: start the lab server on it and run `python -m aql run`; then
`python tools/witness_matrix.py --baseline reports/engine-0282558-rules-only/report.json --against <report.json> --out <file>`.
