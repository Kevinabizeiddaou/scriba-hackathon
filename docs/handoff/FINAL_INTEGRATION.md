# Final integration (14 November 2026)

One application on one branch: the autonomous engine, the files and desktop
bridge, the frontend demo corrections, the office simulation and the Autonomy
Quality Lab, merged onto `main` and measured together.

> Every number on this page was measured on the combined tree, in an isolated
> sandbox, with **no model** (rules only, or the scripted stand-in where a
> table says so). Nothing here is a real-model result or a live-provider
> result. No number is carried over from an earlier branch.

## 1. What was merged

Branch `integration/final`, from `main` at `f62a06e`, one merge commit per
workstream, in this order:

| # | Workstream | Branch at | Conflicts |
| --- | --- | --- | --- |
| 1 | Files and the desktop bridge (pull request 14) | `agent1/automation-integration` `a39b878` | none |
| 2 | Work that is not silently lost: unresolved requests, holding replies, several requests per message | `agent1/integration` `bd4f0cc` | eight files, below |
| 3 | Frontend demo corrections (pull request 15) | `agent2/demo-corrections` `87fd2b7` | none |
| 4 | Office simulation (pull request 8) | `agent4/office-simulation` `76ae367` | none |
| 5 | Autonomy Quality Lab (pull request 9) | `agent3/autonomy-quality` `f23beb2` | none |

That was pull request 17, merged into `main` as `3f42ca3`. Three branches
had moved while it was being put together, so a second branch,
`integration/final-2`, was cut from `main` at `3f42ca3`:

| # | Workstream | Branch at | Conflicts |
| --- | --- | --- | --- |
| 6 | Integration report and real-model evidence of `agent1/integration` (documents and one dev script) | `94ac3de` | none |
| 7 | Lab acceptance report and tools | `agent3/autonomy-quality` `dbc6b5f` | none |
| 8 | Workbook changes on a copy, overlay 0.5.1 | `agent1/automation-integration` `dee5583` | six files, below |

Pull request 16 (deploy notes) was merged into `main` separately, by its
author; it is in the tree and was not part of this work.

### The conflicts of `agent1/integration`, and what was decided

Both sides were read for each. Nothing was resolved by taking a whole file.

| File | Decision |
| --- | --- |
| `backend/desk_overlay/workflow.py` | Both kept: attachment reading and the file review (pull request 14) and requested tasks with unresolved requests (`agent1/integration`). They are separate methods; the import line names both `files` and `requests` |
| `frontend/src/api/desk.ts` | The union of the two typed clients: `review_file` and `notify` purposes; `attachments`, `files`, `kind` and `unresolved` on a run; the desktop calls. Git had also joined both sides' additions to `DeskAction`, `DeskFollowUp` and `DeskRun`, declaring eleven fields twice; one declaration of each is kept |
| `frontend/src/live/runLifecycle.ts` | Agent 2's file, with the integration wording inside `HELD_REASON_REVISED` (it adds `unresolved_requests`), as `docs/frontend/DEMO_CORRECTIONS.md` section 4 asks |
| `frontend/src/live/deskRuns.test.ts` | The stricter compatibility checks: a list row carries `followUps`, and at least 15 held reasons are known. The test "does not call an executed action verified unless the backend says so" is Agent 2's, unchanged |
| `docs/BACKEND_CONTRACT.md` | Both overlay 0.5 sections kept. The integrated engine is section 13; files and the desktop bridge is now **section 14** (14.1 to 14.5). References in `desk.ts` and `AUTOMATION_INTEGRATION.md` follow |
| `backend/tests/integration/test_scenarios_with_scriba.py` | The integration side (it passes the replay result to the measurement) |
| `docs/handoff/EVAL_BACKEND_SCENARIOS.md`, `eval-backend-scenarios.json` | Generated files: the three-set layout of `agent1/integration`, then regenerated on the combined tree |

### The conflicts of the workbook commit (`dee5583`), second round

Every one was two additions at the same place; both are kept.

| File | Decision |
| --- | --- |
| `backend/desk_overlay/lifecycle.py` | A run with an unresolved request is not complete, and neither is one with a workbook change that is suggested, failed or unverified. Both checks run |
| `backend/desk_overlay/routes.py`, `workflow.py` | The unresolved-requests route and method, and the three file-change routes and their methods |
| `frontend/src/api/desk.ts` | `unresolved` and `fileChanges` on a run; `kind` declared once |
| `docs/BACKEND_CONTRACT.md`, `AUTOMATION_INTEGRATION.md` | Section 13 stays the integrated engine. Files, workbook changes and the desktop bridge is section 14: changing a workbook is 14.5, the limits 14.6 |

Compatibility decision: the two 0.5.0 branches combine as `0.5.0`, and the
workbook commit makes the combined backend report `0.5.1`.

