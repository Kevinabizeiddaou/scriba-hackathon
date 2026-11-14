# Root causes: engine-bd4f0cc-rules-only-seed101

These are results of the RULES-ONLY engine in an isolated sandbox. They say nothing about a model.

Traceability: backend `bd4f0cc6cddb` · runner `1.0.0` · seed `101` · model `none` · mode `rules_only+isolated_sandbox`

Failures are grouped by cause. Each group has one minimal reproduction; the other affected cases are listed by id and each has a trace file.

## 1. A time that is written in the message is not read, and the sender is asked for it again

`RC-WRITTEN-TIME-NOT-READ` · severity **missed work** · 6 cases · Incorrect time interpretation

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py (rules.extract_time)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only SEM-direct_meeting-04
```

Input (`SEM-direct_meeting-04`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: kenji.watanabe@pacific-reefer.example
- Subject: Call Friday 12 March 15:30?
- Body: See subject. 30 minutes is enough. Kenji

**Expected:** The time is in the message (in the subject, as 'tomorrow at 11', as '9.30 in the morning', after a second sentence). The Desk books it or offers alternatives. It does not send 'when would suit you?' to someone who just said when.

**Actual:** final_state: book: no new event at the requested time with the requester invited; no_unneeded_mail: to kenji.watanabe@pacific-reefer.example: Re: Call Friday 12 March 15:30?

**The engine said:** classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`.
Its decision: "A reply offering verified free times is proposed."
Its reading: category `meeting_request`, reasons `['question', 'direct_request', 'meeting_request']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, email.send succeeded.

**Suggested correction:** The run is correctly classified as a meeting request and then held as time_not_understood. The reader looks at the body only and at a narrow set of forms. Read the subject as well; accept 'tomorrow', 'today', 'this <weekday>' against the run's clock; accept '9.30', 'noon', 'half past one'. And when a second request follows the first (MR10-second-book), do not let its date ('by Friday 12 March') make the first one ambiguous: dates introduced by 'by', 'before', 'no later than' are deadlines, not meeting times.

**Regression acceptance criteria:**

- SEM-direct_meeting-04 and -09, SEM-indirect_meeting-04, SEM-relative_date-01 are booked.
- MR10-second-book/plus-task books the meeting it booked without the added sentence.
- Unnecessary clarifications (a clarification sent where the truth is a booking) fall to zero.

**Affected cases (6):** `SEM-direct_meeting-04`, `SEM-direct_meeting-09`, `SEM-indirect_meeting-04`, `SEM-multi_request-05`, `SEM-relative_date-01`, `SEM-relative_date-02`

## 2. A request to move or cancel a meeting is read as a request for a new one

`RC-CHANGE-READ-AS-NEW-MEETING` · severity **missed work** · 4 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading); workflow._plan_change

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only MR1-reword-cancel/v3
```

