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

## Measured on one commit, `bd4f0cc`

Everything in a sandbox; external writes off; no live mailbox or calendar.

| Check | Result | Mode |
| --- | --- | --- |
| Backend suites | 869 passed, 56 skipped | no model |
| Frontend | type check clean, 452 of 452 tests, build passes | |
| API smoke on the demo backend | 33 of 33 | no model |
| Backend scenarios (56) | rules 53, scripted model 55, real model 52; **0 unsafe in every mode** | sandbox |
| Official 20 cases | **19 of 20** | real model `gpt-6-luna`, one run |
| Reworded hold-out | **17 of 20** | real model, one run |
| Agent 3's lab, 291 items | 218 completed, 54 handed over, 19 failed, **0 unsafe, 0 false successes** (15 on their trial merge); 7 of 7 gates pass | rules only |
| Agent 4's eight workdays | 55 of 77 with approvals only (54 before), **0 incorrect, 0 invariant violations** | rules only |
| Mutation check | 55 planted, 55 caught | |
| Autonomous path demo | worker, model, checked plan, approval, sandbox execution, read-back, follow-up, completed | real model |

Real-model figures are one run per case and vary: across the five integration
commits measured the official suite scored 19, 19, 18, 18, 19 and the
hold-out 17, 17, 17, 15, 17.

## What a reviewer should know

- **More runs are handed to the person on a rules-only backend.** That is
  the policy: unknown is not "done".
- **Not verified:** a live provider, Postgres, more than one model run per
  case, the lab and the simulation with a model (both are rules-only tools).
- **Frontend wording** for six held reasons and the escalated follow-up
  state is the backend owner's first draft and wants Agent 2's eye.
- Two behaviours change for a client compared with `main`: repeats are
  `COMPLETED`, and unplaced mail is `ESCALATED`.

No external write is possible from this branch. ScribaAssist/Scriba was not
changed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
