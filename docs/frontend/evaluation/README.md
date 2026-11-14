# Recorded evaluation reports

Reports written by `npm run eval` and kept as evidence. Each file says in its own `target` block
what produced it; the evaluation screen reads that block, not the file name.

| File | What produced it | Result |
| --- | --- | --- |
| `rules-only-sandbox-overlay-0.3.0.simulated.json` | The desk suite (`desk-v1`, 20 cases) run on 14 November 2026 against the sandbox evaluation routes of Desk overlay 0.3.0 (`agent1/autonomous-engine` at `e86f449`), on the local seeded backend, with no model: `meta.agent` was `scripted` and the planner was rules alone | 10 passed, 7 failed, 3 could not be scored (`conversation_input_unsupported`), 0 safety violations |

This is a **scripted-model** result: real code and real safeguards in an isolated provider world,
but not the product's agent. It is simulated and must not be quoted as agent performance. No
real-model report exists.

To read it on the evaluation screen, use "Import results". It appears in its own panel and does not
change the headline numbers.

To reproduce: start the backend with `python backend/dev/seeded_desk_server.py --demo`, then from
`frontend/` run `npm run eval -- --scriba-url http://localhost:8788 --signin --suite desk` with
`EVAL_EMAIL` and `EVAL_PASSWORD` set to a seeded test user.
