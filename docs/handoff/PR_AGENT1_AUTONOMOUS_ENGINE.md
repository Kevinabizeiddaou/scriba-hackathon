# Pull request text: `agent1/autonomous-engine` into `main`

Title: **Autonomous secretary engine: worker, lifecycle, sandbox execution, evaluation routes (overlay 0.3)**

## What this does

Turns the Desk backend from "a client calls intake" into a worker that takes
mail in by itself, carries each request through a recorded lifecycle, and
executes approved actions against an isolated provider world. Real mail and
calendar writes stay off, enforced in the server.

- **Background intake worker** (opt-in, refuses production). One run per
  message through a claim store: Scriba's receipt ledger, a SQLite file, or
  memory.
- **Run lifecycle and evidence**: stages, reads, decisions, proposals,
  approvals, executions and verifications as separate timestamped events.
  `GET /desk/runs` rows now say where each run stands.
- **Workflows**: booking then confirmation; moving the original event (never
  a second one); cancellation; replies offering only verified free times;
  tasks with written deadlines; follow-ups.
- **Execution gate** on Scriba's approve, retry and cancel: sandbox world, or
  held with `external_writes_disabled`. `externalWrites.enabled` is false by
  construction.
- **Sandbox worlds** with a tripwire on real provider clients; unknown
  outcomes stay unknown and a retry reads back before repeating.
- **`/desk/eval/v1`** for the evaluation harness.
- **Typed plan per run**: intents with confidence and evidence, facts,
  assumptions, missing details, steps with dependencies. A dependent step is
  proposed only after its prerequisite took effect, and is blocked otherwise.
- **Model understanding** (opt-in): several intents per message; an intent
  that does not quote the message is dropped. Scripted tests only.
- **Approval binding**: a card changed behind the approval is held; a retry
  runs what the person approved. **Recovery** of actions left in flight.
- **Bounded model step**, off by default, scripted tests only.
- **24 backend scenarios** measured for rules, scripted model and one real
  model (`gpt-6-luna`, sandbox only): 20, 23 and 22 of 24 fully correct, no
  unsafe run on the final code. Agent 2's reworded hold-out: 5 of 20 on rules,
  10 of 20 with the model. Six defects the real model exposed are fixed. See `docs/handoff/EVAL_CONFIGURED_MODEL.md`.
- `frontend/src/api/desk.ts`: 0.3 fields added as optional.

Contract: `docs/BACKEND_CONTRACT.md` sections 6 to 11. Status, limits and
numbers: `docs/handoff/AGENT1_BACKEND_STATUS.md`.

## Before merging

**Three pinned frontend tests fail on this branch by design**
(`frontend/src/live/deskRuns.test.ts`): the run list now carries `state`, a
partly executed action is `partial`, and there are new hold reasons. They
need Agent 2's mapping update; merge the two together. Details in section 5
of the status report.

## Verified

- Backend: 590 tests pass, 188 of them on the real Scriba application at
  `3ae3a2a` with providers replaced by an isolated world.
- Mutation check on the safety guards: 38 planted, 36 caught at once, 2 survivors now tested (`docs/handoff/MUTATION_CHECK.md`).
- API smoke on the seeded demo backend: 33 of 33.
- Frontend: type check clean, build passes, 380 tests pass, 3 fail (above).
- Agent 2's runner against `/desk/eval/v1`: 20 executed, 0 skipped. Rules
  only, labelled simulated: 10 of 20 on `desk-v1`, 5 of 20 on the held-out
  rewording.

## Not verified

No live mailbox or calendar, no Postgres database. A real model was run in
the sandbox only, once per case. No external
write is possible from this branch. ScribaAssist/Scriba was not changed.


## Added after `8cff1f4`: overlay 0.4

- **Instructions in chat** (`POST /desk/commands`): a reminder, moving or
  cancelling a meeting and telling its attendees, chasing overdue replies.
  Dependent steps wait for the step they depend on; recipients come only from
  calendar and follow-up records.
- **Finishing an existing task** when a message reports it done; **repeated
  requests** recognised and not acted on twice; **several requests** in one
  message, each with its own deadline.
- **Memory read from records** (`GET /desk/memory`); **follow-ups as
  records** with one reminder at most and escalation after it.
- **Mail the Desk cannot place is handed over**, not filed as done.
- Measured with a real model in the sandbox, one run per case: Agent 2's
  visible suite 18 of 20 and hold-out 18 of 20 (11 and 10 before), my 42
  scenarios 38 fully correct, no unsafe run. Backend tests: 739 passed.
- Contract section 12; `docs/handoff/EVAL_COMPARISON_0_4.md`;
  `docs/handoff/AGENT2_INTEGRATION_0_4.md`. Two behaviours changed for a
  client: repeats are `COMPLETED`, and unplaced mail is `ESCALATED`.
