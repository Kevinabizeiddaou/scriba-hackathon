# Agent 2 status: frontend and evaluation

Written 14 November 2026 on branch `agent2/frontend-overnight`, based on `main` at `2a45537`
(pull requests 1 to 4 merged). `main` had not moved when this was written. For Agent 1 and the
project lead.

Nothing in this report is a result about the agent. No real model, mailbox or calendar was used.

## 1. Commits on this branch

| Commit | What |
| --- | --- |
| `9bf4d42` | Chat recovery test: an old failure must not stay retryable after a later success |
| `6023d54` | Desk runs: data layer for the work queue, pinned to the backend's run contract |
| `c1306c3` | Work queue and run detail on the Desk run contract; check for new work |
| `5a691fa` | Scheduling workspace: find a time across Google and Outlook calendars |
| `bcd1f3d` | First version of this report |
| `79558b3` | Split the bundle: the live app no longer ships the mock or the evaluation harness |
| `eb0e8d1` | Overview: list the picked-up requests that need the user |
| `8ba44ca` | Evaluation: reliability campaigns and run-to-run comparison |
| `5ad0cd8` | Approval cards: explain each safety hold, confirm recipients, link to the run |
| `bcac917` | Docs, feature status and screenshots for the new screens |

No file under `backend/`, `docs/BACKEND_CONTRACT.md` or `frontend/src/api/` was changed.

## 2. What works now

"Browser" means seen in a scripted Chrome session against the seeded Scriba + Desk backend
(`backend/dev/seeded_desk_server.py`, Scriba at `3ae3a2a`), signed in as a seeded user. "Tests"
means covered only by frontend tests on the contract's shapes.

| Capability | Endpoints | Verified |
| --- | --- | --- |
| Work queue: runs sorted by what they need | `GET /desk/runs`, `GET /desk/runs/{id}` | Browser: one run, with the server's state. Other states: tests |
| Check for new work | `POST /desk/intake/sweep` | Browser: 25 examined, 0 opened, 25 needing no run. One request per click |
| Start one run for one message | `POST /desk/intake` | Tests |
| Run detail: source message, mailbox, timeline, actions, verification, next step | `GET /desk/runs/{id}`, `GET /chat/tool-calls/{id}`, `GET /desk/connections` | Browser for a run with no action. With actions: tests |
| Approve, cancel, retry from a run | Scriba's `POST /chat/tool-calls/{id}/approve`, `/cancel`, `/retry` | Tests from a run. The same card was approved in a browser from the approval center before this branch |
| Confirmation reply once the event exists | `POST /desk/runs/{id}/advance` | Tests |
| Reply draft for a run that needs one | Scriba's `POST /drafts/create` with the run's `draftRequest` | Tests. Needs a model |
| Scheduling workspace | `GET /desk/availability`, `POST /desk/slots/check` | Browser: "no calendar connected", stated as unknown. Slots, conflicts, an unreadable calendar: tests |
| Safety holds explained on the card; recipient confirmation | `output.error_code`; approve with `desk_confirmed_recipients` | Tests |
| Overview and navigation: runs that need the user | the run queue | Browser (none needing the user on seeded data); tests |
| Reliability campaigns and run comparison | report files only | Tests, and the command line on the scripted mock |
| Bundle | | Live Desk code 237 kB, React 219 kB, data libraries 93 kB; the evaluation harness (226 kB) and demo mode load on demand. Before: one 754 kB script |

Unchanged and still passing: inbox, message detail, calendar, tasks, reminders, chat, approval
center, activity, demo mode, the evaluation suites and harness.

Rules the new screens keep, each with a test:

- A state is shown when the server reports it. An unknown state is shown as unrecognised with its
  raw value, never as finished.
- "Verified" is the server's `verified` flag. An executed action with no Scriba action record is
  shown as not verified.
- A calendar that could not be read makes availability unknown. Slots in a payload whose
  `complete` is false are ignored. A slot check with `free: null` is never shown as free.
- Opening a page starts no intake. A check runs once per click. The optional timer runs only while
  the tab is open and visible, and switches itself off after three failures in a row.
