# Two-minute demonstration: storyboard, narration, shot list

**No video has been recorded.** This is the plan for one, built on what the
software does today. Every shot is reproducible with
`python -m officesim demo` (terminal) and
`python -m officesim demo --browser --frontend http://localhost:5183`
(the Desk frontend). Still frames of the frontend shots already exist in
`evidence/demo/screenshots/`.

Three rules for whoever records it:

1. Every frame of the frontend carries the "SIMULATED" bar, and the
   narration says "in the sandbox" once, early. A sandbox run is never shown
   or described as a real send.
2. Nothing is narrated that is not on screen in that shot.
3. The numbers spoken are the ones in `evidence/RESULTS.md` on the day of
   recording. Re-run `python -m officesim run all` and
   `python -m officesim results` first, and re-read this script against them.

The job stays the same in every shot: Executive Inbox-to-Action Management.

## Storyboard

| Time | Shot | On screen | Narration |
| --- | --- | --- | --- |
| 00:00 to 00:15 | 1. The job | The office card: Layla Mansour, CEO; three mailboxes, three calendars; eleven meetings this week; two replies awaited. Then the list of the ten things an assistant does with a message | "An executive assistant does the same loop all day: read what arrived, work out what it needs, find a time across calendars, answer, note the deadline, chase the reply that never came, and report back. That job is what Scriba Executive Desk does. This is a simulated office in a sandbox: invented people, nothing real is sent." |
| 00:15 to 00:30 | 2. Mail arrives | Terminal: Monday 08:30, five messages land (a newsletter, an itinerary, good news, a sign-off request, a meeting request). The Desk's inbox with the same five, classified | "Monday, half past eight. Five messages arrived over the weekend. Nobody opens the Desk. Its intake worker picks them up, leaves the newsletter, the itinerary and the good news alone, and opens a run for the two that need work." |
| 00:30 to 00:55 | 3. Understanding and planning | Run detail for Mei's request: the stages; the reads (thread, three calendars); the plan with two steps, the second depending on the first; the fact "free on every connected calendar"; the assumption "the only attendee is the sender" | "For each one it reads the thread and all three calendars, and writes a plan. Book the call on Wednesday at two, then confirm to the sender, and only after the booking exists. It states what it verified, and what it assumed." |
| 00:55 to 01:15 | 4. Two providers, and the approval | Approval center: the booking, and Greta's request for a time that is taken, answered with a reply offering free times. Then the multi-provider day's report rows: a Gmail request not booked because the Outlook board meeting is at that time; an Outlook request booked on the Outlook calendar | "A second client wants a time that is already taken. The Desk does not book it. It proposes a reply with times that are free on Google and on Outlook. Nothing goes out until the executive approves, action by action. On the multi-provider day, a Gmail request was not booked because the conflict was on the Outlook calendar, and requests that reached Outlook were booked on Outlook." |
| 01:15 to 01:40 | 5. Execution, verification, follow-up | Click "Approve in sandbox". The run detail: executed, "Verified: the sandbox world was read back", the confirmation proposed next. Terminal: the client picks one of the offered times; a new run books it; the follow-up closes. Then the unreliable day: a timed-out send settled by a read-back, not sent twice | "She approves. The event is created in the sandbox, and the Desk reads it back before calling it done. Then it proposes the confirmation. Twenty minutes later the client picks one of the offered times: the Desk books it and closes the follow-up. When a provider times out, it reads the state back instead of sending twice." |
| 01:40 to 02:00 | 6. The measured day, and the difference | The results table. Then two lines from the findings | "Across eight simulated days and seventy-seven requests that needed work, fifty-three were handled with nothing from the executive but an approval, and no wrong action reached the world. Fourteen wrong proposals were stopped at the approval step, and nineteen requests were left for a person. That is rules only, in a sandbox, with no model yet. A chatbot answers when asked. This starts on its own, keeps the state of the work, asks before it acts, and checks what it did." |

Read the numbers in shot 6 from `evidence/RESULTS.md` before recording. At
the time of writing they are: 77 actionable requests; 53 handled with
approvals only; 0 incorrect; 14 wrong proposals stopped; 19 left for a human.

## Shot list

| Shot | Source | How to produce it |
| --- | --- | --- |
| 1 | Terminal | `python -m officesim init`, then the table in `docs/JOB_MODEL.md` |
| 2 | Terminal, then frontend inbox | `python -m officesim demo --step`: stop after the first step. Still: `evidence/demo/screenshots/01-morning-proposals-inbox.png` |
| 3 | Frontend run detail | Still: `01-morning-proposals-run-11.png` (plan and reads, before approval) |
| 4 | Frontend approval center; a report | Stills: `01-morning-proposals-approvals.png`, `03-conflict-offer-proposed-approvals.png`. Report: `evidence/multi_provider/report.md`, rows "Holiday shipping plan" and "Budget committee prep" |
| 5 | Frontend run detail; terminal | Live: `python -m officesim serve`, inject Mei's message, `tick`, then click Approve in the frontend. Stills: `02-morning-executed-run-11.png`, `04-client-picked-a-slot-booked-run-86.png`. Terminal: the `unreliable` day, step 9 |
| 6 | The results table | `evidence/RESULTS.md`, first table; `docs/FINDINGS.md`, "What held up" |

For a live recording of shots 2 to 5 in the frontend:

```bash
# terminal 1: the frontend (see ../README.md)
VITE_API_BASE_URL=http://localhost:8914 npx vite --port 5183 --strictPort --host localhost
# terminal 2: the sandbox, kept running, with the Desk's own worker timer on
ALLOWED_ORIGINS=http://localhost:5183 python -m officesim serve
# terminal 3: the day, one step at a time
python -m officesim clock 2026-11-16T08:30:20+01:00
python -m officesim inject --from mei --subject "Cold-chain lanes: intro call" \
  --body "Hi Layla, would you be free on Wednesday at 14:00 for a 30 minute call to walk through the new cold-chain lanes?"
python -m officesim inject --from greta --subject "Peak-season forecast" \
  --body "Hi Layla, could we meet tomorrow at 14:30 for an hour to go over the peak-season forecast?"
# wait for the worker (15 s), or: python -m officesim tick
```

Then approve in the browser.

## What not to show, and why

- **The Calendar, Tasks and Activity screens.** On this backend they read
  Scriba's own seeded stores, not the simulated office. Use "Find a time"
  for the calendars.
- **The briefing as the end-of-day report.** It does not list what was done
  (FINDINGS.md, item 8). Use `evidence/demo/report.md` and say it is the
  simulator's report.
- **Any claim about a model, a live mailbox or time saved.** None of the
  three has been measured.
- **The edit-at-approval path.** It is a known defect (FINDINGS.md, item 1).
  If asked, show it: the Desk catches its own mismatch and escalates.

## A shorter, spoken-only version (about 45 seconds)

"An executive assistant reads what arrives, works out what it needs, finds a
time across calendars, answers, notes the deadline, chases the reply and
reports back. Scriba Executive Desk does that loop. Mail arrives and it
starts on its own. It reads the thread and every calendar, plans the steps,
and puts each action in front of the executive. Nothing is sent or changed
without her approval, and it reads the result back before it says done. In a
simulated office, over eight days and seventy-seven requests, fifty-three
needed nothing from her but an approval, and no wrong action got through.
That is on rules alone, in a sandbox. The model and the live mailbox are next."
