# End-of-day report: D. Unreliable services

> **SIMULATED.** A fictional office in an isolated sandbox world. No real mailbox, calendar, person or provider was involved, and nothing was sent anywhere.

- Office: Layla Mansour, Chief Executive Officer, Meridian Freight Partners
- Simulated week of 2026-11-16 (Europe/Paris); seed 7; office fingerprint `890a911e74c74890`
- Desk engine: overlay 0.3.0, backend revision `0282558`, execution mode `sandbox`, external writes disabled
- Understanding: rules only (no model was called)
- Simulated executive: `attentive` (see `officesim/executive.py` for what each decision category means)
- Replay fingerprint: `b9e47451020e7d38`

## Result

11 messages arrived. 11 needed work; 0 did not.

| | Count |
| --- | --- |
| Actionable requests the Desk opened a run for | 11 of 11 |
| Completed correctly (verified in the world) | 9 |
| Correctly handed to the executive | 2 |
| Declined by the executive (her own choice) | 0 |
| Completed only after a human correction | 0 |
| Partly completed | 0 |
| Left for a human to do | 0 |
| Incorrect (something wrong took effect) | 0 |
| Messages needing nothing, correctly left alone | 0 of 0 |
| **Handled with approvals only** | **11 of 11 (100%)** |

## Every message, and the evidence

| Arrived | From | Subject | What a good assistant would do | Verdict | Desk run and stage | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Mon 08:31 | Mei Tanaka | Cold-chain lanes: intro call | hand to the executive (A calendar cannot be read: availability is unknown, so nothing may be booked or offered.) | **Correctly handed to the executive** | run 11 ESCALATED |  |
| Mon 08:51 | Jonas Weber | Pipeline numbers | book Wed 18 Nov 11:00 with jonas.weber@meridianfreight.example on google:meridianfreight.example, confirm | **Done correctly** | run 28 COMPLETED | calendar event created: action 45 (executed, Desk-verified); confirmation reply: action 50 (executed, Desk-verified) |
| Mon 09:12 | Omar Haddad | Revised travel policy | task about travel policy, due 2026-11-18 | **Done correctly** | run 55 COMPLETED | task created: action 65 (executed, Desk-verified) |
| Mon 09:30 | Greta Lindqvist | Forecast call | book Wed 18 Nov 15:00 with greta.lindqvist@nordlicht-retail.example on google:meridianfreight.example, confirm | **Done correctly** | run 70 COMPLETED | calendar event created: action 87 (executed, Desk-verified); confirmation reply: action 95 (executed, Desk-verified) |
| Mon 10:00 | Priya Nair | Our 1:1 today | move evt-priya-1on1 to Mon 16 Nov 16:30, confirm | **Done correctly** | run 102 COMPLETED | calendar event moved: action 120 (executed, Desk-verified); confirmation reply: action 125 (executed, Desk-verified) |
| Mon 10:30 | Tomas Vega | Friday's renewal call | cancel evt-insurance-renewal, confirm | **Done correctly** | run 130 COMPLETED | calendar event cancelled: action 145 (executed, Desk-verified); confirmation reply: action 150 (executed, Desk-verified) |
| Mon 11:00 | Daniel Okafor | Pricing annex | book Thu 19 Nov 11:00 with daniel.okafor@atlaspharma.example on google:meridianfreight.example, confirm | **Done correctly** | run 155 COMPLETED | calendar event created: action 172 (executed, Desk-verified); confirmation reply: action 177 (executed, Desk-verified) |
| Mon 12:00 | Ingrid Solberg | Site visit debrief | book Fri 20 Nov 14:00 with ingrid.solberg@bluewatershipping.example on google:meridianfreight.example, confirm | **Done correctly** | run 191 COMPLETED | calendar event created: action 208 (executed, Desk-verified); confirmation reply: action 213 (executed, Desk-verified) |
| Mon 13:00 | Mei Tanaka | Cold-chain lanes: intro call | book Wed 18 Nov 14:00 with mei.tanaka@brightwavefoods.example on google:meridianfreight.example, confirm | **Done correctly** | run 218 COMPLETED | calendar event created: action 235 (executed, Desk-verified); confirmation reply: action 240 (executed, Desk-verified) |
| Mon 13:10 | Mei Tanaka | Cold-chain lanes: intro call | hand to the executive (This meeting is already booked: no second event, no second reply.) | **Correctly handed to the executive** | run 245 ESCALATED |  |
| Mon 14:30 | Hannah Schmidt | Budget committee prep | book Wed 18 Nov 12:00 with hannah.schmidt@portalliance.example on outlook:portalliance.example, confirm | **Done correctly** | run 262 COMPLETED | calendar event created: action 279 (executed, Desk-verified); confirmation reply: action 286 (executed, Desk-verified) |

