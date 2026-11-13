# Roadmap: feature reuse and phases

The aim is to reuse nearly all of Scriba's secretary-relevant functionality
by the final submission, by transferring and adapting it, not rebuilding it.

Two things are kept strictly apart in this document:

- **Exists in Scriba** means Scriba has the capability today. It does not
  mean the Desk uses it yet.
- **Desk status** says what the Desk itself does today. Only the rows marked
  "Working" have been run from this repository, and only against Scriba's
  seeded test backend (see [BASELINE.md](BASELINE.md)).

No end-to-end agent run has happened in the Desk. "Backend working on seeded data" means the route runs inside the real Scriba application against Scriba's seeded test backend; it does not mean live Google or Microsoft data.

The Desk backend overlay lives in [`backend/`](../backend/README.md) on the `agent1/backend` branch.

## Feature reuse and migration matrix

Reuse levels: **Direct** = the Desk calls Scriba's existing API as it is.
**Adapt** = existing Scriba capability plus a small change. **New** = Scriba
does not have it; built as a small addition on top of Scriba's parts.

| Capability | Exists in Scriba today | Reuse | What the Desk still needs | Desk status | Phase |
| --- | --- | --- | --- | --- | --- |
| Sign-in and sessions | Yes | Direct | Nothing | Working | 1 |
| Google and Microsoft account connections | Yes: connect routes and connection status | Direct | Nothing | Working (status and connect links) | 1 |
| Gmail inbox reading | Yes: `GET /emails` | Direct | Nothing | Working (seeded data) | 1 |
| Outlook inbox reading | Yes: `GET /emails` | Direct | Live-data check | Route answers; no live data seen | 1 |
| Unified inbox across both mailboxes | Yes, per provider | Adapt | Thread view in the UI | Backend working on seeded data: `GET /desk/inbox` (overlay) | 2 |
| Triage and prioritisation | Yes: priority on every message, user override (`POST /emails/priority`), read state (`POST /emails/read`), bulk-mail filtering | Direct | Triage view in the UI | Backend working on seeded data: every inbox row carries a rule-based triage record | 2 |
| Search | Yes: `GET /search` | Direct | Search box | Not built | 2 |
| Google and Outlook calendar reading | Yes: `GET /calendar/events`, `GET /agenda/today`, `GET /agenda/week` | Direct | Day and week views | Working as a list (empty in seeded data) | 1, then 2 |
| Natural-language chat | Yes: conversations, streaming replies, proposed-action cards | Direct | Chat page wired to Scriba's chat API | Not built (a mock chat exists on the frontend branch) | 2 |
| Chat limited to Desk capabilities | No: chat can still offer excluded integrations | Adapt | A Desk-only tool scope | Not built | 2 to Final |
| Notifications | Yes: `GET /notifications`, read, dismiss, snooze | Direct | Notification list | Not built | 2 |
| Preferences (time zone, working hours, reply style) | Yes: `GET`/`POST /preferences` | Direct | Settings panel | Not built | 2 |
| Daily executive briefing | Yes: on-demand brief (`POST /daily-brief`), scheduled brief by email | Adapt | Briefing view; delivery from an Outlook mailbox | Backend working on seeded data: `GET /desk/briefing` (records only, no model) | 2 (view), 3 (delivery) |
| Contextual reply drafts | Yes: draft generation and a drafts list (`/drafts`) | Direct | Draft review in the inbox | `GET /desk/inbox/item` returns the request for Scriba's draft endpoint; the draft call itself is not yet verified | 2 |
| Sending replies and new mail | Yes: `POST /reply`, `POST /send`, draft send | Direct | Approval UI; backend fixes first | Not built | 3 |
| Calendar create, update, cancel | Yes: `/calendar/events` for Google and Outlook | Direct | Approval UI; backend fixes first | Not built | 3 |
| Availability across both calendars | Partly: free/busy and slot logic exist internally, with no API and not used by chat | New | Live verification on real Google and Outlook calendars | Backend built and tested with providers replaced at the SDK boundary: `GET /desk/availability`, `POST /desk/slots/check`. No live calendar read yet | 3 |
| Conflict detection and slot proposal | Partly: a meeting-conflict notification and slot ranking exist | Adapt | Use them before proposing or booking | Backend built: cross-calendar conflicts and slot checks in the overlay; draft requests carry only verified free times. Not yet wired into chat | 3 |
| Tasks | Yes: list, complete, discard, pin, prioritise; created through chat actions and automations | Direct | Task list; create flow | Not built | 3 |
| Reminders | Yes: upcoming list, cancel; created through chat actions and automations | Adapt | Reminder list; confirm how due reminders are delivered | Not built | 3 |
| Follow-up management | Partly: unanswered-important-email alerts, suggestions (`/suggestions`), post-meeting follow-up reminders | Adapt | Track replies awaited on sent mail and raise overdue ones | Not built | 3 |
| Trigger-based automations | Yes: plain-language drafting, a received-mail trigger for Gmail and Outlook, actions to reply, send, create a task or reminder; run history | Adapt | Automations cannot yet act on a calendar; some routes are off on servers without Scriba's desktop feature | Not built | 3 |
| Human approvals | Yes: approve, cancel, retry on chat actions; approve, reject on automation runs; approvals expire | Direct | Approval centre wired to Scriba | Not built (a mock exists on the frontend branch) | 3 |
| Action verification | Yes: each action records its provider result and an uncertain-outcome state instead of guessing | Direct | Show it per action | Not built | 3 to Final |
| Audit history | Yes: per chat action and per automation run | Adapt | One history across chat and automations | Not built | Final |
| Cost tracking | Partly: model usage and cost are recorded per call and per user, not per run | Adapt | Attribute cost to a run | Not built | Final |
| Evaluation on 20 real cases | No | New | Run the 20 cases on a real backend (cases and harness exist on the frontend branch, run so far on a mock only) | Not run | Final |

