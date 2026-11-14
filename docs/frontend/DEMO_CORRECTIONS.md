# Frontend demo corrections (14 November 2026)

From the frontend owner (Agent 2), for the project lead, the backend owner (Agent 1) and the
office-simulation owner (Agent 4). Branch `agent2/demo-corrections`, started from `main` at
`2df5550`, with `main` at `c0f057d` merged in. It answers the frontend findings in Agent 4's checkpoint
(`hackathon/office-simulation/docs/CHECKPOINT.md` and `INTEGRATION_REQUESTS.md` on
`agent4/office-simulation`).

Nothing here is a result about the product's agent. Everything seen in a browser ran against an
isolated sandbox world with synthetic mail and calendars, rules only, no model. No real mailbox,
calendar or person was involved. No file under `backend/`, not `docs/BACKEND_CONTRACT.md` and not
`frontend/src/api/desk.ts` is changed.

## 1. What changed, by finding

| Finding | Before | Now |
| --- | --- | --- |
| The sidebar says "Live: Scriba" in green while every write is a sandbox write | One green note that merged "a backend is answering" with "writes are real" | The mode is read from `GET /desk/health` once (`live/executionMode.ts`) and shown in three places that always agree: a banner above every screen, the sidebar note and the phone's top bar. Four states: **SANDBOX** (simulated execution), **LIVE** (external writes authorized), **WRITES OFF** (external writes disabled, including a backend without the overlay) and mode unknown. "Connected to a Scriba backend" is a separate line. A sandbox wins over every readiness switch |
| No sandbox marker on Overview and Inbox | Marker only on run pages | The banner is part of the shell, so Overview, Inbox, Calendar, Tasks, Work queue, Run detail, Approvals and Activity all carry it. It cannot be dismissed |
| An executed sandbox card reads as a real send | "Completed", "Email: sent" | "Executed in sandbox, verified" (or "..., not verified"), "What happened in the sandbox (simulated)", "Email: sent in the sandbox", and a line that no real email or invitation went out and nobody was contacted. The approve control reads "Approve in sandbox" for every kind of action in a sandbox |
| A stage name shown as the server's is an alias (`AWAITING_REPLY`) | The screens worked in three first-draft names and printed them | The canonical names are the ones the backend sends: `UNDERSTANDING`, `INVESTIGATING`, `WAITING_FOR_RESPONSE`, `HELD`. The first-draft names are accepted as aliases and never shown. The run page's "Server state" line prints the server's own value |
| Dates in the browser's zone | The executive's zone was learned only when the Overview or Calendar had been opened | The zone is asked for once per session (`/desk/briefing`, in a sandbox the world's zone), whichever screen opens first. Until the backend names it, the sidebar says "(browser zone)". A sandbox world with a fixed clock sets the screens' "now" |
| Card dates from the seeded store ("Wed 15 Jul") | The card footer printed Scriba's record stamp | A card that belongs to a Desk run shows the time on the Desk's own evidence (proposed, decided, executed) |
| Stage labels overlap at 1280 px | Eight stages in one row of a 600 px column | Two rows of four below 1536 px, one row above; labels wrap |
| Scriba's seeded cards are counted in the approval badge and under "Handled by the secretary" | Every chat tool call counted as the secretary's | A card is Desk-owned when its conversation is a Desk run or its id is one of a run's actions (`live/ownership.ts`). Badges, the Overview and the main lists of Approvals and Activity count Desk-owned cards only. Cards from Scriba's chat are listed apart, collapsed, labelled "Not opened by the Desk" |
| After one of two actions executed, the top panel says nothing has happened | Wording keyed on "an approval is waiting" | Step-level progress from the plan and the server's evidence: "1 of 2 steps verified · 1 awaiting your decision", as a bar and in words, on the run page and on each queue row |
| An edit at approval is not shown | The card showed `input` only | When `action.edited` is not empty the card shows the operation as approved (`effectiveInput`) and a table "Originally proposed / Approved and executed" per field. If a backend names the edited fields without the approved values, the card says so and keeps the original |
| Green without evidence | A finished run was green on the server's word | A finished run is green only when every step that ran carries verification evidence; otherwise it is listed as "Executed, not verified". `VERIFICATION_FAILED`, `INTERRUPTED`, an unknown outcome and a blocked dependency each have their own wording, taken from `action.lifecycle` when the backend sends it |
| Calendar and Tasks show Scriba's seeded stores in a sandbox | They read `/calendar/events` and `/tasks` | In a sandbox they read the sandbox world: `GET /desk/memory` (overlay 0.4: meetings for two weeks, open tasks), or `GET /desk/briefing` on a backend without it (today's meetings, open tasks), and say which. The calendar has week navigation. No second state is kept in the frontend |
| Activity shows seeded cards | Same list as above | Desk-owned cards, plus the sandbox world's own operation log from `GET /desk/sandbox` |
| Cancel card says "No title on the card" | | The meeting's title is read from `event_title`, then from `action.target.title` (overlay 0.4) |

Also added because the reconciled contract asks for it: the block for a task a message reports as
finished (`taskUpdates`, with "Mark done" and "Dismiss"), the follow-up state `escalated`, and a
run opened by an instruction (`kind: "command"`) shown without a sender.

## 2. Confirmation: simulation is labelled

In a sandbox session every screen carries the SANDBOX banner; every run, plan, action card and
action record carries a SANDBOX tag; an executed action reads "Executed in sandbox"; verification
by read-back says it is simulated; and no screen says "Live". Checked by test
(`executionMode.test.ts` and the rendering tests) and in a browser: after a full approve, execute
and verify pass, no screen contained a bare "Email: sent" and no screen showed an address outside
the synthetic `.example` domains.

