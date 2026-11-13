# Agent 2 status: frontend and evaluation

Written 14 November 2026 on branch `agent2/frontend-overnight`, based on `main` at `2a45537`
(pull requests 1 to 4 merged). For Agent 1 and the project lead.

Nothing in this report is a result about the agent. No real model, mailbox or calendar was used.

## 1. Latest commits (this branch, on top of main)

| Commit | What |
| --- | --- |
| `9bf4d42` | Chat recovery test: an old failure must not stay retryable after a later success |
| `6023d54` | Desk runs: data layer for the work queue, pinned to the backend's run contract |
| `c1306c3` | Work queue and run detail on the Desk run contract; check for new work |
| `5a691fa` | Scheduling workspace: find a time across Google and Outlook calendars |

Later commits on this branch are listed in the pull request.

## 2. What works now

Verified in a browser against the seeded Scriba + Desk backend (`backend/dev/seeded_desk_server.py`,
Scriba at `3ae3a2a`), signed in as a seeded user, unless marked "tests only".

| Capability | Endpoints | State |
| --- | --- | --- |
| Work queue: runs grouped by what they need (approval, input, running, did not finish, completed, no action, cancelled) | `GET /desk/runs`, `GET /desk/runs/{id}` | Browser: one run listed with its real state. All other states: tests only, because the seeded inbox has no actionable mail (section 6) |
| Check for new work | `POST /desk/intake/sweep` | Browser: 25 examined, 0 opened, 25 need no run. One request per click; the report accounts for every examined message |
| Start one run for one message | `POST /desk/intake` | Tests only |
| Run detail: source message and mailbox, timeline of reported stages, proposed actions, verification, next step | `GET /desk/runs/{id}`, `GET /chat/tool-calls/{id}`, `GET /desk/connections` | Browser for a run with no action. With actions: tests only |
| Approve, cancel, retry an action from a run | Scriba's `POST /chat/tool-calls/{id}/approve`, `/cancel`, `/retry` | Tests only from a run. The same card was exercised in a browser from the approval center before this branch |
| Propose the confirmation reply once the event exists | `POST /desk/runs/{id}/advance` | Tests only |
| Write a reply draft for a run that needs one | Scriba's `POST /drafts/create` with the run's `draftRequest` | Tests only. Needs a model |
| Scheduling workspace: free times, busy time, double bookings, one-time check | `GET /desk/availability`, `POST /desk/slots/check` | Browser: "no calendar connected", stated as unknown. With calendars: tests only |
| Navigation badge: runs that need the user | the run queue | Tests only |

Unchanged and still passing: overview, inbox, message detail, calendar, tasks, reminders, chat,
approval center, activity, demo mode, the evaluation suites and harness.

Rules the new screens keep, each with a test:

- A state is shown when the server reports it and not before. An unknown state is shown as
  unrecognised with its raw value, never as finished.
- "Verified" is the server's `verified` flag. An executed action without a Scriba action record is
  shown as not verified.
- A calendar that could not be read makes availability unknown. Slots in a payload whose
  `complete` is false are ignored. A slot check with `free: null` is never shown as free.
- Opening a page starts no intake. A check runs once per click. The optional timer runs only while
  the tab is open and visible and switches itself off after three failures in a row.
- The screen says the backend has no background worker. Nothing animates as if one existed.
- Mail and calendar approvals stay disabled: no backend reports `externalWrites.enabled`.

## 3. Endpoint reconciliation

Checked by calling the seeded backend on 14 November 2026 and by reading
`backend/desk_overlay/`. "Pinned" means a frontend test reads the backend source and fails if the
fields drift (`src/live/deskRuns.test.ts`, `src/live/LiveScheduling.test.tsx`).

| Endpoint | Used by | Session | Observed | Matches `api/desk.ts` | Notes |
| --- | --- | --- | --- | --- | --- |
| `GET /desk/health` | session, write policy | 401 without | 200; `writes: false`, `chatScope: "enforced"`, `chatTools` | Yes | No `externalWrites`: deliberate, so external approvals are off |
| `GET /desk/connections` | overview, run detail | yes | 200, about 5 s on the seeded backend | Yes | |
| `GET /desk/inbox` | inbox, overview, work queue | yes | 200, about 5 s | Yes | |
| `GET /desk/inbox/item` | message detail | yes | 200 | Yes | |
| `GET /desk/availability` | scheduling workspace | yes | 200; `complete: false`, `reason: "no_calendar_connected"`, no slots; 400 for a range over 31 days | Yes, pinned | |
| `POST /desk/slots/check` | scheduling workspace | yes, cross-site blocked | 200; `free: null` with no calendar | Yes, pinned | |
| `GET /desk/briefing` | overview | yes | 200, about 14 s on the seeded backend | Yes | Slow: the overview shows a loading state for that long |
| `POST /desk/intake` | work queue "Start" | yes | Smoke test: run opened, repeat returns `duplicate: true` | Yes | |
| `POST /desk/intake/sweep` | work queue | yes | 200; counts add up to `examined` | Yes | `already_running` returns `complete: false` and no sources; the screen treats it as "nothing done" |
| `GET /desk/runs` | work queue | yes | 200; rows are `runId, provider, email_id, subject, from_addr, category, created_at` | **Narrower in the client**: the type declares only `runId, subject, category, created_at`, and has no `limit` | **No `state` on a row** (mismatch 1) |
| `GET /desk/runs/{id}` | work queue, run detail | yes | 200; 404 `{"error": "Run not found."}` | Yes, pinned | |
| `POST /desk/runs/{id}/advance` | run detail | yes | 200; safe on a run with nothing to advance | Yes | |
| `GET /chat/tool-calls/{id}`, `POST .../approve`, `/cancel`, `/retry` | action cards | yes | 404 `chat_action_not_found` for an unknown id | In `live/scribaApi.ts` | Retry executes at once; the card says so before the click |
| `GET /tasks`, `GET /reminders/upcoming`, `GET /drafts`, `GET /notifications`, `GET /chat/conversations`, `GET /calendar/events`, `GET /emails` | tasks, reminders, drafts, chat, calendar | yes | 200 | In `live/scribaApi.ts`, `api/scriba.ts` | |
| `GET /desk/eval/v1/meta` | evaluation runner | | **404** | Not in the client | Mismatch 4 |
| `GET /desk/work` | none | | 404 | | Proposed earlier by the frontend; superseded by `/desk/runs` plus mismatch 1 |