Input (`MR1-reword-cancel/v3`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: claire.dubois@port-marseille.example
- Subject: Thursday
- Body: Hi Nadim, Thursday's call is off on my side, sorry. Claire

**Expected:** The sender is already on a meeting. A message from them naming another time, or saying they cannot make it, changes THAT meeting: one update_calendar_event or cancel_calendar_event on the original event. Never a second event beside the first.

**Actual:** intent_understood: new_meeting; final_state: cancel: the meeting is still on the calendar; no_unneeded_mail: to claire.dubois@port-marseille.example: Re: Thursday

**The engine said:** classification `new_meeting`, outcome `alternatives_proposed`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`.
Its decision: "A reply offering verified free times is proposed."
Its reading: category `meeting_request`, reasons `['meeting_request']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, calendar.list_events succeeded, email.send succeeded.

**Suggested correction:** Decide 'new or change' from the calendar, not from the verb. Before planning a booking, look for an upcoming meeting the sender is on. If there is one and the message refers to it (its day, its time, 'our call', 'Thursday's meeting') or gives a reason for not attending, plan a change to that event; if it cannot be told which, hold with event_ambiguous or ask. The contract already promises 'never a second event' for moves; today that holds only when the word reschedule (or move ... to) appears.

**Regression acceptance criteria:**

- SEM-reschedule-03 and SEM-implied_by_thread-05 end with the original event moved, no new event, one confirmation.
- The relation MR1-reword-move holds for all three rewordings (same effect as the base wording).
- MR1-reword-cancel/v3 cancels the meeting, as the base wording does.
- No case in the corpus creates an event for a sender who already has one that week unless the truth is a new meeting (gate: zero_incorrect_external_actions).
- Regenerate the corpus with another seed (--seed) and re-run: the rate must not depend on the lab's wording.

**Affected cases (4):** `MR1-reword-cancel/v3`, `MR1-reword-move/v2`, `SEM-multi_request-04`, `SEM-reschedule-04`

## 3. French and Arabic mail is not understood

`RC-NON-ENGLISH-NOT-READ` · severity **missed work** · 4 cases · Intent misunderstanding, Incorrect time interpretation

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only SEM-language-07
```

Input (`SEM-language-07`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: miguel.santos@atlantico-lines.example
- Subject: call bukra?
- Body: Marhaba Nadim, fina na3mol call bukra el se3a 11 la noss se3a? Merci ktir. Miguel

**Expected:** A meeting request, a cancellation or a deadline written in French or Arabic is handled as its English equivalent is. At the very least it is put in front of the executive.

**Actual:** final_state: book: no new event at the requested time with the requester invited; no_unneeded_mail: to miguel.santos@atlantico-lines.example: Re: call bukra?

**The engine said:** classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`.
Its decision: "A reply offering verified free times is proposed."
Its reading: category `meeting_request`, reasons `['question', 'direct_request', 'meeting_request']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, email.send succeeded.

**Suggested correction:** The rules are English. Two honest options: (a) state in the contract that rule-based reading is English only, and make any message whose language is not English ESCALATED rather than informational/no_action (today three of three Arabic cases are silently filed as news); (b) leave language to the model step and measure it here. Do not add French and Arabic keyword lists: the corpus has nine such cases and the inbox has thousands.

**Regression acceptance criteria:**

- No non-English case ends no_action with stage COMPLETED unless it is a newsletter.
- With a model configured: the language category is re-measured and reported separately.

**Affected cases (4):** `SEM-language-01`, `SEM-language-02`, `SEM-language-07`, `SEM-reschedule-09`

## 4. A message that mentions a meeting or a call is treated as a request for one

`RC-NON-MEETING-READ-AS-MEETING` · severity **missed work** · 4 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only SEM-escalation-08
```

Input (`SEM-escalation-08`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: rima.sfeir@levantine-logistics.example
- Subject: Call me
- Body: Dear Nadim, Call me as soon as you see this. Not for email. Cheers, Rima

**Expected:** 'Minutes of yesterday's operations meeting attached, nothing for you', 'which terminal did we agree on for the weekly call?', 'call me as soon as you see this' are not requests to schedule. No mail asking for a time goes out in the executive's name.

**Actual:** intent_understood: new_meeting; no_unneeded_mail: to rima.sfeir@levantine-logistics.example: Re: Call me; no_needless_approval: 1 approvals requested

**The engine said:** classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`.
Its decision: "A reply offering verified free times is proposed."
Its reading: category `meeting_request`, reasons `['direct_request', 'meeting_request']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, email.send succeeded.

**Suggested correction:** A noun is not an intent. Require a requesting construction about a FUTURE meeting between the sender and the executive. Where the classifier says needs_reply and the rules say meeting, prefer the hold. The unnecessary clarification is the visible symptom: an approval card for a mail that should not exist.

**Regression acceptance criteria:**

- SEM-no_action-06, SEM-escalation-08, SEM-reply_drafting-01 and -06 propose no mail asking for a time.

**Affected cases (4):** `SEM-escalation-08`, `SEM-no_action-06`, `SEM-reply_drafting-01`, `SEM-reply_drafting-06`

## 5. A reply that only makes sense with the thread is read alone

`RC-THREAD-CONTEXT-NOT-USED` · severity **missed work** · 3 cases · Intent misunderstanding, Missing context, Incorrect time interpretation

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/workflow.py (context gathering), reading.py

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only SEM-implied_by_thread-01
```

Input (`SEM-implied_by_thread-01`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: kenji.watanabe@pacific-reefer.example
- Subject: Re: Time to talk?
- Body: 13:30 works for me. Kenji
- Earlier messages in the thread: 2

**Expected:** '13:30 works for me' after the executive asked 'Thursday is better, what time?' books Thursday 13:30. 'The second option please' books the second time the executive offered.

**Actual:** intent_understood: reply_needed; final_state: book: no new event at the requested time with the requester invited

**The engine said:** classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`.
Its decision: "This needs a reply in your words. A draft can be prepared for you to review."
Its reading: category `needs_reply`, reasons `['question']`, source `rules`.
Its actions: email.read_thread succeeded.

**Suggested correction:** The run already reads the thread (email.read_thread appears in every trace) and then reads only the last message for intent and time. Give the reader the thread: the day from the executive's last message plus the time from the reply; an acceptance ('yes', 'that works', 'the second option') of times the executive offered. This is where a model earns its place; by rule, at least hold as NEEDS_CLARIFICATION with the thread's open question, never hand over as an unplaced reply.

**Regression acceptance criteria:**

- SEM-implied_by_thread-01, -02, -03, -06 and SEM-follow_up-04 book the time the thread settled on, or hold naming it.

**Affected cases (3):** `SEM-follow_up-04`, `SEM-implied_by_thread-01`, `SEM-implied_by_thread-02`

## 6. With two requests in one email, the second is dropped and the run is reported complete

`RC-SECOND-REQUEST-DROPPED` · severity **missed work** · 2 cases · Incomplete execution

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/workflow.py (planning from one intent), plans.py

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only SEM-multi_request-08
```

Input (`SEM-multi_request-08`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: rima.sfeir@levantine-logistics.example
- Subject: Before you travel
- Body: Dear Nadim, Before you fly: please approve the travel budget, and call the port director. Neither can wait until you are back. Kind regards, Rima

**Expected:** Both requests are carried out, or the run says which one was not (PARTIALLY_COMPLETED or a hold), so that the executive knows something is still open.

**Actual:** intent_understood: new_meeting; final_state: task: no task records the work that was asked for; no_unneeded_mail: to rima.sfeir@levantine-logistics.example: Re: Before you travel

**The engine said:** classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`.
Its decision: "This only writes your own records, and this Desk is set to do that without asking."
Its reading: category `meeting_request`, reasons `['direct_request', 'meeting_request', 'desk_action_requested']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, task.create succeeded, email.send succeeded.

**Suggested correction:** The rules produce one intent per message; several intents exist only with model understanding on (scripted in tests). Until a model is in the loop, detect that a message holds more than one request (enumerations, 'also', 'separately', 'and please', a second imperative after the first was planned) and add an unsupported/remaining entry to the plan, with lifecycle NEEDS_CLARIFICATION or a 'remaining' flag on the run, instead of COMPLETED. The plan already has 'unsupported' and 'missing' fields for exactly this.

**Regression acceptance criteria:**

- The relation MR10_second_action holds: adding 'Also, please sign the NDA by Friday' to a booking, a cancellation and a task either records the task too or leaves the run not COMPLETED.
- SEM-multi_request-01, -02, -03 are completed, or their runs name what is still open.

**Affected cases (2):** `SEM-multi_request-06`, `SEM-multi_request-08`

## 7. A cancellation worded without 'cancel' is read as a move, and the sender is asked for a new time

`RC-CANCEL-READ-AS-MOVE` · severity **missed work** · 1 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only SEM-cancellation-05
```

Input (`SEM-cancellation-05`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: tarek.younes@beirut-port-authority.example
- Subject: Concession review off
- Body: Good morning Nadim, Please take the concession review out of your diary. The board has postponed the file indefinitely. Best, Tarek

**Expected:** 'Please take the concession review out of your diary' cancels the meeting.

**Actual:** intent_understood: reschedule; final_state: cancel: the meeting is still on the calendar; no_unneeded_mail: to tarek.younes@beirut-port-authority.example: Re: Concession review off

**The engine said:** classification `reschedule`, outcome `alternatives_proposed`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`.
Its decision: "A reply offering verified free times is proposed."
Its reading: category `meeting_request`, reasons `['no_question_or_request', 'desk_meeting_reschedule']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, calendar.list_events succeeded, email.send succeeded.

**Suggested correction:** As RC-CHANGE-READ-AS-NEWS. 'Postponed indefinitely', 'take it out of the diary', 'off' with no new time are cancellations, not moves.

**Regression acceptance criteria:**

- SEM-cancellation-05 cancels ev-port and asks the sender nothing.

**Affected cases (1):** `SEM-cancellation-05`

## 8. Other jobs not done (see each trace)

`RC-OTHER-JOB-NOT-DONE` · severity **handoff** · 21 cases · Intent misunderstanding, Missing context, Wrong tool selection

**Owner:** Agent 1 (backend/desk_overlay)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only SEM-language-06
```

Input (`SEM-language-06`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: fadi.chidiac@levantine-logistics.example
- Subject: الموازنة
- Body: نديم، أحتاج توقيعك على موازنة الربع الثاني قبل يوم الخميس 11 آذار. فادي

**Expected:** one of ['action_required']; the office shows: task

**Actual:** intent_understood: fyi; final_state: task: no task records the work that was asked for

**The engine said:** classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`.
Its decision: "The Desk could not place this message, so it was handed to you instead of being filed."
Its reading: category `informational`, reasons `['no_question_or_request']`, source `rules`.
Its actions: email.read_thread succeeded.

**Suggested correction:** See the witness trace.

**Regression acceptance criteria:**

- The cases MR2-history-book/quoted, MR2-history-cancel/quoted, MR2-history-move/quoted, SEM-cancellation-02, SEM-cancellation-03, SEM-cancellation-04 reach 'completed' with no safety check failing.

**Affected cases (21):** `MR2-history-book/quoted`, `MR2-history-cancel/quoted`, `MR2-history-move/quoted`, `SEM-cancellation-02`, `SEM-cancellation-03`, `SEM-cancellation-04`, `SEM-cancellation-07`, `SEM-conflicting_instructions-01`, `SEM-deadline_reminder-05`, `SEM-direct_meeting-08`, `SEM-implied_by_thread-03`, `SEM-implied_by_thread-06`, `SEM-language-03`, `SEM-language-04`, `SEM-language-05`, `SEM-language-06`, `SEM-multi_people-04`, `SEM-task_extraction-05`, `SEM-task_extraction-06`, `SEM-task_extraction-07`, `SEM-task_extraction-08`

## 9. A scheduling request in ordinary words is not recognised and is handed to the executive

`RC-SCHEDULING-NOT-RECOGNISED` · severity **handoff** · 20 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only SEM-direct_meeting-02
```

Input (`SEM-direct_meeting-02`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: ananya.rao@deccan-freight.example
- Subject: quick one
- Body: Free Tue 9 Mar 11am for 30 min? Ananya

**Expected:** 'Free Thu 11 Mar 9:30am for 45 min?', 'Can I steal 30 minutes of your time on Tuesday at 11:00?', 'Could I have you between 13:30 and 14:00 on Thursday?' are bookings.

**Actual:** intent_understood: reply_needed; final_state: book: no new event at the requested time with the requester invited

**The engine said:** classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`.
Its decision: "This needs a reply in your words. A draft can be prepared for you to review."
Its reading: category `needs_reply`, reasons `['question']`, source `rules`.
Its actions: email.read_thread succeeded.

**Suggested correction:** This is the largest group and the safest failure: nothing wrong happens, the executive does the work. It is the measured cost of rules: 20 of the corpus's meeting requests. Widening the keyword list will move this number and not the next reader's. The durable fix is the model understanding step that is already built (DESK_UNDERSTANDING=model), run for real: the checked pipeline behind it scored 23 of 24 with a scripted reader. The lab is ready to measure it the day a credential exists.

**Regression acceptance criteria:**

- With a model configured, re-run the corpus: complete job success on direct_meeting, indirect_meeting, timezone, daylight_saving and relative_date is reported against today's figures.
- The six hard gates still pass with the model on.

**Affected cases (20):** `SEM-daylight_saving-02`, `SEM-daylight_saving-03`, `SEM-daylight_saving-05`, `SEM-daylight_saving-06`, `SEM-direct_meeting-02`, `SEM-direct_meeting-06`, `SEM-direct_meeting-07`, `SEM-direct_meeting-10`, `SEM-indirect_meeting-01`, `SEM-indirect_meeting-03`, `SEM-indirect_meeting-06`, `SEM-indirect_meeting-07`, `SEM-indirect_meeting-08`, `SEM-indirect_meeting-09`, `SEM-relative_date-03`, `SEM-relative_date-04`, `SEM-reschedule-02`, `SEM-reschedule-05`, `SEM-reschedule-07`, `SEM-timezone-05`

## 10. A task with its deadline is handed over as 'needs a reply' instead of recorded

`RC-TASK-HANDED-OVER` · severity **handoff** · 8 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8811 --seed 101 --only SEM-chat-04
```

Input (`SEM-chat-04`, seed 101, clock 2027-03-08T08:30:00+02:00):

- From: None
- Subject: None
- Body: 

**Expected:** 'Could you approve the Q2 budget? Deadline: Thursday 11 March' is a task due Thursday.

**Actual:** intent_understood: unclear; final_state: task: no task records the work that was asked for

**The engine said:** classification `unclear`, outcome `escalated`, stage `NEEDS_CLARIFICATION`, held `intent_unclear`.
Its decision: "The instruction was not understood; nothing is proposed."
Its reading: category `command`, reasons `None`, source `rules`.

**Suggested correction:** As RC-SCHEDULING-NOT-RECOGNISED: safe, and the price of rules. A question mark currently wins over the action reading.

**Regression acceptance criteria:**

- The relation MR1-reword-task holds for all three rewordings.

**Affected cases (8):** `MR1-reword-task/v3`, `SEM-chat-04`, `SEM-deadline_reminder-06`, `SEM-deadline_reminder-09`, `SEM-task_extraction-01`, `SEM-task_extraction-02`, `SEM-task_extraction-03`, `SEM-task_extraction-09`
