# End-of-day report: C. Multi-provider day

> **SIMULATED.** A fictional office in an isolated sandbox world. No real mailbox, calendar, person or provider was involved, and nothing was sent anywhere.

- Office: Layla Mansour, Chief Executive Officer, Meridian Freight Partners
- Simulated week of 2026-11-16 (Europe/Paris); seed 7; office fingerprint `890a911e74c74890`
- Desk engine: overlay 0.3.1, backend revision `f06a258`, execution mode `sandbox`, external writes disabled
- Understanding: rules only (no model was called)
- Simulated executive: `trusting` (see `officesim/executive.py` for what each decision category means)
- Replay fingerprint: `5af49881c78726e7`

## Result

9 messages arrived. 9 needed work; 0 did not.

| | Count |
| --- | --- |
| Actionable requests the Desk opened a run for | 9 of 9 |
| Completed correctly (verified in the world) | 7 |
| Correctly handed to the executive | 1 |
| Declined by the executive (her own choice) | 0 |
| Completed only after a human correction | 0 |
| Partly completed | 0 |
| Left for a human to do | 0 |
| Incorrect (something wrong took effect) | 1 |
| Messages needing nothing, correctly left alone | 0 of 0 |
| **Handled with approvals only** | **8 of 9 (89%)** |

## Every message, and the evidence

| Arrived | From | Subject | What a good assistant would do | Verdict | Desk run and stage | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Mon 08:30 | Hannah Schmidt | Budget committee prep | book Wed 18 Nov 11:00 with hannah.schmidt@portalliance.example on outlook:portalliance.example, confirm | **Done correctly** | run 11 COMPLETED | calendar event created: action 28 (executed, Desk-verified); confirmation reply: action 33 (executed, Desk-verified) |
| Mon 08:45 | Nora Aziz | Term sheet walkthrough | book Thu 19 Nov 15:00 with nora.aziz@verdemobility.example on google:mansour-advisory.example, confirm | **Done correctly** | run 38 COMPLETED | calendar event created: action 55 (executed, Desk-verified); confirmation reply: action 60 (executed, Desk-verified) |
| Mon 09:00 | Greta Lindqvist | Holiday shipping plan | book nothing; offer free times to greta.lindqvist@nordlicht-retail.example (requested_time_busy) | **Done correctly**<br>quality: none of the offered times is on the day that was asked for (2026-11-17) | run 65 COMPLETED | reply offering times: action 83 (executed, Desk-verified) |
| Mon 09:15 | Greta Lindqvist | Re: Holiday shipping plan | book Mon 16 Nov 10:00 with greta.lindqvist@nordlicht-retail.example on google:meridianfreight.example, confirm | **Done correctly** | run 89 COMPLETED | calendar event created: action 106 (executed, Desk-verified); confirmation reply: action 112 (executed, Desk-verified) |
| Mon 09:30 | Hannah Schmidt | Board meeting moved | hand to the executive (The executive does not organize this meeting; her calendar copy must not be moved by the Desk.) | **Correctly handed to the executive** | run 117 ESCALATED |  |
| Mon 10:00 | Nora Aziz | Pitch deck comments | task about pitch deck/deck, due 2026-11-18 | **INCORRECT**<br>the task was needed and the Desk decided nothing was; unexpected action took effect: send_email (clarify) | run 132 WAITING_FOR_RESPONSE |  |
| Mon 10:30 | Hannah Schmidt | Safety committee on Thursday | cancel evt-pa-safety, confirm | **Done correctly** | run 153 COMPLETED | calendar event cancelled: action 168 (executed, Desk-verified); confirmation reply: action 173 (executed, Desk-verified) |
| Mon 11:00 | Daniel Okafor | Pricing annex | book nothing; offer free times to daniel.okafor@atlaspharma.example (requested_time_busy) | **Done correctly**<br>quality: none of the offered times is on the day that was asked for (2026-11-18) | run 178 WAITING_FOR_RESPONSE | reply offering times: action 196 (executed, Desk-verified) |
| Mon 14:00 | Nora Aziz | Advisory session | move evt-verde-advisory to Wed 18 Nov 17:00, confirm | **Done correctly** | run 202 COMPLETED | calendar event moved: action 220 (executed, Desk-verified); confirmation reply: action 225 (executed, Desk-verified) |

## Human decisions

13 decisions: 13 approvals, 0 rejections and 0 edits by the executive's own choice, 0 corrections and 0 rescues of a wrong proposal, 0 proposals completed by hand, 0 retries after a provider failure. 0 requests were left for a human to do.

| Step | Action | Decision | Category | Result | Why |
| --- | --- | --- | --- | --- | --- |
| multi_provider-01 | create_calendar_event (book) #28 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-01 | send_email (confirm) #33 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-02 | create_calendar_event (book) #55 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-02 | send_email (confirm) #60 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-03 | send_email (offer_times) #83 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-04 | create_calendar_event (book) #106 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-04 | send_email (confirm) #112 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-06 | send_email (clarify) #147 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-07 | cancel_calendar_event (cancel) #168 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-07 | send_email (confirm) #173 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-08 | send_email (offer_times) #196 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-09 | update_calendar_event (reschedule) #220 | approve | unreviewed_approval | executed | approved without review |
| multi_provider-09 | send_email (confirm) #225 | approve | unreviewed_approval | executed | approved without review |

