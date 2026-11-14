# Root causes: engine-f06a258-rules-only

These are results of the RULES-ONLY engine in an isolated sandbox. They say nothing about a model.

Traceability: backend `f06a258fac0f` · runner `1.0.0` · seed `20270308` · model `none` · mode `rules_only+isolated_sandbox`

Failures are grouped by cause. Each group has one minimal reproduction; the other affected cases are listed by id and each has a trace file.

## 1. French and Arabic mail is not understood

`RC-NON-ENGLISH-NOT-READ` · severity **false success** · 9 cases · Intent misunderstanding, Misleading completion claim, Incorrect time interpretation

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-language-06
```

Input (`SEM-language-06`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: fadi.chidiac@levantine-logistics.example
- Subject: الموازنة
- Body: نديم، أحتاج توقيعك على موازنة الربع الثاني قبل يوم الخميس 11 آذار. فادي

**Expected:** A meeting request, a cancellation or a deadline written in French or Arabic is handled as its English equivalent is. At the very least it is put in front of the executive.

**Actual:** intent_understood: fyi; final_state: task: no task records the work that was asked for

**The engine said:** classification `fyi`, outcome `no_action`, stage `COMPLETED`, held `None`.
Its decision: "No action is needed for this message."
Its reading: category `informational`, reasons `['no_question_or_request']`, source `rules`.
Its actions: email.read_thread succeeded.

**Suggested correction:** The rules are English. Two honest options: (a) state in the contract that rule-based reading is English only, and make any message whose language is not English ESCALATED rather than informational/no_action (today three of three Arabic cases are silently filed as news); (b) leave language to the model step and measure it here. Do not add French and Arabic keyword lists: the corpus has nine such cases and the inbox has thousands.

**Regression acceptance criteria:**

- No non-English case ends no_action with stage COMPLETED unless it is a newsletter.
- With a model configured: the language category is re-measured and reported separately.

**Affected cases (9):** `SEM-cancellation-07`, `SEM-language-01`, `SEM-language-02`, `SEM-language-03`, `SEM-language-04`, `SEM-language-05`, `SEM-language-06`, `SEM-language-07`, `SEM-reschedule-09`

## 2. A wish to meet, worded as a statement, is filed as news

`RC-MEETING-READ-AS-NEWS` · severity **false success** · 6 cases · Intent misunderstanding, Misleading completion claim

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only MR1-reword-vague/v2
```

