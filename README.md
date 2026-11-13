# Scriba Executive Desk

An AI executive secretary for meeting coordination across Gmail, Google
Calendar, Outlook Mail and Outlook Calendar. It is a focused product built on
Scriba: the Scriba backend is the runtime, and this repository holds the Desk's
own frontend, its API contract and its tests.

Slack, Teams, Google Drive, OneDrive, Jira and desktop automation are out of
scope and never appear in the Desk.

## Status: Stage 1

A working shell that signs in through Scriba, shows the four connections
(Google and Microsoft, mail and calendar), lists mail per provider, lists
calendar events from both calendars, and reports API health. It reads only;
no mail is sent and no event is written yet.

- Architecture decision and migration map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Backend API contract (for the frontend and evaluation harness): [docs/BACKEND_CONTRACT.md](docs/BACKEND_CONTRACT.md)

## How it runs

The Desk has no backend of its own in Stage 1. It calls an existing Scriba API
with the user's Scriba session cookie. OAuth sign-in and callbacks stay on the
Scriba API host; the Desk never handles a code, a token or a client secret.

| Backend | How | Needs |
| --- | --- | --- |
| Local Scriba backend | Start Scriba from its own checkout (`uvicorn app.main:app --port 8000`) with its own `.env`. The Desk on `http://localhost:5173` finds it automatically. | A Scriba checkout at `3ae3a2aa` or newer |
| Seeded Scriba backend (no providers, no database) | `python e2e/seeded_server.py --port 8788` in the Scriba checkout, then `VITE_API_BASE_URL=http://localhost:8788` | Same checkout |
| Existing Scriba API host | `VITE_API_BASE_URL=<api host>`; sign in to Scriba first | A browser that allows the API host's cookie on `localhost` |

The dev server must run on port 5173. Scriba trusts `http://localhost:5173`
for credentialed requests and refuses other ports.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm test             # unit tests
npm run build        # typecheck + production build
```

## Tests

```bash
# Unit tests
cd frontend && npm test

# API smoke: anonymous checks are read-only and safe against any Scriba API
node scripts/smoke.mjs --base http://localhost:8788

# Adds signed-in checks (signs in and out; reads only)
SMOKE_EMAIL=... SMOKE_PASSWORD=... node scripts/smoke.mjs --base http://localhost:8788

# Refuses secrets, token stores and database dumps in files Git would commit
node scripts/check-no-secrets.mjs
```

## Rules

- No `.env`, token, credential or production data in this repository. The
  secret check above runs before every commit.
- Scriba's repository and its production deployment are not modified from
  here. Backend changes go through Scriba's own review, or through the overlay
  described in the architecture note, and are never deployed without explicit
  authorization.
- Files copied from Scriba keep a header naming their source path and commit.

## Ownership

| Path | Owner |
| --- | --- |
| `frontend/src/api/`, `frontend/src/lib/apiBase.ts`, `frontend/src/lib/connections.ts`, `scripts/`, `docs/` | Backend/contract role |
| The rest of `frontend/` and the evaluation harness | Frontend role (the Stage 1 shell under `frontend/src/shell/` is a starting point to replace or extend) |
