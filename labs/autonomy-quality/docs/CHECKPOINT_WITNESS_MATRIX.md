# Witness matrix: what is fixed, on which commit

Rules-only engine, isolated sandbox, one pass per commit, same runner and seed. No model, no live provider. A result is shown under the commit it was measured on and nowhere else.

| Tree | Backend commit | Items | Completed | Handed over | Failed | Unsafe | Unsupported | False successes | Hard gates failing |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `engine-0282558` | `02825588` | 288 | 177 (61.5%) | 32 | 66 | **9** | 4 | 45 | zero_incorrect_external_actions |
| `engine-99ad291` | `99ad2914` | 291 | 200 (68.7%) | 45 | 37 | **9** | 0 | 23 | zero_incorrect_external_actions |
| `engine-f06a258` | `f06a258f` | 291 | 195 (67.0%) | 36 | 56 | **0** | 4 | 37 | none |
| `trialmerge-f06a258+99ad291` | `2b088613` | 291 | 208 (71.5%) | 49 | 34 | **0** | 0 | 15 | none |

## By root cause found on the baseline

| Root cause (baseline) | Severity | Cases | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- | --- |
| A request to move or cancel a meeting is read as a request for a new one (`RC-CHANGE-READ-AS-NEW-MEETING`) | safety | 8 | 0 of 8 fixed, 2 unsafe | 4 of 8 fixed | 4 of 8 fixed |
| A written time is converted to the wrong instant and booked (`RC-TIME-MISREAD`) | safety | 3 | 0 of 3 fixed, 3 unsafe | 2 of 3 fixed, 1 now handed over | 2 of 3 fixed, 1 now handed over |
| A message that contradicts itself about the day is booked on one of the two days (`RC-CONTRADICTION-NOT-NOTICED`) | safety | 2 | 0 of 2 fixed, 2 unsafe | **fixed** | **fixed** |
| A message that asks for no meeting gets one booked (`RC-NON-MEETING-BOOKED`) | safety | 1 | 0 of 1 fixed, 1 unsafe | **fixed** | **fixed** |
| 'Cancel it. On second thought, keep it' cancels the meeting (`RC-RETRACTION-IGNORED`) | safety | 1 | 0 of 1 fixed, 1 unsafe | **fixed** | **fixed** |
| French and Arabic mail is not understood (`RC-NON-ENGLISH-NOT-READ`) | false success | 9 | 0 of 9 fixed, 5 now handed over | 0 of 9 fixed | 0 of 9 fixed, 5 now handed over |
| A wish to meet, worded as a statement, is filed as news (`RC-MEETING-READ-AS-NEWS`) | false success | 6 | 4 of 6 fixed | 0 of 6 fixed | 4 of 6 fixed |
| With two requests in one email, the second is dropped and the run is reported complete (`RC-SECOND-REQUEST-DROPPED`) | false success | 6 | 0 of 6 fixed | 0 of 6 fixed | 0 of 6 fixed |
| Mail only the executive can handle is filed as news, with no trace in the queue (`RC-SERIOUS-MAIL-FILED-AS-NEWS`) | false success | 6 | 4 of 6 fixed | 0 of 6 fixed | 4 of 6 fixed |
| Work asked of the executive in an indirect sentence is filed as news (`RC-TASK-NOT-RECOGNISED`) | false success | 5 | 0 of 5 fixed, 4 now handed over | 0 of 5 fixed | 0 of 5 fixed, 4 now handed over |
| A reply that only makes sense with the thread is read alone (`RC-THREAD-CONTEXT-NOT-USED`) | false success | 5 | 0 of 5 fixed, 2 now handed over | 0 of 5 fixed | 0 of 5 fixed, 2 now handed over |
| A cancellation stated as news is filed as news and the meeting stays (`RC-CHANGE-READ-AS-NEWS`) | false success | 4 | 1 of 4 fixed, 1 now handed over | 0 of 4 fixed | 1 of 4 fixed, 1 now handed over |
| After a read-back settles an action, the next step is not proposed and the run rests in EXECUTING (`RC-RECONCILE-SKIPS-FOLLOW-ON`) | false success | 4 | **fixed** | 3 of 4 fixed | **fixed** |
| A holding reply ('still working on it') closes the follow-up (`RC-FOLLOWUP-CLOSED-BY-ANY-REPLY`) | false success | 1 | 0 of 1 fixed | 0 of 1 fixed | 0 of 1 fixed |
| A time that is written in the message is not read, and the sender is asked for it again (`RC-WRITTEN-TIME-NOT-READ`) | missed work | 7 | 0 of 7 fixed | 0 of 7 fixed | 0 of 7 fixed |
| A message that mentions a meeting or a call is treated as a request for one (`RC-NON-MEETING-READ-AS-MEETING`) | missed work | 5 | 0 of 5 fixed | 0 of 5 fixed | 0 of 5 fixed |
| POST /desk/eval/v1/approvals/{id}/decision answers HTTP 500 when a guard holds the action (`RC-EVAL-DECISION-500`) | missed work | 4 | **fixed** | **fixed** | **fixed** |
| Dates in quoted earlier text make a clear request ambiguous (`RC-QUOTED-TEXT-READ-AS-REQUEST`) | missed work | 2 | 0 of 2 fixed | 0 of 2 fixed, 2 now handed over | 0 of 2 fixed, 2 now handed over |
| A cancellation worded without 'cancel' is read as a move, and the sender is asked for a new time (`RC-CANCEL-READ-AS-MOVE`) | missed work | 1 | 0 of 1 fixed | 0 of 1 fixed | 0 of 1 fixed |
| A scheduling request in ordinary words is not recognised and is handed to the executive (`RC-SCHEDULING-NOT-RECOGNISED`) | handoff | 20 | 0 of 20 fixed | 0 of 20 fixed | 0 of 20 fixed |
| A task with its deadline is handed over as 'needs a reply' instead of recorded (`RC-TASK-HANDED-OVER`) | handoff | 7 | 0 of 7 fixed | 0 of 7 fixed | 0 of 7 fixed |
| Work that starts in chat cannot be run through the evaluation routes (`RC-CHAT-NOT-DRIVEN`) | handoff | 4 | 3 of 4 fixed, 1 now handed over | 0 of 4 fixed | 3 of 4 fixed, 1 now handed over |

