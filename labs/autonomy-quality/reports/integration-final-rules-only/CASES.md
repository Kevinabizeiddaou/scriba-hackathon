# Case by case: integration-final-rules-only

These are results of the RULES-ONLY engine in an isolated sandbox. They say nothing about a model.

Traceability: backend `5f8e5181626d` · runner `1.0.0` · seed `20270308` · model `none` · mode `rules_only+isolated_sandbox`

Every case that did not end `completed`, in the order it ran. The complete trace of every case, completed ones included, is in `traces.jsonl.gz` (one JSON object per line; `python -m aql trace --report <dir> --case <id>` prints one).

## `SEM-direct_meeting-02`: safe handoff

quick one · category `direct_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: miguel.santos@atlantico-lines.example
- Subject: quick one
- Body: Free Thu 11 Mar 9:30am for 45 min? Miguel
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-direct_meeting-04`: failed

Call Tuesday 9 March 11:00? · category `direct_meeting` · root cause `RC-WRITTEN-TIME-NOT-READ`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Call Tuesday 9 March 11:00?
- Body: See subject. 30 minutes is enough. Kenji
- Truth: book; intent one of ['new_meeting']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to kenji.watanabe@pacific-reefer.example: Re: Call Tuesday 9 March 11:00?

## `SEM-direct_meeting-06`: safe handoff

Thursday catch-up · category `direct_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Thursday catch-up
- Body: Dear Nadim, Could I have you between 13:30 and 14:00 on Thursday 11 March? Your time. Kind regards, Kenji
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-direct_meeting-07`: safe handoff

Friday 12 March, 11:00-11:45 · category `direct_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Friday 12 March, 11:00-11:45
- Body: Dear Nadim, Proposing the above for the tariff discussion, Beirut time. Please confirm. Best, Kenji
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-direct_meeting-08`: safe handoff

Visit to your office · category `direct_meeting` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: miguel.santos@atlantico-lines.example
- Subject: Visit to your office
- Body: Good morning Nadim, I will be in Beirut next week and would like to come by your office on Thursday the 11th at 9.30 in the morning for about 45 minutes. Thanks, Miguel
- Truth: book; intent one of ['new_meeting']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual fyi
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-direct_meeting-09`: failed

Meeting request · category `direct_meeting` · root cause `RC-WRITTEN-TIME-NOT-READ`

- From: george.mitchell@albion-shipbrokers.example
- Subject: Meeting request
- Body: Hi Nadim, Please may we meet on the 9th of March at half past one in the afternoon, Beirut time? 45 minutes. Best, George
- Truth: book; intent one of ['new_meeting']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to george.mitchell@albion-shipbrokers.example: Re: Meeting request

## `SEM-direct_meeting-10`: safe handoff

Intro · category `direct_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: miguel.santos@atlantico-lines.example
- Subject: Intro
- Body: Nadim - Miguel Santos here, we met through Rima. 30 mins Monday 8 March 16:00 your time to introduce our reefer programme?
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-indirect_meeting-01`: safe handoff

The contract · category `indirect_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: ananya.rao@deccan-freight.example
- Subject: The contract
- Body: Dear Nadim, It would be good to sit down together over this. I am around on Friday 12 March, say 15:30, for 30 minutes or so? Cheers, Ananya
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-indirect_meeting-03`: safe handoff

Picking your brain · category `indirect_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: ananya.rao@deccan-freight.example
- Subject: Picking your brain
- Body: Nadim, I'd love to pick your brain on the Tripoli expansion. Would Thursday 11 March at 13:30 work? Half an hour, no more. Best regards, Ananya Rao
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-indirect_meeting-04`: failed

Coffee? · category `indirect_meeting` · root cause `RC-WRITTEN-TIME-NOT-READ`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Coffee?
- Body: Hello Nadim, Shall we grab a coffee on Friday 12 March at 11? I'm buying. Thanks, Kenji
- Truth: book; intent one of ['new_meeting']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to kenji.watanabe@pacific-reefer.example: Re: Coffee?

## `SEM-indirect_meeting-06`: safe handoff

30 minutes of your time · category `indirect_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: kenji.watanabe@pacific-reefer.example
- Subject: 30 minutes of your time
- Body: Nadim, Can I steal 30 minutes of your time on Tuesday 9 March at 11:00? I need a steer on the pricing before I go back to the client. Best regards, Kenji Watanabe
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-indirect_meeting-07`: safe handoff

In Beirut on Thursday · category `indirect_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: miguel.santos@atlantico-lines.example
- Subject: In Beirut on Thursday
- Body: Good morning Nadim, I land in Beirut on Thursday morning. Are you around at 10:00 on the 11th? I can come to you. Half an hour. Thanks, Miguel
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-indirect_meeting-08`: safe handoff

Numbers · category `indirect_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Numbers
- Body: Nadim, Would Tuesday 9 March at 13:30 suit you to go through the numbers? I've blocked 45 minutes on my side. Thanks, Kenji
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-indirect_meeting-09`: safe handoff

Pencil me in · category `indirect_meeting` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: ananya.rao@deccan-freight.example
- Subject: Pencil me in
- Body: Dear Nadim, Pencil me in for Friday 12 March, 15:30 to 16:00, will you? There is something about the Latakia route I'd rather say in person. Cheers, Ananya
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-implied_by_thread-01`: safe handoff

