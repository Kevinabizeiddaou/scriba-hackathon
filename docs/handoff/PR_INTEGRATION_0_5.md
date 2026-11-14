# Integrated autonomous backend (overlay 0.5) on the frontend of main

Branch `agent1/integration`, from `main` at `2df5550`. Merges
`agent1/engine-reconciliation` (`f06a258`) and `agent1/autonomous-engine`
(`2e77414`), then corrects three ways work was being lost without anyone
being told. Full account: `docs/handoff/INTEGRATION_0_5.md`.

## What is in it

- **Both engines, nothing dropped.** Overlay 0.3.1 (the action as approved,
  the explicit action lifecycle, retry modes, reader guards, the right
  meeting or none, unknown-outcome recovery) and overlay 0.4 (instructions in
  chat, dependent multi-step plans, model understanding, task completion,
  follow-up records, memory read from records). All 38 reconciliation
  scenarios and all 18 of 0.4: 56 scenarios, 56 distinct ids.
- **Work is not silently lost** (contract section 13):
  - a message from a person is filed only when "no work" is established;
    otherwise it is handed over;
  - a compound request is not complete while a part of it is open
    (`DeskRun.unresolved`, `lifecycle.reason: "unresolved_requests"`);
  - a holding reply does not satisfy a follow-up.
- **Eight defects found while testing the merged tree**, by Agent 3's lab,
  Agent 4's simulation and a real model, each fixed with a test.
- **The frontend on main passes against it.** The typed client declares
  everything the backend sends (checked by a backend test). Three small
  frontend edits, listed in `docs/handoff/AGENT2_INTEGRATION_0_5.md`:
  wording for new held reasons and the escalated follow-up state, and the
  three tests that pin the backend's source text.

## Measured on the head of this branch, `5b3a1d0`

`5b3a1d0` merges `main` at `326b15d` (Docker, CI, hosting, and main's own
merge of the engines). Its engine differs from `bd4f0cc`, where the full
round below was first run, by one retraction pattern taken from `main`.
Everything in a sandbox; external writes off; no live mailbox or calendar.
Evidence: `docs/handoff/integration-0.5/at-5b3a1d0/`.

| Check | `5b3a1d0` (head) | `bd4f0cc` | Mode |
| --- | --- | --- | --- |
| Backend suites | 869 passed, 56 skipped | same | no model |
| Frontend (main's, with the 0.5 client) | type check clean, 456 of 456 tests, build passes | 452 of 452 | |
| Secret scan (`scripts/check-no-secrets.mjs`) | clean | | |
| Backend scenarios (56) | real model 53 of 56; **0 unsafe** | real model 52; rules 53, scripted 55 | sandbox |
| Official 20 cases | **17, 19, 19** over three runs | 19 | real model `gpt-6-luna` |
| Reworded hold-out | **18, 17, 17** over three runs | 17 | real model |
| Agent 3's lab, 291 items | 219 completed, 53 handed over, 19 failed, **0 unsafe, 0 false successes**; 7 of 7 gates, both seeds | 218 / 54 / 19 | rules only |
| Agent 4's eight workdays | identical to `bd4f0cc`: **0 incorrect, 0 invariant violations** | 55 of 77 approvals only | rules only |
| Mutation check | 55 planted, 55 caught | same | |
| Autonomous path demo | | passes (worker, model, checked plan, approval, sandbox execution, read-back, follow-up, completed) | real model |

Real-model figures vary run to run: 222 model calls on `5b3a1d0`, none
failed. The one official run at 17 missed EVAL-015 because the model read a
resent request as information; it passed in the other two runs. EVAL-023
(a reply plus a task) fails every run and is the main open case.

**The hosted Desk** (https://scriba-hackaton.vercel.app, `main`, overlay
0.4) was checked read-only with a signed-in account: every page loads, no
failing request, no page wider than a phone, `externalWrites.enabled: false`,
execution held.

## What a reviewer should know

- **More runs are handed to the person on a rules-only backend.** That is
  the policy: unknown is not "done".
- **Not verified:** a live provider, Postgres, more than one model run per
  case, the lab and the simulation with a model (both are rules-only tools).
- **Frontend wording** for six held reasons and the escalated follow-up
  state is the backend owner's first draft and wants Agent 2's eye.
- Two behaviours change for a client compared with `main`: repeats are
  `COMPLETED`, and unplaced mail is `ESCALATED`.

## Merging redeploys the hosted Desk

`main` deploys the Desk to https://scriba-hackaton.vercel.app (API on
Railway, see `docs/DEPLOY.md`). The hosted site runs overlay 0.4 today;
merging this branch puts 0.5 there. That is the merger's decision, not this
branch's: nothing here was deployed. After a merge, `/api/health` should
answer 200 and `/api/desk/health` 401 without a session, as they do now.

No external write is possible from this branch. ScribaAssist/Scriba was not
changed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