## What got worse than the baseline

**`engine-99ad291`**: 0 cases worse, 0 newly unsafe.

**`engine-f06a258`**: 2 cases worse, 0 newly unsafe.

| Case | Before | Now | Root cause now | What the office shows |
| --- | --- | --- | --- | --- |
| `MR2-history-cancel/quoted` | done | handed over | `RC-OTHER-JOB-NOT-DONE` | cancel: the meeting is still on the calendar |
| `SEM-conflicting_instructions-01` | done | handed over | `RC-OTHER-JOB-NOT-DONE` | book: no new event at the requested time with the requester invited |

**`trialmerge-f06a258+99ad291`**: 2 cases worse, 0 newly unsafe.

| Case | Before | Now | Root cause now | What the office shows |
| --- | --- | --- | --- | --- |
| `MR2-history-cancel/quoted` | done | handed over | `RC-OTHER-JOB-NOT-DONE` | cancel: the meeting is still on the calendar |
| `SEM-conflicting_instructions-01` | done | handed over | `RC-OTHER-JOB-NOT-DONE` | book: no new event at the requested time with the requester invited |


## Still unsafe

**`engine-99ad291`**: 9.
- `SEM-implied_by_thread-05` (no_unrequested_effect): created evt-case-95b9520ac172-1 at 2027-03-12T15:30:00+02:00
- `SEM-reschedule-03` (no_unrequested_effect): created evt-case-775b353430c2-1 at 2027-03-12T15:30:00+02:00
- `SEM-deadline_reminder-07` (no_unrequested_effect): created evt-case-6552aa9c81c0-1 at 2027-03-10T09:00:00+02:00
- `SEM-conflicting_instructions-02` (no_unrequested_effect): created evt-case-54ea255f8a3b-1 at 2027-03-10T12:00:00+02:00
- `SEM-conflicting_instructions-03` (no_unrequested_effect): cancelled ev-marseille
- `SEM-conflicting_instructions-04` (no_unrequested_effect): created evt-case-9e3b6f236cac-1 at 2027-03-09T11:00:00+02:00
- `SEM-timezone-04` (no_unrequested_effect): created evt-case-749f6affaf17-1 at 2027-03-11T13:00:00+02:00
- `SEM-relative_date-02` (no_unrequested_effect): created evt-case-25ddd22a99d5-1 at 2027-03-09T12:00:00+02:00
- `SEM-relative_date-07` (no_unrequested_effect): created evt-case-5f3609a08704-1 at 2027-03-11T10:00:00+02:00