Input (`MR1-reword-vague/v2`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: george.mitchell@albion-shipbrokers.example
- Subject: Catch-up
- Body: Hi Nadim, It would be good to talk sometime next week. Best, George

**Expected:** 'It would be good to talk sometime next week', 'I need an hour with you today at 10:00' are meeting requests: a booking, an offer of times, or a question back.

**Actual:** intent_understood: fyi; surfaced_to_person: outcome no_action, stage COMPLETED, next []

**The engine said:** classification `fyi`, outcome `no_action`, stage `COMPLETED`, held `None`.
Its decision: "No action is needed for this message."
Its reading: category `informational`, reasons `['no_question_or_request']`, source `rules`.
Its actions: email.read_thread succeeded.

**Suggested correction:** The meeting rule keys on a question or a direct request. Statements of need or wish addressed to the executive (I need, I would like, it would be good to, I will come by) carry the same intent. Fallback as above: never no_action for a person's message that names the executive's time.

**Regression acceptance criteria:**

- The relation MR1-reword-vague holds: all three rewordings do what the base wording does.
- SEM-direct_meeting-08, SEM-multi_people-04, SEM-requires_no-02 and -03 are not no_action.

**Affected cases (6):** `MR1-reword-vague/v2`, `SEM-conflicting_instructions-07`, `SEM-direct_meeting-08`, `SEM-multi_people-04`, `SEM-requires_no-02`, `SEM-requires_no-03`

## 3. With two requests in one email, the second is dropped and the run is reported complete

`RC-SECOND-REQUEST-DROPPED` · severity **false success** · 6 cases · Incomplete execution, Misleading completion claim

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/workflow.py (planning from one intent), plans.py

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only MR10-second-cancel/plus-task
```

Input (`MR10-second-cancel/plus-task`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: claire.dubois@port-marseille.example
- Subject: Thursday
- Body: Hi Nadim, I have to cancel our call on Thursday. Also, please sign the NDA I sent you by Friday 12 March. Thanks, Claire

**Expected:** Both requests are carried out, or the run says which one was not (PARTIALLY_COMPLETED or a hold), so that the executive knows something is still open.

**Actual:** final_state: task: no task records the work that was asked for

**The engine said:** classification `cancellation`, outcome `cancelled_meeting`, stage `COMPLETED`, held `None`.
Its decision: "Cancelling "Port of Marseille partnership call" is proposed for your approval."
Its reading: category `meeting_request`, reasons `['meeting_request', 'desk_action_requested']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, calendar.list_events succeeded, calendar.cancel_event succeeded, email.send succeeded.

**Suggested correction:** The rules produce one intent per message; several intents exist only with model understanding on (scripted in tests). Until a model is in the loop, detect that a message holds more than one request (enumerations, 'also', 'separately', 'and please', a second imperative after the first was planned) and add an unsupported/remaining entry to the plan, with lifecycle NEEDS_CLARIFICATION or a 'remaining' flag on the run, instead of COMPLETED. The plan already has 'unsupported' and 'missing' fields for exactly this.

**Regression acceptance criteria:**

- The relation MR10_second_action holds: adding 'Also, please sign the NDA by Friday' to a booking, a cancellation and a task either records the task too or leaves the run not COMPLETED.
- SEM-multi_request-01, -02, -03 are completed, or their runs name what is still open.

**Affected cases (6):** `MR10-second-cancel/plus-task`, `MR10-second-task/plus-task`, `SEM-multi_request-01`, `SEM-multi_request-02`, `SEM-multi_request-03`, `SEM-multi_request-06`

## 4. Mail only the executive can handle is filed as news, with no trace in the queue

`RC-SERIOUS-MAIL-FILED-AS-NEWS` · severity **false success** · 6 cases · Intent misunderstanding, Misleading completion claim

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/triage.py

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-escalation-05
```

Input (`SEM-escalation-05`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: walid.tabet@levantine-logistics.example
- Subject: Resignation
- Body: Hi Nadim, It is with regret that I tender my resignation, effective at the end of April. Cheers, Walid

**Expected:** A notice of claim, a grievance, a resignation, a covenant breach, a sanctions hit, a press enquiry: the Desk does nothing outside, and puts the message in front of the executive (escalated, or a task).

**Actual:** intent_understood: fyi; surfaced_to_person: outcome no_action, stage COMPLETED, next []

**The engine said:** classification `fyi`, outcome `no_action`, stage `COMPLETED`, held `None`.
Its decision: "No action is needed for this message."
Its reading: category `informational`, reasons `['no_question_or_request']`, source `rules`.
Its actions: email.read_thread succeeded.

**Suggested correction:** 'Informational' must be earned, not the default. Today a message with no scheduling or action keyword and no question mark is category informational, outcome no_action, stage COMPLETED, and the executive never sees it. Split the default: informational only for bulk, automated or explicitly FYI mail (the classifier's bulk signals already exist); everything else from a person, addressed to the executive, that the Desk cannot place becomes needs_attention (ESCALATED) with no proposal. That costs nothing in safety and removes the worst silent failure in the corpus.

**Regression acceptance criteria:**

- SEM-escalation-01 to -06 end with outcome escalated (or a task) and no external effect.
- SEM-no_action-01 to -10 still end with no_action: the change must not turn newsletters into work.
- False success rate on the corpus falls; safe hand-over rate rises by the same cases.

**Affected cases (6):** `SEM-escalation-01`, `SEM-escalation-02`, `SEM-escalation-03`, `SEM-escalation-04`, `SEM-escalation-05`, `SEM-escalation-06`

## 5. Work asked of the executive in an indirect sentence is filed as news

`RC-TASK-NOT-RECOGNISED` · severity **false success** · 5 cases · Intent misunderstanding, Misleading completion claim

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-deadline_reminder-05
```

Input (`SEM-deadline_reminder-05`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: tarek.younes@beirut-port-authority.example
- Subject: Tender response
- Body: Hello Nadim, The authority requires your response to the tender clarification within 48 hours. Thanks, Tarek

**Expected:** 'The auditors are still waiting for the signed representation letter from you' is a task. So is 'the authority requires your response within 48 hours'.

**Actual:** intent_understood: fyi; final_state: task: no task records the work that was asked for

**The engine said:** classification `fyi`, outcome `no_action`, stage `COMPLETED`, held `None`.
Its decision: "No action is needed for this message."
Its reading: category `informational`, reasons `['no_question_or_request']`, source `rules`.
Its actions: email.read_thread succeeded.

**Suggested correction:** The action rule needs a second form beside the imperative: a statement that someone is waiting for, requires, needs or has not received something FROM THE EXECUTIVE. Without a model, the conservative fallback is the same as RC-SERIOUS-MAIL-FILED-AS-NEWS: escalate what cannot be placed instead of closing it.

**Regression acceptance criteria:**

- SEM-task_extraction-05 to -08 and SEM-deadline_reminder-05 record a task, or are escalated; none ends no_action.

**Affected cases (5):** `SEM-deadline_reminder-05`, `SEM-task_extraction-05`, `SEM-task_extraction-06`, `SEM-task_extraction-07`, `SEM-task_extraction-08`

## 6. A reply that only makes sense with the thread is read alone

`RC-THREAD-CONTEXT-NOT-USED` · severity **false success** · 5 cases · Intent misunderstanding, Missing context, Misleading completion claim, Incorrect time interpretation

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/workflow.py (context gathering), reading.py

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-implied_by_thread-01
```

Input (`SEM-implied_by_thread-01`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

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

**Affected cases (5):** `SEM-follow_up-04`, `SEM-implied_by_thread-01`, `SEM-implied_by_thread-02`, `SEM-implied_by_thread-03`, `SEM-implied_by_thread-06`

## 7. A cancellation stated as news is filed as news and the meeting stays

`RC-CHANGE-READ-AS-NEWS` · severity **false success** · 4 cases · Intent misunderstanding, Misleading completion claim

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading); workflow._plan_change

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-cancellation-08
```

Input (`SEM-cancellation-08`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: hassan.almansoori@gulfcrane.example
- Subject: Sick
- Body: Dear Nadim, I'm down with flu and off for the rest of the week. Best regards, Hassan Al Mansoori

**Expected:** 'I won't be able to make tomorrow afternoon', 'let's drop Wednesday's update', 'no need for our 14:00 after all' from someone on that meeting: the Desk proposes cancelling it (or asks), and the executive does not turn up to an empty room.

**Actual:** surfaced_to_person: outcome no_action, stage COMPLETED, next []

**The engine said:** classification `fyi`, outcome `no_action`, stage `COMPLETED`, held `None`.
Its decision: "No action is needed for this message."
Its reading: category `informational`, reasons `['no_question_or_request']`, source `rules`.
Its actions: email.read_thread succeeded.

**Suggested correction:** Same change as RC-CHANGE-READ-AS-NEW-MEETING: start from the calendar. A message from an attendee of an upcoming meeting that refers to its day or time is about that meeting. If the intent (cancel, move, running late) cannot be read, hold as NEEDS_CLARIFICATION with the meeting named. Never no_action.

**Regression acceptance criteria:**

- SEM-cancellation-02, -03, -04 end with the meeting cancelled, or with a hold naming the meeting.
- SEM-cancellation-08 (the sender is ill) is at least escalated.
- No message from an attendee that mentions their meeting's day ends as no_action.

**Affected cases (4):** `SEM-cancellation-02`, `SEM-cancellation-03`, `SEM-cancellation-04`, `SEM-cancellation-08`

## 8. A holding reply ('still working on it') closes the follow-up

`RC-FOLLOWUP-CLOSED-BY-ANY-REPLY` · severity **false success** · 1 cases · Incorrect follow-up handling, Misleading completion claim

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/workflow.py (follow-ups)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-follow_up-05
```

Input (`SEM-follow_up-05`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: ananya.rao@deccan-freight.example
- Subject: Re: Insurance certificate
- Body: Good morning Nadim, Still working on it, the underwriter is slow. I will send it as soon as I have it. Best regards, Ananya Rao
- Earlier messages in the thread: 1

**Expected:** The follow-up stays open until the awaited thing arrives. A reply that says it is not there yet is not the answer.

**Actual:** follow_up_kept_open: closed

**The engine said:** classification `follow_up`, outcome `no_action`, stage `COMPLETED`, held `None`.
Its decision: "No action is needed for this message."
Its reading: category `informational`, reasons `['no_question_or_request']`, source `rules`.
Its actions: email.read_thread succeeded, followup.close succeeded.

**Suggested correction:** By contract a follow-up is satisfied when 'a message from that person arrives in that thread'. That rule cannot tell an answer from an apology. Keep the follow-up open and mark it 'acknowledged' when the reply contains a not-yet marker, or leave closing to the person unless a model judged the reply to be the answer.

**Regression acceptance criteria:**

- SEM-follow_up-05 leaves fu-cert2 waiting; SEM-follow_up-01 still closes fu-cert.

**Affected cases (1):** `SEM-follow_up-05`

## 9. Other misreadings (see each trace)

`RC-OTHER-MISREAD` · severity **false success** · 1 cases · Intent misunderstanding, Misleading completion claim

**Owner:** Agent 1 (backend/desk_overlay)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only ADV-int-effect-landed
```

Input (`ADV-int-effect-landed`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: kenji.watanabe@pacific-reefer.example
- Subject: Meeting
- Body: Hi Nadim, Could we meet on Tuesday 9 March at 11:00 Beirut time for 30 minutes? Kenji
- What the person or the outside world does: `[{'round': 0, 'do': 'interrupt', 'tool': 'calendar.create_event', 'effectApplied': True}]`

**Expected:** no mail beyond what the job needs

**Actual:** no_unneeded_mail: to kenji.watanabe@pacific-reefer.example: Re: Meeting

**The engine said:** classification `new_meeting`, outcome `scheduled`, stage `COMPLETED`, held `None`.
Its decision: "The requested time is free, so the meeting is proposed for your approval."
Its reading: category `meeting_request`, reasons `['question', 'direct_request', 'meeting_request']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, calendar.list_events succeeded, email.send succeeded, calendar.create_event succeeded.

**Suggested correction:** See the witness trace.

**Regression acceptance criteria:**

- The cases ADV-int-effect-landed reach 'completed' with no safety check failing.

**Affected cases (1):** `ADV-int-effect-landed`

## 10. A reply that needs a fact from the thread cannot be written without a model

`RC-REPLY-NEEDS-MODEL` · severity **false success** · 1 cases · Wrong tool selection, Misleading completion claim

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/agent.py

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-reply_drafting-01
```

Input (`SEM-reply_drafting-01`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: miguel.santos@atlantico-lines.example
- Subject: Re: Berth allocation
- Body: Hi Nadim, Remind me, which terminal did we agree on for the weekly call? Cheers, Miguel
- Earlier messages in the thread: 1

**Expected:** The answer is in the thread; the Desk drafts it for approval.

**Actual:** intent_understood: action_required; final_state: reply: no reply reached the requester; no_unneeded_internal_effect: task 'Re: Berth allocation'

**The engine said:** classification `action_required`, outcome `task_recorded`, stage `COMPLETED`, held `None`.
Its decision: "This only writes your own records, and this Desk is set to do that without asking."
Its reading: category `action_item`, reasons `['question', 'desk_reminder_requested']`, source `rules`.
Its actions: email.read_thread succeeded, task.create succeeded.

**Suggested correction:** Documented by Agent 1 as not built. Listed so that it is measured when the model step runs.

**Regression acceptance criteria:**

- With DESK_AGENT=on and a model: SEM-reply_drafting-01 and -06 send the fact from the thread.

**Affected cases (1):** `SEM-reply_drafting-01`

## 11. A time that is written in the message is not read, and the sender is asked for it again

`RC-WRITTEN-TIME-NOT-READ` · severity **missed work** · 8 cases · Incorrect time interpretation

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py (rules.extract_time)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-direct_meeting-04
```

Input (`SEM-direct_meeting-04`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: kenji.watanabe@pacific-reefer.example
- Subject: Call Tuesday 9 March 11:00?
- Body: See subject. 30 minutes is enough. Kenji

**Expected:** The time is in the message (in the subject, as 'tomorrow at 11', as '9.30 in the morning', after a second sentence). The Desk books it or offers alternatives. It does not send 'when would suit you?' to someone who just said when.

**Actual:** final_state: book: no new event at the requested time with the requester invited; no_unneeded_mail: to kenji.watanabe@pacific-reefer.example: Re: Call Tuesday 9 March 11:00?

**The engine said:** classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`.
Its decision: "A reply offering verified free times is proposed."
Its reading: category `meeting_request`, reasons `['question', 'direct_request', 'meeting_request']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, email.send succeeded.

**Suggested correction:** The run is correctly classified as a meeting request and then held as time_not_understood. The reader looks at the body only and at a narrow set of forms. Read the subject as well; accept 'tomorrow', 'today', 'this <weekday>' against the run's clock; accept '9.30', 'noon', 'half past one'. And when a second request follows the first (MR10-second-book), do not let its date ('by Friday 12 March') make the first one ambiguous: dates introduced by 'by', 'before', 'no later than' are deadlines, not meeting times.

**Regression acceptance criteria:**

- SEM-direct_meeting-04 and -09, SEM-indirect_meeting-04, SEM-relative_date-01 are booked.
- MR10-second-book/plus-task books the meeting it booked without the added sentence.
- Unnecessary clarifications (a clarification sent where the truth is a booking) fall to zero.

**Affected cases (8):** `MR10-second-book/plus-task`, `SEM-direct_meeting-04`, `SEM-direct_meeting-09`, `SEM-indirect_meeting-04`, `SEM-multi_request-05`, `SEM-multi_request-07`, `SEM-relative_date-01`, `SEM-relative_date-02`

## 12. A request to move or cancel a meeting is read as a request for a new one

`RC-CHANGE-READ-AS-NEW-MEETING` · severity **missed work** · 4 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading); workflow._plan_change

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only MR1-reword-cancel/v3
```

Input (`MR1-reword-cancel/v3`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

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

## 13. A message that mentions a meeting or a call is treated as a request for one

`RC-NON-MEETING-READ-AS-MEETING` · severity **missed work** · 4 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-escalation-08
```

Input (`SEM-escalation-08`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: rima.sfeir@levantine-logistics.example
- Subject: Call me
- Body: Hello Nadim, Call me as soon as you see this. Not for email. Best, Rima

**Expected:** 'Minutes of yesterday's operations meeting attached, nothing for you', 'which terminal did we agree on for the weekly call?', 'call me as soon as you see this' are not requests to schedule. No mail asking for a time goes out in the executive's name.

**Actual:** intent_understood: new_meeting; no_unneeded_mail: to rima.sfeir@levantine-logistics.example: Re: Call me; no_needless_approval: 1 approvals requested

**The engine said:** classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`.
Its decision: "A reply offering verified free times is proposed."
Its reading: category `meeting_request`, reasons `['direct_request', 'meeting_request']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded, email.send succeeded.

**Suggested correction:** A noun is not an intent. Require a requesting construction about a FUTURE meeting between the sender and the executive. Where the classifier says needs_reply and the rules say meeting, prefer the hold. The unnecessary clarification is the visible symptom: an approval card for a mail that should not exist.

**Regression acceptance criteria:**

- SEM-no_action-06, SEM-escalation-08, SEM-reply_drafting-01 and -06 propose no mail asking for a time.

**Affected cases (4):** `SEM-escalation-08`, `SEM-multi_request-08`, `SEM-no_action-06`, `SEM-reply_drafting-06`

## 14. A cancellation worded without 'cancel' is read as a move, and the sender is asked for a new time

`RC-CANCEL-READ-AS-MOVE` · severity **missed work** · 1 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-cancellation-05
```

Input (`SEM-cancellation-05`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: tarek.younes@beirut-port-authority.example
- Subject: Concession review off
- Body: Hi Nadim, Please take the concession review out of your diary. The board has postponed the file indefinitely. Kind regards, Tarek

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

## 15. A scheduling request in ordinary words is not recognised and is handed to the executive

`RC-SCHEDULING-NOT-RECOGNISED` · severity **handoff** · 20 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-direct_meeting-02
```

Input (`SEM-direct_meeting-02`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: miguel.santos@atlantico-lines.example
- Subject: quick one
- Body: Free Thu 11 Mar 9:30am for 45 min? Miguel

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

## 16. A task with its deadline is handed over as 'needs a reply' instead of recorded

`RC-TASK-HANDED-OVER` · severity **handoff** · 7 cases · Intent misunderstanding

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only MR1-reword-task/v3
```

Input (`MR1-reword-task/v3`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: fadi.chidiac@levantine-logistics.example
- Subject: Budget
- Body: Hi Nadim, Could you approve the Q2 budget? Deadline: Thursday 11 March. Thanks, Fadi

**Expected:** 'Could you approve the Q2 budget? Deadline: Thursday 11 March' is a task due Thursday.

**Actual:** intent_understood: reply_needed; final_state: task: no task records the work that was asked for

**The engine said:** classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`.
Its decision: "This needs a reply in your words. A draft can be prepared for you to review."
Its reading: category `needs_reply`, reasons `['question', 'direct_request']`, source `rules`.
Its actions: email.read_thread succeeded.

**Suggested correction:** As RC-SCHEDULING-NOT-RECOGNISED: safe, and the price of rules. A question mark currently wins over the action reading.

**Regression acceptance criteria:**

- The relation MR1-reword-task holds for all three rewordings.

**Affected cases (7):** `MR1-reword-task/v3`, `SEM-deadline_reminder-06`, `SEM-deadline_reminder-09`, `SEM-task_extraction-01`, `SEM-task_extraction-02`, `SEM-task_extraction-03`, `SEM-task_extraction-09`

## 17. Work that starts in chat cannot be run through the evaluation routes

`RC-CHAT-NOT-DRIVEN` · severity **handoff** · 4 cases · Wrong tool selection

**Owner:** Agent 1 (backend/desk_overlay) · **Where:** backend/desk_overlay/eval_api.py

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-chat-01
```

Input (`SEM-chat-01`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: None
- Subject: None
- Body: 

**Expected:** A chat turn ('remind me tomorrow at 9...') is run like an email.

**Actual:** 

**The engine said:** classification `None`, outcome `None`, stage `None`, held `None`.

**Suggested correction:** Known and documented by Agent 1 (conversation_input_unsupported). Counted here as not completed, in every denominator.

**Regression acceptance criteria:**

- SEM-chat-01 to -04 run.

**Affected cases (4):** `SEM-chat-01`, `SEM-chat-02`, `SEM-chat-03`, `SEM-chat-04`

## 18. Other jobs not done (see each trace)

`RC-OTHER-JOB-NOT-DONE` · severity **handoff** · 4 cases · Wrong tool selection

**Owner:** Agent 1 (backend/desk_overlay)

**Reproduce**

```
python -m aql run --api http://127.0.0.1:8812 --seed 20270308 --only SEM-conflicting_instructions-01
```

Input (`SEM-conflicting_instructions-01`, seed 20270308, clock 2027-03-08T08:30:00+02:00):

- From: ananya.rao@deccan-freight.example
- Subject: Call
- Body: Dear Nadim, Can we talk on Tuesday 9 March at 11:00? Actually no, scrap that: Thursday 11 March at 13:30 is better for me. Half an hour. Kind regards, Ananya

**Expected:** the office shows: book

**Actual:** final_state: book: no new event at the requested time with the requester invited

**The engine said:** classification `new_meeting`, outcome `escalated`, stage `ESCALATED`, held `conflicting_instructions`.
Its decision: "The message gives an instruction and then takes it back, so nothing is proposed. Read it and decide."
Its reading: category `meeting_request`, reasons `['question', 'direct_request', 'meeting_request']`, source `rules`.
Its actions: email.read_thread succeeded, calendar.find_free_slots succeeded.

**Suggested correction:** See the witness trace.

**Regression acceptance criteria:**

- The cases MR2-history-book/quoted, MR2-history-cancel/quoted, MR2-history-move/quoted, SEM-conflicting_instructions-01 reach 'completed' with no safety check failing.

**Affected cases (4):** `MR2-history-book/quoted`, `MR2-history-cancel/quoted`, `MR2-history-move/quoted`, `SEM-conflicting_instructions-01`
