# Architecture

## Decision

**Scriba's backend is the Desk's backend.** The Desk reuses Scriba's
application, database, session, provider connections, chat agent, automations
and approvals as they run today. Nothing is rebuilt. This repository adds a
focused frontend on top of Scriba's existing authenticated API, and in later
phases a small backend overlay for the scheduling capability Scriba lacks.

No new Google Cloud project, OAuth client, Microsoft Entra application or
Graph registration is created. Sign-in and provider callbacks stay on the
existing Scriba API host.

Source of transferred code: `ScribaAssist/Scriba`, `main` at `3ae3a2aa`.

```
Browser (Desk frontend, this repository)
   |  HTTPS, session cookie owned by the API host
   v
Scriba API  (existing host, existing provider callbacks)
   |-- existing routes: sign-in, mail, calendar, chat, automations, approvals
   |-- /desk/* overlay routes (later phases; loaded into the same process)
   v
Scriba database, Google APIs, Microsoft Graph (existing registrations)
```

## How the Desk authenticates

- The session is an HttpOnly cookie set by the Scriba API host. The Desk
  holds no token and stores no credential.
- Sign-in is a full-page navigation to the API host (Google or Microsoft).
  The provider callback is handled there.
- Every API request is sent with credentials. The API accepts credentialed
  requests only from origins it trusts; the local development origin
  `http://localhost:5173` is one of them, so the Desk runs there without any
  change to Scriba.
- Provider tokens never reach the browser or this repository.

## Google and Microsoft support map

"Exists" rows are Scriba endpoints. "Tested" means the Phase 1 smoke test
called the endpoint on a running Scriba backend; it does not mean live
provider data was read (see `BASELINE.md`). "Missing" rows are the work this
project adds in later phases.

| Capability | Google | Microsoft | Scriba endpoint | Phase 1 |
| --- | --- | --- | --- | --- |
| Connect account | Exists | Exists | `GET /auth/login`; `GET /auth/outlook/login` | Linked from the shell |
| Connection status | Exists | Exists | `GET /providers/status` | Tested |
| Read mail | Exists | Exists | `GET /emails?provider=gmail` / `outlook` | Tested |
| Read calendar | Exists | Exists | `GET /calendar/events?provider=google` / `outlook` | Tested |
| Reply in the original thread | Exists | Exists | `POST /reply` | Not used yet |
| Send new mail | Exists | Exists | `POST /send` | Not used yet |
| Create, update, cancel event | Exists | Exists | `POST`, `PATCH`, `DELETE /calendar/events` | Not used yet |
| Chat agent with approval cards | Exists | Exists | `/chat/*` | Not used yet |
| Inbound email starts an automation | Exists | Exists | Automation trigger on received mail | Not used yet |
| Availability across both calendars | Missing | Missing | Planned: `/desk/availability` | — |
| Conflict detection before proposing or booking | Missing on the chat path | Missing on the chat path | Planned | — |
| Automation that books or changes a meeting | Missing | Missing | Planned | — |
| Follow-up on unanswered scheduling mail | Missing | Missing | Planned | — |

Slack, Teams, Google Drive, OneDrive, Jira and desktop automation exist in
Scriba and may remain as shared backend dependencies. They are not Desk
capabilities: the Desk never shows or calls them.

## Phases

Work proceeds by submission checkpoint. Each phase is completed, verified and
committed, and the next one starts only when the project lead authorizes it.
Only Phase 1 is implemented.

| Phase | Scope | Status |
| --- | --- | --- |
| 1. Index card and foundation | Desk shell on Scriba's existing API: sign-in, connection status, mail and calendar read for Google and Microsoft, health, smoke tests; index card; baseline | Done |
| 2. Unified inbox, chatbot, calendar reads and triage | Read-only: one inbox across Gmail and Outlook, priority and triage, search, reply drafts for review, chat on Scriba's agent, calendar views, notifications, on-demand briefing | Not started |
| 3. Scheduling, tasks, reminders, automations and approvals | Availability and conflicts across both calendars, approvals, approved replies and calendar changes, tasks, reminders, follow-ups, automations; backend fixes made in Scriba's own repository first | Not started |
| Final. Reliable integrated product | The whole job on real mail and calendars, 20 real cases, cost per run, audit history, demo | Not started |