- The screen says the backend has no background worker. Nothing animates as if one existed.
- Mail and calendar approvals stay disabled: no backend reports `externalWrites.enabled`.
- A held card offers only the way forward the contract names for its code. An unknown code offers
  none.
- There is no run-level retry. Retry stays on the action card, where it warns that it runs at once.

## 3. Endpoint reconciliation

Checked by calling the seeded backend on 14 November 2026 and by reading `backend/desk_overlay/`.
"Pinned" means a frontend test reads the backend source and fails if the fields, states or codes
drift (`deskRuns.test.ts`, `LiveScheduling.test.tsx`, `LiveWork.test.tsx`).

| Endpoint | Used by | Observed | Matches `api/desk.ts` | Notes |
| --- | --- | --- | --- | --- |
| `GET /desk/health` | session, write policy | 200; `writes: false`, `chatScope: "enforced"`, `chatTools`; 401 without a session | Yes | No `externalWrites`: deliberate |
| `GET /desk/connections` | overview, run detail | 200, about 5 s on the seeded backend | Yes | |
| `GET /desk/inbox` | inbox, overview, work queue | 200, about 5 s | Yes | |
| `GET /desk/inbox/item` | message detail | 200 | Yes | |
| `GET /desk/availability` | scheduling workspace | 200; `complete: false`, `reason: "no_calendar_connected"`, no slots; 400 for a range over 31 days | Yes, pinned | |
| `POST /desk/slots/check` | scheduling workspace | 200; `free: null` with no calendar; blocked from another site | Yes, pinned | |
| `GET /desk/briefing` | overview | 200, about 14 s on the seeded backend | Yes | Slow there; the overview shows a loading state |
| `POST /desk/intake` | work queue "Start" | Smoke test: run opened, repeat returns `duplicate: true` | Yes | |
| `POST /desk/intake/sweep` | work queue | 200; the counts add up to `examined` | Yes | `already_running` comes back with `complete: false` and no sources; shown as "nothing done" |
| `GET /desk/runs` | work queue | 200; rows are `runId, provider, email_id, subject, from_addr, category, created_at` | **Narrower in the client** | **No `state` on a row** (mismatch 1). The client type lacks `provider`, `email_id`, `from_addr` and `limit` |
| `GET /desk/runs/{id}` | work queue, run detail | 200; 404 `{"error": "Run not found."}` | Yes, pinned | |
| `POST /desk/runs/{id}/advance` | run detail | 200; harmless on a run with nothing to advance | Yes | |
| `GET /chat/tool-calls/{id}`, `POST .../approve`, `/cancel`, `/retry` | action cards | 404 `chat_action_not_found` for an unknown id | In `live/scribaApi.ts` | Retry executes at once |
| `GET /tasks`, `/reminders/upcoming`, `/drafts`, `/notifications`, `/chat/conversations`, `/calendar/events`, `/emails` | tasks, reminders, drafts, chat, calendar | 200 | In `live/scribaApi.ts`, `api/scriba.ts` | |
| `GET /desk/eval/v1/meta` | evaluation runner | **404** | Not in the client | Mismatch 4 |

## 4. Contract mismatches

1. **`GET /desk/runs` has no state.** The queue reads the newest 20 runs, four at a time, and says
   how many it did not read. Wanted per row: `state`, `next`, `held.reason`, action counts by status.
2. **A partly executed action makes the run `completed`.** `workflow._DONE` contains
   `partially_executed`, and `verified` is true for it. The frontend lists such a run under "Did
   not finish". Wanted: `partial`.
3. **`externalWrites` is not emitted.** Agreed and deliberate. No frontend change is needed when it
   appears.
4. **No `/desk/eval/v1`.** The runner signs in, reads `/desk/health`, gets 404 and stops. Run on
   the seeded backend on 14 November: "This backend has no sandbox evaluation routes... Nothing was
   sent."
5. **No worker status.** Runs start only when a client calls intake or sweep. The screen says so.
6. **A run carries little evidence.** No time for any stage but `createdAt`, no arrival time or
   preview of the message, no reason for a proposal, no `output` on an action.
