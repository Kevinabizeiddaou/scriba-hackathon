> **Moved.** This workspace was `executive-desk/`. Its code is now in `frontend/` (the API layer
> it describes as `src/api/` is `frontend/src/harness/`), its documents are here in
> `docs/frontend/`, and the app it describes is the demo mode of the one application
> (`npm run dev:demo`). What follows is the predecessor's description, kept as written. For the
> live application see [LIVE_INTEGRATION.md](LIVE_INTEGRATION.md) and
> [FEATURE_STATUS.md](FEATURE_STATUS.md).

# Scriba Executive Desk: frontend and evaluation workspace

The Role 2 workspace for a private simulation of the AlphaHack 2026 AI Agent Challenge (13 to 15 November). It is not an official competition entry.

Scriba Executive Desk automates the recurring administrative work of an executive secretary: triaging the inbox, drafting replies, keeping two calendars straight, scheduling and rescheduling, tracking tasks and the replies someone is waiting for, and asking a human before anything is sent or changed. It is not a general-purpose assistant. It covers Gmail, Outlook Mail, Google Calendar and Outlook Calendar, and nothing else.

This folder holds the interface, an API contract with a mock and a reference server for it, a synthetic evaluation suite and the runner that scores it. It has no backend and no agent logic; those are Role 1's.

**What is real today:** nothing here is connected to the Scriba backend. Every screen runs on an in-memory mock with fictional people, and says so on every page. The mock cannot send email or change a calendar. [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md) lists every feature as connected, mocked, waiting for a backend contract, or not built.

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
| `npm run eval` | Harness self-test: every reference script and every planted defect |
| `npm run eval -- --target mock` | Run the desk suite against the scripted mock and write a report |
| `npm run eval -- --target mock --suite scheduling` | The same for the scheduling regression set (`--suite all` for every case) |
| `npm run eval -- --base-url <url>` | Run the suite against a backend over HTTP |
| `npm run fixtures:export` | Rewrite the JSON case files in `fixtures/` from the TypeScript fixtures |
| `npm run docs:generate` | Rewrite the generated documents in `docs/` |

The options of `npm run eval` are listed at the top of [`scripts/eval.ts`](scripts/eval.ts) and explained in [docs/handoff/CONNECTING.md](docs/handoff/CONNECTING.md).

## The screens

| Screen | Address | What it shows |
| --- | --- | --- |
| Overview | `#/overview` | What needs a decision, today's meetings from both calendars, the mail that needs attention, what is due or overdue, and the integration status |
| Inbox | `#/inbox` | Gmail and Outlook in one list with category and priority. Per message: summary, action items, the thread, a reply draft that goes to approval, and for meeting requests the scheduling detail |
| Calendar | `#/calendar` | Google and Outlook calendars in one week or day view, the calendar each event comes from, conflicts between them, slots the secretary has proposed, and a preparation panel per meeting |
| Tasks and follow-ups | `#/tasks` | Tasks by urgency, reminders, and the replies you are waiting for, with overdue ones marked and a reminder you can send for approval |
| Secretary chat | `#/chat` | Conversation history, the agent's steps as they run, approval cards inline, and a way back after a failure |
| Approval center | `#/approvals` | Every proposed email and calendar change as numbered steps, why it is proposed, approve and reject, then progress and the result of each step |
| Activity | `#/activity` | Everything read, proposed, decided, sent or changed, newest first |
| Evaluation | `#/evaluation` | The desk suite by area, expected versus actual, traces, and Friday, Saturday and Sunday snapshots |

On a phone the navigation is a bottom bar with four destinations and a "More" sheet for the rest. Screenshots on mock data are in [docs/screenshots](docs/screenshots).

Nothing is sent and no calendar is changed without an approval. Tasks, reminders and the follow-up list are the principal's own records, so the secretary writes those without asking.

## How the data reaches the screens

Two interfaces, both in `src/api/`:

| Interface | For | Backed by |
| --- | --- | --- |
| `ExecutiveDeskApi` (`client.ts`) | Requests, agent runs, approvals, chat, evaluation | The mock (default), or the HTTP adapter to the reference server (`npm run dev:reference`), or the HTTP adapter to a backend that serves [docs/API_CONTRACT.md](docs/API_CONTRACT.md) (`VITE_API_MODE=http VITE_API_BASE_URL=<url>`) |
| `WorkspaceApi` (`workspace.ts`) | Mail, calendars, tasks, reminders, follow-ups, activity | The mock only. Against anything else every call answers "waiting for the backend contract" and the screen says so. Nothing is invented. |

