# Feature status

<!-- Generated from frontend/src/lib/featureStatus.ts by `npm run docs:generate`. Do not edit by hand. -->

What the Executive Desk frontend does on live data (the default mode), and what each part still needs.

| Status | Meaning | Features |
| --- | --- | --- |
| Connected, verified on the seeded backend | Uses Scriba's real API, and was exercised in a browser against Scriba's seeded backend with the Desk overlay | 24 |
| Connected, not verified end to end | Calls the real endpoint, but needs a model or a live provider to exercise. Covered by unit tests only | 9 |
| Waiting for a backend | No backend exists for it. The live screen says so and shows nothing in its place | 6 |
| Not implemented | Not built | 1 |

The seeded backend is Scriba's real application with in-memory storage: no database, no provider network and no model. **Nothing here has been verified against live Gmail, Outlook or calendars, and nothing here measures the agent.** Demo mode (`npm run dev:demo`) still runs every screen on the labelled mock.

## Workspace

| Feature | Status | Backend used | Still open |
| --- | --- | --- | --- |
| Sign-in and session | Connected, verified on the seeded backend | Scriba session cookie; GET /providers/status; POST /auth/signin; POST /auth/logout | Google and Microsoft sign-in are navigations to Scriba and were not exercised here |
| Executive overview and work queue | Connected, verified on the seeded backend | GET /desk/briefing, GET /desk/inbox, GET /desk/connections, chat action records | A backend work-queue listing, so the queue is not limited to recent conversations |
| Overview: waiting on you, with the secretary, and finished work | Connected, verified on the seeded backend | Chat action records and GET /desk/runs: counts and the finished list come from server statuses only | A run for an actionable message on the seeded backend: in a browser only completed chat actions and a no-action run were seen |
| Run lifecycle, recorded events, evidence per action and background intake status | Connected, verified on the seeded backend | GET /desk/runs, GET /desk/runs/{id}, GET /desk/worker and GET /desk/health on Desk overlay 0.3; falls back to the run state on overlay 0.2 | Overlay 0.3 merged. Seen in a browser in the sandbox: awaiting approval, executing to verified, awaiting reply, escalated, completed. Partial, failed and unknown outcome are covered by tests |
| Connected accounts (Gmail, Outlook Mail, Google Calendar, Outlook Calendar) | Connected, verified on the seeded backend | GET /desk/connections | Nothing for the Desk; reconnecting happens in Scriba |
| Activity and execution history | Connected, verified on the seeded backend | GET /chat/conversations and their messages: every action card with its server status | The same work-queue listing; automation runs are not included yet |

## Chat and approvals

| Feature | Status | Backend used | Still open |
| --- | --- | --- | --- |
| Approving mail and calendar actions in a sandbox | Connected, verified on the seeded backend | POST /chat/tool-calls/{id}/approve with health.executionMode "sandbox" (overlay 0.3): applied to an isolated provider world, marked simulated | Nothing for the sandbox. Real sending stays off until health.externalWrites.enabled, which no backend reports |
| Secretary chat with history and streaming | Connected, verified on the seeded backend | GET and POST /chat/conversations; GET messages; POST messages/stream (server-sent events), with the blocking POST as fallback | A backend with a model: the seeded backend answers every turn with its own "AI service unavailable" message |
| Action cards and the approval center | Connected, verified on the seeded backend | Chat action records; POST /chat/tool-calls/{id}/approve and /cancel | Approving and cancelling a task were exercised. Mail and calendar approvals are disabled until the backend reports its safety fixes |
| Execution progress, partial success and failure | Connected, not verified end to end | Server status on each action card, polled while it is approved or executing | A backend that produces executing, partially executed and failed actions |
| Retry of a failed action | Connected, not verified end to end | POST /chat/tool-calls/{id}/retry, which executes at once without a second approval | The same; the control says the retry runs immediately and asks for confirmation first |
| Booking despite an availability finding | Connected, not verified end to end | payload_overrides.desk_availability_override on approve (Desk chat scope, not yet on main) | The chat scope merged and running; external writes enabled |
| Safety holds explained on the card, with recipient confirmation | Connected, not verified end to end | output.error_code on a held card; approve with payload_overrides.desk_confirmed_recipients | A held card on a backend that can produce one. The seeded backend has none |
| Editing a proposal before approving | Not implemented | Approve accepts payload_overrides | The list of fields the backend validates as overrides per action. Until it is stated, only the two documented confirmations are sent and an incomplete card is finished in chat |

## Email

| Feature | Status | Backend used | Still open |
| --- | --- | --- | --- |
| Unified Gmail and Outlook inbox | Connected, verified on the seeded backend | GET /desk/inbox | Paging beyond the most recent 50 messages |
| Priority and classification | Connected, verified on the seeded backend | GET /desk/inbox: rule-based triage on subject and preview, no model | Triage on the full message body |
| Thread view | Connected, verified on the seeded backend | GET /desk/inbox/item: the messages of the thread found in the recent inbox, as previews | Full message bodies and older messages of the thread |
| Summaries and extracted action items | Waiting for a backend | None: the backend returns the provider preview only | A summary and action items per message. The live screen shows the preview and says so |
| Reply drafts for review | Connected, not verified end to end | POST /drafts/create with the body from GET /desk/inbox/item; GET /drafts; POST /drafts/{id}/discard | A backend with a model and a real mailbox to verify it. Sending a draft is not exposed |
| Work status per message | Waiting for a backend | None: Scriba does not record where a message stands in the secretary's work | A work record per message, linked to its actions |