7. **Retry has no safety signal.** Wanted: whether a failed action's provider outcome is known.
8. **`reply_target_missing` is not in the contract.** `safeguards.py` emits it; section 7 of the
   contract and `DeskHoldCode` do not list it. The frontend handles it.
9. **Which fields `payload_overrides` may change is not stated.** The frontend sends only
   `desk_confirmed_recipients` and `desk_availability_override`. Editing a proposal's text or time
   before approving is not built until the validated fields are listed.
10. **Reschedule and cancel requests are held** (`held.reason: "change_request"`).
11. **No follow-up lifecycle, and no cost or model usage per run.**

## 5. Tests and results (14 November 2026, Windows 11, Node 22, Python 3.13)

| What | Result |
| --- | --- |
| Backend unit and route tests | 129 passed |
| Backend with integration tests on the real Scriba app at `3ae3a2a` | 196 passed |
| API smoke on the seeded backend (`scripts/smoke.mjs --desk`) | 27 of 27 checks passed |
| Frontend type check | Clean |
| Frontend tests | 364 passed in 19 files (`main` before this branch: 284 in 15) |
| Production build | Passes; no chunk over 500 kB |
| Harness self-test | 32 of 32 reference scripts scored as passing; 36 of 36 planted defects caught. A check of the harness, not an agent result |
| Runner against the seeded backend with sign-in | Stops at the missing `/desk/eval/v1/meta`; nothing sent |
| Browser, seeded backend, 1440 and 390 px | New screens correct; no request answered 400 or above; no horizontal overflow |
| Mutation check on this branch's new code | 21 defects planted one at a time (run sorting, verification, unknown states, bounded reads, slots from an incomplete read, unknown shown as free, recipient confirmation, the automatic check, campaign arithmetic). 20 caught at once. The one that was not, a partial cost reported as a total, got a test and is caught now. Kept separate from any agent score |
| Secret scan | No token or key pattern in tracked files, no tracked env file, no address outside reserved domains and no password in this branch's changes |

Not run: anything with a real model; anything with a live Gmail, Outlook or calendar.

Results by kind, as the evaluation screen separates them:

| Kind | State |
| --- | --- |
| Harness self-test | Exists (above) |
| Seeded integration | Exists: this section and section 2. No pass rate |
| Real-model sandbox | None |
| Live provider | None |

## 6. Blocking issues

- **The seeded backend has no mail that needs work.** A sweep opens nothing, so no run there
  reaches approval. The approval, held, executing, partial and verified states of the new screens
  are proven by tests, not seen in a browser.
- **No model.** Reading a meeting time from an email and writing a reply draft cannot be exercised.
- **No evaluation backend.** No real-agent result of any kind exists.

## 7. What I need from Agent 1

1. Seeded fixtures in `backend/dev/`: one action item, one meeting request at a free time, one at a
   busy time, one reschedule request, one message that needs a reply, and two connected seeded
   calendars. This is the cheapest way to make the whole run flow visible.
2. `state`, `next`, `held.reason` and action counts on `GET /desk/runs` rows; `partial` for a
   partly executed action (mismatches 1 and 2).
3. `/desk/eval/v1`, running the real Desk orchestration on synthetic providers with
   `sandbox: true` (`LIVE_INTEGRATION.md` section 9.3). The runner and adapter are ready.
4. Worker status once a background worker exists.
5. The fields `payload_overrides` may change per action, and `reply_target_missing` in the
   contract (mismatches 8 and 9).
6. `fetchDeskRuns` in `frontend/src/api/desk.ts` widened to what the server sends, with `limit`.
   I did not edit that file.

## 8. Three highest-impact improvements

1. **A sandbox evaluation backend.** Until it exists there is no number about the agent.
2. **Seeded mail that needs work, and run state in the list.** It turns the work queue from
   "proven by tests" into something a person can watch from arrival to verified result.
3. **External-write readiness, tested on isolated provider accounts.** It is the one switch between
   the Desk proposing work and the Desk finishing it.
