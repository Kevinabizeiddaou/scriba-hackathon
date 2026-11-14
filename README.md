# Scriba Executive Desk

An autonomous executive secretary for daily inbox-to-action management. It
does one repeatable job: **turn an executive's incoming correspondence into
verified administrative outcomes**, across Gmail, Outlook Mail, Google
Calendar and Outlook Calendar.

It is built on [Scriba](https://scribaassist.com), an existing assistant
product, by progressively transferring and adapting Scriba's working code
rather than rebuilding it. This is a private simulation of the AlphaHack 2026
challenge.

> **Where it stands:** the workspace runs on Scriba's API: unified inbox with
> rule-based triage, calendar, tasks, Scriba's chat agent, and an approval
> center on Scriba's action records. It was exercised on Scriba's seeded test
> backend only. No live mailbox or calendar and no model has been used, mail
> and calendar approvals are switched off in the Desk, and no end-to-end agent
> run has happened. See [docs/frontend/LIVE_INTEGRATION.md](docs/frontend/LIVE_INTEGRATION.md)
> and [docs/BASELINE.md](docs/BASELINE.md).

## The job

Someone who runs an executive's inbox and calendar repeats the same loop all
day: read what arrived, decide what each message needs, answer it, arrange
the meeting, note the task, chase the reply that never came, and report
back. The Desk is meant to do that loop and to ask for approval before
anything is sent or changed.

**Trigger:** a new email in the executive's Gmail or Outlook inbox. The
executive can also start the job from chat, and a daily briefing runs on a
schedule.

**Planned workflow:**

1. Read the message and its thread.
2. Triage it: what kind of message, how urgent.
3. Decide the outcome: reply, meeting, task or reminder, follow-up, or none.
4. Gather context from the thread, both calendars and existing tasks.
5. Prepare the action: draft the reply, check availability and conflicts,
   write the task.
6. Ask the executive to approve anything outbound or calendar-changing.
7. Execute: reply in the original thread, change the calendar, create the
   task or reminder.
8. Verify the provider accepted it and record the result.
9. Track awaited replies and raise overdue ones.
10. Brief the executive daily.

The full index card is [docs/INDEX_CARD.md](docs/INDEX_CARD.md).

## Target capabilities

All of these serve the one job above. "Planned" means not in the Desk yet.

| Capability | In the Desk today |
| --- | --- |
| Gmail and Outlook inbox management | Read-only list per provider |
| Email triage and prioritisation | Planned |
| Contextual replies and drafts | Planned |
| Google and Outlook calendar coordination | Read-only list |
| Tasks and reminders | Planned |
| Follow-up management | Planned |
| Daily executive briefings | Planned |
| Natural-language chat | Planned |
| Trigger-based automations | Planned |
| Human approvals | Planned |
| Action verification, audit history, cost tracking | Planned |

Most of these already exist in Scriba and will be reused directly; a few
need small adaptations and a few are new. The capability-by-capability
breakdown is [docs/ROADMAP.md](docs/ROADMAP.md).

Not part of the product: Slack, Teams, Google Drive, OneDrive, Jira and
desktop automation.

## What is reused from Scriba

Scriba's backend is the Desk's backend. The Desk has no authentication,
database or provider registration of its own, and none will be created.

In use today: sign-in and sessions, Google and Microsoft account
connections, Gmail and Outlook mail reading, Google and Outlook calendar
reading.

To be reused in later phases: message priority and triage, search, reply
drafts, sending and threaded replies, calendar changes, the chat agent with
approval cards, tasks, reminders, suggestions and alerts, daily briefs,
automations triggered by incoming mail, approvals, and action records.

Frontend pieces transferred from Scriba (`Gmail/frontend` at `3ae3a2aa`),
each marked with its source: the API client, API base-URL resolution, the
provider-status hook, the design tokens and component styles, and the
Tailwind and TypeScript configuration.

## Present limitations

- The Desk is a read-only shell: sign-in, four connection cards, a mail list
  per provider, a calendar list, API health.
- No end-to-end agent run has happened, and none of the 20 evaluation cases
  has been executed.
- Live Google and Microsoft data have not been tested from the Desk; tests
  ran against Scriba's seeded test backend.
- Some target capabilities do not exist in Scriba yet: availability across
  both calendars, tracking of awaited replies, a meeting-booking automation,
  cost per run. See the roadmap.
- Triage state lives in Scriba; the Desk will not archive, label or move
  mail in Gmail or Outlook.
- The Desk runs locally in Docker on `http://localhost:5173`. Hosting it needs
  configuration decisions listed in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Phases

Work proceeds one submission checkpoint at a time; a phase starts only when
authorized.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Index card and foundation | Done |
| 2 | Unified inbox, chatbot, calendar reads and triage (read-only) | Not started |
| 3 | Scheduling, tasks, reminders, automations and approvals | Not started |
| Final | Reliable integrated product, 20 real cases, metrics and demo | Not started |

## Run it

The app runs in Docker only; nothing else needs to be installed. `npm run dev`
outside the container refuses to start and points here.

One-time setup: the API is Scriba's own backend, so a Scriba checkout must sit
next to this repository (or set `SCRIBA_PATH` to an existing checkout's
`Gmail/` directory):

```bash
git clone https://github.com/ScribaAssist/Scriba ../scriba
```

The repository is tested against the Scriba revision in
[`backend/SCRIBA_REVISION`](backend/SCRIBA_REVISION). The `api` container
checks the checkout when it starts (`docker compose logs api`): it refuses to
start if Scriba's `requirements.txt` changed since the image was built (run
`docker compose build api`), and warns if the checkout is on another revision.

