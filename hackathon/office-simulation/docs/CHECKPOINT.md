# Checkpoint package (14 November 2026)

Written from the office-simulation workstream. It gathers what exists across
the workstreams for the checkpoint and says, for every figure, who measured
it, on which commit, with which model and in which execution mode.

**Figures from different workstreams are separate measurements on different
cases. They are listed side by side and never added or averaged.**

The canonical index card (`docs/INDEX_CARD.md`) is not changed by this
package. The frontend was not edited from this workstream: its integration
with the backend's typed contract belongs to pull request 7 and its owner.

## The job, in one sentence

Scriba Executive Desk turns an executive's incoming correspondence into
verified administrative outcomes: it reads each message, works out what it
needs, coordinates the calendars, prepares the action, waits for the
executive's approval, carries it out, checks the result and follows up.

## Exact trigger

A new email arrives in the executive's Gmail or Outlook inbox. The Desk's
background intake worker opens a run for it; nobody asks.

Observed: in the recording, the worker opened the run 12 seconds after the
message was delivered (`trigger: "worker"`, worker on its own 15-second
timer). Every run in `../evidence/*/runs.json` has `trigger: "worker"`.

## Workflow

1. Incoming message
2. The worker picks it up: one run per message
3. Understanding: what kind of request, how urgent
4. Reads: the thread, every connected calendar, the open tasks
5. A typed plan: steps, what each depends on, facts, assumptions
6. Proposed actions, each waiting for the executive
7. Approval, per action, through Scriba's approve route
8. Execution (in the sandbox; real external writes are disabled)
9. Verification by reading the provider state back
10. Follow-on step, follow-up, completed status

## Definition of done

The right outcome is in the mailbox and on the calendar, once, on the right
account, with no double booking; nothing was sent or written without
approval; each action was verified; nobody had to repair anything
afterwards. Checked per message by the simulator's oracle against the
sandbox world's state ([SUBMISSION_EVIDENCE.md](SUBMISSION_EVIDENCE.md),
section 4).

## The official 20 use cases

`docs/frontend/TEST_CASES.md` on `main` (the frontend owner's suite
`desk-v1`), with its reworded hold-out `desk-holdout-v1`. They are not
restated here and were not run from this workstream.

## One reproducible end-to-end example

A client asks for a call on Wednesday at 14:00. The worker opens a run; the
Desk reads three calendars, plans "book, then confirm"; the executive
approves the booking; it is created in the sandbox and read back; the
confirmation is proposed, approved, sent in the sandbox and verified; the
run is completed.

- **Recording:** `../evidence/demo/recording/desk-demo.webm` (1:59, silent,
  captioned, one continuous take), with `desk-demo.json` (every step, id and
  server answer) and eleven stills. Frontend `298b7d6`, backend `f06a258`
  (overlay 0.3.1), model off, execution mode sandbox. The approvals are real
  clicks on "Approve in sandbox". The second half shows a request for a busy
  time answered with an offer of free times, and the run waiting for the reply.
- **Terminal:** `python -m officesim demo` replays a whole day (14 messages)
  and prints the outcomes confirmed in the sandbox.
- **To record it again:** `../browser/README.md`, "Recording a video".

More advanced, and passing on `f06a258`: a client answers the offer and the
Desk books the chosen time and closes the follow-up (`../evidence/normal/report.md`);
a time edited by the executive at approval is booked, verified and confirmed
at the edited time (`../evidence/human_in_loop/report.md`); a timed-out send
is settled by a read-back, not sent twice (`../evidence/unreliable/report.md`).
Not passing: one message with two requests (`../evidence/compound/report.md`).

## Latest test matrix

Each row is one measurement. Rows are not comparable with each other and are
not combined.