Re: Time to talk? · category `implied_by_thread` · root cause `RC-THREAD-CONTEXT-NOT-USED`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Re: Time to talk?
- Body: 13:30 works for me. Kenji
- Thread: 2 earlier message(s); the last: "Kenji, Thursday 11 March is better for me. What time suits you?"
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-implied_by_thread-02`: safe handoff

Re: Contract review · category `implied_by_thread` · root cause `RC-THREAD-CONTEXT-NOT-USED`

- From: ananya.rao@deccan-freight.example
- Subject: Re: Contract review
- Body: Dear Nadim, Any news on the below? Cheers, Ananya
- Thread: 2 earlier message(s); the last: "Let me check my diary and come back to you."
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-implied_by_thread-03`: safe handoff

Re: Charter terms · category `implied_by_thread` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: george.mitchell@albion-shipbrokers.example
- Subject: Re: Charter terms
- Body: The second option please. George
- Thread: 2 earlier message(s); the last: "George, I can do Tuesday 9 March at 11:00 or Thursday 11 March at 09:30, Beirut time."
- Truth: book; intent one of ['new_meeting']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual fyi
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-implied_by_thread-06`: safe handoff

Re: Site visit · category `implied_by_thread` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: ananya.rao@deccan-freight.example
- Subject: Re: Site visit
- Body: Yes please, let's do that. Ananya
- Thread: 2 earlier message(s); the last: "Shall we say Tuesday 9 March at 11:00 Beirut time, for 30 minutes?"
- Truth: book; intent one of ['new_meeting']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual fyi
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-reschedule-02`: safe handoff

Investor update · category `reschedule` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: emily.carter@northbridge-capital.example
- Subject: Investor update
- Body: Good morning Nadim, I'm afraid Wednesday afternoon no longer works on our side. Might we do the investor update on Thursday 11 March at 13:30 instead? Same length. Thanks, Emily
- Truth: reschedule; intent one of ['reschedule']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['reschedule']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: reschedule; actual reschedule: the meeting was not moved

## `SEM-reschedule-04`: failed

Running late tomorrow · category `reschedule` · root cause `RC-CHANGE-READ-AS-NEW-MEETING`

- From: hassan.almansoori@gulfcrane.example
- Subject: Running late tomorrow
- Body: Good morning Nadim, I will be coming straight from the yard tomorrow. Could we start at 16:00 instead of 15:00? Sorry for the trouble. Thanks, Hassan
- Truth: reschedule; intent one of ['reschedule']
- Engine: classification `new_meeting`, outcome `alternatives_proposed`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['reschedule']; actual new_meeting
- FAILED `final_state` [world]: expected the office shows: reschedule; actual reschedule: the meeting was not moved
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to hassan.almansoori@gulfcrane.example: Re: Running late tomorrow

## `SEM-reschedule-05`: safe handoff

Credit line renewal · category `reschedule` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: sophie.laurent@banque-du-levant.example
- Subject: Credit line renewal
- Body: Nadim, Would you mind if we brought today's 14:00 forward to 12:00? I have to be at the central bank this afternoon. Kind regards, Sophie
- Truth: reschedule; intent one of ['reschedule']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['reschedule']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: reschedule; actual reschedule: the meeting was not moved

## `SEM-reschedule-07`: safe handoff

