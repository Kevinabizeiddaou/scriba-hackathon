# Integration handoff: Role 2 to Role 1

The frontend and the evaluation system are ready to be connected to the Scriba backend. They have never been connected to it: everything here was built and tested against a scripted mock and against a reference server that speaks the contract over real HTTP.

No real evaluation has been run. There is no pass rate, cost or latency figure yet.

## Read these, in this order

| # | Document | What it is |
| --- | --- | --- |
| 1 | [API_CONTRACT.md](API_CONTRACT.md) | The final contract, version 1.0.0: endpoints, types, errors, states, idempotency, auth, traces and metrics |
| 2 | [handoff/BACKEND_REQUIREMENTS.md](handoff/BACKEND_REQUIREMENTS.md) | What the backend must provide, as a numbered list with how each item is verified |
| 3 | [handoff/ASSUMPTIONS.md](handoff/ASSUMPTIONS.md) | The assumption register and the fields Role 1 must confirm |
| 4 | [handoff/CONNECTING.md](handoff/CONNECTING.md) | Exact commands for connecting the backend, and what each should print |
| 5 | [handoff/INTEGRATION_CHECKLIST.md](handoff/INTEGRATION_CHECKLIST.md) | A tick list from handshake to first snapshot |
| 6 | [handoff/CODE_REVIEW_RESOLUTION.md](handoff/CODE_REVIEW_RESOLUTION.md) | The independent review: 20 findings and how each was resolved |
| 7 | [handoff/TEST_REPORT.md](handoff/TEST_REPORT.md) | What was run, and the results |

Reference material: [API_EXAMPLES.md](API_EXAMPLES.md) (real JSON for every type), [TEST_CASES.md](TEST_CASES.md) (the twenty cases in full).

## What exists

| Piece | Where | State |
| --- | --- | --- |
| Four screens | `src/pages`, `src/components` | Working on the mock, and over HTTP against the reference server |
| Contract | `src/api/types.ts`, `src/api/validate.ts` | Frozen at 1.0.0; not yet confirmed by Role 1 |
| Mock adapter | `src/api/mock/` | Scripted, no network code, every side effect simulated |
| HTTP adapter | `src/api/httpAdapter.ts` | Implements the contract: handshake, auth, idempotency keys, timeout, retries, validation. Tested over real HTTP. Never run against the real backend. |
| Reference server | `src/api/reference/`, `npm run contract:server` | The contract served by the scripted mock, with fault injection for tests |
| Evaluation cases | `src/evaluation/fixtures`, `fixtures/evaluation-cases.json` | Twenty synthetic cases, labelled as such |
| Evaluation runner | `src/evaluation`, `npm run eval` | Runs against the mock or any HTTP backend; writes JSON and JUnit reports |

## The three things that need Role 1 most

1. **A sandbox evaluation mode** (requirements group C). The cases cannot be run safely without injected calendars and a guarantee that nothing real is sent.
2. **`GET /meta` that tells the truth** about whether a real agent is behind the URL and whether it is a sandbox. Every "live" label and the runner's refusal to touch a non-sandbox service depend on it.
3. **The approval gate as specified** (contract 8.4): a person approves, the agent never approves its own request, and what runs is exactly what was approved.

## Boundaries kept

- The Scriba repository was read only for its visual theme. Nothing in it was modified; no secrets, production data or deployment configuration were copied.
- This workspace contains no backend integration and no agent logic.
- Everything is inside `executive-desk/`, on the branch `role2/frontend-evaluation` of the shared repository. It has not been merged into `main`.
- All fixture people, companies and addresses are invented and use the reserved `.example` domain.
