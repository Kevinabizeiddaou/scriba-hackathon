# Desk backend overlay

Desk-specific backend code. It runs **inside Scriba's existing API process**
and adds routes under `/desk/` to Scriba's application. It has no
authentication, database, provider registration or configuration of its own:
it reuses Scriba's session, Scriba's stored Google and Microsoft connections,
and Scriba's mail listing, calendar clients, classifier and preferences.

Nothing here sends mail or writes to a real calendar. It proposes actions as
Scriba approval cards, and puts an execution gate on Scriba's approve path:
a mail or calendar action runs against an isolated sandbox world when one is
in force, and is otherwise held (`external_writes_disabled`). See
[../docs/BACKEND_CONTRACT.md](../docs/BACKEND_CONTRACT.md) section 8.

## Layout

| Path | What it is |
| --- | --- |
| `desk_overlay/asgi.py` | Entry point: Scriba's app, unchanged, plus `/desk/*` |
| `desk_overlay/install.py` | Mounts the routes on a Scriba app (idempotent) |
| `desk_overlay/gateway.py` | The one seam into Scriba's code. Every Scriba import is here |
| `desk_overlay/routes.py` | The `/desk/*` routes |
| `desk_overlay/availability.py` | Multi-calendar availability: merge, buffers, working hours, conflicts (pure) |
| `desk_overlay/triage.py` | Secretary triage on top of Scriba's classifier (pure) |
| `desk_overlay/capabilities.py` | The four Desk capabilities from Scriba's provider status (pure) |
| `desk_overlay/briefing.py` | The executive briefing from Scriba records (pure) |
| `desk_overlay/service.py` | The operations shared by the routes and the chat tools |
| `desk_overlay/chat_scope.py` | The Desk scope for Scriba's chat agent: tool scope, availability tools, booking gate |
| `desk_overlay/workflow.py` | One incoming email to proposed, approvable Scriba action cards: booking, moving, cancelling, replies, tasks, follow-ups |
| `desk_overlay/lifecycle.py` | The stages of a run and its evidence, derived from the cards and recorded events (pure) |
| `desk_overlay/reading.py`, `planning.py` | Reading a message by rule: scheduling and action signals, a time written in full, deadlines, text addressed to the assistant (pure) |
| `desk_overlay/plans.py` | The typed plan of a run: intents, facts, assumptions, steps and what each depends on (pure) |
| `desk_overlay/understanding.py` | A message's intents with confidence and evidence, from the rules or from one validated model call |
| `eval/scenarios.py` | The backend's own 24 evaluation scenarios; measured by `tests/integration/test_scenarios_with_scriba.py` |
| `dev/mutation_check.py` | Plants one defect at a time in a safety guard and checks the suite notices |
| `desk_overlay/claims.py` | One run per message across processes and restarts: Scriba's receipt ledger, a SQLite file, or memory |
| `desk_overlay/worker.py` | The opt-in background intake worker |
| `desk_overlay/sandbox.py` | Isolated provider worlds, and the gateway that routes reads to them |
| `desk_overlay/execution.py` | The execution gate on Scriba's approve, retry and cancel; the tripwire on real provider clients |
| `desk_overlay/readiness.py` | Whether real writes are enabled. They are not: the verified-revision list is empty (pure) |
| `desk_overlay/eval_api.py` | `/desk/eval/v1`: the evaluation harness's five calls, on one sandbox world per case |
| `desk_overlay/agent.py` | A bounded model step: read tools from a fixed list, and a reply, task or reminder as proposals. Off by default |
| `desk_overlay/safeguards.py` | The Desk's own checks on a proposed action: completeness, recipient provenance, reply target (pure) |
| `desk_overlay/scriba_transferred/` | Scriba's slot search and time rules, transferred unchanged |
| `dev/seeded_desk_server.py` | Scriba's seeded test backend with the overlay mounted. `--demo` adds sandbox worlds and the worker |
| `dev/demo_world.py` | The synthetic mail and calendars of the demo |
| `tests/` | Unit and route tests (no Scriba needed) and `tests/integration/` (real Scriba app) |

