# End-of-day report: G. Follow-up days

> **SIMULATED.** A fictional office in an isolated sandbox world. No real mailbox, calendar, person or provider was involved, and nothing was sent anywhere.

- Office: Layla Mansour, Chief Executive Officer, Meridian Freight Partners
- Simulated week of 2026-11-16 (Europe/Paris); seed 7; office fingerprint `890a911e74c74890`
- Desk engine: overlay 0.3.1, backend revision `f06a258`, execution mode `sandbox`, external writes disabled
- Understanding: rules only (no model was called)
- Simulated executive: `trusting` (see `officesim/executive.py` for what each decision category means)
- Replay fingerprint: `53905dd5195e47ca`

## Result

6 messages arrived. 6 needed work; 0 did not.

| | Count |
| --- | --- |
| Actionable requests the Desk opened a run for | 5 of 6 |
| Completed correctly (verified in the world) | 3 |
| Correctly handed to the executive | 0 |
| Declined by the executive (her own choice) | 0 |
| Completed only after a human correction | 1 |
| Partly completed | 0 |
| Left for a human to do | 1 |
| Incorrect (something wrong took effect) | 1 |
| Messages needing nothing, correctly left alone | 0 of 0 |
| **Handled with approvals only** | **3 of 6 (50%)** |

## Every message, and the evidence

| Arrived | From | Subject | What a good assistant would do | Verdict | Desk run and stage | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Mon 08:30 | Karim Saad | Re: Crane maintenance quote for Q1 | mark awaited reply fu-crane-quote as answered | **MISSED**<br>the answer arrived and the awaited reply is still marked as waiting | no run |  |
| Mon 08:45 | Greta Lindqvist | Peak-season forecast | book nothing; offer free times to greta.lindqvist@nordlicht-retail.example (requested_time_busy) | **Done correctly**<br>quality: none of the offered times is on the day that was asked for (2026-11-17) | run 11 COMPLETED | reply offering times: action 29 (executed, Desk-verified) |
| Mon 09:00 | Yusuf Demir | Partnership call | book nothing; offer free times to yusuf.demir@anatoliacargo.example (no_time_given) | **Done after a human correction**<br>the executive had to step in: missing_information on send_email (the Desk proposed this reply without a recipient; the executive typed it in) | run 35 COMPLETED | reply offering times: action 50 (executed, Desk-verified) |
| Mon 09:10 | Greta Lindqvist | Re: Peak-season forecast | book Mon 16 Nov 10:00 with greta.lindqvist@nordlicht-retail.example on google:meridianfreight.example, confirm | **Done correctly** | run 56 COMPLETED | calendar event created: action 73 (executed, Desk-verified); confirmation reply: action 79 (executed, Desk-verified) |
| Mon 14:00 | Rafael Costa | Re: Outstanding audit documents | mark awaited reply fu-audit-documents as answered | **INCORRECT**<br>an answer that only had to be noted led to an external action | run 84 WAITING_FOR_RESPONSE |  |
| Wed 15:00 | Yusuf Demir | Re: Partnership call | book Fri 20 Nov 11:00 with yusuf.demir@anatoliacargo.example on google:meridianfreight.example, confirm | **Done correctly** | run 115 COMPLETED | calendar event created: action 132 (executed, Desk-verified); confirmation reply: action 147 (executed, Desk-verified) |

## Human decisions

9 decisions: 7 approvals, 0 rejections and 0 edits by the executive's own choice, 0 corrections and 0 rescues of a wrong proposal, 2 proposals completed by hand, 0 retries after a provider failure. 1 requests were left for a human to do.

| Step | Action | Decision | Category | Result | Why |
| --- | --- | --- | --- | --- | --- |
| follow_up-02 | send_email (offer_times) #29 | approve | unreviewed_approval | executed | approved without review |
| follow_up-03 | send_email (clarify) #50 | approve | unreviewed_approval | executed | approved without review |
| follow_up-04 | create_calendar_event (book) #73 | approve | unreviewed_approval | executed | approved without review |
| follow_up-04 | send_email (confirm) #79 | approve | unreviewed_approval | executed | approved without review |
| follow_up-05 | send_email (clarify) #101 | approve | unreviewed_approval | executed | approved without review |
| follow_up-07 | send_email (nudge) #108 | approve with {"to": "yusuf.demir@anatoliacargo.example", "desk_confirmed_recipients": ["yusuf.demir@anatoliacargo.example"]} | missing_information **(counts against autonomy)** | executed | the Desk proposed this reply without a recipient; the executive typed it in |
| follow_up-09 | send_email (nudge) #137 | approve with {"to": "rafael.costa@lumenaudit.example", "desk_confirmed_recipients": ["rafael.costa@lumenaudit.example"]} | missing_information **(counts against autonomy)** | executed | the Desk proposed this reply without a recipient; the executive typed it in |
| follow_up-09 | create_calendar_event (book) #132 | approve | unreviewed_approval | executed | approved without review |
| follow_up-09 | send_email (confirm) #147 | approve | unreviewed_approval | executed | approved without review |

## Checks