## 4. Contract mismatches

1. **`GET /desk/runs` has no state.** The queue has to read every listed run. It reads the newest
   20, four at a time, and says how many it did not read. Wanted on each row: `state`, `next`,
   `held.reason`, and the number of actions by status. Then the queue is one request.
2. **A partly executed action makes the run `completed`.** `workflow._DONE` contains
   `partially_executed`, and `verified` is true for it. The frontend shows such a run under "Did
   not finish". Wanted: state `partial` when any action is `partially_executed`.
3. **`externalWrites` is not emitted.** Agreed and deliberate. The frontend needs no change when it
   appears; until then mail and calendar approvals are disabled with the reason shown.
4. **No `/desk/eval/v1`.** The evaluation runner signs in, reads `/desk/health`, gets 404 from
   `/desk/eval/v1/meta` and stops. No case is posted.
5. **No worker status.** Runs start only when a client calls intake or sweep. The screen says so.
   When a worker exists the queue needs: running or paused, last check, pending count, last error.
6. **A run carries little evidence.** No time for any stage but `createdAt`, no message arrival
   time or preview, no text for why an action was proposed, no `output` on an action (the frontend
   reads each card through `GET /chat/tool-calls/{id}`).
7. **Retry has no safety signal.** A retry runs at once. The frontend warns before the click and
   offers no run-level retry. Wanted: a field that says whether a failed action's provider outcome
   is known, so the warning can be exact.
8. **Reschedule and cancel requests are held** (`held.reason: "change_request"`). The run detail
   says so and points to chat.
9. **No follow-up lifecycle and no per-run cost or model usage.** The follow-ups tab says it is not
   available; the evaluation dashboard shows no cost.

## 5. Tests and results (14 November 2026, Windows 11, Node 22, Python 3.13)

| What | Result |
| --- | --- |
| Backend unit and route tests (`pytest tests --ignore=tests/integration`) | 129 passed |
| Backend with integration tests on the real Scriba app at `3ae3a2a` | 196 passed |
| API smoke on the seeded backend (`scripts/smoke.mjs --desk`) | 27 of 27 checks passed |
| Frontend type check | Clean |
| Frontend tests on `main` before this branch | 284 passed in 15 files |
| Frontend tests on this branch | See the pull request for the current count; 345 passed in 18 files at commit `5a691fa` |
| Production build | Passes |
| Browser, seeded backend | Sign-in, work queue, check for new work, run detail, scheduling workspace: correct, no console errors, no sideways scroll at 1024 px |

Not run: anything with a real model; anything with a live Gmail, Outlook or calendar; a secret
scan beyond the repository's ignore rules (section 6).

## 6. Blocking issues

- **The seeded backend has no actionable mail.** All seeded messages are informational, so a sweep
  opens nothing and no run reaches approval. The approval, held, executing, partial and verified
  states of the new screens are proven by tests with the contract's shapes, not seen in a browser.
- **No model.** Time extraction for meeting requests and reply drafts cannot be exercised.
- **No evaluation backend.** No real-agent result of any kind exists.

## 7. What I need from Agent 1

In order of value to the product:

1. Seeded fixtures in `backend/dev/`: one action item, one meeting request at a free time, one at a
   busy time, one reschedule request, one message that needs a reply. Two connected seeded
   calendars would also make the scheduling workspace testable in a browser.
2. `state`, `next`, `held.reason` and action counts on `GET /desk/runs` rows (mismatch 1), and
   `partial` for a partly executed action (mismatch 2).
3. `/desk/eval/v1` as in `docs/frontend/LIVE_INTEGRATION.md` section 9.3. The runner and the
   adapter exist; they need a backend that runs the real Desk orchestration on synthetic
   providers and reports `sandbox: true`.
4. Worker status when a background worker exists (mismatch 5).
5. Widening `fetchDeskRuns` in `frontend/src/api/desk.ts` to the fields the server already sends,
   with a `limit` parameter. I did not edit that file, since the contract types are yours.

## 8. Three highest-impact improvements

1. **A sandbox evaluation backend.** Until it exists there is no number about the agent, and
   everything else is measured only by its own tests.
2. **Actionable seeded data plus run state in the list.** It turns the work queue from "proven by
   tests" into something a person can watch from arrival to verified result.
3. **External-write readiness, tested on isolated provider accounts.** It is the one switch between
   the Desk proposing work and the Desk finishing it.