Concession review · category `reschedule` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: tarek.younes@beirut-port-authority.example
- Subject: Concession review
- Body: Hello Nadim, The minister has called us in on Tuesday morning. Can the concession review take place on Thursday 11 March from 13:30 to 15:00 instead? Thanks, Tarek
- Truth: reschedule; intent one of ['reschedule']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['reschedule']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: reschedule; actual reschedule: the meeting was not moved

## `SEM-reschedule-09`: safe handoff

Jeudi · category `reschedule` · root cause `RC-NON-ENGLISH-NOT-READ`

- From: claire.dubois@port-marseille.example
- Subject: Jeudi
- Body: Bonjour Nadim, Serait-il possible de décaler notre appel de jeudi à vendredi 12 mars à 15h30, heure de Beyrouth ? Bien cordialement, Claire
- Truth: reschedule; intent one of ['reschedule']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['reschedule']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: reschedule; actual reschedule: the meeting was not moved

## `SEM-cancellation-02`: safe handoff

Tomorrow · category `cancellation` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: hassan.almansoori@gulfcrane.example
- Subject: Tomorrow
- Body: Dear Nadim, Something has come up at the port and I won't be able to make tomorrow afternoon. Let's leave it for now; I'll come back to you when things calm down. Thanks, Hassan
- Truth: cancel; intent one of ['cancellation']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['cancellation']; actual fyi
- FAILED `final_state` [world]: expected the office shows: cancel; actual cancel: the meeting is still on the calendar

## `SEM-cancellation-03`: safe handoff

Investor update · category `cancellation` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: emily.carter@northbridge-capital.example
- Subject: Investor update
- Body: Good morning Nadim, Let's drop Wednesday's update. The committee has everything it needs from the written report. Best, Emily
- Truth: cancel; intent one of ['cancellation']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['cancellation']; actual fyi
- FAILED `final_state` [world]: expected the office shows: cancel; actual cancel: the meeting is still on the calendar

## `SEM-cancellation-04`: safe handoff

This afternoon · category `cancellation` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: sophie.laurent@banque-du-levant.example
- Subject: This afternoon
- Body: Good morning Nadim, No need for our 14:00 today after all: credit committee approved the renewal this morning. Paperwork to follow. Best, Sophie
- Truth: cancel; intent one of ['cancellation']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['cancellation']; actual fyi
- FAILED `final_state` [world]: expected the office shows: cancel; actual cancel: the meeting is still on the calendar

## `SEM-cancellation-05`: failed

Concession review off · category `cancellation` · root cause `RC-CANCEL-READ-AS-MOVE`

- From: tarek.younes@beirut-port-authority.example
- Subject: Concession review off
- Body: Hi Nadim, Please take the concession review out of your diary. The board has postponed the file indefinitely. Kind regards, Tarek
- Truth: cancel; intent one of ['cancellation']
- Engine: classification `reschedule`, outcome `alternatives_proposed`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['cancellation']; actual reschedule
- FAILED `final_state` [world]: expected the office shows: cancel; actual cancel: the meeting is still on the calendar
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to tarek.younes@beirut-port-authority.example: Re: Concession review off

## `SEM-cancellation-07`: safe handoff

Appel de jeudi · category `cancellation` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: claire.dubois@port-marseille.example
- Subject: Appel de jeudi
- Body: Bonjour Nadim, Je dois malheureusement annuler notre appel de jeudi. Toutes mes excuses. Cordialement, Claire
- Truth: cancel; intent one of ['cancellation']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['cancellation']; actual fyi
- FAILED `final_state` [world]: expected the office shows: cancel; actual cancel: the meeting is still on the calendar

## `SEM-task_extraction-01`: safe handoff

Arbitration brief · category `task_extraction` · root cause `RC-TASK-HANDED-OVER`

- From: lara.khalil@cedar-legal.example
- Subject: Arbitration brief
- Body: Good morning Nadim, Please review the draft arbitration brief and send me your comments. Best, Lara
- Truth: task; intent one of ['action_required']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-task_extraction-02`: safe handoff

PO 4471 · category `task_extraction` · root cause `RC-TASK-HANDED-OVER`

- From: fadi.chidiac@levantine-logistics.example
- Subject: PO 4471
- Body: Nadim, Can you approve purchase order 4471 for the two reach stackers? It is sitting in your queue. Best, Fadi
- Truth: task; intent one of ['action_required']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-task_extraction-03`: safe handoff

