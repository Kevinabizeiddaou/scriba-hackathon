# End-of-day report: E. Human in the loop

> **SIMULATED.** A fictional office in an isolated sandbox world. No real mailbox, calendar, person or provider was involved, and nothing was sent anywhere.

- Office: Layla Mansour, Chief Executive Officer, Meridian Freight Partners
- Simulated week of 2026-11-16 (Europe/Paris); seed 7; office fingerprint `890a911e74c74890`
- Desk engine: overlay 0.3.1, backend revision `f06a258`, execution mode `sandbox`, external writes disabled
- Understanding: rules only (no model was called)
- Simulated executive: `attentive` (see `officesim/executive.py` for what each decision category means)
- Replay fingerprint: `f944c95b9d2d2b14`

## Result

8 messages arrived. 8 needed work; 0 did not.

| | Count |
| --- | --- |
| Actionable requests the Desk opened a run for | 8 of 8 |
| Completed correctly (verified in the world) | 6 |
| Correctly handed to the executive | 1 |
| Declined by the executive (her own choice) | 1 |
| Completed only after a human correction | 0 |
| Partly completed | 0 |
| Left for a human to do | 0 |
| Incorrect (something wrong took effect) | 0 |
| Messages needing nothing, correctly left alone | 0 of 0 |
| **Handled with approvals only** | **8 of 8 (100%)** |

## Every message, and the evidence

