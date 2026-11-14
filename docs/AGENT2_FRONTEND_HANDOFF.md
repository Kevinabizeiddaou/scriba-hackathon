# Agent 2 frontend handoff

Branch `agent2/frontend-excellence`, based on `main` at `a006db0`. Frontend and its documents only.
Nothing under `backend/`, `docs/BACKEND_CONTRACT.md` or `frontend/src/api/` is changed, and no
endpoint, request or response type is added or altered. Not merged.

This pass audits and polishes screens that already existed. It adds no new data source: every
number and state on a live screen still comes from the same server reads as before.

Written 14 November 2026.

## 1. Audit: what was wrong, in order of importance

The audit ran every screen in demo mode and in live mode (on Scriba's seeded test backend) at
1440, 768 and 375 px: 60 page loads, each checked for horizontal overflow, contrast, text size,
target size, unnamed controls, heading order and failed requests, and then looked at by eye.

Found clean: no horizontal overflow anywhere, no contrast failure, no unnamed control, one `h1` per
screen with headings in order.

| # | Problem | Where | Fixed |
| --- | --- | --- | --- |
| 1 | On a phone the overview stacked five full-width tiles, so the decisions waiting for the user started below the first screen | Overview (demo) | Yes |
| 2 | The overview showed six equal tiles; nothing separated what is waiting on the user from what the secretary has in hand, and nothing listed what it had finished | Overview (live) | Yes |
| 3 | On a phone the action card footer squeezed "Updated Wed 15 Jul, 08:05" into a four-line column beside the buttons | Approval center, activity, chat, run detail (live) | Yes |
| 4 | Text under 12 px (10 to 11.5 px) on every screen: chips, section labels, badges, timestamps. 46 places in the code, plus the shared chip and label styles | Everywhere | Yes |
| 5 | Small touch targets: task checkboxes 20 px, "View" links 28 by 22, section links 22 px high | Tasks, activity, overview | Yes |
| 6 | A step that failed three times appeared as three identical rows; there was no way to see only what failed or what is waiting | Activity (demo) | Yes |
| 7 | Every inbox row carried the same weight: a "For information" chip looked like an "Action required" chip, and urgent mail was marked only by one chip among several | Inbox | Yes |
| 8 | Filter rows that scroll sideways were cut mid-word with no sign that more followed | Inbox, activity, calendar day picker, chat prompts, work queue | Yes |
| 9 | Six empty headline tiles, each drawing a large dash, took two rows before any result existed | Evaluation | Yes |
| 10 | The week view did not show where the day had got to, and a conflict was marked by border colour only | Calendar | Yes |
| 11 | A chat reply carrying several actions gave no count and no order; assistant messages were not labelled | Secretary chat (live) | Yes |
| 12 | Page titles disagreed with the navigation ("Approval Center", "Evaluation Dashboard", "Secretary Chat") | Three screens | Yes |
| 13 | Every page load requested a favicon that did not exist (404 in the console) | All | Yes |

Looked at and left alone, with the reason:

| Observation | Why it was left |
| --- | --- |
| The live overview shows skeleton rows for several seconds on the seeded backend | The briefing read is slow there. The screen already shows each section as its own read finishes; hiding the wait would mean showing something not yet known |
| Page subtitles take three lines on a phone | They carry the trust statements ("nothing here has happened yet"). Cutting them was judged worse than the space |
| Four evaluation case buttons are 38 px high on a phone | Above the 24 px minimum; changing the grid would reflow the twenty-case strip |
| The inbox detail pane is empty until a message is chosen | Choosing one automatically would mark a read the user did not make |

## 2. Features improved

**Overview (live).** The six tiles are one strip in two halves. "Waiting on you": awaiting approval,
failed or partial, mail that needs action. "With the secretary": arrived, executing, completed. A
new section, "Handled by the secretary", lists finished work: chat actions whose server status is
`executed`, and Desk runs whose state puts them in the "completed" or "no action needed" group. A
proposal that is waiting and an action that failed are never listed there. On a phone the
explanations under the numbers are dropped, except when a read failed.

**Overview (demo).** Tiles sit two to a row on a phone, with the approvals tile across the top.

**Inbox.** Urgent and high-priority mail has a rail down the side and the word. Each kind of mail has
its own icon (meeting, action, reply, follow-up). Mail that asks for nothing is labelled in plain
text. Unread mail has a dot and is announced as unread.

**Calendar.** Today's column is tinted; a line marks the current time, on today only and only inside
the hours shown; an event in conflict carries a warning mark beside its title.

**Secretary chat (live).** Assistant messages are labelled "Secretary". A reply with more than one
action says how many there are and where each stands, from the server statuses, and numbers the
cards ("Action 2 of 3").

**Approval cards (live).** On a phone the source and time take their own line above the buttons.

**Activity (demo).** A second filter row by outcome (waiting, failed, done, rejected) with counts.
Identical consecutive records are one row with a count ("Tried 3 times") and the time span.

**Evaluation.** The six headline numbers are one strip. A number that does not exist is drawn small
and grey. No number is added or changed.

**Everywhere.** No text under 12 px. Small links and checkboxes get a 44 px touch area without
changing their size in the layout. Rows that scroll sideways fade at the trailing edge. A favicon.
Titles match the navigation.

## 3. Files changed

Screens and components: `frontend/src/live/LiveOverviewPage.tsx`, `LiveChatPage.tsx`,
`ToolCallCard.tsx`; `frontend/src/pages/OverviewPage.tsx`, `InboxPage.tsx`, `CalendarPage.tsx`,
`ActivityPage.tsx`, `EvaluationPage.tsx`, `ApprovalsPage.tsx`, `ChatPage.tsx`, `TasksPage.tsx`.

Styles and shell: `frontend/src/index.css` (the `.hit` touch area, the `.scroll-fade` edge),
`frontend/index.html` (favicon, theme colour).

Text size only (a class name changed from an 10 to 11.5 px size to 12 px): `components/ActionTimeline.tsx`,
`AppShell.tsx`, `ApprovalCard.tsx`, `CaseDetail.tsx`, `RequestDetail.tsx`, `RunCard.tsx`,
`workspace.tsx`, `live/LiveRunDetail.tsx`, `live/LiveWorkPages.tsx`, `live/LiveWorkQueuePage.tsx`.

Tests: `frontend/src/App.test.tsx`, `frontend/src/Desk.test.tsx`, new
`frontend/src/pages/presentation.test.ts`.

Documents: this file, `docs/frontend/FEATURE_STATUS.md` (generated from
`frontend/src/lib/featureStatus.ts`, one entry added), `docs/frontend/screenshots/` (15 demo images
and 5 live-seeded images retaken, with their notes).

## 4. Tests performed

All run on this branch on 14 November 2026.

| What | Result |
| --- | --- |
| Frontend tests | 383 passed in 21 files (`main`: 372 in 20) |
| Type check | Clean |
| Production build | Clean; largest script 242 kB, no chunk over 500 kB |
| Harness self-test | Passed: every reference script passes, every planted defect is caught |
| Mutation check on the new tests | 16 planted defects, 16 caught. Two more were discarded because they did not change behaviour |
| Browser, demo mode, 1440 / 768 / 375 px | 30 page loads: no overflow, no contrast failure, no text under 12 px, no failed request |
| Browser, live mode on the seeded backend, 1440 / 768 / 375 px | 30 page loads: the same |
| Touch targets on an emulated touch phone (375 px), 20 page loads | No control under 40 px in either direction, except: the skip link (shown on focus), four 38 px evaluation buttons, and the 16 px box of the work queue's timer option, whose whole label is the target |

New tests cover: the two halves of the overview strip and which tile is in which; the finished-work
list (present only for server-reported completion, absent for waiting and failed work); inbox
priority rail, kind icons and the quiet label; the calendar now line and conflict mark; activity
outcome filter and collapsed repeats; the chat summary for several actions.

Not covered by an automated test: the 12 px floor, the touch areas and the edge fade are CSS, and
the unit tests run without CSS. They were measured in the browser passes above.

One caution about the browser passes: the seeded backend has no mail that needs work and no
connected calendar. Live screens were seen with completed chat actions, two task proposals and one
no-action run. A run awaiting approval, a held meeting request and a partly executed action were
not seen in a browser on this branch either; they remain covered by tests on the contract's shapes.

## 5. What is mock and what is live

Unchanged by this branch. The full list is `docs/frontend/FEATURE_STATUS.md`.

Live (reads Scriba or the Desk overlay): overview, work queue, run detail, inbox, calendar,
find a time, tasks, reminders, secretary chat, approval center, activity, connected accounts.

Mock only, and labelled as such on screen: demo mode (`npm run dev:demo`), where every screen runs
on fictional data; the evaluation screen's scripted reference agent. The activity outcome filter
and the collapsed repeats are on the demo activity screen: the live activity screen lists Scriba's
action cards and already filters by stage.

Nothing mock is shown in live mode, and a failed live read is still shown as a failure.

## 6. Backend capabilities still needed

None is new. This pass asks for nothing that is not already listed in
`docs/frontend/AGENT2_FRONTEND_STATUS.md` section 7 and `docs/frontend/LIVE_INTEGRATION.md`. The
ones this pass ran into again:

- A state per row on `GET /desk/runs`, so the overview and the work queue do not read runs one by one.
- A work-queue listing across conversations, so "Completed" and the finished-work list are not
  limited to the twelve most recent conversations.
- Tracking of sent mail awaiting a reply; until then the overview says follow-ups are not tracked.
- Evaluation routes for the real agent; until then every headline number stays empty.

## 7. Assumptions that need Agent 1's confirmation

1. **A completed action and its run may both appear as finished work.** The finished-work list takes
   completed chat actions and completed runs. If a run's action is also returned as a chat action in
   a recent conversation, the same piece of work can be listed twice (once by its action, once by
   its message). If `DeskRun.actions[].toolCallId` always matches a chat tool call id, say so and
   the list will drop the action when its run is listed.
2. **`no_action_proposed` is treated as handled.** A run in that state is listed under "Handled by the
   secretary" as "No action needed". If that state can also mean "the secretary could not tell",
   it belongs under "Waiting on you" instead.
3. **A status this frontend does not know counts as planning**, never as completed, in the chat
   summary. This follows the existing rule in `frontend/src/live/workQueue.ts`.

## 8. Possible integration conflicts

- `frontend/src/live/LiveOverviewPage.tsx` is restructured (the status strip and one new section).
  A concurrent edit to the same file will conflict; the data it reads is unchanged.
- The region formerly labelled "Work queue" on the overview is now "Where the work stands", because
  "Work queue" is also the name of a screen. A test or script that looks the region up by its old
  name needs the new one.
- The headings "Approval Center" and "Evaluation Dashboard" are now "Approval center" and
  "Evaluation".
- Text-size class names changed in ten shared components. A branch that edits the same lines will
  see small conflicts that are safe to resolve either way, as long as no size under 12 px returns.
- No file Agent 1 owns is touched, so no conflict is expected with backend work.