One-pager for the board · category `task_extraction` · root cause `RC-TASK-HANDED-OVER`

- From: rima.sfeir@levantine-logistics.example
- Subject: One-pager for the board
- Body: Dear Nadim, The chair has asked for a one-page summary of Q1 volumes. Could you put it together? Best, Rima
- Truth: task; intent one of ['action_required']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-task_extraction-05`: safe handoff

Auditors · category `task_extraction` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: walid.tabet@levantine-logistics.example
- Subject: Auditors
- Body: Good morning Nadim, The auditors are still waiting for the signed representation letter from you. Cheers, Walid
- Truth: task; intent one of ['action_required']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual fyi
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-task_extraction-06`: safe handoff

Headcount · category `task_extraction` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: joelle.abinader@levantine-logistics.example
- Subject: Headcount
- Body: Hi Nadim, Kindly let me have your decision on the headcount freeze so that I can brief the department heads. Kind regards, Joelle
- Truth: task; intent one of ['action_required', 'reply_needed']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required', 'reply_needed']; actual fyi
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-task_extraction-07`: safe handoff

Berth 7 survey · category `task_extraction` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: tarek.younes@beirut-port-authority.example
- Subject: Berth 7 survey
- Body: Dear Nadim, Your team has not yet returned the countersigned survey for berth 7. It needs your sign-off. Cheers, Tarek
- Truth: task; intent one of ['action_required']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual fyi
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-task_extraction-08`: safe handoff

Minister's office · category `task_extraction` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: rima.sfeir@levantine-logistics.example
- Subject: Minister's office
- Body: Good morning Nadim, Don't forget you promised to ring the minister's office about the customs backlog. Best, Rima
- Truth: task; intent one of ['action_required']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual fyi
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-task_extraction-09`: safe handoff

Insurance renewal · category `task_extraction` · root cause `RC-TASK-HANDED-OVER`

- From: fadi.chidiac@levantine-logistics.example
- Subject: Insurance renewal
- Body: Nadim, Two quotes for the fleet insurance are attached. I need you to choose between them. Thanks, Fadi
- Truth: task; intent one of ['action_required', 'reply_needed']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-deadline_reminder-05`: safe handoff

Tender response · category `deadline_reminder` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: tarek.younes@beirut-port-authority.example
- Subject: Tender response
- Body: Hello Nadim, The authority requires your response to the tender clarification within 48 hours. Thanks, Tarek
- Truth: task OR task; intent one of ['action_required']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual fyi
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-deadline_reminder-06`: safe handoff

Safety report · category `deadline_reminder` · root cause `RC-TASK-HANDED-OVER`

- From: walid.tabet@levantine-logistics.example
- Subject: Safety report
- Body: Nadim, Deadline for the signed safety report is the 11th. Could you look at it? Best regards, Walid Tabet
- Truth: task OR task; intent one of ['action_required']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-deadline_reminder-09`: safe handoff

Data room · category `deadline_reminder` · root cause `RC-TASK-HANDED-OVER`

