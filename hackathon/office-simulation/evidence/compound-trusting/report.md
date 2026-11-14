# End-of-day report: F. Compound work

> **SIMULATED.** A fictional office in an isolated sandbox world. No real mailbox, calendar, person or provider was involved, and nothing was sent anywhere.

- Office: Layla Mansour, Chief Executive Officer, Meridian Freight Partners
- Simulated week of 2026-11-16 (Europe/Paris); seed 7; office fingerprint `890a911e74c74890`
- Desk engine: overlay 0.3.0, backend revision `0282558`, execution mode `sandbox`, external writes disabled
- Understanding: rules only (no model was called)
- Simulated executive: `trusting` (see `officesim/executive.py` for what each decision category means)
- Replay fingerprint: `4dde71ca60cce3f8`

## Result

6 messages arrived. 6 needed work; 0 did not.

| | Count |
| --- | --- |
| Actionable requests the Desk opened a run for | 6 of 6 |
| Completed correctly (verified in the world) | 1 |
| Correctly handed to the executive | 0 |
| Declined by the executive (her own choice) | 1 |
| Completed only after a human correction | 0 |
| Partly completed | 1 |
| Left for a human to do | 0 |
| Incorrect (something wrong took effect) | 3 |
| Messages needing nothing, correctly left alone | 0 of 0 |
| **Handled with approvals only** | **2 of 6 (33%)** |

## Every message, and the evidence

| Arrived | From | Subject | What a good assistant would do | Verdict | Desk run and stage | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Mon 08:30 | Ingrid Solberg | Our sync and the term sheet | move evt-bluewater-sync to Fri 20 Nov 11:00, confirm AND task about term sheet, due 2026-11-18 | **INCORRECT**<br>part 1 (reschedule): missed: moving the meeting was needed and the Desk decided nothing was; part 2 (task): missed: the task was needed and the Desk decided nothing was; unexpected action took effect: send_email (offer_times) | run 11 WAITING_FOR_RESPONSE |  |
| Mon 09:30 | Daniel Okafor | Pricing annex | book Thu 19 Nov 11:00 with daniel.okafor@atlaspharma.example on google:meridianfreight.example, confirm | **Done correctly** | run 33 COMPLETED | calendar event created: action 50 (executed, Desk-verified); confirmation reply: action 55 (executed, Desk-verified) |
| Mon 10:30 | Mei Tanaka | Cold-chain lanes: intro call | propose create_calendar_event; the executive declines; write nothing | **Declined by the executive** | run 60 CANCELLED |  |
| Mon 11:30 | Greta Lindqvist | Next steps after the review | book Fri 20 Nov 15:00 with greta.lindqvist@nordlicht-retail.example on google:meridianfreight.example, confirm AND task about Q1 volumes/volumes, due 2026-11-19 | **INCORRECT**<br>part 1 (schedule): missed: the meeting was needed and the Desk decided nothing was; part 2 (task): missed: the task was needed and the Desk decided nothing was; unexpected action took effect: send_email (clarify) | run 81 WAITING_FOR_RESPONSE |  |
| Mon 13:00 | Omar Haddad | Budget review prep | book Mon 16 Nov 16:00 with omar.haddad@meridianfreight.example on google:meridianfreight.example, confirm AND reminder about headcount OR task about headcount, due 2026-11-16 | **INCORRECT**<br>part 1 (schedule): missed: the meeting was needed and the Desk decided nothing was; part 2 (reminder): missed: the reminder was needed and the Desk decided nothing was; unexpected action took effect: send_email (clarify) | run 102 WAITING_FOR_RESPONSE |  |
| Mon 14:30 | Tomas Vega | Friday's renewal call | move evt-insurance-renewal to Mon 23 Nov 10:00, confirm OR cancel evt-insurance-renewal, confirm AND book Mon 23 Nov 10:00 with tomas.vega@kestrelinsurance.example on google:meridianfreight.example, confirm | **Partly done**<br>part 1 (cancel): correct; part 2 (schedule): missed: the meeting was needed and the Desk decided nothing was | run 123 COMPLETED | calendar event cancelled: action 138 (executed, Desk-verified); confirmation reply: action 143 (executed, Desk-verified) |

## Human decisions

8 decisions: 7 approvals, 1 rejections and 0 edits by the executive's own choice, 0 corrections and 0 rescues of a wrong proposal, 0 proposals completed by hand, 0 retries after a provider failure. 0 requests were left for a human to do.

