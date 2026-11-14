# Browser capture

Screenshots of the Scriba Executive Desk frontend, in live mode, reading the
office-simulation sandbox. Everything is synthetic and stays on this machine.

```
node browser/capture.mjs --frontend http://localhost:5183 --api http://localhost:8924 \
     --out evidence/screenshots --name 01-proposed [--run <runId>] [--approve <toolCallId>]
```

It signs in through the Desk's sign-in form as the seeded user, opens each
screen, waits for its data, and writes `<name>-<screen>.png` and
`<name>-capture.json` into `--out`.

| Screen | Route | File |
| --- | --- | --- |
| Overview | `#/overview` | `<name>-overview.png` |
| Inbox | `#/inbox` | `<name>-inbox.png` |
| Work queue (Desk runs) | `#/work` | `<name>-work-queue.png` |
| One run, with `--run N` | `#/work/N` | `<name>-run-N.png` |
| Approval center | `#/approvals` | `<name>-approvals.png` |
| Tasks and follow-ups | `#/tasks` | `<name>-tasks.png` |
| Activity | `#/activity` | `<name>-activity.png` |
| Find a time | `#/calendar/find-a-time` | `<name>-find-a-time.png` |
| Calendar week | `#/calendar` | `<name>-calendar.png` |

`--screens a,b,c` limits the set. Secretary chat and Evaluation are not captured.

## What the script guarantees

- **Every picture is labelled.** A yellow bar reading `SIMULATED: sandbox data,
  fictional office, nothing real was sent or changed`, the sandbox clock and
  the capture name is added above the application. The application is made shorter by the
  bar's height; nothing is covered, and the script fails if it would be.
- **Read-only.** Every request from the page to the API other than GET and the
  sign-in POST is aborted in the browser and listed under `log.blockedWrites`.
- **`--approve <toolCallId>`** is the one exception: it opens that action's run,
  clicks the Desk's real Approve control (in a sandbox it reads "Approve in
  sandbox") and lets exactly one request through, `POST
  /chat/tool-calls/<id>/approve`. It refuses when the control is missing or
  disabled, and reports the status the server gives afterwards. It writes
  `<name>-approve-<id>-before.png` and `-after.png`.
- **No faked result.** A screen with an error note, a sign-in form, or a loader
  that never ends is still saved, is listed with its problem, and makes the
  exit code 1. Exit 2 is a bad argument; exit 3 is no browser, no frontend or a
  failed sign-in.
- **Warnings, not failures,** when a screen is honest but is not showing the
  simulation: the calendar week grid and the task list read Scriba's own
  `/calendar/events` and `/tasks`, and the script says so when those do not
  hold what the sandbox world holds.

## The browser clock

The Desk works out "today" and "this week" from the browser's clock. The
sandbox world has its own date, so the script sets the page's `Date.now()` to
the world's clock (`GET /sim/state`) and prints that clock in the bar.
`--real-clock` turns this off.

## Setup

```
cd browser && npm install        # Playwright only; no browser download
```

The script uses Playwright's own Chromium when it is installed, otherwise the
system Chrome, otherwise Edge (`--channel chrome|msedge|bundled` forces one).

Both URLs must use `localhost` (not `127.0.0.1` for one of them): the session
cookie is SameSite=Lax. The sandbox must be started with
`ALLOWED_ORIGINS=http://localhost:5183` so that Scriba's API accepts the
frontend's origin, and the frontend with
`VITE_API_BASE_URL=http://localhost:8924 npx vite --port 5183 --strictPort`
(its default mode is live; `--mode demo` would be the mock).

Other options: `--email`, `--password` (or `OFFICESIM_EMAIL`,
`OFFICESIM_PASSWORD`; default is the seeded user), `--timeout <ms per screen>`,
`--headed`.

## Which screens to publish

`python -m officesim demo --browser --frontend http://localhost:5183` runs
this script at six moments of the demonstration day and asks only for the
screens that read the sandbox world: overview, inbox, work queue, run detail,
approval center and find a time. Its output is `evidence/demo/screenshots/`.

Do not publish the Tasks, Calendar or Activity screens from this backend.
They read Scriba's own seeded test stores, not the simulated office: Tasks
and Calendar show nothing of the simulation, and Activity lists Scriba's own
seeded cards, whose text was not written for this simulation and is not
limited to reserved example addresses.

## Recording a video

```
node browser/record.mjs --frontend http://localhost:5183 --api http://localhost:8924 \
     --out evidence/demo/recording --name desk-demo [--frontend-rev <sha>] [--no-second-part]
```

One continuous video (`<name>.webm`, VP9, 1152x720) of the Desk handling two
messages, plus `<name>.json` and `<name>-still-NN-*.png`. The sandbox must be
freshly started with `--worker thread`: the Desk's own background worker opens
the runs, and the message ids are used once per sandbox.

- The script itself, outside the page, makes `POST /sim/clock` once and
  `POST /sim/deliver` once per message (listed under `scriptRequests`).
- The page may make the sign-in POST and `POST /chat/tool-calls/<id>/approve`
  for the action being approved at that moment (listed under `pageWrites`).
  Any other write from the page is aborted (`blockedWrites`).
- Every frame carries the yellow bar: the SIMULATED line and a caption for the
  step. A step that does not happen is captioned as such and gives exit code 1.
- The browser is put on the sandbox world's clock and time zone.
- Video needs Playwright's ffmpeg helper: `npx playwright install ffmpeg`.
  It cannot write MP4; use a full ffmpeg for that.
