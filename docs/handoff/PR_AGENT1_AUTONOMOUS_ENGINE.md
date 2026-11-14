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
- **Bounded model step**, off by default, scripted tests only.
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

- Backend: 505 tests pass, 130 of them on the real Scriba application at
  `3ae3a2a` with providers replaced by an isolated world.
- Mutation check on the safety guards: 30 planted, 28 caught at once, 2 survivors now tested (`docs/handoff/MUTATION_CHECK.md`).
- API smoke on the seeded demo backend: 33 of 33.
- Frontend: type check clean, build passes, 369 tests pass, 3 fail (above).
- Agent 2's runner against `/desk/eval/v1`: 20 executed, 0 skipped. Rules
  only, labelled simulated: 10 of 20 on `desk-v1`, 5 of 20 on the held-out
  rewording.

## Not verified

No real model, no live mailbox or calendar, no Postgres database. No external
write is possible from this branch. ScribaAssist/Scriba was not changed.