| Measurement | By | Backend commit | Model | Execution | Result | Source |
| --- | --- | --- | --- | --- | --- | --- |
| Office simulation: 8 days, 77 actionable requests | this workstream | `f06a258` (reconciliation, 0.3.1) | none (rules only) | sandbox | 54 handled with approvals only; 0 incorrect; 0 invariant violations | `../evidence/RESULTS.md` |
| The same days | this workstream | `e080c82` (autonomous-engine head, 0.3.0) | none | sandbox | 53; 0; 0 | `../evidence/RESULTS.md`, "By backend revision" |
| The same days | this workstream | `0282558` (0.3.0) | none | sandbox | 53; 0; 0 | `../evidence/history/0282558/RESULTS.md` |
| The same days, every proposal approved unread | this workstream | `f06a258` | none | sandbox | 13 requests end with something wrong | `../evidence/RESULTS.md` |
| Robustness and repeatability | this workstream | `f06a258` | none | sandbox | 26 passed, 0 failed, 1 not run (needs a model) | `../evidence/robustness/robustness.md` |
| Tests of the simulator | this workstream | `f06a258` for the live test | none | sandbox | 68 passed | `../tests/` |
| Demonstration recording | this workstream | `f06a258`, frontend `298b7d6` | none | sandbox | 3 approvals, 3 operations, all verified by read-back | `../evidence/demo/recording/desk-demo.json` |
| Official 20 cases and hold-out; 24 backend scenarios; with a real model | backend owner | stated in their document | `gpt-6-luna`, and rules only | sandbox | see their document | `docs/handoff/EVAL_CONFIGURED_MODEL.md` on `agent1/engine-reconciliation` |
| Engine and typed-client tests; contract reconciliation | backend owner | `f06a258` | none | sandbox | see their document | `docs/handoff/ENGINE_RECONCILIATION.md` on `agent1/engine-reconciliation` |
| Black-box quality lab | quality lab | `0282558` and `34ad288` | none | sandbox | see their document | `labs/autonomy-quality/docs/RESULTS.md` on `agent3/autonomy-quality` (pull request 9) |
| Frontend tests and the evaluation runner | frontend owner | their branch | | | see their document | `docs/frontend/AGENT2_FRONTEND_STATUS.md` on `agent2/frontend-excellence` (pull request 7) |

**Not measured anywhere in this package:** the official 20 cases and the
hold-out on the integrated backend `f06a258`. The earlier figures for those
suites belong to the commit they were measured on and must not be shown as
the integrated backend's result until they are re-run there.

## Human approval and rescue counts

Office simulation, `f06a258`, rules only, sandbox, an executive who reads
each proposal ([SUBMISSION_EVIDENCE.md](SUBMISSION_EVIDENCE.md), section 10):

| | Count |
| --- | --- |
| Approvals of a correct proposal | 72 |
| Her own rejections / edits | 3 / 2 |
| Wrong proposals stopped (rescues) | 12 |
| Corrected at approval / completed by hand | 1 / 1 |
| Retries after a provider failure | 6 |
| Requests left for a human | 19 of 77 |

An approval is not a rescue. The Desk asked 72 times and was right 72 times;
it was wrong 12 times and was stopped 12 times.

## Real-model sandbox performance

Measured by the backend owner with `gpt-6-luna` in the sandbox, on their
cases and the frontend owner's suites: `docs/handoff/EVAL_CONFIGURED_MODEL.md`
on the backend branch. That document states its own commit, runs and
variance; read the figures there.

**The office simulation has not been run with a model.** No model credential
was given to this workstream. The command is ready
([INTEGRATION_REQUESTS.md](INTEGRATION_REQUESTS.md), section D) and is untested.

## Known limitations

- The simulator's results are rules only. Understanding is brittle to
  wording; all four messages with two requests needed a person.
- Sandbox only. No live Google or Microsoft account; external writes are
  disabled by construction on every backend revision used.
- The two backend branches are not yet one. `f06a258` has the typed contract
  and three fixes that `e080c82` lacks; `e080c82` has follow-ups as records
  that `f06a258` lacks ([FINDINGS.md](FINDINGS.md), "Status by backend revision").
- Open defects on `f06a258`: offered times can start at the second of
  writing; the reminder for an overdue follow-up has no recipient; an
  awaited reply is recognised only when the message opens a run; the
  briefing does not report done, awaited or overdue work; a new call that
  mentions an existing meeting is proposed as a move of that meeting.
- Frontend `298b7d6` on `f06a258`: the workflow screens work and approvals
  are real. The Calendar, Tasks and Activity screens read Scriba's seeded
  stores, the sidebar says "Live: Scriba", the sandbox marker is missing on
  Overview and Inbox, and one stage name shown as the server's is an alias
  ([FINDINGS.md](FINDINGS.md), last section).
- The recording is silent. No narrated video exists.
- The job-holder on the index card and the weekly workload are not established.

## Links

- Repository: https://github.com/Kevinabizeiddaou/scriba-hackathon
- Office simulation, evidence and recording: pull request 8, https://github.com/Kevinabizeiddaou/scriba-hackathon/pull/8
- Frontend: pull request 7, https://github.com/Kevinabizeiddaou/scriba-hackathon/pull/7
- Quality lab: pull request 9, https://github.com/Kevinabizeiddaou/scriba-hackathon/pull/9
- Integrated backend: branch `agent1/engine-reconciliation`; newest engine work: branch `agent1/autonomous-engine`
- Recording: `hackathon/office-simulation/evidence/demo/recording/desk-demo.webm` on branch `agent4/office-simulation`
- Storyboard: [DEMO_STORYBOARD.md](DEMO_STORYBOARD.md); evidence pack: [SUBMISSION_EVIDENCE.md](SUBMISSION_EVIDENCE.md)