## What it reuses from Scriba

| Desk need | Scriba code reached through the gateway |
| --- | --- |
| Who is signed in; refusing another user's account | `apps.api.auth.authenticated_user` (the dependency Scriba's own routers use) |
| Session guard, cross-site guard, CORS | Scriba's middleware; the routes are mounted on Scriba's app |
| Connection status | The runtime behind `GET /providers/status` |
| Mail per provider | The runtime behind `GET /emails` |
| Needs-reply, bulk, meeting and urgency signals | `app.reply_draft_policy.classify_reply_candidate` |
| Time zone, working hours, weekdays, buffer, default duration | `app.preferences_service.get_user_preferences` |
| Google busy time, per account | `app.calendar_client.calendar_service` + Google's free/busy query |
| Outlook busy time | `app.outlook_client.get_access_token` + `graph_get` (calendar view) |
| Free-slot search | `packages.domain.calendar_read.compute_free_slots`, transferred unchanged |

## Run it

**Use Docker:** `docker compose build`, then `docker compose up -d` from the
repository root runs the overlay on Scriba's seeded backend (the `api`
service; see "Run it" in the [main README](../README.md)). The manual commands
below are what that container does, kept for reference and for running the
overlay on a real Scriba backend.

You need a Scriba checkout at commit `3ae3a2aa` or newer and its Python
environment (the overlay adds no dependency). Nothing in Scriba is edited.
Scriba's configuration stays where it is; none of it is copied here.

In every command, `SCRIBA` is the `Gmail/` directory of the Scriba checkout
and `DESK` is this repository's `backend/` directory.

### With seeded data (no database, no providers, no model)

```bash
SCRIBA_BACKEND_PATH=$SCRIBA  $SCRIBA/.venv/Scripts/python  $DESK/dev/seeded_desk_server.py --port 8788
```

Then point the frontend at it: `VITE_API_BASE_URL=http://localhost:8788`.
Seeded users are listed at the top of Scriba's `e2e/seeded_server.py`.

Any Python with FastAPI, httpx and psycopg works; Scriba's `.venv` is not
required. This backend makes no model call (`DESK_MODEL=off` by default here:
Scriba's test harness installs a placeholder key, and a call with it would be
an outbound request that can only fail).

### The demo: the whole flow, with no provider

```bash
SCRIBA_BACKEND_PATH=$SCRIBA  python  $DESK/dev/seeded_desk_server.py --port 8788 --demo
```

The seeded users Alice and Bob each get an isolated provider world
(`dev/demo_world.py`): synthetic Gmail and Outlook mail covering every case
the Desk handles, a Google and an Outlook calendar, and the intake worker on
a 15 second tick. Within a minute their mail has become runs. Approving an
action executes it against the world; `GET /desk/sandbox` lists what was
done. `POST /desk/sandbox/deliver` adds a message of your own.

Without `--demo` the server behaves as before: Scriba's seeded inbox, where
nothing needs work.

To put a real model behind it (none has been, from this repository): a real
key in the environment, `DESK_MODEL=on`, `DESK_UNDERSTANDING=model` for intent
understanding and `DESK_AGENT=on` for the bounded model step. Mail in a sandbox world is synthetic; that is all a model sees.

### With a real local Scriba backend

Start Scriba exactly as you normally do, from its own directory and with its
own environment, changing only the application module and the Python path:

```bash
cd $SCRIBA
PYTHONPATH=$SCRIBA:$DESK  python -m uvicorn desk_overlay.asgi:app --host 0.0.0.0 --port 8000
```

(On Windows PowerShell: `$env:PYTHONPATH = "$SCRIBA;$DESK"`.) Scriba's own
container start command reads `APP_MODULE`, so in a container the same thing
is `APP_MODULE=desk_overlay.asgi:app` with `backend/` on `PYTHONPATH`.

