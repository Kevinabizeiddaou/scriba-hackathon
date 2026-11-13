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
| 1. Shell and index card | Desk shell on Scriba's existing API: sign-in, connection status, mail and calendar read for Google and Microsoft, health, smoke tests; index card; baseline | Done |
| 2. Backend safety and availability | Fixes to existing backend issues, made in Scriba's own repository through its review process; a read-only availability service across Google and Outlook calendars (busy intervals, working hours, buffers, conflicts, suggested slots) | Not started |
| 3. Secretary workflow | An inbound meeting request produces a proposed reply and calendar action as approval cards; approval executes them through Scriba's existing action and approval machinery | Not started |
| 4. Triggers, follow-ups, execution history | Run the workflow from Scriba's inbound-mail trigger; follow-ups for unanswered proposals; a run history view | Not started |
| 5. Evaluation | The 20-case scheduling suite, reliability measurement, cost per run | Not started |
| 6. Final interface and demo | Desk-only tool scope, final UI, demo and submission | Not started |

### The backend overlay (Phase 2 onward)

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
