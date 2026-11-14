# Integration requests

For the backend owner (Agent 1) and the frontend owner (Agent 2). Each item
says what the simulator does today without it, and what would change. The
evidence behind every item is in [FINDINGS.md](FINDINGS.md). Nothing in the
backend or the frontend was edited from this workstream.

## What the simulator depends on today

It was built against `agent1/autonomous-engine` at `0282558` and runs unchanged on
`agent1/engine-reconciliation` at `f06a258` (overlay 0.3.1, where it reads
`action.effectiveInput`) and on `agent1/autonomous-engine` at `e080c82`. It uses:

- Scriba: `POST /auth/signin`, `GET /chat/tool-calls/{id}`,
  `POST /chat/tool-calls/{id}/approve | cancel | retry`
- Desk overlay: `GET /desk/health`, `GET /desk/runs`, `GET /desk/runs/{id}`,
  `POST /desk/runs/{id}/advance`, `POST /desk/intake`,
  `POST /desk/intake/sweep`, `GET /desk/briefing`, `GET /desk/follow-ups`,
  `GET /desk/worker`, `GET /desk/sandbox`
- In process, imported and not copied: `desk_overlay.install`,
  `desk_overlay.sandbox.SandboxWorld` and `WorldRegistry`,
  `desk_overlay.worker.IntakeWorker`, `desk_overlay.claims.SqliteClaims`,
  and the seeded-store shims in `backend/dev/seeded_desk_server.py`

**It cannot run on `main`** (`2d70a29`): `main` has no sandbox world, no
execution gate and no worker. `python -m officesim doctor` says so and names
the missing modules. Until the engine branch is merged, point
`DESK_BACKEND_PATH` at a checkout of it.

## For the backend owner

### A. Sandbox control over HTTP (the smallest interface the simulator needs)

The engine has no route to move a world's clock or to seed and inspect it,
so the simulator starts the backend itself (`officesim/sandbox_server.py`)
and mounts its own control routes (`officesim/control.py`) on the same
application. They touch only the sandbox world and the worker object. If the
engine offered these, the simulator's server wrapper could be deleted and
the frontend could drive a demo without it:

| Needed | Today (simulator's own route) | Engine call it wraps |
| --- | --- | --- |
| Set the world's clock, forward only | `POST /sim/clock {now}` | `SandboxWorld.set_now` |
| Deliver a message with a chosen id, mailbox and received time | `POST /sim/deliver` | `SandboxWorld.deliver` (the existing `POST /desk/sandbox/deliver` fixes none of the three) |
| Arm a provider fault; make a calendar or mailbox unreadable | `POST /sim/fault`, `POST /sim/unreadable` | `SandboxWorld.add_fault`, `.unreadable` |
| Run one worker pass now | `POST /sim/worker/tick` | `IntakeWorker.tick` |
| Read the whole world: mail, sent, events, tasks, reminders, awaited replies | `GET /sim/state` | `GET /desk/sandbox` returns counts and the operation log only |
| Build a world from a specification at start | `control.build_world` | `demo_world.py` builds a fixed one |

Two notes from using them. The worker's back-off runs on the real monotonic
clock, so a simulated day has to clear it after a mailbox outage
(`/sim/worker/tick` does). And `recover_stale` compares the world's clock
with the card's real `updated_at`, which mixes the two clocks.

### B. Defects to fix (in the order of FINDINGS.md)

Status on `f06a258`: items 1, 2 and 3 are fixed. Two cases appeared with
those fixes and are worth a test each: a new call "right after the
quarterly review" is proposed as a move of the review; and "please disregard
my last message ... could we meet on Wednesday at 14:00" is held as
contradictory. When the two backend branches are combined, `e080c82` still
has items 1 and 3 (FINDINGS.md, "Status by backend revision").

1. Carry an approve-time edit into the card's effective input, so that the
   confirmation states the edited time and verification compares against it.
2. A change request whose target was already cancelled must not fall back to
   the sender's other meetings; and a meeting in the past is not a candidate.
3. Recognise "move tomorrow's ... to 15:00" (and similar) as a change, or
   refuse to create an event when the sender is already on a meeting with
   the same subject at another time.
4. Offer times with a lead time and on a grid, and prefer times near the day
   that was asked for.
5. Give the reminder for an overdue follow-up its recipient.
6. Close an awaited reply whenever its answer arrives, whatever the
   message's category; do not propose a meeting reply for it.
7. Let awaited replies that predate the Desk become overdue and appear in
   `/desk/follow-ups`.
8. Briefing: add what was handled, what is awaited, what is overdue; count
   only mail that still needs something; give meetings their times.

### C. Smaller requests

- Record `step_blocked` when the rejection happens, without a client call.
- Record one execution and one verification per attempt after a recovery.
- Answer `GET /calendar/events` and `GET /tasks` from the sandbox world when
  one is in force, so the frontend's Calendar and Tasks screens show it.
- A way to tell a held card from an incomplete one in `actionCounts`
  (`needs_info` covers both today).

### D. Not measured, and why

No model credential exists in this environment. `DESK_MODEL=on` with a real
key, `DESK_UNDERSTANDING=model` and `DESK_AGENT=on` in the environment are
passed through to the sandbox backend unchanged, so the same eight days can
be replayed with a model:

```bash
DESK_MODEL=on DESK_UNDERSTANDING=model DESK_AGENT=on python -m officesim run all --out evidence-model
```

This has not been tried: it is the intended way, not a tested one. Mail in
the sandbox is synthetic; that is all a model would see. The replay log
records every decision, so the variance between two model runs can be read
line by line.

## For the frontend owner

Seen with `origin/agent2/frontend-excellence` at `d60b892`, unmodified,
against the sandbox:

- Works: sign-in, overview, inbox, work queue, run detail with plan and
  evidence, approval center with "Approve in sandbox", find a time. A real
  click on Approve executed in the sandbox and the run completed.
- Calendar and Tasks read Scriba's own routes and show nothing of the
  sandbox world (request C above, or read the Desk routes on those screens).
- The cancel card shows "No title on the card"; the backend sends
  `event_title`.
- After one of two actions has executed, the run detail's top panel still
  says nothing has happened.
- The sidebar says "Live: Scriba" in green while every write is a sandbox
  write. A sandbox marker on Overview, Inbox, Find a time and executed
  Activity cards would make captures self-labelling; the capture script adds
  its own bar meanwhile.
- Scriba's seeded cards (unrelated to the Desk) are counted in the
  Approval-center badge and listed under "Handled by the secretary".
- Card dates come from the seeded store ("Wed 15 Jul"), not the sandbox clock.

To run it: `VITE_API_BASE_URL=http://localhost:8914 npx vite --port 5183
--strictPort --host localhost`, with the sandbox started through
`python -m officesim demo --browser --frontend http://localhost:5183` or
`ALLOWED_ORIGINS=http://localhost:5183 python -m officesim serve`.

## For the project lead

- The index card's job-holder is still a placeholder. The human-time figure
  in the reports is an assumption until a real job-holder supplies minutes
  per task; it must not be presented as time saved.
- Tasks and reminders: approval required, or automatic? The product asks;
  the evaluation contract does not. The simulation ran with approvals
  required.
- A silent, captioned recording of the workflow in the Desk frontend exists
  (`evidence/demo/recording/desk-demo.webm`). No narrated video has been
  recorded; see [DEMO_STORYBOARD.md](DEMO_STORYBOARD.md).