This uses the Google and Microsoft connections already stored for the
signed-in Scriba user. No new OAuth client, redirect URI or cloud setup.

Running the overlay on a hosted Scriba API is a deployment change and needs
explicit authorization. It is not done from this repository.

The Desk's own hosted API is a separate deployment: `Dockerfile.railway` builds
Scriba at a pinned commit with the overlay mounted, for Railway. See
[../docs/DEPLOY.md](../docs/DEPLOY.md).

## Test it

Use Scriba's Python environment (it has FastAPI, pytest and httpx).

```bash
cd backend

# Unit and route tests: no Scriba checkout needed
python -m pytest tests --ignore=tests/integration -q

# Everything, including the overlay mounted on the real Scriba app
SCRIBA_BACKEND_PATH=$SCRIBA  python -m pytest tests -q

# API smoke against a running backend that has the overlay
SMOKE_EMAIL=... SMOKE_PASSWORD=... node ../scripts/smoke.mjs --base http://localhost:8788 --desk

# The same against a backend started with --demo: also follows one synthetic
# message from arrival to a verified result inside the sandbox
SMOKE_EMAIL=... SMOKE_PASSWORD=... node ../scripts/smoke.mjs --base http://localhost:8788 --desk-demo
```

Every test runs with an outbound-connection guard (`tests/conftest.py`): a
test that opens a socket to another host fails.

The integration tests are hermetic in the same way as Scriba's own tests: a
developer's `.env` is never loaded, the database URL is a dummy, and storage
is in memory. They replace Google and Microsoft at the SDK boundary, so they
prove the integration with Scriba's code, not with live provider data.

## Rules for availability

- Slots are offered only when **every** connected calendar was read. A
  calendar that fails is reported with `ok: false`; it is never treated as
  free.
- A conflict is reported even when another calendar failed; "free" is only
  claimed on a complete read.
- Every busy interval keeps its provider and account.
- Outlook times are read in the zone Graph reports for them, and events
  marked free or working-elsewhere do not block.
- An unknown time zone is a 400, not a fallback to another zone.
- Known limits: Google busy time comes from the primary calendar of each
  connected Google account; a working day is treated as ending by 23:00; an
  Outlook range with more than 250 events is refused rather than truncated.

The API contract for clients is [../docs/BACKEND_CONTRACT.md](../docs/BACKEND_CONTRACT.md),
with types in `frontend/src/api/desk.ts`.

## Chat scope

`DESK_CHAT_SCOPE=on` narrows Scriba's own chat agent to the Desk's tools,
adds the availability tools, and puts the booking gate on Scriba's validation
(see `desk_overlay/chat_scope.py` and section 5 of the contract). It applies
to the **whole process**, so turn it on only in a process that serves the
Desk and nobody else. `dev/seeded_desk_server.py` turns it on by default; with
a real local Scriba backend, add `DESK_CHAT_SCOPE=on` to the command above.
`GET /desk/health` reports whether it is enforced. Do not set it on a backend
that Scriba's own users also use.

## The worker, claims and environment

The background intake worker is opt-in and refuses to start in a production
process. On a real local Scriba backend:

```bash
DESK_CHAT_SCOPE=on  DESK_INTAKE_WORKER=on  DESK_INTAKE_USERS=you@example.com  \
PYTHONPATH=$SCRIBA:$DESK  python -m uvicorn desk_overlay.asgi:app --port 8000
```

It reads the user's inbox through the runtime behind `GET /emails` (mail
reaches Scriba through Scriba's own ingestion), opens runs, and proposes.
Claims default to Scriba's own receipt ledger (`DESK_CLAIMS=scriba`), which
adds no table; that path has not been run against a database from here.
Every variable is listed in section 11 of the contract. Real mail and
calendar writes cannot be switched on by any of them.