Authentication is Scriba's own session cookie. The frontend stores no token and has no sign-in system. Writes are never repeated automatically unless the backend says it handles idempotency keys.

Whether data is labelled live or simulated is decided by what the backend says about itself in `GET /meta`, not by how it is reached. A scripted server is simulated even over HTTP.

The mock cannot send email or change a calendar. A test scans its source for network and credential APIs, and another runs every flow with `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource` and `sendBeacon` rigged to throw.

## The evaluation suite

Twenty synthetic cases, the desk suite (`desk-v1`):

| Area | Cases | Examples |
| --- | --- | --- |
| Inbox triage | 3 | A newsletter is filed and nothing else happens; an urgent decision request becomes an urgent task; a re-sent request is recognised |
| Email replies | 3 | A reply that depends on what was agreed earlier in the thread; a drafted reply the principal rejects; a question that is handed over instead of guessed |
| Scheduling | 5 | A free slot, a conflict, another time zone, a move, a cancellation |
| Tasks and reminders | 3 | A deadline becomes a task and not a meeting; a reminder at a stated time; finished work closes its task |
| Follow-ups | 2 | Only the overdue reply is chased; an awaited reply closes its follow-up |
| Multi-step workflows | 2 | Book, confirm and record the promised document; move, notify and remind |
| Security and failure | 2 | A calendar service that stays down; a prompt injection |

Each case states the expected outcome, the tool calls that must and must not happen, which side effects need approval, wording checks on what is sent, and assertions about the state afterwards: what must and must not exist on the calendar, the task list, the reminders and the follow-up list once the run is over. Every case also gets the same safety checks, such as the approval gate and no double booking. The cases are in [docs/TEST_CASES.md](docs/TEST_CASES.md).

The original twenty scheduling cases remain as a regression set (`synthetic-v3`, [docs/TEST_CASES_SCHEDULING.md](docs/TEST_CASES_SCHEDULING.md)); eight of them are part of the desk suite. There are thirty-two cases in all.

## Evaluation numbers

The dashboard shows a pass rate, intervention count, cost and latency only for a run against a real agent. No such run exists yet, so those tiles show a dash.

- "Run harness self-test" checks the harness, not the agent: the reference script of every case must score as passing, and thirty-six deliberately broken scripts must each be caught by the intended check. Its output is labelled simulated, never fills the headline tiles, and cannot be saved as a snapshot.
- A report from the scripted mock is written as `*.simulated.json` and shows counts, never a pass rate.
- Cost is never estimated from assumed prices. The price table ships empty. See [docs/submission/COST_PER_RUN.md](docs/submission/COST_PER_RUN.md).
- A day's snapshot needs a complete run of the whole case set against a real agent in sandbox mode.
- The cases are synthetic fixtures, labelled as such in every file and report. Cases derived from real requests would go in `fixtures/real-world/`, are kept in separate sets, and are never reported together with the synthetic ones.

## Layout

```
src/api/            contract types, client interfaces, validation, mock, HTTP adapter, reference server
src/evaluation/     fixtures, case-set loader, matchers, scorer, runner, reports, self-test
src/pages/          the eight screens
src/components/     shared UI
src/lib/            routing, time, labels, feature status
scripts/            eval CLI, reference server, fixture export, doc generation
fixtures/           evaluation-cases.json and scheduling-regression-cases.json (generated); real-world/ (empty, with rules)
eval-results/       reports (ignored by git) and snapshots/ (committed)
docs/               contract, feature status, integration requirements, test cases, handoff package, submission drafts
```

## Documents

- [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md): what is connected, mocked, waiting or missing (generated)
- [docs/API_INTEGRATION_REQUIREMENTS.md](docs/API_INTEGRATION_REQUIREMENTS.md): what each screen needs, set against what Scriba has today
- [docs/API_CONTRACT.md](docs/API_CONTRACT.md): the Desk contract, version 1.1.0
- [docs/INTEGRATION_HANDOFF.md](docs/INTEGRATION_HANDOFF.md) and [docs/handoff/](docs/handoff): backend requirements, assumption register, connection guide, checklist, code-review resolution, test report
- [docs/TEST_CASES.md](docs/TEST_CASES.md), [docs/TEST_CASES_SCHEDULING.md](docs/TEST_CASES_SCHEDULING.md) and [docs/API_EXAMPLES.md](docs/API_EXAMPLES.md): generated from code
- [docs/submission/](docs/submission): index card, demo storyboard, cost template, voice-note questions, presentation outline

All fixture people, companies, emails and calendar entries are invented. They are development fixtures, not customer cases.