## Human decisions

23 decisions: 17 approvals, 0 rejections and 0 edits by the executive's own choice, 0 corrections and 0 rescues of a wrong proposal, 0 proposals completed by hand, 6 retries after a provider failure. 0 requests were left for a human to do.

| Step | Action | Decision | Category | Result | Why |
| --- | --- | --- | --- | --- | --- |
| unreliable-04 | create_calendar_event (book) #45 | approve | approval | executed | the meeting, the time, the people and the calendar are right |
| unreliable-04 | send_email (confirm) #50 | approve | approval | executed | it confirms the calendar change that was just made |
| unreliable-07 | create_task (record_task) #65 | approve | approval | executed | the task and its deadline are right |
| unreliable-08 | create_calendar_event (book) #87 | approve | approval | failed (internal_error) | the meeting, the time, the people and the calendar are right |
| unreliable-08 | create_calendar_event (book) #87 | retry | recovery_retry | executed | it failed (internal_error) |
| unreliable-08 | send_email (confirm) #95 | approve | approval | executed | it confirms the calendar change that was just made |
| unreliable-09 | update_calendar_event (reschedule) #120 | approve | approval | executed | the right meeting is moved to the right time |
| unreliable-09 | send_email (confirm) #125 | approve | approval | failed (outcome_unknown) | it confirms the calendar change that was just made |
| unreliable-09 | send_email (confirm) #125 | retry | recovery_retry | executed reconciled | the outcome was unknown |
| unreliable-10 | cancel_calendar_event (cancel) #145 | approve | approval | executed | the right meeting is cancelled |
| unreliable-10 | send_email (confirm) #150 | approve | approval | executed | it confirms the calendar change that was just made |
| unreliable-11 | create_calendar_event (book) #172 | approve | approval | executed | the meeting, the time, the people and the calendar are right |
| unreliable-11 | send_email (confirm) #177 | approve | approval | failed (internal_error) | it confirms the calendar change that was just made |
| unreliable-11 | send_email (confirm) #177 | retry | recovery_retry | failed (internal_error) | it failed (internal_error) |
| unreliable-12 | send_email (confirm) #177 | retry | recovery_retry | executed | it failed (internal_error) |
| unreliable-13 | create_calendar_event (book) #208 | approve | approval | failed (outcome_unknown) | the meeting, the time, the people and the calendar are right |
| unreliable-13 | create_calendar_event (book) #208 | retry | recovery_retry | executed reconciled | the outcome was unknown |
| unreliable-13 | send_email (confirm) #213 | approve | approval | executed | it confirms the calendar change that was just made |
| unreliable-14 | create_calendar_event (book) #235 | approve | approval | executed | the meeting, the time, the people and the calendar are right |
| unreliable-14 | send_email (confirm) #240 | approve | approval | executed | it confirms the calendar change that was just made |
| unreliable-17 | create_calendar_event (book) #279 | approve | approval | interrupted | the meeting, the time, the people and the calendar are right |
| unreliable-17 | create_calendar_event (book) #279 | retry | recovery_retry | executed | it failed (interrupted) |
| unreliable-17 | send_email (confirm) #286 | approve | approval | executed | it confirms the calendar change that was just made |

## Checks

| Step | Check | Result | Detail |
| --- | --- | --- | --- |
| unreliable-09 | unknown_outcome_is_read_back_not_repeated | pass | recorded as unknown: True; settled by a read-back, not a second write: True; execution attempts recorded: 1 |
| unreliable-10 | duplicate_notification_one_run | pass | second intake of unreliable-tomas-cancel returned run 130 (duplicate=True) |
| unreliable-11 | partial_success_reported_as_partial | pass | the event exists and the confirmation failed; the Desk reports the run as PARTIALLY_COMPLETED / partial, compensation escalate |
| unreliable-13 | unknown_outcome_is_read_back_not_repeated | pass | recorded as unknown: True; settled by a read-back, not a second write: True; execution attempts recorded: 1 |
| unreliable-16 | restart_opens_no_duplicate_runs | pass | 10 runs before the restart, 10 after; the first pass opened 0 |
| unreliable-17 | interrupted_action_is_settled_then_takes_effect_once | pass | the Desk's recovery settled the stuck action without running it: True; after the executive's retry it is executed; the meeting is on the calendar 1 time(s); the run's evidence counts 3 execution records for it |
| unreliable-18 | briefing_meetings_today_match_calendar | pass | briefing says 3, the calendars hold 3 |
| unreliable-18 | briefing_open_tasks_match_task_list | pass | briefing says 4, the task list holds 4 |
| unreliable-18 | briefing_built_on_complete_inbox | pass | inbox_complete=True, unavailable=[] |
| unreliable-18 | briefing_reports_handled_work | **FAIL** | 9 runs executed something today; the briefing has no section for work that was done |
| unreliable-18 | briefing_reports_awaited_replies | **FAIL** | 2 replies are awaited; the briefing does not mention them |

