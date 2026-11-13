# Scriba Executive Desk

An AI executive secretary that handles incoming meeting requests and
coordinates an executive's schedule across Gmail, Outlook Mail, Google
Calendar and Outlook Calendar.

It is built on [Scriba](https://scribaassist.com), an existing assistant
product, by progressively transferring and adapting Scriba's working code
rather than rebuilding it. This is a private simulation of the AlphaHack 2026
challenge.

## The job

Someone who manages an executive's calendar spends hours each week on the
same loop: read a meeting request, check the calendars, propose or confirm a
time, book it, reply. The Desk automates that loop and asks for approval
before anything leaves the building.

**Trigger:** a new email in the executive's Gmail or Outlook mailbox asking
to set up, move or cancel a meeting.

**Planned workflow:**

1. Read the message and its thread.
2. Extract the request: intent, attendees, dates, duration.
3. Check availability in the connected Google and Outlook calendars.
4. Detect conflicts.
5. Choose the requested time or propose alternatives.
6. Ask the executive to approve the reply and the calendar change.
7. Create, update or cancel the event.
8. Reply in the original thread from the mailbox that received it.
9. Log the run and open a follow-up when an answer is awaited.

The full index card is in [docs/INDEX_CARD.md](docs/INDEX_CARD.md).

## What is reused from Scriba

Scriba's backend is the Desk's backend. The Desk does not have its own
authentication, database or provider registrations.

| Reused as it runs today | Used by the Desk in Phase 1 |
| --- | --- |
| Sign-in and sessions | Yes |
| Google and Microsoft account connections | Yes (status and connect links) |
| Gmail and Outlook Mail reading | Yes |
| Google Calendar and Outlook Calendar reading | Yes |
| Mail sending and threaded replies | Not yet |
| Calendar create, update, cancel | Not yet |
| Chat agent with approval cards | Not yet |
| Automations triggered by incoming mail | Not yet |

Frontend pieces transferred from Scriba (`Gmail/frontend` at `3ae3a2aa`),
each marked with its source: the API client, API base-URL resolution, the
provider-status hook, the design tokens and component styles, and the
Tailwind and TypeScript configuration.

Not part of the Desk: Slack, Teams, Google Drive, OneDrive, Jira and desktop
automation.

## Present limitations

- **Phase 1 is a read-only shell.** It signs in, shows which of the four
  accounts are connected, lists mail per provider, lists calendar events and
  reports API health. It does not run the secretary workflow.
- No end-to-end agent run has happened. See [docs/BASELINE.md](docs/BASELINE.md).
- Live Google and Microsoft data have not been tested from the Desk; tests
  ran against Scriba's seeded test backend.
- Availability across both calendars, conflict detection, follow-ups and a
  meeting-booking automation do not exist yet in Scriba and are later-phase
  work.
- The Desk runs locally on `http://localhost:5173`. Hosting it needs
  configuration decisions listed in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Phases

Work proceeds one submission checkpoint at a time; a phase starts only when
authorized.

1. **Shell and index card** (done)
2. Backend safety and a read-only availability service
3. Secretary workflow with approvals
4. Triggers, follow-ups and execution history
5. Evaluation: 20 scheduling cases, reliability, cost per run
6. Final interface and demo

## Run it

The Desk needs a running Scriba backend. It never stores a credential; the
session is a cookie owned by the Scriba API.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (this port is required)
```

By default the Desk on `localhost:5173` talks to a Scriba backend on
`localhost:8000`. Set `VITE_API_BASE_URL` to use another Scriba API.

## Tests

```bash
cd frontend && npm test && npm run build     # unit tests, typecheck, build
node scripts/smoke.mjs --base <scriba api>   # read-only API smoke
node scripts/check-no-secrets.mjs            # run before every commit
```

Signed-in smoke checks run when `SMOKE_EMAIL` and `SMOKE_PASSWORD` are set in
the environment. The smoke test only reads; the one thing it changes is its
own session.

## Repository rules

- This repository is public. No `.env`, token, credential, customer data or
  private configuration is committed.
- Scriba's repository and its production service are not modified from here.
  Nothing is deployed without explicit authorization.
- Collaborators work on separate branches of this repository.

| Path | Owner |
| --- | --- |
| `frontend/src/api/`, `frontend/src/lib/apiBase.ts`, `frontend/src/lib/connections.ts`, `scripts/`, `docs/`, later `backend/` | Backend and contract |
| Visual pages, chat UI, evaluation dashboard, scenario fixtures | Frontend and evaluation (the shell under `frontend/src/shell/` is a starting point) |

More: [architecture](docs/ARCHITECTURE.md) · [backend contract](docs/BACKEND_CONTRACT.md) · [baseline](docs/BASELINE.md)