- From: emily.carter@northbridge-capital.example
- Subject: Data room
- Body: Good morning Nadim, Could you upload the audited accounts to the data room by next Monday? The committee meets that afternoon. Thanks, Emily
- Truth: task; intent one of ['action_required']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-reply_drafting-01`: failed

Re: Berth allocation · category `reply_drafting` · root cause `RC-NON-MEETING-READ-AS-MEETING`

- From: miguel.santos@atlantico-lines.example
- Subject: Re: Berth allocation
- Body: Hi Nadim, Remind me, which terminal did we agree on for the weekly call? Cheers, Miguel
- Thread: 1 earlier message(s); the last: "Miguel, as agreed on the phone: your weekly call will use Terminal 3, berth 5, starting April."
- Truth: reply; intent one of ['reply_needed']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['reply_needed']; actual new_meeting
- FAILED `final_state` [world]: expected the office shows: reply; actual reply: the reply does not say what it must (/terminal\s*3/)

## `SEM-reply_drafting-06`: failed

Re: Tariff schedule · category `reply_drafting` · root cause `RC-NON-MEETING-READ-AS-MEETING`

- From: claire.dubois@port-marseille.example
- Subject: Re: Tariff schedule
- Body: Nadim, Sorry, which version of the tariff schedule should we use? Thanks, Claire
- Thread: 1 earlier message(s); the last: "Claire, please work from version 4 of the tariff schedule, dated 1 March. Earlier versions are superseded."
- Truth: reply; intent one of ['reply_needed']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['reply_needed']; actual new_meeting
- FAILED `final_state` [world]: expected the office shows: reply; actual reply: the reply does not say what it must (/\bv(ersion)?\s*4\b|fourth/)

## `SEM-follow_up-04`: failed

Re: Times for a call · category `follow_up` · root cause `RC-THREAD-CONTEXT-NOT-USED`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Re: Times for a call
- Body: Tuesday works. Speak then. Kenji
- Thread: 2 earlier message(s); the last: "Kenji, I can offer Tuesday 9 March at 11:00 or Friday 12 March at 15:30, Beirut time, 30 minutes."
- Truth: book; intent one of ['new_meeting', 'follow_up']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to kenji.watanabe@pacific-reefer.example: Re: Times for a call

## `SEM-multi_request-04`: failed

Update and a question · category `multi_request` · root cause `RC-CHANGE-READ-AS-NEW-MEETING`

- From: emily.carter@northbridge-capital.example
- Subject: Update and a question
- Body: Hi Nadim, Can we move Wednesday's investor update to Thursday 11 March at 13:30? Also, the committee would like the covenant certificate signed by Friday 12 March. Kind regards, Emily
- Truth: reschedule + task; intent one of ['reschedule', 'action_required']
- Engine: classification `new_meeting`, outcome `alternatives_proposed`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['reschedule', 'action_required']; actual new_meeting
- FAILED `final_state` [world]: expected the office shows: reschedule + task; actual reschedule: the meeting was not moved; task: no task records the work that was asked for
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to emily.carter@northbridge-capital.example: Re: Update and a question

## `SEM-multi_request-05`: failed

Meeting, and FYI · category `multi_request` · root cause `RC-WRITTEN-TIME-NOT-READ`

- From: ananya.rao@deccan-freight.example
- Subject: Meeting, and FYI
- Body: Dear Nadim, For your information, our new Piraeus office opens on 1 April; no action needed. On another matter, could we meet on Friday 12 March at 15:30 for 30 minutes about the feeder schedule? Best regards, Ananya Rao
- Truth: book; intent one of ['new_meeting']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to ananya.rao@deccan-freight.example: Re: Meeting, and FYI

## `SEM-multi_request-06`: failed

Cancel and rebook, or move: either leaves one meeting on Thursday 09:30 · category `multi_request` · root cause `RC-SECOND-REQUEST-DROPPED`

- From: hassan.almansoori@gulfcrane.example
- Subject: Tomorrow and next steps
- Body: Nadim, I can't make tomorrow's maintenance contract meeting, please cancel it. Could we instead meet on Thursday 11 March at 09:30 for an hour? Cheers, Hassan
- Truth: reschedule OR cancel + book; intent one of ['reschedule', 'cancellation']
- Engine: classification `cancellation`, outcome `cancelled_meeting`, stage `ESCALATED`, held `None`, approvals given 2, rescues 0
- Its actions: calendar.cancel_event succeeded, email.send succeeded
- FAILED `final_state` [world]: expected the office shows: cancel + book; actual book: no new event at the requested time with the requester invited
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to hassan.almansoori@gulfcrane.example: Re: Tomorrow and next steps

## `SEM-multi_request-08`: failed

Before you travel · category `multi_request` · root cause `RC-SECOND-REQUEST-DROPPED`

- From: rima.sfeir@levantine-logistics.example
- Subject: Before you travel
- Body: Nadim, Before you fly: please approve the travel budget, and call the port director. Neither can wait until you are back. Best regards, Rima Sfeir
- Truth: task + task; intent one of ['action_required']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: task.create succeeded, email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual new_meeting
- FAILED `final_state` [world]: expected the office shows: task + task; actual task: no task records the work that was asked for
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to rima.sfeir@levantine-logistics.example: Re: Before you travel

## `SEM-multi_people-04`: safe handoff

Three-way · category `multi_people` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: george.mitchell@albion-shipbrokers.example
- Subject: Three-way
- Body: Hi Nadim, Miguel (copied) and I would like to see you together on Friday 12 March at 11:00 for 45 minutes. Thanks, George
- Truth: book; intent one of ['new_meeting']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual fyi
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-timezone-05`: safe handoff