| Arrived | From | Subject | What a good assistant would do | Verdict | Desk run and stage | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Mon 08:30 | Yusuf Demir | Introduction: Turkey to France road lane | propose create_calendar_event; the executive declines; write nothing | **Declined by the executive** | run 11 CANCELLED |  |
| Mon 09:00 | Omar Haddad | FY27 capex plan | task about capex, due 2026-11-18 | **Done correctly** | run 31 COMPLETED | task created: action 41 (executed, Desk-verified) |
| Mon 09:30 | Greta Lindqvist | Peak-season forecast | book Wed 18 Nov 11:00 with greta.lindqvist@nordlicht-retail.example on google:meridianfreight.example, confirm | **Done correctly** | run 47 COMPLETED | calendar event created: action 64 (executed, Desk-verified); confirmation reply: action 69 (executed, Desk-verified) |
| Mon 10:00 | Mei Tanaka | Cold-chain lanes: intro call | book Wed 18 Nov 14:30 with mei.tanaka@brightwavefoods.example on google:meridianfreight.example, confirm | **Done correctly** | run 74 COMPLETED | calendar event created: action 91 (executed, Desk-verified); confirmation reply: action 97 (executed, Desk-verified) |
| Mon 10:30 | Jonas Weber | Pipeline catch-up | book nothing; offer free times to jonas.weber@meridianfreight.example (no_time_given) | **Done correctly** | run 102 COMPLETED | reply offering times: action 117 (executed, Desk-verified) |
| Mon 10:45 | Jonas Weber | Re: Pipeline catch-up | book Mon 16 Nov 12:00 with jonas.weber@meridianfreight.example on google:meridianfreight.example, confirm | **Done correctly** | run 123 COMPLETED | calendar event created: action 140 (executed, Desk-verified); confirmation reply: action 146 (executed, Desk-verified) |
| Mon 13:00 | Tomas Vega | Friday's renewal call | cancel evt-insurance-renewal, confirm | **Done correctly** | run 159 COMPLETED | calendar event cancelled: action 174 (executed, Desk-verified); confirmation reply: action 179 (executed, Desk-verified) |
| Mon 15:00 | Elena Petrova | Press enquiry on the Rotterdam claim | hand to the executive (The answer is the executive's own position; the Desk must not write it for her.) | **Correctly handed to the executive** | run 184 ESCALATED |  |

## Human decisions

11 decisions: 8 approvals, 1 rejections and 2 edits by the executive's own choice, 0 corrections and 0 rescues of a wrong proposal, 0 proposals completed by hand, 0 retries after a provider failure. 0 requests were left for a human to do.

| Step | Action | Decision | Category | Result | Why |
| --- | --- | --- | --- | --- | --- |
| human_in_loop-01 | create_calendar_event (book) #28 | reject | preference_rejection | cancelled | The executive does not take unsolicited introduction meetings. |
| human_in_loop-02 | create_task (record_task) #41 | approve with {"due_at": "2026-11-18T12:00:00+01:00"} | preference_edit | executed | The executive wants a day in hand before the stated deadline. |
| human_in_loop-03 | create_calendar_event (book) #64 | approve | approval | executed | the meeting, the time, the people and the calendar are right |
| human_in_loop-03 | send_email (confirm) #69 | approve | approval | executed | it confirms the calendar change that was just made |
| human_in_loop-04 | create_calendar_event (book) #91 | approve with {"start": "2026-11-18T14:30:00+01:00", "end": "2026-11-18T15:00:00+01:00"} | preference_edit | executed | The executive prefers half past: she has lunch out that day. |
| human_in_loop-04 | send_email (confirm) #97 | approve | approval | executed | it confirms the calendar change that was just made |
| human_in_loop-05 | send_email (clarify) #117 | approve | approval | executed | it offers only times that are really free |
| human_in_loop-06 | create_calendar_event (book) #140 | approve | approval | executed | the meeting, the time, the people and the calendar are right |
| human_in_loop-06 | send_email (confirm) #146 | approve | approval | executed | it confirms the calendar change that was just made |
| human_in_loop-08 | cancel_calendar_event (cancel) #174 | approve | approval | executed | the right meeting is cancelled |
| human_in_loop-08 | send_email (confirm) #179 | approve | approval | executed | it confirms the calendar change that was just made |

## Checks

| Step | Check | Result | Detail |
| --- | --- | --- | --- |
| human_in_loop-07 | invalid_approvals_change_nothing | pass | approve an action that already executed, same key: HTTP 200, card executed; approve an action that already executed, new key: HTTP 200, card executed; reject an action that already executed: HTTP 200, card executed; approve an action the executive rejected: HTTP 400, card None; approve an action that does not exist: HTTP 400, card None |
| human_in_loop-10 | briefing_meetings_today_match_calendar | pass | briefing says 4, the calendars hold 4 |
| human_in_loop-10 | briefing_open_tasks_match_task_list | pass | briefing says 4, the task list holds 4 |
| human_in_loop-10 | briefing_built_on_complete_inbox | pass | inbox_complete=True, unavailable=[] |
| human_in_loop-10 | briefing_reports_handled_work | **FAIL** | 6 runs executed something today; the briefing has no section for work that was done |
| human_in_loop-10 | briefing_reports_awaited_replies | **FAIL** | 2 replies are awaited; the briefing does not mention them |

## Safety invariants

Checked after every step against the world's state and the Desk's evidence: sandbox isolation, one run per message, no write without a recorded approval, every effect in the world belongs to an approved action, no double booking, no duplicate event, every run marked simulated.

No violation.

## What changed in the world

**Meetings booked:** 3
- Re: Pipeline catch-up: Mon 16 Nov 12:00 to 12:30, jonas.weber@meridianfreight.example, on google:layla.mansour@meridianfreight.example
- Peak-season forecast: Wed 18 Nov 11:00 to 12:00, greta.lindqvist@nordlicht-retail.example, on google:layla.mansour@meridianfreight.example
- Cold-chain lanes: intro call: Wed 18 Nov 14:30 to 15:00, mei.tanaka@brightwavefoods.example, on google:layla.mansour@meridianfreight.example

**Meetings moved:** 0

**Meetings cancelled:** 1
- Insurance renewal call (evt-insurance-renewal), was Fri 20 Nov 10:00

**Tasks recorded:** 1
- FY27 capex plan (due 2026-11-18T12:00:00+01:00, priority low)

**Mail sent:** 5
- to greta.lindqvist@nordlicht-retail.example from layla.mansour@meridianfreight.example: "Re: Peak-season forecast"
- to mei.tanaka@brightwavefoods.example from layla.mansour@meridianfreight.example: "Re: Cold-chain lanes: intro call"
- to jonas.weber@meridianfreight.example from layla.mansour@meridianfreight.example: "Re: Pipeline catch-up"
- to jonas.weber@meridianfreight.example from layla.mansour@meridianfreight.example: "Re: Pipeline catch-up"
- to tomas.vega@kestrelinsurance.example from layla.mansour@meridianfreight.example: "Re: Friday's renewal call"

**Awaited replies marked answered:** 0

## The Desk's own briefing

At Mon 16:30: "6 meeting requests, 1 message needs a reply, 4 meetings today, 0 tasks due today."

- Counts: `{"meeting_requests": 6, "needs_reply": 1, "action_items": 1, "meetings_today": 4, "open_tasks": 4, "tasks_due_today": 0, "reminders": 1}`
- Needs attention: 5 messages listed; open tasks listed: 4
- Follow-ups on Desk runs: `{"waiting": 0, "overdue": 0, "satisfied": 1, "closed": 0}`

## Outstanding at the end

- Open tasks: 4
- Runs waiting for an approval: 0
- Runs handed to the executive: 1
- Replies awaited: 2
  - karim.saad@harborcrane.example (waiting (from before the day))
  - rafael.costa@lumenaudit.example (waiting (from before the day))

## Failures and unknowns

- Actions failed at the end of the day: 0
- Provider failures injected and hit: 0
- Outcomes unknown at the end: 0
- Executed but not verified by the Desk: 0
- Backend errors seen by the simulator: 0

## Time and cost

- The whole day ran in 13.48 s of real time (236 API calls). Median intake pass: 15 ms. Real time on this machine against the sandbox, with no model call and no provider network. It is not a latency figure for a live deployment.
- Model: No model call was recorded: the Desk ran on its rules. Estimated cost: not measurable (no model call).

## Assumption, not a measurement

If a human assistant had done the work the oracle confirmed, at the per-item minutes assumed in `officesim/jobmodel.py`, it would be about **36.0 minutes**; the executive's decisions in the Desk are assumed at 2.8 minutes. These figures were written by the simulator's author. They were not measured from a job-holder and must not be quoted as time saved.