## 3. Browser verification

Chrome through Playwright, signed in through the Desk's own form, approvals given by real clicks
on "Approve in sandbox". Backend: the seeded Desk server with `--demo`.

| Workflow | Seen |
| --- | --- |
| Autonomous mail intake | The worker opened eight runs with no client action; the Overview and the queue say background intake is running |
| Worker opening a run | Run page: "Started by: the background intake worker" |
| Structured plan | Plan with intent, facts, assumptions and ordered steps |
| Approval | "Approve in sandbox" on the booking; then on the confirmation |
| Simulated execution | "Executed in sandbox" on the card and in the action record |
| Verification | "Verified. Evidence: the sandbox world was read back..." |
| Partial progress | "0 of 2", then "1 of 2 steps verified · 1 awaiting your decision", then "2 of 2 steps verified" |
| Follow-up waiting | The offer-of-times run rests in `WAITING_FOR_RESPONSE`, shown as "Waiting for a response", with the awaited reply |
| Completion | "Completed and verified", stage `COMPLETED` |
| Edit at approval | Start and end changed in the approve request: the card shows the approved time and the original beside it; the sandbox calendar shows the meeting at the approved time |

Responsive: all eight screens at 375, 768, 1280 and 1440 px. No horizontal overflow of the page or
of the main column on any of the 32, and no console error.

Screenshots: `docs/frontend/screenshots/demo-corrections/`. `00-before-*` are `main` at `2df5550`.

## 4. Backend compatibility

While this work was in progress the integrated backend was merged into `main` (`c0f057d`: the
reconciliation and overlay 0.4 together, with the reconciled typed client). This branch has
`main` merged in. Each row is a full pass through the Desk in a browser against that backend's
seeded demo server: approve, execute in the sandbox, verify, follow-up waiting, completion.

| Backend | Overlay | Result |
| --- | --- | --- |
| `main` at `c0f057d`, the integrated backend, run from this branch | 0.4.0 with the 0.3.1 fields | Passes. `effectiveInput` and `/desk/memory` both present. The committed screenshots are from this one, except `05` (the edited approval, taken earlier on a local merge of the same two backend branches) and `13` (the server without a sandbox) |
| `agent1/integration` at `14fba48` (not merged) | 0.5.0 | Passes. A send takes about two seconds there; the run page now re-reads itself when a card has moved on and the run has not |
| `agent1/engine-reconciliation` at `f06a258` | 0.3.1 | Passes. Calendar and Tasks use the briefing fallback (no `/desk/memory`) |
| `agent1/autonomous-engine` at `2e77414` | 0.4.0 | Passes |
| The integrated server without `--demo` | 0.4.0, no sandbox | WRITES OFF on every screen; mail and calendar approvals disabled with the server's reason |

Typed client: `frontend/src/api/desk.ts` is not edited on this branch. The branch type-checks
against the client on `main`. In a trial merge with `agent1/integration` (aborted, nothing
committed) it also type-checks against that branch's client.

**For whoever merges `agent1/integration`:** it conflicts with `main` itself in seven files, two of
them in the frontend. `runLifecycle.ts`: keep this branch's file and take the integration wording
inside `HELD_REASON_REVISED`; `FOLLOW_UP_STATE_REVISED` is already identical on both sides.
`deskRuns.test.ts`: take the integration side of the compatibility section only; the test "does
not call an executed action verified unless the backend says so" must stay as it is here, because
the wording it pins changed on purpose. With that, 519 of 519 tests pass on the merge.

## 5. Tests

In `frontend/`, with `main` merged in: `npm run typecheck` clean, `npm test` 519 passed in 28
files (452 before this work on the old `main`; 63 added here, 4 came with `main`), `npm run build`
succeeds. The fourteen tests that pinned the old wording were rewritten to the new behaviour, not
removed. One new test caught a real defect before the commit: on a backend without the overlay the
Overview counted no cards while the navigation counted them all.

Not run from this workstream: the backend's own suites, the evaluation runner, and anything with a
model or a real provider.

## 6. What still depends on someone else

For the backend owner:

1. **Overlay 0.5 (`agent1/integration`) still has to be merged with `main`.** Section 4 says how the two
   frontend conflicts resolve. The run page already shows its `unresolved` requests and the
   take-over control; that block was built from the contract and has not been seen with a run
   that carries one, because the demo world stages none.
2. **The executive's time zone on `GET /desk/health`** (or `/desk/connections`). Today it is only
   on the briefing, which is a slow read on a real backend and null on the seeded backend without
   a world. One field, `timezone`, removes the "(browser zone)" state.
3. **A capability name for `/desk/memory`** in `health.capabilities`. Today its presence is found
   by a 404, once per session.
4. **The sandbox world's reminders and completed tasks** have no list route. The Tasks screen says
   so; `/desk/memory` could carry them.
5. **A marker on Scriba's own card record** when it was executed in a sandbox. Scriba's outcome
   text says "Calendar invitation sent by Google Calendar"; the Desk overrides that wording only
   because the run's action says `simulated`. A card approved from Scriba chat in a sandbox has no
   run, so its simulation cannot be labelled from the card alone. Such cards are kept apart from
   the secretary's work, and the banner still applies.
6. From the earlier handoffs, unchanged: widen `DeskRunHeld.reason`, fold the revised kinds and
   codes into the typed client.

For the office-simulation owner: the capture script's own yellow bar and its `Date.now()` override
are no longer needed for labelling, and a world with `fixedClock` now sets the screens' clock
through `GET /desk/sandbox`. The recording was not re-made from this workstream.

Not done: an edit control on the approval card (the Desk shows an edit made through the approve
request; it does not offer one), and no real provider or model was used.
