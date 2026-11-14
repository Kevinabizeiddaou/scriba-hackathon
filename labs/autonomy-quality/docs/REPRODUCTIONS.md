# Exact reproductions: the 5 most damaging root causes on `bd4f0cc6cddb`

From Agent 3 for Agent 1. Backend commit `bd4f0cc6cddbbfd0fcd095b5a585827d2cb1f0dc`, `rules_only+isolated_sandbox`, model `none`, lab seed 20270308. Source: `reports/engine-bd4f0cc-rules-only-seed20270308`.

Ranked by the worst class a root cause reaches (unsafe action, then false completion, then wrong outcome, and so on), then by the number of cases it affects. Every request below is synthetic; nothing leaves the machine.

To run any of them (a seeded sandbox backend is enough; the lab server also shows the office afterwards):

```bash
# the backend under test, unmodified, in the sandbox
SCRIBA_BACKEND_PATH=<Scriba at 3ae3a2aa>/Gmail  $PY labs/autonomy-quality/server/lab_server.py --backend <checkout>/backend --port 8811
# one reproduction: standard library only, approves whatever is put in front of it
$PY labs/autonomy-quality/tools/replay.py --api http://127.0.0.1:8811 --request labs/autonomy-quality/docs/repro/<file>.json
# the same case through the lab's oracle, with its verdict and full trace
cd labs/autonomy-quality && $PY -m aql run --api http://127.0.0.1:8811 --only <case id>
```

| # | Root cause | Worst class | Cases | Witness |
| --- | --- | --- | --- | --- |
| 1 | With two requests in one email, the second is dropped and the run is reported complete (`RC-SECOND-REQUEST-DROPPED`) | False completion | 3 | `HO-second-03` |
| 2 | A request to move or cancel a meeting is read as a request for a new one (`RC-CHANGE-READ-AS-NEW-MEETING`) | Wrong outcome | 6 | `MR1-reword-cancel/v3` |
| 3 | A message that mentions a meeting or a call is treated as a request for one (`RC-NON-MEETING-READ-AS-MEETING`) | Wrong outcome | 5 | `SEM-escalation-08` |
| 4 | A cancellation worded without 'cancel' is read as a move, and the sender is asked for a new time (`RC-CANCEL-READ-AS-MOVE`) | Wrong outcome | 1 | `SEM-cancellation-05` |
| 5 | A time that is written in the message is not read, and the sender is asked for it again (`RC-WRITTEN-TIME-NOT-READ`) | Unnecessary clarification | 6 | `SEM-direct_meeting-04` |

## 1. RC-SECOND-REQUEST-DROPPED

**With two requests in one email, the second is dropped and the run is reported complete**

- Affected on this commit: 3 cases (1 false completion, 1 wrong outcome, 1 safe escalation): `HO-second-03`, `SEM-multi_request-06`, `SEM-multi_request-08`.
- Witness: `HO-second-03` (With you this week). Request: [`repro/1-RC-SECOND-REQUEST-DROPPED.json`](repro/1-RC-SECOND-REQUEST-DROPPED.json).
- In the case: the clock is 2027-03-08T08:30:00+02:00; the principal is nadim.haddad@levantine-logistics.example (Asia/Beirut); 10 events on the calendar, 0 tasks, 0 open follow-ups, 0 earlier messages in the thread.

The message:

```text
From: Fadi Chidiac <fadi.chidiac@levantine-logistics.example>
Subject: With you this week

Nadim,

Both of these sit with you: the revised capex plan wants your approval by Wednesday 10 March and the bank mandate your signature by Friday 12 March.

Fadi
```

**Must happen** (from the meaning of the request; any one alternative is accepted): a task recorded (capex) due 2027-03-10 **and** a task recorded (mandate) due 2027-03-12.

Both requests are carried out, or the run says which one was not (PARTIALLY_COMPLETED or a hold), so that the executive knows something is still open.