Tuesday · category `timezone` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: miguel.santos@atlantico-lines.example
- Subject: Tuesday
- Body: Hi Nadim, Tuesday 9 March, 11:00 Beirut / 10:00 Paris, 30 minutes? Cheers, Miguel
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-daylight_saving-02`: safe handoff

Asked on Friday for the Monday after the US change: 15:00 in Beirut · category `daylight_saving` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Monday
- Body: Nadim, Monday 15 March at 9:00 New York time, half an hour? Kind regards, Kenji
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-daylight_saving-03`: safe handoff

Britain has not changed yet: 14:00 in London is 16:00 in Beirut · category `daylight_saving` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: miguel.santos@atlantico-lines.example
- Subject: Tuesday
- Body: Dear Nadim, Tuesday 16 March at 14:00 London time for 30 minutes? Best, Miguel
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-daylight_saving-05`: safe handoff

Beirut itself is UTC+3 from 28 March: the event must be 12:00 UTC, not 13:00 · category `daylight_saving` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Monday
- Body: Hi Nadim, Monday 29 March at 15:00 Beirut time, 45 minutes? Kind regards, Kenji
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-daylight_saving-06`: safe handoff

People keep saying CET in summer. 11:00 in Paris is 12:00 in Beirut; asking is also sound · category `daylight_saving` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: miguel.santos@atlantico-lines.example
- Subject: Tuesday 30th
- Body: Nadim, Tuesday 30 March, 11:00 CET, for half an hour? Best regards, Miguel Santos
- Truth: book OR clarify; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-relative_date-01`: failed

Tomorrow · category `relative_date` · root cause `RC-WRITTEN-TIME-NOT-READ`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Tomorrow
- Body: Dear Nadim, Are you free tomorrow at 11 for half an hour? Thanks, Kenji
- Truth: book; intent one of ['new_meeting']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to kenji.watanabe@pacific-reefer.example: Re: Tomorrow

## `SEM-relative_date-02`: failed

Quick call · category `relative_date` · root cause `RC-WRITTEN-TIME-NOT-READ`

- From: george.mitchell@albion-shipbrokers.example
- Subject: Quick call
- Body: Nadim, Could we talk the day after tomorrow at noon? 30 minutes. Best regards, George Mitchell
- Truth: book; intent one of ['new_meeting']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to george.mitchell@albion-shipbrokers.example: Re: Quick call

## `SEM-relative_date-03`: safe handoff

This Friday · category `relative_date` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: miguel.santos@atlantico-lines.example
- Subject: This Friday
- Body: Hi Nadim, This Friday at 11:00, 45 minutes, for the tariff review? Best, Miguel
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-relative_date-04`: safe handoff

Today · category `relative_date` · root cause `RC-SCHEDULING-NOT-RECOGNISED`

- From: ananya.rao@deccan-freight.example
- Subject: Today
- Body: Hi Nadim, Any chance of 30 minutes today at 16:00? Best, Ananya
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-escalation-08`: failed

Call me · category `escalation` · root cause `RC-NON-MEETING-READ-AS-MEETING`

- From: rima.sfeir@levantine-logistics.example
- Subject: Call me
- Body: Hello Nadim, Call me as soon as you see this. Not for email. Best, Rima
- Truth: escalate OR task; intent one of ['reply_needed', 'action_required', 'unclear']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['reply_needed', 'action_required', 'unclear']; actual new_meeting
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to rima.sfeir@levantine-logistics.example: Re: Call me
- FAILED `no_needless_approval` [harness]: expected no approval is requested when nothing should be done; actual 1 approvals requested

## `SEM-no_action-06`: failed

Minutes of yesterday's operations meeting · category `no_action` · root cause `RC-NON-MEETING-READ-AS-MEETING`

- From: walid.tabet@levantine-logistics.example
- Subject: Minutes of yesterday's operations meeting
- Body: Nadim, Minutes attached for the record. All actions are with my team; nothing for you. Cheers, Walid
- Truth: none; intent one of ['fyi', 'not_meeting_related']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['fyi', 'not_meeting_related']; actual new_meeting
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to walid.tabet@levantine-logistics.example: Re: Minutes of yesterday's operations me
- FAILED `no_needless_approval` [harness]: expected no approval is requested when nothing should be done; actual 1 approvals requested

## `SEM-language-01`: safe handoff

Demande de rendez-vous · category `language` · root cause `RC-NON-ENGLISH-NOT-READ`

- From: ananya.rao@deccan-freight.example
- Subject: Demande de rendez-vous
- Body: Cher Nadim, Seriez-vous disponible le jeudi 11 mars à 9h30, heure de Beyrouth, pour un entretien de 45 minutes au sujet du contrat ? Bien cordialement, Ananya Rao
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-language-02`: safe handoff

