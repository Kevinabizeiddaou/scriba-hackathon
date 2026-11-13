# Scriba Executive Desk: frontend and evaluation workspace

The Role 2 workspace for a private simulation of the AlphaHack 2026 AI Agent Challenge (13 to 15 November). It is not an official competition entry.

Scriba Executive Desk is an AI executive secretary: it reads incoming meeting requests, checks the calendar, schedules or reschedules, drafts replies, asks a human before anything is sent or changed, and records what it did.

This folder holds the interface, a mock API, twenty synthetic test cases and an evaluation runner. It has no backend and no agent logic; those are Role 1's. Everything here runs on scripted mock data until the real backend is connected.

## Run it

Developed and tested on Node 22.

```bash
npm install
```

```bash
npm run dev
```

Open http://localhost:5183. The sidebar shows "Mock data" while the mock adapter is active.

| Command | What it does |
| --- | --- |
| `npm run dev` | Start the app on port 5183 with the mock adapter |
| `npm test` | Run the 79 unit and UI tests |
| `npm run build` | Type-check and build to `dist/` |
| `npm run eval` | Harness self-test against the scripted mock |
| `npm run eval -- --base-url <url>` | Run the twenty cases against a real backend |
| `npm run fixtures:export` | Rewrite `fixtures/evaluation-cases.json` from the TypeScript fixtures |
| `npm run docs:generate` | Rewrite `docs/TEST_CASES.md` and `docs/API_EXAMPLES.md` |

## The four screens

- **Secretary Chat** (`#/chat`): conversation history, the agent's steps as they run, and approval requests inline.
- **Request Inbox** (`#/inbox`): incoming requests with classification, priority, flags, extracted meeting details, processing status, agent activity and history.
- **Approval Center** (`#/approvals`): each proposed email and calendar change, why the agent proposes it, approve and reject, and what was executed.
- **Evaluation Dashboard** (`#/evaluation`): the twenty cases, expected versus actual, traces, and Friday, Saturday and Sunday snapshots.

Screenshots of each screen on mock data are in [docs/screenshots](docs/screenshots).

## Mock data and real data

The UI talks to one interface, `ExecutiveDeskApi` in `src/api/client.ts`. `src/api/index.ts` picks the implementation:

| `VITE_API_MODE` | Implementation | Behaviour |
| --- | --- | --- |
| unset or `mock` | `src/api/mock/mockAdapter.ts` | Replays hand-written scripts in memory. No network. Every side effect is marked simulated. |
| `http` | `src/api/httpAdapter.ts` | Calls the backend at `VITE_API_BASE_URL`. See `docs/INTEGRATION_HANDOFF.md`. |

The mock cannot send email or change a calendar: it contains no network code, and a test asserts `fetch` is never called.

## Evaluation numbers

The dashboard shows a pass rate, intervention count, cost and latency only for a run against a live backend. Until one exists, those tiles show a dash.

"Run harness self-test" points the runner at the scripted mock. It checks the harness, not the agent: the twenty reference scripts must score as passing, and twelve deliberately broken scripts must each be caught by the intended check. Its output is labelled as simulated, never fills the headline tiles, and cannot be saved as a snapshot.

Cost is never estimated from assumed prices. `src/evaluation/pricing.ts` ships with an empty price table. See `docs/submission/COST_PER_RUN.md`.

## Layout

```
src/api/            contract types, client interface, mock and HTTP adapters
src/evaluation/     fixtures, matchers, scorer, runner, report, self-test
src/pages/          the four screens
src/components/     shared UI
scripts/            eval CLI, fixture export, doc generation
fixtures/           evaluation-cases.json (generated)
eval-results/       reports (ignored) and snapshots/ (committed)
docs/               API contract, examples, test cases, handoff, submission drafts
```

## Documents

- [docs/API_CONTRACT.md](docs/API_CONTRACT.md): endpoints, types and state transitions
- [docs/API_EXAMPLES.md](docs/API_EXAMPLES.md): JSON examples (generated)
- [docs/TEST_CASES.md](docs/TEST_CASES.md): the twenty cases in full (generated)
- [docs/INTEGRATION_HANDOFF.md](docs/INTEGRATION_HANDOFF.md): what Role 1 needs to provide and confirm
- [docs/submission/](docs/submission): index card, demo storyboard, cost template, voice-note questions, presentation outline

All fixture people, companies, emails and calendar entries are invented. They are development fixtures, not customer cases.