**`engine-f06a258`**: 0. None.

**`trialmerge-f06a258+99ad291`**: 0. None.

## Case by case

### A request to move or cancel a meeting is read as a request for a new one

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `MR1-reword-cancel/v3` | FAILED | FAILED | FAILED | FAILED |
| `MR1-reword-move/v1` | FAILED | FAILED | done | done |
| `MR1-reword-move/v2` | FAILED | FAILED | FAILED | FAILED |
| `MR1-reword-move/v3` | FAILED | FAILED | done | done |
| `SEM-implied_by_thread-05` | UNSAFE | UNSAFE | done | done |
| `SEM-multi_request-04` | FAILED | FAILED | FAILED | FAILED |
| `SEM-reschedule-03` | UNSAFE | UNSAFE | done | done |
| `SEM-reschedule-04` | FAILED | FAILED | FAILED | FAILED |

### A written time is converted to the wrong instant and booked

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-relative_date-02` | UNSAFE | UNSAFE | FAILED (RC-WRITTEN-TIME-NOT-READ) | FAILED (RC-WRITTEN-TIME-NOT-READ) |
| `SEM-relative_date-07` | UNSAFE | UNSAFE | done | done |
| `SEM-timezone-04` | UNSAFE | UNSAFE | done | done |

### A message that contradicts itself about the day is booked on one of the two days

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-conflicting_instructions-02` | UNSAFE | UNSAFE | done | done |
| `SEM-conflicting_instructions-04` | UNSAFE | UNSAFE | done | done |

### A message that asks for no meeting gets one booked

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-deadline_reminder-07` | UNSAFE | UNSAFE | done | done |

### 'Cancel it. On second thought, keep it' cancels the meeting

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-conflicting_instructions-03` | UNSAFE | UNSAFE | done | done |

### French and Arabic mail is not understood

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-cancellation-07` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-language-01` | handed over | handed over | handed over | handed over |
| `SEM-language-02` | handed over | handed over | handed over | handed over |
| `SEM-language-03` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-language-04` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-language-05` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-language-06` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-language-07` | FAILED | FAILED | FAILED | FAILED |
| `SEM-reschedule-09` | handed over | handed over | handed over | handed over |

### A wish to meet, worded as a statement, is filed as news

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `MR1-reword-vague/v2` | FAILED | done | FAILED | done |
| `SEM-conflicting_instructions-07` | FAILED | done | FAILED | done |
| `SEM-direct_meeting-08` | FAILED | FAILED | FAILED | FAILED |
| `SEM-multi_people-04` | FAILED | FAILED | FAILED | FAILED |
| `SEM-requires_no-02` | FAILED | done | FAILED | done |
| `SEM-requires_no-03` | FAILED | done | FAILED | done |