Then, from the repository root:

```bash
docker compose build
```

```bash
docker compose up -d
```

Open http://localhost:5173. Stop it with `docker compose down`. Both ports are
published on `127.0.0.1` only, so the app is not reachable from other machines.

`up -d` starts two containers:

| Service | What it is | Port |
| --- | --- | --- |
| `api` | Scriba's seeded test backend (the real app, in-memory data, no database, providers or model) with the Desk overlay | 8000 |
| `desk` | The Desk frontend, Vite dev server with hot reload; starts once `api` is healthy | 5173 |

Seeded sign-in users are listed at the top of Scriba's
`e2e/seeded_server.py`. All data resets when `api` restarts.

Settings are optional and go in a `.env` file next to `docker-compose.yml`;
[`.env.example`](.env.example) lists them all. Put them in `.env` rather than
in front of one command: every `docker compose` command must see the same
values, or compose recreates `api` with the other ones.

**The demo:** with `DESK_DEMO=on` in `.env` and `docker compose up -d`, the
seeded users Alice and Bob get synthetic Gmail and Outlook mail and calendars.
The intake worker turns that mail into runs within a minute, and approving an
action executes it against the synthetic world (`GET /desk/sandbox` lists what
was done). Without it, `api` serves Scriba's own seeded inbox, where nothing
needs work.

- Edits under `frontend/` reload in the browser. The overlay (`backend/`) and
  the Scriba checkout are mounted read-only: run `docker compose restart api`
  after editing them.
- Port 5173 is required (Scriba only trusts that origin), so nothing else may
  be listening on it.
- The browser, not the container, calls the API, so the Desk looks for it at
  `http://localhost:8000`. Set `VITE_API_BASE_URL` in your shell or in a
  `.env` next to `docker-compose.yml` to use another Scriba API.
- After a dependency change in `frontend/package.json`, run
  `docker compose build` and then `docker compose up -d -V` to refresh the
  container's `node_modules`.
- Logs: `docker compose logs -f api` or `docker compose logs -f desk`
  (rotated at 10 MB, three files kept).