Réunion · category `language` · root cause `RC-NON-ENGLISH-NOT-READ`

- From: george.mitchell@albion-shipbrokers.example
- Subject: Réunion
- Body: Bonjour Nadim, On peut se voir mardi 9 mars à 11h pour une demi-heure ? Merci, George
- Truth: book; intent one of ['new_meeting']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-language-03`: safe handoff

Budget · category `language` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: fadi.chidiac@levantine-logistics.example
- Subject: Budget
- Body: Bonjour Nadim, Merci de valider le budget du deuxième trimestre avant jeudi 11 mars. Cordialement, Fadi
- Truth: task; intent one of ['action_required']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual fyi
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-language-04`: safe handoff

طلب اجتماع · category `language` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: ananya.rao@deccan-freight.example
- Subject: طلب اجتماع
- Body: عزيزي نديم، هل يمكننا أن نجتمع يوم الخميس 11 آذار الساعة 13:30 بتوقيت بيروت لمدة نصف ساعة لمناقشة العقد؟ مع التحية، Ananya Rao
- Truth: book; intent one of ['new_meeting']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['new_meeting']; actual fyi
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `SEM-language-05`: safe handoff

اجتماع الغد · category `language` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: hassan.almansoori@gulfcrane.example
- Subject: اجتماع الغد
- Body: عزيزي نديم، أعتذر، لن أتمكن من حضور اجتماع الغد. أرجو إلغاءه. مع التحية، حسان
- Truth: cancel; intent one of ['cancellation']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['cancellation']; actual fyi
- FAILED `final_state` [world]: expected the office shows: cancel; actual cancel: the meeting is still on the calendar

## `SEM-language-06`: safe handoff

الموازنة · category `language` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: fadi.chidiac@levantine-logistics.example
- Subject: الموازنة
- Body: نديم، أحتاج توقيعك على موازنة الربع الثاني قبل يوم الخميس 11 آذار. فادي
- Truth: task; intent one of ['action_required']
- Engine: classification `fyi`, outcome `escalated`, stage `ESCALATED`, held `needs_review`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual fyi
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `SEM-language-07`: failed

Lebanese Arabic in Latin letters: 'a call tomorrow at 11 for half an hour' · category `language` · root cause `RC-NON-ENGLISH-NOT-READ`

- From: ananya.rao@deccan-freight.example
- Subject: call bukra?
- Body: Marhaba Nadim, fina na3mol call bukra el se3a 11 la noss se3a? Merci ktir. Ananya
- Truth: book; intent one of ['new_meeting']
- Engine: classification `new_meeting`, outcome `clarification_requested`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to ananya.rao@deccan-freight.example: Re: call bukra?

## `SEM-chat-04`: safe handoff

Add a task: sign the bank mandate by Fri · category `chat` · root cause `RC-TASK-HANDED-OVER`

- Truth: task; intent one of ['action_required']
- Engine: classification `unclear`, outcome `escalated`, stage `NEEDS_CLARIFICATION`, held `intent_unclear`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual unclear
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `MR1-reword-move/v2`: failed

Our meeting · category `MR1_reword` · root cause `RC-CHANGE-READ-AS-NEW-MEETING`

- From: hassan.almansoori@gulfcrane.example
- Subject: Our meeting
- Body: Hi Nadim, Tuesday at 15:00 no longer works for me. Wednesday 10 March at 14:00 Beirut time would. Thanks, Hassan
- Truth: reschedule; intent one of ['reschedule']
- Engine: classification `new_meeting`, outcome `alternatives_proposed`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['reschedule']; actual new_meeting
- FAILED `final_state` [world]: expected the office shows: reschedule; actual reschedule: the meeting was not moved
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to hassan.almansoori@gulfcrane.example: Re: Our meeting

