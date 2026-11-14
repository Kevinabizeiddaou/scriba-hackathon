# Office simulation

A fictional executive office, a controlled clock and a stream of incoming
work, played against **the Desk's real workflow** in an isolated sandbox.
It answers one question with evidence: when a working day's worth of mail
arrives, how much of the executive assistant's job does Scriba Executive Desk
actually do, and what does a person still have to do?

> **Everything here is simulated.** The office, its people and its mail are
> invented, every address is under the reserved `.example` domain, the
> mailboxes and calendars are the Desk's sandbox world, and nothing was sent
> anywhere. **No model was called**: the Desk ran on its rules, so no number
> here is a result about a model-driven agent. No live Google or Microsoft
> account was read or written.

The measured results are in [evidence/RESULTS.md](evidence/RESULTS.md), which
is generated from the evidence files. What the simulation found wrong is in
[docs/FINDINGS.md](docs/FINDINGS.md).

## What it is, and what it is not

The simulator is **not a second agent**. It plays two roles the Desk does not:

- **the outside world**: people write to the executive, providers fail, time
  passes;
- **the executive**: she approves, rejects or edits what the Desk proposes.

The work in between is done by the Desk's own code (the evidence here was
produced on `agent1/engine-reconciliation` at `f06a258`; it also runs on
`agent1/autonomous-engine`): the background intake worker, triage, the typed
plan, Scriba's approval cards and approve route, the execution gate, the
sandbox world and verification. The simulator then reads the sandbox world's
state and judges, message by message, whether the right thing happened.

```
 scenario step ──► /sim/clock, /sim/deliver, /sim/fault      (the outside world)
                        │
                        ▼
            Desk intake worker ─► run ─► plan ─► approval cards      (the Desk)
                        │
 simulated executive ──► POST /chat/tool-calls/{id}/approve | cancel | retry
                        │                                    (Scriba's own route)
                        ▼
        execution gate ─► sandbox world ─► verification ─► follow-on step
                        │
 oracle ◄── GET /sim/state, GET /desk/runs/{id}         (what really happened)
```

It never writes a run, a card, an approval or an outcome.

## Run it

You need a Scriba checkout (read only), the Desk backend with the sandbox
engine, and a Python that has Scriba's dependencies. Put the three paths in
`.officesim.local.json` (untracked) or in the environment:

```json
{
  "SCRIBA_BACKEND_PATH": "<Scriba checkout>/Gmail",
  "DESK_BACKEND_PATH": "<checkout of the engine branch>/backend",
  "SCRIBA_PYTHON": "<python with Scriba's dependencies>"
}
```

`DESK_BACKEND_PATH` defaults to this repository's own `backend/`, which works
once the engine branch is merged. Then, from this directory, with that Python:

```bash
python -m officesim doctor            # what is configured, what is missing
python -m officesim demo              # the replayable demonstration (about 40 s)
python -m officesim run normal        # one simulated day, with evidence
python -m officesim run all           # all eight days and a combined summary
python -m officesim run all --executive trusting   # the same, approving everything unread
python -m officesim robustness        # replays, repeats, duplicates, failures
python -m officesim results           # regenerate evidence/RESULTS.md
python -m pytest tests -q             # the simulator's own tests
```

Each whole-day command starts its own clean sandbox backend on port 8914 and
stops it. A sandbox left by an interrupted run is stopped first.

### One step at a time

```bash
python -m officesim serve                         # start the sandbox and keep it running
python -m officesim status                        # health, clock, worker, world counts
python -m officesim clock 2026-11-16T08:30:20+01:00
python -m officesim inject --from mei --subject "Intro call" --body "Would you be free on Wednesday at 14:00 for 30 minutes?"
python -m officesim tick                          # one pass of the Desk's intake worker
python -m officesim runs                          # the Desk's runs
python -m officesim show 11                       # plan, actions, evidence timeline
python -m officesim approvals                     # what waits for the executive
python -m officesim approve 28                    # also: reject, retry, --overrides '{"start": "..."}'
python -m officesim state calendar                # also: inbox, sent, tasks, operations
python -m officesim briefing
```

### With the Desk frontend

```bash
# 1. the frontend, pointed at the demo's sandbox port
cd <frontend checkout>/frontend
VITE_API_BASE_URL=http://localhost:8914 npx vite --port 5183 --strictPort --host localhost
# 2. the demonstration, capturing the screens as the day goes
python -m officesim demo --browser --frontend http://localhost:5183
```

Screenshots go to `evidence/demo/screenshots/`, each with a visible
"SIMULATED" bar. See [browser/README.md](browser/README.md).

## The eight days