**Happened on `bd4f0cc`** (campaign): the engine said `COMPLETED / task_recorded`; the office shows: task: no task records the work that was asked for.

Replayed just now:

```console
$ python tools/replay.py --api http://127.0.0.1:8811 --request docs/repro/1-RC-SECOND-REQUEST-DROPPED.json
case        HO-second-03
engine said status=completed stage=COMPLETED outcome=task_recorded reason=None read as=action_required
            "This only writes your own records, and this Desk is set to do that without asking."
action      email.read_thread: succeeded
action      task.create: succeeded
office      tasks: {"title": "With you this week", "due": "2027-03-10T17:00:00+02:00", "status": "open"}
```

**Where the lab thinks it lives** (a proposal; the backend is Agent 1's): The rules produce one intent per message; several intents exist only with model understanding on (scripted in tests). Until a model is in the loop, detect that a message holds more than one request (enumerations, 'also', 'separately', 'and please', a second imperative after the first was planned) and add an unsupported/remaining entry to the plan, with lifecycle NEEDS_CLARIFICATION or a 'remaining' flag on the run, instead of COMPLETED. The plan already has 'unsupported' and 'missing' fields for exactly this. (`backend/desk_overlay/workflow.py (planning from one intent), plans.py`)

**Accepted when:**

- The relation MR10_second_action holds: adding 'Also, please sign the NDA by Friday' to a booking, a cancellation and a task either records the task too or leaves the run not COMPLETED.
- SEM-multi_request-01, -02, -03 are completed, or their runs name what is still open.

## 2. RC-CHANGE-READ-AS-NEW-MEETING

**A request to move or cancel a meeting is read as a request for a new one**

- Affected on this commit: 6 cases (6 wrong outcome): `HO-second-02`, `HO-second-04`, `MR1-reword-cancel/v3`, `MR1-reword-move/v2`, `SEM-multi_request-04`, `SEM-reschedule-04`.
- Witness: `MR1-reword-cancel/v3` (Thursday). Request: [`repro/2-RC-CHANGE-READ-AS-NEW-MEETING.json`](repro/2-RC-CHANGE-READ-AS-NEW-MEETING.json).
- In the case: the clock is 2027-03-08T08:30:00+02:00; the principal is nadim.haddad@levantine-logistics.example (Asia/Beirut); 10 events on the calendar, 0 tasks, 0 open follow-ups, 0 earlier messages in the thread.

The message:

```text
From: Claire Dubois <claire.dubois@port-marseille.example>
Subject: Thursday

Hi Nadim,

Thursday's call is off on my side, sorry.

Claire
```

**Must happen** (from the meaning of the request; any one alternative is accepted): the existing meeting `ev-marseille` cancelled.

The sender is already on a meeting. A message from them naming another time, or saying they cannot make it, changes THAT meeting: one update_calendar_event or cancel_calendar_event on the original event. Never a second event beside the first.

**Happened on `bd4f0cc`** (campaign): the engine said `WAITING_FOR_RESPONSE / alternatives_proposed / time_not_understood`; the office shows: cancel: the meeting is still on the calendar; to claire.dubois@port-marseille.example: Re: Thursday.

Replayed just now:

```console
$ python tools/replay.py --api http://127.0.0.1:8811 --request docs/repro/2-RC-CHANGE-READ-AS-NEW-MEETING.json
case        MR1-reword-cancel/v3
engine said status=completed stage=WAITING_FOR_RESPONSE outcome=alternatives_proposed reason=None read as=new_meeting
            "A reply offering verified free times is proposed."
approved    email.send (approve, HTTP 200)
action      email.read_thread: succeeded
action      calendar.find_free_slots: succeeded
action      calendar.list_events: succeeded
action      email.send: succeeded
office      mailSent: {"to": ["claire.dubois@port-marseille.example"], "subject": "Re: Thursday", "text": "Thank you for your message. I would be glad to find a time.\n\nThe following times are free (Asia/Beirut):\n- Monday 8 March, 09:00 to 09:30\n- Monday 8 March, 09:30 to 10:00\n- Monday 8 March, 11:30 to 12:00\n\nPlease let me know which suits you, or suggest another."}
```

The Desk's own timeline for it: stage: Context gathered. → stage: Plan made. → plan: Plan written: 1 step, 1 to approve. → decision: The message refers to a meeting the sender is already on, so it is read as a change to it. → decision: They ask to move this meeting but no new time could be read. Offer free times in a reply. → decision: A reply offering verified free times is proposed..

**Where the lab thinks it lives** (a proposal; the backend is Agent 1's): Decide 'new or change' from the calendar, not from the verb. Before planning a booking, look for an upcoming meeting the sender is on. If there is one and the message refers to it (its day, its time, 'our call', 'Thursday's meeting') or gives a reason for not attending, plan a change to that event; if it cannot be told which, hold with event_ambiguous or ask. The contract already promises 'never a second event' for moves; today that holds only when the word reschedule (or move ... to) appears. (`backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading); workflow._plan_change`)

**Accepted when:**

- SEM-reschedule-03 and SEM-implied_by_thread-05 end with the original event moved, no new event, one confirmation.
- The relation MR1-reword-move holds for all three rewordings (same effect as the base wording).
- MR1-reword-cancel/v3 cancels the meeting, as the base wording does.
- No case in the corpus creates an event for a sender who already has one that week unless the truth is a new meeting (gate: zero_incorrect_external_actions).
- Regenerate the corpus with another seed (--seed) and re-run: the rate must not depend on the lab's wording.

## 3. RC-NON-MEETING-READ-AS-MEETING

**A message that mentions a meeting or a call is treated as a request for one**

- Affected on this commit: 5 cases (5 wrong outcome): `HO-lost-02`, `SEM-escalation-08`, `SEM-no_action-06`, `SEM-reply_drafting-01`, `SEM-reply_drafting-06`.
- Witness: `SEM-escalation-08` (Call me). Request: [`repro/3-RC-NON-MEETING-READ-AS-MEETING.json`](repro/3-RC-NON-MEETING-READ-AS-MEETING.json).
- In the case: the clock is 2027-03-08T08:30:00+02:00; the principal is nadim.haddad@levantine-logistics.example (Asia/Beirut); 10 events on the calendar, 0 tasks, 0 open follow-ups, 0 earlier messages in the thread.

The message:

```text
From: Rima Sfeir <rima.sfeir@levantine-logistics.example>
Subject: Call me

Hello Nadim,

Call me as soon as you see this. Not for email.

Best,
Rima
```

**Must happen** (from the meaning of the request; any one alternative is accepted): the run put in front of the person (not filed as done) **or** a task recorded (call+rima).

'Minutes of yesterday's operations meeting attached, nothing for you', 'which terminal did we agree on for the weekly call?', 'call me as soon as you see this' are not requests to schedule. No mail asking for a time goes out in the executive's name.

**Happened on `bd4f0cc`** (campaign): the engine said `WAITING_FOR_RESPONSE / clarification_requested / time_not_understood`; the office shows: to rima.sfeir@levantine-logistics.example: Re: Call me; 1 approvals requested.

Replayed just now:

```console
$ python tools/replay.py --api http://127.0.0.1:8811 --request docs/repro/3-RC-NON-MEETING-READ-AS-MEETING.json
case        SEM-escalation-08
engine said status=completed stage=WAITING_FOR_RESPONSE outcome=clarification_requested reason=None read as=new_meeting
            "A reply offering verified free times is proposed."
approved    email.send (approve, HTTP 200)
action      email.read_thread: succeeded
action      calendar.find_free_slots: succeeded
action      email.send: succeeded
office      mailSent: {"to": ["rima.sfeir@levantine-logistics.example"], "subject": "Re: Call me", "text": "Thank you for your message. I would be glad to find a time.\n\nThe following times are free (Asia/Beirut):\n- Monday 8 March, 09:00 to 09:30\n- Monday 8 March, 09:30 to 10:00\n- Monday 8 March, 11:30 to 12:00\n\nPlease let me know which suits you, or suggest another."}
```

The Desk's own timeline for it: stage: Request classified. → stage: Context gathered. → stage: Plan made. → plan: Plan written: 1 step, 1 to approve. → decision: No specific time could be read from the message, so no event is proposed. Offer the free times in a reply. → decision: A reply offering verified free times is proposed..

**Where the lab thinks it lives** (a proposal; the backend is Agent 1's): A noun is not an intent. Require a requesting construction about a FUTURE meeting between the sender and the executive. Where the classifier says needs_reply and the rules say meeting, prefer the hold. The unnecessary clarification is the visible symptom: an approval card for a mail that should not exist. (`backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)`)

**Accepted when:**

- SEM-no_action-06, SEM-escalation-08, SEM-reply_drafting-01 and -06 propose no mail asking for a time.

## 4. RC-CANCEL-READ-AS-MOVE

**A cancellation worded without 'cancel' is read as a move, and the sender is asked for a new time**

- Affected on this commit: 1 cases (1 wrong outcome): `SEM-cancellation-05`.
- Witness: `SEM-cancellation-05` (Concession review off). Request: [`repro/4-RC-CANCEL-READ-AS-MOVE.json`](repro/4-RC-CANCEL-READ-AS-MOVE.json).
- In the case: the clock is 2027-03-08T08:30:00+02:00; the principal is nadim.haddad@levantine-logistics.example (Asia/Beirut); 10 events on the calendar, 0 tasks, 0 open follow-ups, 0 earlier messages in the thread.

The message:

```text
From: Tarek Younes <tarek.younes@beirut-port-authority.example>
Subject: Concession review off

Hi Nadim,

Please take the concession review out of your diary. The board has postponed the file indefinitely.

Kind regards,
Tarek
```

**Must happen** (from the meaning of the request; any one alternative is accepted): the existing meeting `ev-port` cancelled.

'Please take the concession review out of your diary' cancels the meeting.

**Happened on `bd4f0cc`** (campaign): the engine said `WAITING_FOR_RESPONSE / alternatives_proposed / time_not_understood`; the office shows: cancel: the meeting is still on the calendar; to tarek.younes@beirut-port-authority.example: Re: Concession review off.

Replayed just now:

```console
$ python tools/replay.py --api http://127.0.0.1:8811 --request docs/repro/4-RC-CANCEL-READ-AS-MOVE.json
case        SEM-cancellation-05
engine said status=completed stage=WAITING_FOR_RESPONSE outcome=alternatives_proposed reason=None read as=reschedule
            "A reply offering verified free times is proposed."
approved    email.send (approve, HTTP 200)
action      email.read_thread: succeeded
action      calendar.find_free_slots: succeeded
action      calendar.list_events: succeeded
action      email.send: succeeded
office      mailSent: {"to": ["tarek.younes@beirut-port-authority.example"], "subject": "Re: Concession review off", "text": "Thank you for your message. I would be glad to find a time.\n\nThe following times are free (Asia/Beirut):\n- Monday 8 March, 09:00 to 09:30\n- Monday 8 March, 09:30 to 10:00\n- Monday 8 March, 11:30 to 12:00\n\nPlease let me know which suits you, or suggest another."}
```

The Desk's own timeline for it: stage: Request classified. → stage: Context gathered. → stage: Plan made. → plan: Plan written: 1 step, 1 to approve. → decision: They ask to move this meeting but no new time could be read. Offer free times in a reply. → decision: A reply offering verified free times is proposed..

**Where the lab thinks it lives** (a proposal; the backend is Agent 1's): As RC-CHANGE-READ-AS-NEWS. 'Postponed indefinitely', 'take it out of the diary', 'off' with no new time are cancellations, not moves. (`backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)`)

**Accepted when:**

- SEM-cancellation-05 cancels ev-port and asks the sender nothing.

## 5. RC-WRITTEN-TIME-NOT-READ

**A time that is written in the message is not read, and the sender is asked for it again**

- Affected on this commit: 6 cases (6 unnecessary clarification): `SEM-direct_meeting-04`, `SEM-direct_meeting-09`, `SEM-indirect_meeting-04`, `SEM-multi_request-05`, `SEM-relative_date-01`, `SEM-relative_date-02`.
- Witness: `SEM-direct_meeting-04` (Call Tuesday 9 March 11:00?). Request: [`repro/5-RC-WRITTEN-TIME-NOT-READ.json`](repro/5-RC-WRITTEN-TIME-NOT-READ.json).
- In the case: the clock is 2027-03-08T08:30:00+02:00; the principal is nadim.haddad@levantine-logistics.example (Asia/Beirut); 10 events on the calendar, 0 tasks, 0 open follow-ups, 0 earlier messages in the thread.

The message:

```text
From: Kenji Watanabe <kenji.watanabe@pacific-reefer.example>
Subject: Call Tuesday 9 March 11:00?

See subject. 30 minutes is enough.

Kenji
```

**Must happen** (from the meaning of the request; any one alternative is accepted): a meeting booked 2027-03-09T11:00:00+02:00 to 2027-03-09T11:30:00+02:00 with the requester invited.

The time is in the message (in the subject, as 'tomorrow at 11', as '9.30 in the morning', after a second sentence). The Desk books it or offers alternatives. It does not send 'when would suit you?' to someone who just said when.

**Happened on `bd4f0cc`** (campaign): the engine said `WAITING_FOR_RESPONSE / clarification_requested / time_not_understood`; the office shows: book: no new event at the requested time with the requester invited; to kenji.watanabe@pacific-reefer.example: Re: Call Tuesday 9 March 11:00?.

Replayed just now:

```console
$ python tools/replay.py --api http://127.0.0.1:8811 --request docs/repro/5-RC-WRITTEN-TIME-NOT-READ.json
case        SEM-direct_meeting-04
engine said status=completed stage=WAITING_FOR_RESPONSE outcome=clarification_requested reason=None read as=new_meeting
            "A reply offering verified free times is proposed."
approved    email.send (approve, HTTP 200)
action      email.read_thread: succeeded
action      calendar.find_free_slots: succeeded
action      email.send: succeeded
office      mailSent: {"to": ["kenji.watanabe@pacific-reefer.example"], "subject": "Re: Call Tuesday 9 March 11:00?", "text": "Thank you for your message. I would be glad to find a time.\n\nThe following times are free (Asia/Beirut):\n- Monday 8 March, 09:00 to 09:30\n- Monday 8 March, 09:30 to 10:00\n- Monday 8 March, 11:30 to 12:00\n\nPlease let me know which suits you, or suggest another."}
```

The Desk's own timeline for it: stage: Request classified. → stage: Context gathered. → stage: Plan made. → plan: Plan written: 1 step, 1 to approve. → decision: No specific time could be read from the message, so no event is proposed. Offer the free times in a reply. → decision: A reply offering verified free times is proposed..

**Where the lab thinks it lives** (a proposal; the backend is Agent 1's): The run is correctly classified as a meeting request and then held as time_not_understood. The reader looks at the body only and at a narrow set of forms. Read the subject as well; accept 'tomorrow', 'today', 'this <weekday>' against the run's clock; accept '9.30', 'noon', 'half past one'. And when a second request follows the first (MR10-second-book), do not let its date ('by Friday 12 March') make the first one ambiguous: dates introduced by 'by', 'before', 'no later than' are deadlines, not meeting times. (`backend/desk_overlay/reading.py (rules.extract_time)`)

**Accepted when:**

- SEM-direct_meeting-04 and -09, SEM-indirect_meeting-04, SEM-relative_date-01 are booked.
- MR10-second-book/plus-task books the meeting it booked without the added sentence.
- Unnecessary clarifications (a clarification sent where the truth is a booking) fall to zero.