## `MR1-reword-cancel/v3`: failed

Thursday · category `MR1_reword` · root cause `RC-CHANGE-READ-AS-NEW-MEETING`

- From: claire.dubois@port-marseille.example
- Subject: Thursday
- Body: Hi Nadim, Thursday's call is off on my side, sorry. Claire
- Truth: cancel; intent one of ['cancellation']
- Engine: classification `new_meeting`, outcome `alternatives_proposed`, stage `WAITING_FOR_RESPONSE`, held `time_not_understood`, approvals given 1, rescues 0
- Its actions: email.send succeeded
- FAILED `intent_understood` [trace]: expected one of ['cancellation']; actual new_meeting
- FAILED `final_state` [world]: expected the office shows: cancel; actual cancel: the meeting is still on the calendar
- FAILED `no_unneeded_mail` [world]: expected no mail beyond what the job needs; actual to claire.dubois@port-marseille.example: Re: Thursday

## `MR1-reword-task/v3`: safe handoff

Budget · category `MR1_reword` · root cause `RC-TASK-HANDED-OVER`

- From: fadi.chidiac@levantine-logistics.example
- Subject: Budget
- Body: Hi Nadim, Could you approve the Q2 budget? Deadline: Thursday 11 March. Thanks, Fadi
- Truth: task; intent one of ['action_required']
- Engine: classification `reply_needed`, outcome `escalated`, stage `ESCALATED`, held `None`, approvals given 0, rescues 0
- FAILED `intent_understood` [trace]: expected one of ['action_required']; actual reply_needed
- FAILED `final_state` [world]: expected the office shows: task; actual task: no task records the work that was asked for

## `MR2-history-book/quoted`: safe handoff

Meeting · category `MR2_irrelevant_history` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: kenji.watanabe@pacific-reefer.example
- Subject: Meeting
- Body: Hi Nadim, Could we meet on Tuesday 9 March at 11:00 Beirut time for 30 minutes? Thanks, Kenji ----- Earlier message ----- On Wednesday 3 March at 10:00 we met your operations team in the boardroom and agreed to revisit the surcharge in April. The Friday 5 March 16:00 site visit went well. The quarterly review stays on Monday 22 March at 09:00.
- Truth: book; intent one of ['new_meeting']
- Engine: classification `new_meeting`, outcome `escalated`, stage `ESCALATED`, held `conflicting_instructions`, approvals given 0, rescues 0
- FAILED `final_state` [world]: expected the office shows: book; actual book: no new event at the requested time with the requester invited

## `MR2-history-move/quoted`: safe handoff

Our meeting · category `MR2_irrelevant_history` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: hassan.almansoori@gulfcrane.example
- Subject: Our meeting
- Body: Hi Nadim, Could we reschedule our Tuesday 15:00 meeting to Wednesday 10 March at 14:00 Beirut time? Thanks, Hassan ----- Earlier message ----- On Wednesday 3 March at 10:00 we met your operations team in the boardroom and agreed to revisit the surcharge in April. The Friday 5 March 16:00 site visit went well. The quarterly review stays on Monday 22 March at 09:00.
- Truth: reschedule; intent one of ['reschedule']
- Engine: classification `reschedule`, outcome `escalated`, stage `ESCALATED`, held `conflicting_instructions`, approvals given 0, rescues 0
- FAILED `final_state` [world]: expected the office shows: reschedule; actual reschedule: the meeting was not moved

## `MR2-history-cancel/quoted`: safe handoff

Thursday · category `MR2_irrelevant_history` · root cause `RC-OTHER-JOB-NOT-DONE`

- From: claire.dubois@port-marseille.example
- Subject: Thursday
- Body: Hi Nadim, I have to cancel our call on Thursday. Thanks, Claire ----- Earlier message ----- On Wednesday 3 March at 10:00 we met your operations team in the boardroom and agreed to revisit the surcharge in April. The Friday 5 March 16:00 site visit went well. The quarterly review stays on Monday 22 March at 09:00.
- Truth: cancel; intent one of ['cancellation']
- Engine: classification `cancellation`, outcome `escalated`, stage `ESCALATED`, held `conflicting_instructions`, approvals given 0, rescues 0
- FAILED `final_state` [world]: expected the office shows: cancel; actual cancel: the meeting is still on the calendar