Not part of the product: Slack, Teams, Google Drive, OneDrive, Jira and
desktop automation. They remain in Scriba's backend as shared dependencies
and are never shown or called by the Desk.

## Feature by phase

A phase starts only when the project lead authorizes it. Only Phase 1 is
done.

| Phase | Delivers | Reused directly | Adapted or new | Status |
| --- | --- | --- | --- | --- |
| **1. Index card and foundation** | Index card; Desk shell on Scriba's API; sign-in; connection status for the four accounts; mail list per provider; calendar list; health; smoke tests; baseline | Sign-in, sessions, connections, mail read, calendar read | Desk connection model that hides excluded integrations | Done |
| **2. Unified inbox, chatbot, calendar reads and triage** | One inbox across Gmail and Outlook with threads; priority and triage view; search; reply drafts for review; chat on Scriba's agent; day and week calendar; notifications; on-demand daily briefing. Read-only: nothing is sent and no calendar is changed | Mail read, priority, search, drafts, chat, calendar and agenda reads, notifications, preferences, on-demand brief | Merged inbox; Desk-only chat scope | Not started |
| **3. Scheduling, tasks, reminders, automations and approvals** | Availability and conflict checks across both calendars; slot proposals; approval centre; approved replies and calendar changes; tasks and reminders; follow-up tracking; automations from the received-mail trigger; scheduled briefing | Send and reply, calendar writes, tasks, reminders, approvals, automations, verification records | Availability service; follow-up tracking; calendar action for automations; backend fixes made in Scriba's repository | Not started |
| **Final. Reliable integrated product** | The whole job end to end on real mail and calendars; 20 real cases executed and scored; reliability, cost per run and latency reported; audit history across chat and automations; demo | Everything above | Cost per run; unified audit history; evaluation on a real backend | Not started |

## Missing capabilities

Scriba does not have these today; they are the real new work.

- Availability across Google and Outlook calendars as a service, and its use
  by the chat agent before it proposes a time.
- Tracking of replies awaited on sent mail.
- An automation action that books or changes a meeting.
- Cost attributed to a single run.
- A chat tool scope limited to the Desk's capabilities.
- Changes to the mailbox itself: Scriba's read and priority state is kept in
  Scriba and is not written back to Gmail or Outlook, and it has no archive,
  label or move operation. "Inbox management" in the Desk therefore means
  triage inside the Desk, not reorganising the provider mailbox.
- Daily briefing delivery from an Outlook mailbox (delivery is by Gmail
  today).

## Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| The scope is now the whole inbox-to-action job, with the final submission days away | Breadth can crowd out reliability | Phase 2 is read-only and almost entirely direct reuse; writes arrive only in Phase 3, behind approvals |
| No live Google or Microsoft data has been tested from the Desk | Seeded data cannot show provider quirks | First task of Phase 2: a signed-in live read on both providers |
| Known backend issues must be fixed before the Desk sends mail or writes calendars | A mistake in an outbound action is visible to third parties and cannot be recalled | Fixes are submitted for review in Scriba's own repository and are not merged or deployed yet; the Desk enables writes only after them |
| The Desk and the frontend branch are separate histories with separate API contracts | Two contracts drift | Agree one contract before merging; merge is a deliberate, reviewed step |
| The Desk only runs on the local development origin | A hosted demo needs settings on the existing API service | Listed in [ARCHITECTURE.md](ARCHITECTURE.md); no change without authorization |
| Model behaviour decides the quality of triage, drafts and scheduling | It cannot be proven by unit tests | The 20-case evaluation, run early and repeatedly on a real backend |
| Automations depend on parts of Scriba built for its desktop feature | Some automation routes are off by default | Decide in Phase 3 between enabling them on a non-production server and driving the workflow from the chat action path |
