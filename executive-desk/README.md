# Scriba Executive Desk: frontend and evaluation workspace

The Role 2 workspace for a private simulation of the AlphaHack 2026 AI Agent Challenge (13 to 15 November). It is not an official competition entry.

Scriba Executive Desk is an AI executive secretary: it reads incoming meeting requests, checks the calendar, schedules or reschedules, drafts replies, asks a human before anything is sent or changed, and records what it did.

This folder holds the interface, the API contract, a mock and a reference server for it, twenty synthetic test cases and an evaluation runner. It has no backend and no agent logic; those are Role 1's. Everything here runs on scripted data until the real backend is connected, and it has never been connected to one.

To connect a backend, start at [docs/INTEGRATION_HANDOFF.md](docs/INTEGRATION_HANDOFF.md).

## Run it

Developed and tested on Node 22.

```bash
npm install
```

```bash
npm run dev
```

Open http://localhost:5183. The sidebar shows "Mock data" while a scripted agent is behind the app.

| Command | What it does |
| --- | --- |
| `npm run dev` | The app on port 5183 with the in-memory mock |
| `npm run dev:reference` | The app on port 5184 talking over real HTTP to the reference server on port 8787 |
| `npm run contract:server` | The reference server alone: the contract served by the scripted mock |
| `npm test` | Unit, UI and HTTP integration tests |
| `npm run build` | Type-check and build to `dist/` |
| `npm run eval` | Harness self-test: reference scripts and planted defects |
| `npm run eval -- --target mock` | Run the cases against the scripted mock and write a report |
| `npm run eval -- --base-url <url>` | Run the cases against a backend over HTTP |
| `npm run fixtures:export` | Rewrite `fixtures/evaluation-cases.json` from the TypeScript fixtures |
| `npm run docs:generate` | Rewrite `docs/TEST_CASES.md` and `docs/API_EXAMPLES.md` |

The options of `npm run eval` are listed at the top of [`scripts/eval.ts`](scripts/eval.ts) and explained in [docs/handoff/CONNECTING.md](docs/handoff/CONNECTING.md).

## The four screens

- **Secretary Chat** (`#/chat`): conversation history, the agent's steps as they run, and approval requests inline.
- **Request Inbox** (`#/inbox`): incoming requests with classification, priority, flags, extracted meeting details, processing status, agent activity and history.
- **Approval Center** (`#/approvals`): each proposed email and calendar change, why the agent proposes it, approve and reject, and what was executed.
- **Evaluation Dashboard** (`#/evaluation`): the twenty cases, expected versus actual, traces, and Friday, Saturday and Sunday snapshots.

Screenshots of each screen on mock data are in [docs/screenshots](docs/screenshots).

## One interface, three things behind it

The UI and the evaluation runner talk to one interface, `ExecutiveDeskApi` in `src/api/client.ts`.

| Behind it | How to select | What it is |
| --- | --- | --- |
| Mock adapter (`src/api/mock/`) | default | Replays hand-written scripts in memory. No network code at all. |
| HTTP adapter (`src/api/httpAdapter.ts`) to the reference server | `npm run dev:reference` | The real transport path, with the scripted mock on the other end |
| HTTP adapter to Role 1's backend | `VITE_API_MODE=http VITE_API_BASE_URL=<url>` | The real thing. Not yet done. |

Whether data is labelled live or simulated is decided by what the backend says about itself in `GET /meta`, not by how it is reached. A scripted server is simulated even over HTTP.

The mock cannot send email or change a calendar. A test scans its source for network and credential APIs, and another runs every flow with `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource` and `sendBeacon` rigged to throw.

## Evaluation numbers

The dashboard shows a pass rate, intervention count, cost and latency only for a run against a real agent. Until one exists, those tiles show a dash.

- "Run harness self-test" checks the harness, not the agent: the twenty reference scripts must score as passing, and a set of deliberately broken scripts must each be caught by the intended check. Its output is labelled simulated, never fills the headline tiles, and cannot be saved as a snapshot.
- Cost is never estimated from assumed prices. The price table ships empty. See [docs/submission/COST_PER_RUN.md](docs/submission/COST_PER_RUN.md).
- A day's snapshot needs a complete run of the whole case set against a real agent in sandbox mode.
- The twenty cases are synthetic fixtures, labelled as such in every file and report. Cases derived from real requests would go in `fixtures/real-world/`, are kept in separate sets, and are never reported together with the synthetic ones.

## Layout

```
src/api/            contract types, client interface, validation, mock, HTTP adapter, reference server
src/evaluation/     fixtures, case-set loader, matchers, scorer, runner, reports, self-test
src/pages/          the four screens
src/components/     shared UI
scripts/            eval CLI, reference server, fixture export, doc generation
fixtures/           evaluation-cases.json (generated); real-world/ (empty, with rules)
eval-results/       reports (ignored by git) and snapshots/ (committed)
docs/               contract, examples, test cases, handoff package, submission drafts
```

## Documents

- [docs/INTEGRATION_HANDOFF.md](docs/INTEGRATION_HANDOFF.md): start here to connect a backend
- [docs/API_CONTRACT.md](docs/API_CONTRACT.md): the contract, version 1.0.0
- [docs/handoff/](docs/handoff): backend requirements, assumption register, connection guide, checklist, code-review resolution, test report
- [docs/API_EXAMPLES.md](docs/API_EXAMPLES.md) and [docs/TEST_CASES.md](docs/TEST_CASES.md): generated from code
- [docs/submission/](docs/submission): index card, demo storyboard, cost template, voice-note questions, presentation outline

All fixture people, companies, emails and calendar entries are invented. They are development fixtures, not customer cases.