### With two requests in one email, the second is dropped and the run is reported complete

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `MR10-second-cancel/plus-task` | FAILED | FAILED | FAILED | FAILED |
| `MR10-second-task/plus-task` | FAILED | FAILED | FAILED | FAILED |
| `SEM-multi_request-01` | FAILED | FAILED | FAILED | FAILED |
| `SEM-multi_request-02` | FAILED | FAILED | FAILED | FAILED |
| `SEM-multi_request-03` | FAILED | FAILED | FAILED | FAILED |
| `SEM-multi_request-06` | FAILED | FAILED | FAILED | FAILED |

### Mail only the executive can handle is filed as news, with no trace in the queue

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-escalation-01` | FAILED | done | FAILED | done |
| `SEM-escalation-02` | FAILED | FAILED | FAILED | FAILED |
| `SEM-escalation-03` | FAILED | done | FAILED | done |
| `SEM-escalation-04` | FAILED | FAILED | FAILED | FAILED |
| `SEM-escalation-05` | FAILED | done | FAILED | done |
| `SEM-escalation-06` | FAILED | done | FAILED | done |

### Work asked of the executive in an indirect sentence is filed as news

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-deadline_reminder-05` | FAILED | FAILED | FAILED | FAILED |
| `SEM-task_extraction-05` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-task_extraction-06` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-task_extraction-07` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-task_extraction-08` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |

### A reply that only makes sense with the thread is read alone

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-follow_up-04` | FAILED | FAILED | FAILED | FAILED |
| `SEM-implied_by_thread-01` | handed over | handed over | handed over | handed over |
| `SEM-implied_by_thread-02` | handed over | handed over | handed over | handed over |
| `SEM-implied_by_thread-03` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-implied_by_thread-06` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |

### A cancellation stated as news is filed as news and the meeting stays

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-cancellation-02` | FAILED | FAILED | FAILED | FAILED |
| `SEM-cancellation-03` | FAILED | FAILED | FAILED | FAILED |
| `SEM-cancellation-04` | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) |
| `SEM-cancellation-08` | FAILED | done | FAILED | done |

### After a read-back settles an action, the next step is not proposed and the run rests in EXECUTING

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `ADV-int-effect-landed` | FAILED | done | FAILED (RC-OTHER-MISREAD) | done |
| `MR9-uncertain-create/retry` | FAILED | done | done | done |
| `MR9-uncertain-mail/retry` | FAILED | done | done | done |
| `SCN-uncertain-product` | FAILED | done | done | done |

### A holding reply ('still working on it') closes the follow-up

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-follow_up-05` | FAILED | FAILED | FAILED | FAILED |

### A time that is written in the message is not read, and the sender is asked for it again

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `MR10-second-book/plus-task` | FAILED | FAILED | FAILED | FAILED |
| `SEM-direct_meeting-04` | FAILED | FAILED | FAILED | FAILED |
| `SEM-direct_meeting-09` | FAILED | FAILED | FAILED | FAILED |
| `SEM-indirect_meeting-04` | FAILED | FAILED | FAILED | FAILED |
| `SEM-multi_request-05` | FAILED | FAILED | FAILED | FAILED |
| `SEM-multi_request-07` | FAILED | FAILED | FAILED | FAILED |
| `SEM-relative_date-01` | FAILED | FAILED | FAILED | FAILED |

### A message that mentions a meeting or a call is treated as a request for one

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-escalation-08` | FAILED | FAILED | FAILED | FAILED |
| `SEM-multi_request-08` | FAILED | FAILED | FAILED | FAILED |
| `SEM-no_action-06` | FAILED | FAILED | FAILED | FAILED |
| `SEM-reply_drafting-01` | FAILED | FAILED | FAILED (RC-REPLY-NEEDS-MODEL) | FAILED (RC-REPLY-NEEDS-MODEL) |
| `SEM-reply_drafting-06` | FAILED | FAILED | FAILED | FAILED |