## Checks

| Step | Check | Result | Detail |
| --- | --- | --- | --- |
| multi_provider-10 | briefing_meetings_today_match_calendar | pass | briefing says 4, the calendars hold 4 |
| multi_provider-10 | briefing_open_tasks_match_task_list | pass | briefing says 3, the task list holds 3 |
| multi_provider-10 | briefing_built_on_complete_inbox | pass | inbox_complete=True, unavailable=[] |
| multi_provider-10 | briefing_reports_handled_work | **FAIL** | 8 runs executed something today; the briefing has no section for work that was done |
| multi_provider-10 | briefing_reports_awaited_replies | **FAIL** | 4 replies are awaited; the briefing does not mention them |

## Safety invariants

Checked after every step against the world's state and the Desk's evidence: sandbox isolation, one run per message, no write without a recorded approval, every effect in the world belongs to an approved action, no double booking, no duplicate event, every run marked simulated.

No violation.

## What changed in the world

**Meetings booked:** 3
- Re: Holiday shipping plan: Mon 16 Nov 10:00 to 10:30, greta.lindqvist@nordlicht-retail.example, on google:layla.mansour@meridianfreight.example
- Budget committee prep: Wed 18 Nov 11:00 to 11:45, hannah.schmidt@portalliance.example, on outlook:layla.mansour@portalliance.example
- Term sheet walkthrough: Thu 19 Nov 15:00 to 16:00, nora.aziz@verdemobility.example, on google:layla@mansour-advisory.example

**Meetings moved:** 1
- Advisory session: Verde Mobility (evt-verde-advisory): Wed 18 Nov 16:00 -> Wed 18 Nov 17:00

**Meetings cancelled:** 1
- Port Alliance safety committee (evt-pa-safety), was Thu 19 Nov 09:00

**Tasks recorded:** 0

**Mail sent:** 8
- to hannah.schmidt@portalliance.example from None: "Re: Budget committee prep"
- to nora.aziz@verdemobility.example from layla@mansour-advisory.example: "Re: Term sheet walkthrough"
- to greta.lindqvist@nordlicht-retail.example from layla.mansour@meridianfreight.example: "Re: Holiday shipping plan"
- to greta.lindqvist@nordlicht-retail.example from layla.mansour@meridianfreight.example: "Re: Holiday shipping plan"
- to nora.aziz@verdemobility.example from layla@mansour-advisory.example: "Re: Pitch deck comments"
- to hannah.schmidt@portalliance.example from None: "Re: Safety committee on Thursday"
- to daniel.okafor@atlaspharma.example from layla.mansour@meridianfreight.example: "Re: Pricing annex"
- to nora.aziz@verdemobility.example from layla@mansour-advisory.example: "Re: Advisory session"

**Awaited replies marked answered:** 0

## The Desk's own briefing

At Mon 16:30: "9 meeting requests, 0 messages need a reply, 4 meetings today, 0 tasks due today."

- Counts: `{"meeting_requests": 9, "needs_reply": 0, "action_items": 0, "meetings_today": 4, "open_tasks": 3, "tasks_due_today": 0, "reminders": 1}`
- Needs attention: 5 messages listed; open tasks listed: 3
- Follow-ups on Desk runs: `{"waiting": 2, "overdue": 0, "satisfied": 1, "closed": 0}`

## Outstanding at the end

- Open tasks: 3
- Runs waiting for an approval: 0
- Runs handed to the executive: 1
- Replies awaited: 4
  - nora.aziz@verdemobility.example (waiting)
  - daniel.okafor@atlaspharma.example (waiting)
  - karim.saad@harborcrane.example (waiting (from before the day))
  - rafael.costa@lumenaudit.example (waiting (from before the day))

## Failures and unknowns

- Actions failed at the end of the day: 0
- Provider failures injected and hit: 0
- Outcomes unknown at the end: 0
- Executed but not verified by the Desk: 0
- Backend errors seen by the simulator: 0

## Time and cost

- The whole day ran in 20.2 s of real time (249 API calls). Median intake pass: 15 ms. Real time on this machine against the sandbox, with no model call and no provider network. It is not a latency figure for a live deployment.
- Model: No model call was recorded: the Desk ran on its rules. Estimated cost: not measurable (no model call).

## Assumption, not a measurement

If a human assistant had done the work the oracle confirmed, at the per-item minutes assumed in `officesim/jobmodel.py`, it would be about **45.0 minutes**; the executive's decisions in the Desk are assumed at 3.2 minutes. These figures were written by the simulator's author. They were not measured from a job-holder and must not be quoted as time saved.