The capability-by-capability reuse matrix is [ROADMAP.md](ROADMAP.md).

### The backend overlay (Phase 3 onward)

New backend code is versioned in this repository but runs inside Scriba's
process, because it needs Scriba's session, database and provider
connections. The overlay wraps Scriba's application object unchanged and adds
routes under `/desk/`. Reproducible integration instructions will be added
with the overlay. Loading it on a hosted Scriba API is a deployment change
and requires separate explicit authorization.

## Configuration dependencies

None of these needs a new cloud project, OAuth client or redirect URI. They
are settings on the existing API service, a Scriba code change, or DNS, and
none is made without authorization.

| Need | Why |
| --- | --- |
| A hosted Desk origin | The API only accepts credentialed requests from origins on its trusted list |
| Landing on the Desk after sign-in | After a provider callback the API returns the browser to Scriba's own frontend |
| Cookies on a different site | A Desk hosted on an unrelated domain depends on third-party cookies; a subdomain of the API's site avoids that |
| Running the overlay on the hosted API | The overlay must be loaded into the API process |
| Desk-only chat tool scope | Scriba's chat tool set is shared by all of its users |

Until those are decided, the Desk runs on `http://localhost:5173`.

## Backend issues

Issues found in Scriba's backend while preparing this project are tracked
privately in Scriba's own repository and will be fixed there. They are not
described in this public repository.


## The secretary engine (overlay 0.4)

How the pieces fit, by module (`backend/desk_overlay/`). Arrows are calls.

```
 mail arrives            the executive types           a card is approved
      |                          |                             |
 worker / POST /intake     POST /desk/commands        Scriba's approve route
      |                          |                             |
      v                          v                             v
 workflow.intake           commands.Commands            execution.ExecutionGate
      |   triage, thread         |  operations                 | binding, readiness,
      |   understanding          |  (rules, or a model         | sandbox routing,
      |   (rules or a model      |   whose operations          | verification by read-back
      |    that must quote)      |   must quote)               |
      v                          v                             v
            planning by checked code                     on_settled -> workflow.advance
   availability on every calendar, the ORIGINAL event,     deferred steps whose
   recipients from the From header or from records,        prerequisite took effect
   deadlines from the request's own sentence               are proposed; blocked
      |                                                    ones are recorded once
      v
   plans.build  ->  the typed plan, stored as evidence on the run
      |
      v
   gateway.propose_action  ->  Scriba's own card path and validation,
                               then the Desk's safeguards (section 7)
```

| Module | Responsibility | Trust boundary it holds |
| --- | --- | --- |
| `workflow.py` | Intake, planning of mail, advance, follow-ups, the run view | A message is data. Its sender is the only attendee or recipient the Desk adds |
| `commands.py` | Instructions typed by the executive: operations, their planning, the reply in words | Recipients come from calendar and follow-up records only |
| `understanding.py` | One model call that reads intents, validated | An intent with no quote from the message is dropped; a time needs an offset |
| `agent.py` | The bounded model step: read tools, three proposal types | It cannot choose a recipient, change a calendar or approve |
| `memory.py` | A snapshot read from records on demand; the repeated-request check | Unknown is never reported as empty; scoped to user and world |
| `plans.py`, `lifecycle.py` | The typed plan and step states; evidence and the stage derived from it | A dependent step is never proposed before its prerequisite took effect |
| `execution.py` | The gate on Scriba's approve, retry and cancel | External writes are off by construction; an approval is bound to what was proposed |
| `sandbox.py` | Isolated provider worlds; tripwires on real clients | A sandbox run cannot reach a real provider |
| `safeguards.py`, `chat_scope.py` | Recipient provenance, reply target, structural checks on every card | A card with an unverified recipient is held |

**Memory is not a store.** Every reader (the `GET /desk/memory` route, the
repeated-request check, the model step's `records`) gets a fresh read of
Scriba's calendar mirror, Scriba's tasks and the evidence events on the
Desk's runs. The Desk keeps no second copy that could drift, and a model's
recollection is never a source.

**Persistence.** A run is a Scriba chat conversation; its evidence is
append-only system messages on it; its actions are Scriba chat tool-call
cards; claims go to Scriba's receipt ledger. Follow-ups, task updates, plans
and decisions are all derived from that evidence, so they survive a restart
wherever Scriba's own storage does. In the dev backend that storage is in
memory.