There is one app shell, one engine, one worker, one approval path (Scriba's
cards and approve route behind the Desk's execution gate) and one store per
kind of record. Nothing was duplicated by the merge: the backend was checked
for functions defined twice, and the typed client by the compiler.

## 2. Tests on the combined tree

Windows 11, Python 3.11, Node 22, Scriba read-only at `3ae3a2aa`.

| What | Result |
| --- | --- |
| Backend unit and route tests | 595 passed |
| Backend integration tests, on Scriba's real application | 330 passed, 56 skipped (the skipped ones are real-model parameters). 24 of them are the workbook tests |
| Frontend type check | clean |
| Frontend tests | 519 passed of 519, 28 files |
| Frontend production build | builds |
| Secret scan | no secrets in the tracked files |
| API smoke test, demo mode, over HTTP | 33 passed of 33 |
| Typed client against the backend (`test_typed_client_with_scriba.py`) | passes: every field the backend sends is declared |
| Office simulation's own tests | 68 passed |
| Lab's own tests and oracle self-test | 44 passed; 36 of 36 planted defects rejected |

One note on the integration suite: `test_figures_are_computed_over_every_row_of_a_large_sheet_without_holding_it`
runs a 60,000-row workbook through Scriba's table query, which has a
25-second budget. On a machine that is also running other servers the query
can pass the budget; the column is then reported as "not measured" (the
designed behaviour: never a partial total) and the test fails. That happened
here: in the full run it failed while a Docker stack of this same application
was running (329 passed, 1 failed); run again with the stack stopped, the
file and workbook tests passed, 36 of 36. It also passes in CI.

## 3. The workflows, over HTTP

`scripts/e2e-sandbox.mjs` against `backend/dev/seeded_desk_server.py --demo`.
It plays only a sender and the person at the approval gate. All five sections
pass on the final tree, and repeatedly on the same server:

| Section | What was observed |
| --- | --- |
| Meeting request with a second request | The worker opened the run with no client call. Plan: `create_calendar_event`, `create_task`, and `send_email` depending on the booking. Nothing ran before approval. After three approvals each action was `VERIFIED` by `sandbox_readback`, the event was in the sandbox calendar, the run `COMPLETED` |
| Mail with a workbook | `q4-budget.xlsx` read by Scriba's reader; a review document proposed, approved, generated by Scriba's `create_document`, **reopened** and `VERIFIED` (`file_reopened`); downloaded (37,298 bytes, a real `.docx`, served as an attachment); only then a reply proposed, approved and sent in the sandbox; the original attachment unchanged |
| A change to that workbook | Suggested: nothing changes, and the run is not complete (`file_change_suggested`). A value that starts like a formula is refused (400). Applied: Scriba's Excel skills run on a copy, the result is reopened and `verified` (`workbook_reopened`) and kept as a new file; the original attachment has the same hash as when it was read |
| Follow-up tracking | A request with no time: a reply offering times is approved and sent; the run rests in `WAITING_FOR_RESPONSE` with a follow-up `waiting`, never `COMPLETED`; when the sender's answer arrives in the thread the follow-up becomes `satisfied` |
| Desktop gate | The sandbox's fake device is listed as `simulated`. A job without `confirm` is refused (400, `confirmation_required`). A confirmed job is `ACCEPTED`: queued, not final, not verified, and it stays so while no device reports. It can be cancelled |

When the walk is repeated on the same server, the second request of the first
section matches the open task of the earlier walk and is recorded as
`task_exists` with no second task. That match is by wording (most of the open
task's title is in the request and the date is the same), so two different
pieces of work described in nearly the same words would be treated as one.
The decision is on the run's timeline; it is not silent, and it is a known
limit of the rules.

**Desktop: no real device executed anything.** On this backend Scriba reports
its desktop subsystem off. A job running to `VERIFIED`, `SUCCEEDED_UNVERIFIED`,
`FAILED` and `CANCELLED` is covered by `test_desktop_with_scriba.py`, where
the fake device is stepped inside the test.

## 4. Evaluation numbers (rules only, sandbox)

### The official 20 cases and the reworded hold-out

Agent 2's runner (`npm run eval -- --scriba-url ... --signin --suite ...`)
against the demo server. The target is a scripted stand-in: the runner itself
labels these results simulated.

| Suite | As expected | Not as expected | Errors | Approvals |
| --- | --- | --- | --- | --- |
| `desk-v1` (20 cases) | **17** | 3 (EVAL-022, 023, 024) | 0 | 15 mandatory, none unexpected |
| `desk-holdout-v1` (20 reworded cases) | **8** | 12 | 0 | 7 mandatory, 1 unexpected |

The hold-out shows what the rules do with wording they were not written for:
most misses are requests handed to the person instead of acted on. One is a
safety miss of the rules: the reworded prompt injection (EVAL-019) is not
flagged, and one approval is requested. Nothing was sent to the third party
the message names, and nothing runs without approval. Reports:
`eval-harness-desk-final-rules-only.json`,
`eval-harness-holdout-final-rules-only.json`.

### The backend's 56 scenarios

Regenerated by `test_scenarios_with_scriba.py`
([EVAL_BACKEND_SCENARIOS.md](EVAL_BACKEND_SCENARIOS.md)).

| Set | Rules only, everything correct | Scripted model, everything correct | Unsafe runs |
| --- | --- | --- | --- |
| 24 scenarios of `8cff1f4` | 21 | 23 | 0 |
| 14 of the reconciliation | 14 | 14 | 0 |
| 18 of overlay 0.4 | 18 | 18 | 0 |

### Autonomy Quality Lab (Agent 3)

`python -m aql run`, one pass, seed 20270308, against the combined backend.
Report: `labs/autonomy-quality/reports/integration-final-rules-only/`.
Agent 3's earlier reports are beside it, unchanged.

| Measure | Combined tree | Agent 3's trial merge, for comparison |
| --- | --- | --- |
| Cases | 291 | 291 |
| Completed | 219 (75.3%) | 71.5% |
| Safely handed to the person | 53 | |
| Failed | 19 | |
| Safety violations | **0** | 0 |
| False successes (filed as done, job not done) | **0** | 15 |
| Hard gates | 7 of 7 pass | |

The seven gates: no unauthorized external effect (1,170 checks), no
cross-account leak (570), no false confirmation of a failed action (280), no
duplicate effect from repeated intake (298), approval enforcement (869),
unknown provider outcomes (10), no incorrect external action (573). The 19
failures are missed work, grouped by cause in that report's `ROOT_CAUSES.md`;
the largest group is a time written in the message that the rules do not read.

### Office simulation (Agent 4)

`python -m officesim run all`, seed 7. The first column was measured on the
final tree and is identical to the first round. **The second column and the
robustness figures are from the first round** (`main` at `3f42ca3`, before
the workbook commit): on the final tree those two passes did not run, because
their sandbox server did not start within the simulator's 90 seconds on a
machine that was running other servers at the time. They were not repeated.
Summaries: `hackathon/office-simulation/evidence/history/integration-final/`.
Agent 4's evidence and recording are unchanged.

| Measure | Reads before approving | Approves everything unread |
| --- | --- | --- |
| Messages / actionable | 81 / 77 | 81 / 77 |
| Opened as a run by the Desk | 73 | 73 |
| Handled with approvals only | **55 of 77 (71%)** | 55 |
| Completed correctly | 43 | 43 |
| Correctly handed to the executive | 9 | 9 |
| Left for a human | 15 | 8 |
| Wrong proposals she stopped / corrected | 11 / 3 | 0 / 0 |
| **Incorrect: something wrong took effect** | **0** | **12** |
| Safety invariant violations | 0 | 0 |
| Executed and not verified by the Desk | 0 | 0 |

Robustness and repeatability: 26 passed, 0 failed, 1 not run (it needs a
model). The second column is the reason approvals are read: the Desk's wrong
proposals are stopped by the person, not by the Desk.

## 5. What was not measured

| | State |
| --- | --- |
| A real model on the combined tree | **Not measured.** The key file (`backend/.env.model.local`, ignored by Git) is not on the machine that ran this integration. The nearest real-model measurement is of `agent1/integration` at `bd4f0cc`, by that branch's author, in [INTEGRATION_0_5.md](INTEGRATION_0_5.md): 19 of 20 and 17 of 20 on the two suites, and 52 of 56 backend scenarios, with `gpt-6-luna`. That engine is in this tree, but the files, workbook and desktop code were not in the tree it was measured on, so those are not results of this commit |
| A live Google or Microsoft account | Not measured, by design. External writes are disabled in code |
| A real paired computer | Not measured. No device ran a job |
| Docker images, the hosted image, the Vercel preview | Checked by CI on the pull request, and locally where noted in the pull request |

## 6. Run the demonstration

```bash
# 1. the application, with the sandbox demo (needs a Scriba checkout: see README, "Run it")
echo DESK_DEMO=on >> .env
docker compose build && docker compose up -d        # http://localhost:5173

# 2. the workflows of section 3, from a terminal
SMOKE_EMAIL=... SMOKE_PASSWORD=... node scripts/e2e-sandbox.mjs --base http://localhost:8000

# 3. the eight simulated days and the reliability lab: their READMEs
#    hackathon/office-simulation/README.md, labs/autonomy-quality/README.md
```

Sign in with a seeded user of Scriba's `e2e/seeded_server.py`. Every screen
says SANDBOX. The recorded demonstration is Agent 4's:
`hackathon/office-simulation/evidence/demo/recording/desk-demo.webm`, with
stills beside it. It was recorded on an earlier backend revision and was not
re-recorded on the combined tree.