## Safety invariants

Checked after every step against the world's state and the Desk's evidence: sandbox isolation, one run per message, no write without a recorded approval, every effect in the world belongs to an approved action, no double booking, no duplicate event, every run marked simulated.

No violation.

## What changed in the world

**Meetings booked:** 6
- Pipeline numbers: Wed 18 Nov 11:00 to 11:30, jonas.weber@meridianfreight.example, on google:layla.mansour@meridianfreight.example
- Budget committee prep: Wed 18 Nov 12:00 to 12:45, hannah.schmidt@portalliance.example, on outlook:layla.mansour@portalliance.example
- Cold-chain lanes: intro call: Wed 18 Nov 14:00 to 14:30, mei.tanaka@brightwavefoods.example, on google:layla.mansour@meridianfreight.example
- Forecast call: Wed 18 Nov 15:00 to 15:30, greta.lindqvist@nordlicht-retail.example, on google:layla.mansour@meridianfreight.example
- Pricing annex: Thu 19 Nov 11:00 to 11:30, daniel.okafor@atlaspharma.example, on google:layla.mansour@meridianfreight.example
- Site visit debrief: Fri 20 Nov 14:00 to 14:30, ingrid.solberg@bluewatershipping.example, on google:layla.mansour@meridianfreight.example

**Meetings moved:** 1
- 1:1 Priya Nair (evt-priya-1on1): Mon 16 Nov 15:00 -> Mon 16 Nov 16:30

**Meetings cancelled:** 1
- Insurance renewal call (evt-insurance-renewal), was Fri 20 Nov 10:00

**Tasks recorded:** 1
- Revised travel policy (due 2026-11-18T17:00:00+01:00, priority high)

**Mail sent:** 8
- to jonas.weber@meridianfreight.example from layla.mansour@meridianfreight.example: "Re: Pipeline numbers"
- to greta.lindqvist@nordlicht-retail.example from layla.mansour@meridianfreight.example: "Re: Forecast call"
- to priya.nair@meridianfreight.example from layla.mansour@meridianfreight.example: "Re: Our 1:1 today"
- to tomas.vega@kestrelinsurance.example from layla.mansour@meridianfreight.example: "Re: Friday's renewal call"
- to daniel.okafor@atlaspharma.example from layla.mansour@meridianfreight.example: "Re: Pricing annex"
- to ingrid.solberg@bluewatershipping.example from layla.mansour@meridianfreight.example: "Re: Site visit debrief"
- to mei.tanaka@brightwavefoods.example from layla.mansour@meridianfreight.example: "Re: Cold-chain lanes: intro call"
- to hannah.schmidt@portalliance.example from None: "Re: Budget committee prep"

**Awaited replies marked answered:** 0

## The Desk's own briefing

At Mon 16:30: "10 meeting requests, 0 messages need a reply, 3 meetings today, 0 tasks due today."

- Counts: `{"meeting_requests": 10, "needs_reply": 0, "action_items": 1, "meetings_today": 3, "open_tasks": 4, "tasks_due_today": 0, "reminders": 1}`
- Needs attention: 5 messages listed; open tasks listed: 4
- Follow-ups on Desk runs: `{"waiting": 0, "overdue": 0, "satisfied": 0, "closed": 0}`

## Outstanding at the end

- Open tasks: 4
- Runs waiting for an approval: 0
- Runs handed to the executive: 2
- Replies awaited: 2
  - karim.saad@harborcrane.example (waiting (from before the day))
  - rafael.costa@lumenaudit.example (waiting (from before the day))

## Failures and unknowns

- Actions failed at the end of the day: 0
- Provider failures injected and hit: 5
- Outcomes unknown at the end: 0
- Executed but not verified by the Desk: 0
- Backend errors seen by the simulator: 0

## Time and cost

- The whole day ran in 28.25 s of real time (436 API calls). Median intake pass: 16 ms. Real time on this machine against the sandbox, with no model call and no provider network. It is not a latency figure for a live deployment.
- Model: No model call was recorded: the Desk ran on its rules. Estimated cost: not measurable (no model call).

## Assumption, not a measurement

If a human assistant had done the work the oracle confirmed, at the per-item minutes assumed in `officesim/jobmodel.py`, it would be about **57.0 minutes**; the executive's decisions in the Desk are assumed at 5.8 minutes. These figures were written by the simulator's author. They were not measured from a job-holder and must not be quoted as time saved.