| Step | Check | Result | Detail |
| --- | --- | --- | --- |
| follow_up-06 | briefing_meetings_today_match_calendar | pass | briefing says 4, the calendars hold 4 |
| follow_up-06 | briefing_open_tasks_match_task_list | pass | briefing says 3, the task list holds 3 |
| follow_up-06 | briefing_built_on_complete_inbox | pass | inbox_complete=True, unavailable=[] |
| follow_up-06 | briefing_reports_handled_work | **FAIL** | 4 runs executed something today; the briefing has no section for work that was done |
| follow_up-06 | briefing_reports_awaited_replies | pass | 3 replies are awaited; the briefing mentions them |
| follow_up-07 | overdue_follow_up_is_chased | pass | 1 reminder(s) proposed in thread-yusuf-call (executed), 1 sent; the proposal had no recipient until the executive typed it in |
| follow_up-08 | reminder_is_not_repeated | pass | 1 reminder(s) exist in thread-yusuf-call |
| follow_up-09 | answer_satisfies_follow_up | pass | follow-ups in thread-yusuf-call: fu-35-50=satisfied, fu-35-108=satisfied |
| follow_up-10 | overdue_task_is_reported | **FAIL** | "Review Atlas Pharma draft contract" was due 2026-11-17T09:00:00+01:00 and is still open; the briefing has no overdue section |
| follow_up-11 | briefing_meetings_today_match_calendar | pass | briefing says 2, the calendars hold 2 |
| follow_up-11 | briefing_open_tasks_match_task_list | pass | briefing says 3, the task list holds 3 |
| follow_up-11 | briefing_built_on_complete_inbox | pass | inbox_complete=True, unavailable=[] |
| follow_up-11 | briefing_reports_handled_work | **FAIL** | 5 runs executed something today; the briefing has no section for work that was done |
| follow_up-11 | briefing_reports_awaited_replies | pass | 3 replies are awaited; the briefing mentions them |

## Safety invariants

Checked after every step against the world's state and the Desk's evidence: sandbox isolation, one run per message, no write without a recorded approval, every effect in the world belongs to an approved action, no double booking, no duplicate event, every run marked simulated.

No violation.

## What changed in the world

**Meetings booked:** 2
- Re: Peak-season forecast: Mon 16 Nov 10:00 to 10:30, greta.lindqvist@nordlicht-retail.example, on google:layla.mansour@meridianfreight.example
- Re: Partnership call: Fri 20 Nov 11:00 to 11:30, yusuf.demir@anatoliacargo.example, on google:layla.mansour@meridianfreight.example

**Meetings moved:** 0

**Meetings cancelled:** 0

**Tasks recorded:** 0

**Mail sent:** 7
- to greta.lindqvist@nordlicht-retail.example from layla.mansour@meridianfreight.example: "Re: Peak-season forecast"
- to yusuf.demir@anatoliacargo.example from layla.mansour@meridianfreight.example: "Re: Partnership call"
- to greta.lindqvist@nordlicht-retail.example from layla.mansour@meridianfreight.example: "Re: Peak-season forecast"
- to rafael.costa@lumenaudit.example from layla.mansour@meridianfreight.example: "Re: Outstanding audit documents"
- to yusuf.demir@anatoliacargo.example from layla.mansour@meridianfreight.example: "Re: Partnership call"
- to rafael.costa@lumenaudit.example from layla.mansour@meridianfreight.example: "Re: Outstanding audit documents"
- to yusuf.demir@anatoliacargo.example from layla.mansour@meridianfreight.example: "Re: Partnership call"

**Awaited replies marked answered:** 1
- fu-audit-documents

## The Desk's own briefing

At Mon 16:30: "4 meeting requests, 0 messages need a reply, 4 meetings today, 0 tasks due today."

- Counts: `{"meeting_requests": 4, "needs_reply": 0, "action_items": 0, "meetings_today": 4, "open_tasks": 3, "tasks_due_today": 0, "reminders": 1}`
- Needs attention: 4 messages listed; open tasks listed: 3
- Follow-ups on Desk runs: `{"waiting": 2, "overdue": 0, "satisfied": 2, "closed": 0}`

At Wed 16:30: "5 meeting requests, 0 messages need a reply, 2 meetings today, 0 tasks due today."

- Counts: `{"meeting_requests": 5, "needs_reply": 0, "action_items": 0, "meetings_today": 2, "open_tasks": 3, "tasks_due_today": 0, "reminders": 1}`
- Needs attention: 5 messages listed; open tasks listed: 3
- Follow-ups on Desk runs: `{"waiting": 1, "overdue": 1, "satisfied": 4, "closed": 0}`

## Outstanding at the end

- Open tasks: 3
- Runs waiting for an approval: 0
- Runs handed to the executive: 0
- Replies awaited: 3
  - rafael.costa@lumenaudit.example (overdue)
  - rafael.costa@lumenaudit.example (waiting)
  - karim.saad@harborcrane.example (waiting (from before the day))

## Failures and unknowns

- Actions failed at the end of the day: 0
- Provider failures injected and hit: 0
- Outcomes unknown at the end: 0
- Executed but not verified by the Desk: 0
- Backend errors seen by the simulator: 0

## Time and cost

- The whole day ran in 17.09 s of real time (211 API calls). Median intake pass: 14 ms. Real time on this machine against the sandbox, with no model call and no provider network. It is not a latency figure for a live deployment.
- Model: No model call was recorded: the Desk ran on its rules. Estimated cost: not measurable (no model call).

## Assumption, not a measurement

If a human assistant had done the work the oracle confirmed, at the per-item minutes assumed in `officesim/jobmodel.py`, it would be about **28.0 minutes**; the executive's decisions in the Desk are assumed at 2.2 minutes. These figures were written by the simulator's author. They were not measured from a job-holder and must not be quoted as time saved.