- Containers do not restart on their own: after a reboot or a Docker Desktop
  restart, run `docker compose up -d` again.
- `failed to get build context scriba` from `docker compose build` means the
  Scriba checkout is missing: clone it as above or set `SCRIBA_PATH`.

Other profiles:

```bash
docker compose --profile demo up -d desk-demo     # mock data, no backend:     http://localhost:5174
docker compose --profile prod up -d desk-prod     # production build on nginx: http://localhost:5173 (instead of desk)
docker compose --profile test run --rm frontend-tests   # typecheck + unit tests
docker compose --profile test run --rm backend-tests    # whole backend suite, incl. overlay on the real Scriba app
docker compose --profile test run --rm smoke            # API smoke test against the running api
```

For `desk-prod`, `VITE_API_BASE_URL` is baked in at build time, so rebuild
after changing it.

## Tests

```bash
docker compose --profile test run --rm frontend-tests   # typecheck + unit tests
docker compose --profile test run --rm backend-tests    # whole backend suite, incl. overlay on the real Scriba app
docker compose --profile test run --rm smoke            # read-only API smoke against the api service
docker compose --profile test run --rm smoke --desk-demo   # the same plus one demo run (DESK_DEMO=on)
cd frontend && npm run eval                  # evaluation harness self-test (no backend, no agent)
```

`backend-tests` runs in the `api` image (same Python, Scriba's pinned
packages), including the integration tests that mount the overlay on the real
Scriba app. Signed-in smoke checks run when `SMOKE_EMAIL` and `SMOKE_PASSWORD`
(a seeded user) are set in `.env` or the environment. The smoke test only
reads; the one thing it changes is its own session.

Every commit runs the secret scan (`scripts/check-no-secrets.mjs`) through a
Git hook. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

## CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push to
`main` and every pull request:

| Job | What it checks |
| --- | --- |
| `secret-scan` | No secret, token store or dump in the tracked files |
| `frontend` | Typecheck, unit tests, production build |
| `images` | The compose file is valid; the frontend dev and production images build |
| `backend` | The whole backend suite in the `api` image, then the smoke test against the running seeded `api`, in normal and demo mode |
| `hosted-image` | `backend/Dockerfile.railway` builds, starts against a throwaway Postgres and passes the anonymous smoke checks; its Scriba pin matches `backend/SCRIBA_REVISION` |

`backend` and `hosted-image` need Scriba, a private repository. They read it
with the repository secret `SCRIBA_GITHUB_TOKEN`: a fine-grained GitHub token
with **Contents: read-only** on `ScribaAssist/Scriba` and nothing else. To set
it (the command asks for the token):

```bash
gh secret set SCRIBA_GITHUB_TOKEN --repo nabiljaber/scriba-hackathon
```

Pull requests from forks get no secrets, so those two jobs are skipped there.
This repository's Actions logs are public: the jobs print no Scriba code
(pytest runs with `--tb=line`; run the suite locally for full tracebacks).

## Repository rules

- This repository is public. No `.env`, token, credential, customer data or
  private configuration is committed.
- Scriba's repository and its production service are not modified from here.
  Nothing is deployed without explicit authorization.
- `main` is the official branch. Collaborators work on separate branches.

| Path | Owner |
| --- | --- |
| `frontend/src/api/`, `frontend/src/lib/apiBase.ts`, `frontend/src/lib/connections.ts`, `scripts/`, `docs/`, later `backend/` | Backend and contract |
| Visual pages, chat UI, evaluation dashboard, scenario fixtures | Frontend and evaluation (the shell under `frontend/src/shell/` is a starting point) |

More: [index card](docs/INDEX_CARD.md) · [roadmap](docs/ROADMAP.md) · [baseline](docs/BASELINE.md) · [architecture](docs/ARCHITECTURE.md) · [backend contract](docs/BACKEND_CONTRACT.md) · [Phase 1 report](docs/PHASE_1_REPORT.md)