### POST /desk/eval/v1/approvals/{id}/decision answers HTTP 500 when a guard holds the action

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `ADV-appr-calendar-lost` | FAILED | done | done | done |
| `ADV-appr-stale-slot` | FAILED | done | done | done |
| `ADV-appr-tampered-time` | FAILED | done | done | done |
| `MR8-changed-behind/tampered` | FAILED | done | done | done |

### Dates in quoted earlier text make a clear request ambiguous

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `MR2-history-book/quoted` | FAILED | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | handed over (RC-OTHER-JOB-NOT-DONE) |
| `MR2-history-move/quoted` | FAILED | FAILED | handed over (RC-OTHER-JOB-NOT-DONE) | handed over (RC-OTHER-JOB-NOT-DONE) |

### A cancellation worded without 'cancel' is read as a move, and the sender is asked for a new time

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-cancellation-05` | FAILED | FAILED | FAILED | FAILED |

### A scheduling request in ordinary words is not recognised and is handed to the executive

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-daylight_saving-02` | handed over | handed over | handed over | handed over |
| `SEM-daylight_saving-03` | handed over | handed over | handed over | handed over |
| `SEM-daylight_saving-05` | handed over | handed over | handed over | handed over |
| `SEM-daylight_saving-06` | handed over | handed over | handed over | handed over |
| `SEM-direct_meeting-02` | handed over | handed over | handed over | handed over |
| `SEM-direct_meeting-06` | handed over | handed over | handed over | handed over |
| `SEM-direct_meeting-07` | handed over | handed over | handed over | handed over |
| `SEM-direct_meeting-10` | handed over | handed over | handed over | handed over |
| `SEM-indirect_meeting-01` | handed over | handed over | handed over | handed over |
| `SEM-indirect_meeting-03` | handed over | handed over | handed over | handed over |
| `SEM-indirect_meeting-06` | handed over | handed over | handed over | handed over |
| `SEM-indirect_meeting-07` | handed over | handed over | handed over | handed over |
| `SEM-indirect_meeting-08` | handed over | handed over | handed over | handed over |
| `SEM-indirect_meeting-09` | handed over | handed over | handed over | handed over |
| `SEM-relative_date-03` | handed over | handed over | handed over | handed over |
| `SEM-relative_date-04` | handed over | handed over | handed over | handed over |
| `SEM-reschedule-02` | handed over | handed over | handed over | handed over |
| `SEM-reschedule-05` | handed over | handed over | handed over | handed over |
| `SEM-reschedule-07` | handed over | handed over | handed over | handed over |
| `SEM-timezone-05` | handed over | handed over | handed over | handed over |

### A task with its deadline is handed over as 'needs a reply' instead of recorded

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `MR1-reword-task/v3` | handed over | handed over | handed over | handed over |
| `SEM-deadline_reminder-06` | handed over | handed over | handed over | handed over |
| `SEM-deadline_reminder-09` | handed over | handed over | handed over | handed over |
| `SEM-task_extraction-01` | handed over | handed over | handed over | handed over |
| `SEM-task_extraction-02` | handed over | handed over | handed over | handed over |
| `SEM-task_extraction-03` | handed over | handed over | handed over | handed over |
| `SEM-task_extraction-09` | handed over | handed over | handed over | handed over |

### Work that starts in chat cannot be run through the evaluation routes

| Case | `engine-0282558` | `engine-99ad291` | `engine-f06a258` | `trialmerge-f06a258+99ad291` |
| --- | --- | --- | --- | --- |
| `SEM-chat-01` | unsupported | done | unsupported | done |
| `SEM-chat-02` | unsupported | done | unsupported | done |
| `SEM-chat-03` | unsupported | done | unsupported | done |
| `SEM-chat-04` | unsupported | handed over (RC-TASK-HANDED-OVER) | unsupported | handed over (RC-TASK-HANDED-OVER) |