## Calendar

| Feature | Status | Backend used | Still open |
| --- | --- | --- | --- |
| Unified Google and Outlook calendar, day and week | Connected, verified on the seeded backend | GET /calendar/events per provider | Seeded data has no connected calendar, so only the disconnected and failed states were seen in the browser; events are covered by unit tests |
| Conflicts between calendars | Connected, not verified end to end | Computed in the frontend from the events of both providers | Two connected calendars to verify it against |
| Free time for a meeting request | Connected, not verified end to end | GET /desk/inbox/item: slots verified free on every connected calendar | A meeting request and connected calendars to verify it against |
| Scheduling workspace: free time across calendars, one-time check | Connected, verified on the seeded backend | GET /desk/availability; POST /desk/slots/check | Two seeded calendars: in a browser only "no calendar connected" could be seen. Slots, conflicts and an unreadable calendar are covered by tests |
| Meeting preparation view | Waiting for a backend | None | Related mail, open tasks and notes per event |

## Tasks and follow-ups

| Feature | Status | Backend used | Still open |
| --- | --- | --- | --- |
| Tasks | Connected, verified on the seeded backend | GET /tasks; POST /tasks/{id}/complete | Reopening a completed task has no verified endpoint |
| Reminders | Connected, verified on the seeded backend | GET /reminders/upcoming; POST /reminders/{id}/cancel | Seeded data has no reminder, so cancelling one was not exercised |
| Follow-up tracking and overdue indicators | Connected, verified on the seeded backend | GET /desk/follow-ups and POST /desk/runs/{id}/follow-ups/{id}/close, on Desk overlay 0.3 only (agent1/autonomous-engine, not on main) | Overlay 0.3 merged. On an older backend the screen says follow-ups are not tracked. Seen in a browser in the sandbox: waiting. Overdue, answered and closed are covered by tests |

## Automation

| Feature | Status | Backend used | Still open |
| --- | --- | --- | --- |
| Work queue of Desk runs | Connected, verified on the seeded backend | GET /desk/runs and GET /desk/runs/{id} | The state on each list row, so the queue is one request. Seeded mail that needs work: the seeded backend only produces runs with no action |
| Check for new work (bounded inbox sweep) | Connected, verified on the seeded backend | POST /desk/intake/sweep; POST /desk/intake for one message | Seeded mail that needs work, to see a run opened in a browser |
| Run detail: proposed actions, approval, execution, verification | Connected, not verified end to end | GET /desk/runs/{id}; GET /chat/tool-calls/{id}; Scriba approve, cancel and retry | A run with an action on a backend available here. Timestamps per stage and the reason for each proposal are not on the run |
| Confirmation reply after a booking | Connected, not verified end to end | POST /desk/runs/{id}/advance | A meeting request, a model to read its time, and external writes to send it |
| Intake with no client open | Waiting for a backend | None: a sweep runs only when a signed-in client calls it | A background worker, and its status: running or paused, last check, pending, last error |
| Rescheduling and cancelling from an email | Waiting for a backend | None: the backend holds these requests (held.reason change_request) | Proposals for moving and cancelling an event |
| Work stages | Connected, verified on the seeded backend | Classified, planning, needs information, awaiting approval, executing, completed, partly completed, failed, cancelled: each from a server status | Received, verifying, awaiting reply and escalated are not reported by the backend and are not shown as if they were |

## Evaluation

| Feature | Status | Backend used | Still open |
| --- | --- | --- | --- |
| Twenty-case suite, scheduling regression suite, scorer, runner, reports | Connected, verified on the seeded backend | None needed: the harness runs against its scripted reference agent | These are harness results, not agent results |
| Reliability campaigns and run-to-run comparison | Connected, verified on the seeded backend | None needed: computed from report files | Real-agent reports to run them on. On scripted runs they show counts and never a pass rate |
| Holdout variations of the desk suite | Connected, verified on the seeded backend | None needed: reworded inputs with the official expectations | A real agent to run them on |
| Scripted-model evaluation on the sandbox routes | Connected, verified on the seeded backend | /desk/eval/v1 on Desk overlay 0.3, run with npm run eval --scriba-url; the report is imported into its own panel | Overlay 0.3 merged. Cases that start from a chat turn are not supported by the backend and come back as errors |
| Results against the real agent | Waiting for a backend | None: the sandbox routes exist on overlay 0.3, but no model has been run through them | A backend with a model configured (meta.agent "real"). Until then every headline number stays empty |

See [LIVE_INTEGRATION.md](LIVE_INTEGRATION.md) for the endpoints, the mapping rules and the open backend requirements.