| Profile | What it exercises |
| --- | --- |
| `normal` | Weekend backlog, a conflict, a deadline, a reschedule, an awaited reply, an urgent decision, a cancellation, a preparation note, a silent supplier, a briefing |
| `busy` | Overlapping requests for the same slot, deadlines today, a meeting before working hours, a repeated cancellation |
| `multi_provider` | Gmail and Outlook mail, two Google calendars and one Outlook calendar; the right account for every event and reply |
| `unreliable` | A calendar outage, a mailbox outage, a failed write, two uncertain outcomes, a duplicate notification, a partial failure, a restart, an interrupted action |
| `human_in_loop` | Approvals, a rejected proposal, two edited proposals, a clarification asked of the sender, approvals that must be refused |
| `compound` | Single messages that need several dependent actions |
| `follow_up` | Awaited replies arrive; one request stays unanswered for two days and is chased; a deadline passes |
| `surprise` | Colloquial and French wording, a prompt injection, an ambiguous time zone, a legal notice, messages out of order, an empty message |

Later steps depend on earlier ones: a meeting booked at 08:30 is a conflict
at 15:00, and a client can only accept a time the Desk really offered.

## How honesty is enforced

- **The oracle reads the world, not the Desk's word.** A card that says
  "executed" for a meeting that is not on the calendar is judged incorrect.
- **Expectations are resolved against the live state.** "Book Wednesday 14:00,
  or offer other times if that is taken" becomes one or the other by the
  oracle's own overlap test at the moment the message arrives.
- **The executive never repairs silently.** Every decision is logged with a
  category. Approvals and her own preferences do not count against the agent;
  a wrong proposal she stops, a correction and a proposal she completes by
  hand do, and the outcome is then `corrected` or `rescued`, never `correct`.
- **Safety invariants are checked after every step**: sandbox isolation, one
  run per message, no write without a recorded approval, every effect in the
  world belongs to an approved action, no double booking, no duplicate event.
- **A stand-in backend that does nothing scores nothing.** `officesim/fakes.py`
  and the tests prove that every actionable request is then `missed`.
- **The human-time figure is an assumption** and is labelled as one wherever
  it appears.
- **No message was reworded after a run.** See the note at the top of
  `officesim/scenarios.py`.

## Layout

| Path | What it is |
| --- | --- |
| `officesim/jobmodel.py` | The ten steps of the secretary's job; the assumed human minutes |
| `officesim/office.py` | The fictional office: people, three mailboxes, three calendars, tasks, awaited replies. Deterministic ids, fingerprinted |
| `officesim/scenarios.py` | The eight days, each message with its hidden ground truth |
| `officesim/sandbox_server.py`, `control.py` | Starts the Desk's sandbox backend with the office in it; the `/sim/*` control routes (clock, delivery, faults, one worker pass, state) |
| `officesim/adapter.py` | The only HTTP client: Scriba's approve routes, `/desk/*`, `/sim/*`; the backend process |
| `officesim/runner.py` | The stateful runner: clock, delivery, intake, decisions, checks, invariants, replay log |
| `officesim/executive.py` | The simulated executive and the decision categories |
| `officesim/oracle.py` | Resolving expectations, verdicts, invariants |
| `officesim/metrics.py`, `report.py`, `results.py` | Measurement, per-day evidence and report, the combined results |
| `officesim/demo.py`, `robustness.py`, `cli.py` | The demonstration, the robustness suite, the command line |
| `officesim/fakes.py` | A backend that does nothing or misbehaves, for testing the simulator |
| `browser/` | Read-only Playwright capture of the Desk frontend |
| `tests/` | 63 tests of the simulator; one starts the real sandbox when it is configured |
| `evidence/` | Results of the runs: per day `report.md`, `summary.json`, `replay.jsonl`, `runs.json`, world state before and after |
| `docs/` | Job model, findings, integration requests, demo storyboard, submission evidence, differentiation |

## Documents

- [docs/JOB_MODEL.md](docs/JOB_MODEL.md): the job being automated, and the office
- [docs/FINDINGS.md](docs/FINDINGS.md): defects and gaps the simulation found
- [docs/INTEGRATION_REQUESTS.md](docs/INTEGRATION_REQUESTS.md): what is needed from the backend and frontend owners
- [docs/DEMO_STORYBOARD.md](docs/DEMO_STORYBOARD.md): the two-minute demonstration
- [docs/CHECKPOINT.md](docs/CHECKPOINT.md): the checkpoint package, with links to every workstream
- [docs/SUBMISSION_EVIDENCE.md](docs/SUBMISSION_EVIDENCE.md): the evidence pack
- [docs/DIFFERENTIATION.md](docs/DIFFERENTIATION.md): why this is more than a chatbot, claim by claim

## Limits of this simulation

- Rules only. No model was configured, so intent understanding, reply
  writing and the bounded model step were never exercised.
- A sandbox, not a provider. Google and Microsoft behaviour (invitations,
  threading, rate limits, permissions) is the sandbox world's approximation.
- One office, one author. The scenarios and the ground truth were written by
  one person who had read the Desk's rules; profiles A to G are well-formed
  requests. The independent adversarial evaluation is a separate workstream
  under `labs/autonomy-quality/`.
- The seeded backend keeps runs in memory, so a full process restart cannot
  be simulated: only the worker and its claim store are restarted.
- The Desk's Tasks, Calendar and Activity screens read Scriba's own stores,
  not the sandbox world, so they do not show the simulated office.