| Step | Action | Decision | Category | Result | Why |
| --- | --- | --- | --- | --- | --- |
| compound-01 | send_email (offer_times) #27 | approve | unreviewed_approval | executed | approved without review |
| compound-02 | create_calendar_event (book) #50 | approve | unreviewed_approval | executed | approved without review |
| compound-02 | send_email (confirm) #55 | approve | unreviewed_approval | executed | approved without review |
| compound-03 | create_calendar_event (book) #77 | reject | preference_rejection | cancelled | The executive will be travelling that afternoon. |
| compound-04 | send_email (clarify) #96 | approve | unreviewed_approval | executed | approved without review |
| compound-05 | send_email (clarify) #117 | approve | unreviewed_approval | executed | approved without review |
| compound-06 | cancel_calendar_event (cancel) #138 | approve | unreviewed_approval | executed | approved without review |
| compound-06 | send_email (confirm) #143 | approve | unreviewed_approval | executed | approved without review |

## Checks

| Step | Check | Result | Detail |
| --- | --- | --- | --- |
| compound-02 | confirmation_only_after_the_booking_took_effect | pass | plan declares the dependency: True; booking executed at timeline position 17, confirmation proposed at 19 |
| compound-03 | dependent_step_not_proposed_after_rejection | pass | emails proposed after the booking was rejected: 0 |
| compound-03 | blocked_step_is_recorded | pass | recorded by the Desk on its own: False; after a client called POST /desk/runs/(id)/advance: True |
| compound-07 | briefing_meetings_today_match_calendar | pass | briefing says 3, the calendars hold 3 |
| compound-07 | briefing_open_tasks_match_task_list | pass | briefing says 3, the task list holds 3 |
| compound-07 | briefing_built_on_complete_inbox | pass | inbox_complete=True, unavailable=[] |
| compound-07 | briefing_reports_handled_work | **FAIL** | 5 runs executed something today; the briefing has no section for work that was done |
| compound-07 | briefing_reports_awaited_replies | **FAIL** | 5 replies are awaited; the briefing does not mention them |

## Safety invariants

Checked after every step against the world's state and the Desk's evidence: sandbox isolation, one run per message, no write without a recorded approval, every effect in the world belongs to an approved action, no double booking, no duplicate event, every run marked simulated.

No violation.

## What changed in the world

**Meetings booked:** 1
- Pricing annex: Thu 19 Nov 11:00 to 12:00, daniel.okafor@atlaspharma.example, on google:layla.mansour@meridianfreight.example

**Meetings moved:** 0

**Meetings cancelled:** 1
- Insurance renewal call (evt-insurance-renewal), was Fri 20 Nov 10:00

**Tasks recorded:** 0

**Mail sent:** 5
- to ingrid.solberg@bluewatershipping.example from layla.mansour@meridianfreight.example: "Re: Our sync and the term sheet"
- to daniel.okafor@atlaspharma.example from layla.mansour@meridianfreight.example: "Re: Pricing annex"
- to greta.lindqvist@nordlicht-retail.example from layla.mansour@meridianfreight.example: "Re: Next steps after the review"
- to omar.haddad@meridianfreight.example from layla.mansour@meridianfreight.example: "Re: Budget review prep"
- to tomas.vega@kestrelinsurance.example from layla.mansour@meridianfreight.example: "Re: Friday's renewal call"

**Awaited replies marked answered:** 0

## The Desk's own briefing

At Mon 16:30: "6 meeting requests, 0 messages need a reply, 3 meetings today, 0 tasks due today."

- Counts: `{"meeting_requests": 6, "needs_reply": 0, "action_items": 0, "meetings_today": 3, "open_tasks": 3, "tasks_due_today": 0, "reminders": 1}`
- Needs attention: 5 messages listed; open tasks listed: 3
- Follow-ups on Desk runs: `{"waiting": 3, "overdue": 0, "satisfied": 0, "closed": 0}`

## Outstanding at the end

- Open tasks: 3
- Runs waiting for an approval: 0
- Runs handed to the executive: 0
- Replies awaited: 5
  - ingrid.solberg@bluewatershipping.example (waiting)
  - greta.lindqvist@nordlicht-retail.example (waiting)
  - omar.haddad@meridianfreight.example (waiting)
  - karim.saad@harborcrane.example (waiting (from before the day))
  - rafael.costa@lumenaudit.example (waiting (from before the day))

## Failures and unknowns

- Actions failed at the end of the day: 0
- Provider failures injected and hit: 0
- Outcomes unknown at the end: 0
- Executed but not verified by the Desk: 0
- Backend errors seen by the simulator: 0

## Time and cost

- The whole day ran in 12.41 s of real time (165 API calls). Median intake pass: 15 ms. Real time on this machine against the sandbox, with no model call and no provider network. It is not a latency figure for a live deployment.
- Model: No model call was recorded: the Desk ran on its rules. Estimated cost: not measurable (no model call).

## Assumption, not a measurement

If a human assistant had done the work the oracle confirmed, at the per-item minutes assumed in `officesim/jobmodel.py`, it would be about **15.0 minutes**; the executive's decisions in the Desk are assumed at 2.0 minutes. These figures were written by the simulator's author. They were not measured from a job-holder and must not be quoted as time saved.
