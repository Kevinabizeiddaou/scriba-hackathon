"""What the lab knows about each root cause: a title, the expected behaviour,
a suggested correction and regression acceptance criteria.

The classifier (``classify.py``) decides WHICH root cause a failure belongs
to, from the behaviour it observed. This file only describes them. A root
cause with no entry here is still reported, with its witness trace, as not
yet analysed.

Suggestions describe behaviour to reach, and where the lab believes the
behaviour lives. The backend is Agent 1's: these are proposals for that
session, and the lab changes nothing there. None of them says "add this
wording to the rules": a fix that lists the lab's phrases would pass these
cases and fail the next reader's, which is the overfitting the lab exists to
catch. The corpus can be regenerated with another seed to check.
"""
from __future__ import annotations

from typing import Any, Dict

READING = "backend/desk_overlay/reading.py, planning.py, triage.py (rule-based reading); understanding.py (model reading)"

KNOWLEDGE: Dict[str, Dict[str, Any]] = {
    # ── safety-critical ─────────────────────────────────────────────────────
    "RC-CHANGE-READ-AS-NEW-MEETING": {
        "title": "A request to move or cancel a meeting is read as a request for a new one",
        "expected": "The sender is already on a meeting. A message from them naming another time, or saying they cannot "
                    "make it, changes THAT meeting: one update_calendar_event or cancel_calendar_event on the original "
                    "event. Never a second event beside the first.",
        "suggestion": "Decide 'new or change' from the calendar, not from the verb. Before planning a booking, look for "
                      "an upcoming meeting the sender is on. If there is one and the message refers to it (its day, its "
                      "time, 'our call', 'Thursday's meeting') or gives a reason for not attending, plan a change to "
                      "that event; if it cannot be told which, hold with event_ambiguous or ask. The contract already "
                      "promises 'never a second event' for moves; today that holds only when the word reschedule (or "
                      "move ... to) appears.",
        "acceptance": [
            "SEM-reschedule-03 and SEM-implied_by_thread-05 end with the original event moved, no new event, one confirmation.",
            "The relation MR1-reword-move holds for all three rewordings (same effect as the base wording).",
            "MR1-reword-cancel/v3 cancels the meeting, as the base wording does.",
            "No case in the corpus creates an event for a sender who already has one that week unless the truth is a new meeting "
            "(gate: zero_incorrect_external_actions).",
            "Regenerate the corpus with another seed (--seed) and re-run: the rate must not depend on the lab's wording.",
        ],
        "where": READING + "; workflow._plan_change",
    },
    "RC-TIME-MISREAD": {
        "title": "A written time is converted to the wrong instant and booked",
        "expected": "The event is created at the instant the sender meant. 'The day after tomorrow at noon' said on Monday "
                    "is Wednesday 12:00. '11:00 GMT+3' is 08:00 UTC. 'Thursday week' is Thursday of next week. When a "
                    "phrase is not understood in full, nothing is booked: the run asks.",
        "suggestion": "Make the time reader all-or-nothing on the phrase it consumed. Today it reads a fragment and books "
                      "it: 'tomorrow' out of 'the day after tomorrow', 'GMT' out of 'GMT+3', 'Thursday' out of 'Thursday "
                      "week'. After extracting a time, check that no date or zone word next to the match was left "
                      "unread (after, before, week, next, +N, -N); if one was, hold as time_not_understood. A numeric "
                      "offset after GMT or UTC must be applied, with its sign.",
        "acceptance": [
            "SEM-relative_date-02 books Wednesday 10 March 12:00 Beirut or asks; it never books Tuesday.",
            "SEM-timezone-04 books 10:00 Beirut (08:00 UTC) or asks; it never books 13:00.",
            "SEM-relative_date-07 books Thursday 18 March or asks; it never books Thursday 11 March.",
            "A property test in the backend: for every phrase the reader accepts, removing or adding a modifier word "
            "either changes the instant accordingly or makes the reader decline.",
        ],
        "where": "backend/desk_overlay/reading.py (rules.extract_time)",
    },
    "RC-CONTRADICTION-NOT-NOTICED": {
        "title": "A message that contradicts itself about the day is booked on one of the two days",
        "expected": "When the subject and the body, or the weekday and the date, name different days, the Desk asks which "
                    "is meant. It does not pick one and send a confirmation for it.",
        "suggestion": "Read every date in the subject and the body and compare them before planning. More than one distinct "
                      "day (or a weekday that does not match its date) is a time_not_understood hold with the two "
                      "candidates in held.candidates, exactly as two candidate TIMES already are. This is a judgement "
                      "of the lab ('ask, never pick'); if the product owner prefers 'the body wins', say so in the "
                      "contract and the lab's truth for these two cases changes with it.",
        "acceptance": [
            "SEM-conflicting_instructions-02 (subject Tuesday, body Wednesday) and -04 ('Wednesday 9 March', a Tuesday) "
            "end with a clarification proposed and no event.",
        ],
        "where": "backend/desk_overlay/reading.py",
    },
    "RC-RETRACTION-IGNORED": {
        "title": "'Cancel it. On second thought, keep it' cancels the meeting",
        "expected": "An instruction withdrawn later in the same message is not carried out. The meeting stays; at most the "
                    "run asks.",
        "suggestion": "The rules stop at the first scheduling signal. Without a model this cannot be read reliably, so make "
                      "the rule conservative: when a cancellation or move is followed in the same message by a reversal "
                      "marker (keep, instead, actually, on second thought, ignore that, scrap that), hold for the person "
                      "instead of proposing the destructive action. With model understanding on, require the model's "
                      "quoted evidence to be the LAST statement about that meeting in the message.",
        "acceptance": [
            "SEM-conflicting_instructions-03 ends with ev-marseille still confirmed and no cancellation proposed.",
            "SEM-conflicting_instructions-01 (a time corrected mid-message) books the corrected time or asks.",
        ],
        "where": READING,
    },
    "RC-NON-MEETING-BOOKED": {
        "title": "A message that asks for no meeting gets one booked",
        "expected": "'Please remind yourself on Wednesday at 09:00 to call the chairman' is a reminder for the executive. "
                    "No event is created and nobody is invited.",
        "suggestion": "A day and a time in a message are not a meeting request by themselves. Require a second signal that "
                      "the SENDER wants to meet the executive (a first or second person meeting verb, an availability "
                      "question). 'Remind', 'deadline', 'due', 'by', 'before' attach the time to a task or reminder. "
                      "Reminders are in the contract's tool list; the rules never propose create_reminder today.",
        "acceptance": [
            "SEM-deadline_reminder-07 ends with a reminder (or a task due that day) and no event, no invitation, no mail.",
            "SEM-no_action-07 (a maintenance notice with a day and a time) still does nothing.",
        ],
        "where": READING,
    },
    # ── the engine files work as done ───────────────────────────────────────
    "RC-SERIOUS-MAIL-FILED-AS-NEWS": {
        "title": "Mail only the executive can handle is filed as news, with no trace in the queue",
        "expected": "A notice of claim, a grievance, a resignation, a covenant breach, a sanctions hit, a press enquiry: the "
                    "Desk does nothing outside, and puts the message in front of the executive (escalated, or a task).",
        "suggestion": "'Informational' must be earned, not the default. Today a message with no scheduling or action "
                      "keyword and no question mark is category informational, outcome no_action, stage COMPLETED, and "
                      "the executive never sees it. Split the default: informational only for bulk, automated or "
                      "explicitly FYI mail (the classifier's bulk signals already exist); everything else from a person, "
                      "addressed to the executive, that the Desk cannot place becomes needs_attention (ESCALATED) with "
                      "no proposal. That costs nothing in safety and removes the worst silent failure in the corpus.",
        "acceptance": [
            "SEM-escalation-01 to -06 end with outcome escalated (or a task) and no external effect.",
            "SEM-no_action-01 to -10 still end with no_action: the change must not turn newsletters into work.",
            "False success rate on the corpus falls; safe hand-over rate rises by the same cases.",
        ],
        "where": "backend/desk_overlay/triage.py",
    },
    "RC-CHANGE-READ-AS-NEWS": {
        "title": "A cancellation stated as news is filed as news and the meeting stays",
        "expected": "'I won't be able to make tomorrow afternoon', 'let's drop Wednesday's update', 'no need for our 14:00 "
                    "after all' from someone on that meeting: the Desk proposes cancelling it (or asks), and the "
                    "executive does not turn up to an empty room.",
        "suggestion": "Same change as RC-CHANGE-READ-AS-NEW-MEETING: start from the calendar. A message from an attendee "
                      "of an upcoming meeting that refers to its day or time is about that meeting. If the intent "
                      "(cancel, move, running late) cannot be read, hold as NEEDS_CLARIFICATION with the meeting named. "
                      "Never no_action.",
        "acceptance": [
            "SEM-cancellation-02, -03, -04 end with the meeting cancelled, or with a hold naming the meeting.",
            "SEM-cancellation-08 (the sender is ill) is at least escalated.",
            "No message from an attendee that mentions their meeting's day ends as no_action.",
        ],
        "where": READING + "; workflow._plan_change",
    },
    "RC-CANCEL-READ-AS-MOVE": {
        "title": "A cancellation worded without 'cancel' is read as a move, and the sender is asked for a new time",
        "expected": "'Please take the concession review out of your diary' cancels the meeting.",
        "suggestion": "As RC-CHANGE-READ-AS-NEWS. 'Postponed indefinitely', 'take it out of the diary', 'off' with no new "
                      "time are cancellations, not moves.",
        "acceptance": ["SEM-cancellation-05 cancels ev-port and asks the sender nothing."],
        "where": READING,
    },
    "RC-TASK-NOT-RECOGNISED": {
        "title": "Work asked of the executive in an indirect sentence is filed as news",
        "expected": "'The auditors are still waiting for the signed representation letter from you' is a task. So is "
                    "'the authority requires your response within 48 hours'.",
        "suggestion": "The action rule needs a second form beside the imperative: a statement that someone is waiting "
                      "for, requires, needs or has not received something FROM THE EXECUTIVE. Without a model, the "
                      "conservative fallback is the same as RC-SERIOUS-MAIL-FILED-AS-NEWS: escalate what cannot be "
                      "placed instead of closing it.",
        "acceptance": ["SEM-task_extraction-05 to -08 and SEM-deadline_reminder-05 record a task, or are escalated; none ends no_action."],
        "where": READING,
    },
    "RC-MEETING-READ-AS-NEWS": {
        "title": "A wish to meet, worded as a statement, is filed as news",
        "expected": "'It would be good to talk sometime next week', 'I need an hour with you today at 10:00' are meeting "
                    "requests: a booking, an offer of times, or a question back.",
        "suggestion": "The meeting rule keys on a question or a direct request. Statements of need or wish addressed to "
                      "the executive (I need, I would like, it would be good to, I will come by) carry the same intent. "
                      "Fallback as above: never no_action for a person's message that names the executive's time.",
        "acceptance": ["The relation MR1-reword-vague holds: all three rewordings do what the base wording does.",
                       "SEM-direct_meeting-08, SEM-multi_people-04, SEM-requires_no-02 and -03 are not no_action."],
        "where": READING,
    },
    "RC-SECOND-REQUEST-DROPPED": {
        "title": "With two requests in one email, the second is dropped and the run is reported complete",
        "expected": "Both requests are carried out, or the run says which one was not (PARTIALLY_COMPLETED or a hold), so "
                    "that the executive knows something is still open.",
        "suggestion": "The rules produce one intent per message; several intents exist only with model understanding on "
                      "(scripted in tests). Until a model is in the loop, detect that a message holds more than one "
                      "request (enumerations, 'also', 'separately', 'and please', a second imperative after the first "
                      "was planned) and add an unsupported/remaining entry to the plan, with lifecycle "
                      "NEEDS_CLARIFICATION or a 'remaining' flag on the run, instead of COMPLETED. The plan already has "
                      "'unsupported' and 'missing' fields for exactly this.",
        "acceptance": [
            "The relation MR10_second_action holds: adding 'Also, please sign the NDA by Friday' to a booking, a "
            "cancellation and a task either records the task too or leaves the run not COMPLETED.",
            "SEM-multi_request-01, -02, -03 are completed, or their runs name what is still open.",
        ],
        "where": "backend/desk_overlay/workflow.py (planning from one intent), plans.py",
    },
    "RC-THREAD-CONTEXT-NOT-USED": {
        "title": "A reply that only makes sense with the thread is read alone",
        "expected": "'13:30 works for me' after the executive asked 'Thursday is better, what time?' books Thursday 13:30. "
                    "'The second option please' books the second time the executive offered.",
        "suggestion": "The run already reads the thread (email.read_thread appears in every trace) and then reads only the "
                      "last message for intent and time. Give the reader the thread: the day from the executive's last "
                      "message plus the time from the reply; an acceptance ('yes', 'that works', 'the second option') "
                      "of times the executive offered. This is where a model earns its place; by rule, at least hold "
                      "as NEEDS_CLARIFICATION with the thread's open question, never hand over as an unplaced reply.",
        "acceptance": ["SEM-implied_by_thread-01, -02, -03, -06 and SEM-follow_up-04 book the time the thread settled on, "
                       "or hold naming it."],
        "where": "backend/desk_overlay/workflow.py (context gathering), reading.py",
    },
    "RC-NON-ENGLISH-NOT-READ": {
        "title": "French and Arabic mail is not understood",
        "expected": "A meeting request, a cancellation or a deadline written in French or Arabic is handled as its English "
                    "equivalent is. At the very least it is put in front of the executive.",
        "suggestion": "The rules are English. Two honest options: (a) state in the contract that rule-based reading is "
                      "English only, and make any message whose language is not English ESCALATED rather than "
                      "informational/no_action (today three of three Arabic cases are silently filed as news); (b) "
                      "leave language to the model step and measure it here. Do not add French and Arabic keyword "
                      "lists: the corpus has nine such cases and the inbox has thousands.",
        "acceptance": ["No non-English case ends no_action with stage COMPLETED unless it is a newsletter.",
                       "With a model configured: the language category is re-measured and reported separately."],
        "where": READING,
    },
    "RC-FOLLOWUP-CLOSED-BY-ANY-REPLY": {
        "title": "A holding reply ('still working on it') closes the follow-up",
        "expected": "The follow-up stays open until the awaited thing arrives. A reply that says it is not there yet is not "
                    "the answer.",
        "suggestion": "By contract a follow-up is satisfied when 'a message from that person arrives in that thread'. That "
                      "rule cannot tell an answer from an apology. Keep the follow-up open and mark it 'acknowledged' "
                      "when the reply contains a not-yet marker, or leave closing to the person unless a model judged "
                      "the reply to be the answer.",
        "acceptance": ["SEM-follow_up-05 leaves fu-cert2 waiting; SEM-follow_up-01 still closes fu-cert."],
        "where": "backend/desk_overlay/workflow.py (follow-ups)",
    },
    # ── the job is not done; the person is told or asked ────────────────────
    "RC-WRITTEN-TIME-NOT-READ": {
        "title": "A time that is written in the message is not read, and the sender is asked for it again",
        "expected": "The time is in the message (in the subject, as 'tomorrow at 11', as '9.30 in the morning', after a "
                    "second sentence). The Desk books it or offers alternatives. It does not send 'when would suit you?' "
                    "to someone who just said when.",
        "suggestion": "The run is correctly classified as a meeting request and then held as time_not_understood. The "
                      "reader looks at the body only and at a narrow set of forms. Read the subject as well; accept "
                      "'tomorrow', 'today', 'this <weekday>' against the run's clock; accept '9.30', 'noon', 'half past "
                      "one'. And when a second request follows the first (MR10-second-book), do not let its date "
                      "('by Friday 12 March') make the first one ambiguous: dates introduced by 'by', 'before', 'no "
                      "later than' are deadlines, not meeting times.",
        "acceptance": ["SEM-direct_meeting-04 and -09, SEM-indirect_meeting-04, SEM-relative_date-01 are booked.",
                       "MR10-second-book/plus-task books the meeting it booked without the added sentence.",
                       "Unnecessary clarifications (a clarification sent where the truth is a booking) fall to zero."],
        "where": "backend/desk_overlay/reading.py (rules.extract_time)",
    },
    "RC-QUOTED-TEXT-READ-AS-REQUEST": {
        "title": "Dates in quoted earlier text make a clear request ambiguous",
        "expected": "Adding a quoted old message below the request changes nothing: the request above the quote is what is "
                    "asked.",
        "suggestion": "Strip quoted and forwarded text (lines after a reply separator, 'On ... wrote:', '-----Original "
                      "Message-----', '>' prefixes) before reading intent and time. The same stripping is the first "
                      "defence against instructions hidden in quoted mail.",
        "acceptance": ["The relation MR2_irrelevant_history holds for every follow-up, including the two with quoted dates."],
        "where": "backend/desk_overlay/reading.py",
    },
    "RC-NON-MEETING-READ-AS-MEETING": {
        "title": "A message that mentions a meeting or a call is treated as a request for one",
        "expected": "'Minutes of yesterday's operations meeting attached, nothing for you', 'which terminal did we agree on "
                    "for the weekly call?', 'call me as soon as you see this' are not requests to schedule. No mail asking "
                    "for a time goes out in the executive's name.",
        "suggestion": "A noun is not an intent. Require a requesting construction about a FUTURE meeting between the sender "
                      "and the executive. Where the classifier says needs_reply and the rules say meeting, prefer the "
                      "hold. The unnecessary clarification is the visible symptom: an approval card for a mail that "
                      "should not exist.",
        "acceptance": ["SEM-no_action-06, SEM-escalation-08, SEM-reply_drafting-01 and -06 propose no mail asking for a time."],
        "where": READING,
    },
    "RC-SCHEDULING-NOT-RECOGNISED": {
        "title": "A scheduling request in ordinary words is not recognised and is handed to the executive",
        "expected": "'Free Thu 11 Mar 9:30am for 45 min?', 'Can I steal 30 minutes of your time on Tuesday at 11:00?', 'Could "
                    "I have you between 13:30 and 14:00 on Thursday?' are bookings.",
        "suggestion": "This is the largest group and the safest failure: nothing wrong happens, the executive does the work. "
                      "It is the measured cost of rules: 20 of the corpus's meeting requests. Widening the keyword list "
                      "will move this number and not the next reader's. The durable fix is the model understanding step "
                      "that is already built (DESK_UNDERSTANDING=model), run for real: the checked pipeline behind it "
                      "scored 23 of 24 with a scripted reader. The lab is ready to measure it the day a credential exists.",
        "acceptance": ["With a model configured, re-run the corpus: complete job success on direct_meeting, indirect_meeting, "
                       "timezone, daylight_saving and relative_date is reported against today's figures.",
                       "The six hard gates still pass with the model on."],
        "where": READING,
    },
    "RC-TASK-HANDED-OVER": {
        "title": "A task with its deadline is handed over as 'needs a reply' instead of recorded",
        "expected": "'Could you approve the Q2 budget? Deadline: Thursday 11 March' is a task due Thursday.",
        "suggestion": "As RC-SCHEDULING-NOT-RECOGNISED: safe, and the price of rules. A question mark currently wins over "
                      "the action reading.",
        "acceptance": ["The relation MR1-reword-task holds for all three rewordings."],
        "where": READING,
    },
    "RC-REPLY-NEEDS-MODEL": {
        "title": "A reply that needs a fact from the thread cannot be written without a model",
        "expected": "The answer is in the thread; the Desk drafts it for approval.",
        "suggestion": "Documented by Agent 1 as not built. Listed so that it is measured when the model step runs.",
        "acceptance": ["With DESK_AGENT=on and a model: SEM-reply_drafting-01 and -06 send the fact from the thread."],
        "where": "backend/desk_overlay/agent.py",
    },
    "RC-TASK-DETAILS-WRONG": {
        "title": "A task is recorded with the wrong title or due date",
        "expected": "The task names the work and carries the date that was written, or none.",
        "suggestion": "See the witness trace.",
        "acceptance": ["The affected cases record a task that matches the truth."],
        "where": "backend/desk_overlay/planning.py",
    },
    "RC-NEEDLESS-TASK": {
        "title": "A task is recorded for a message that asks nothing of the executive, or with a title that says nothing",
        "expected": "No task unless the message asks the executive to do something; a task's title names the work.",
        "suggestion": "'ASAP' is a task title in SEM-unclear_time-04. A title taken from a short subject needs the request's "
                      "own words. In an evaluation world internal writes are automatic, so a needless task is created "
                      "with no approval at all: the bar for proposing one should be at least as high as for a mail.",
        "acceptance": ["SEM-unclear_time-04 either asks for a time or records a task whose title names the call."],
        "where": "backend/desk_overlay/planning.py",
    },
    # ── the machinery around approvals and execution ────────────────────────
    "RC-EVAL-DECISION-500": {
        "title": "POST /desk/eval/v1/approvals/{id}/decision answers HTTP 500 when a guard holds the action",
        "expected": "When an approve is refused by a guard (the action changed behind the approval, the slot was taken "
                    "meanwhile, a calendar stopped answering), the route answers 200 with the approval in its new state, "
                    "or 409 with a code. Never a server error.",
        "suggestion": "In EvalRuns.decide, after the approve the card is needs_info, which approvals_of() leaves out by "
                      "design ('a held card is not offered'). The final `next(a for a in approvals_of(...) if a['id'] "
                      "== approval_id)` then finds nothing and raises StopIteration. Return the approval as it was "
                      "shown with execution.status 'not_started' and an error carrying the hold's code, or raise "
                      "EvalError(409, <error_code>, <message>). THE GUARD ITSELF WORKS: in all four cases nothing was "
                      "executed. Only the answer is broken, and Agent 2's runner will see it as a failed request.",
        "acceptance": ["ADV-appr-tampered-time, ADV-appr-stale-slot, ADV-appr-calendar-lost and MR8-changed-behind/tampered: "
                       "the decision call returns a 2xx or 4xx, and the office is unchanged (as it is today)."],
        "where": "backend/desk_overlay/eval_api.py: EvalRuns.decide",
    },
    "RC-RECONCILE-SKIPS-FOLLOW-ON": {
        "title": "After a read-back settles an action, the next step is not proposed and the run rests in EXECUTING",
        "expected": "When a retry finds that an unknown-outcome action did take effect (or recovery finds it after an "
                    "interruption), the run goes on exactly as if the action had executed normally: the confirmation is "
                    "proposed, a reply that awaits an answer opens its follow-up.",
        "suggestion": "ExecutionGate._reconcile and recover_stale mark the card executed and return before _after(), so "
                      "on_settled (workflow.advance) never runs. The run shows next: ['advance'] and waits for a client. "
                      "In the product the worker's next tick does it; with no worker, and always under /desk/eval/v1 "
                      "(which has no advance call), the run stays 'running' for ever and its confirmation is never "
                      "sent. Call on_settled after a successful reconcile and after recovery finds the effect, and let "
                      "the same path open the follow-up for offer_times/clarify mail (MR9-uncertain-mail: reply sent, "
                      "no follow-up, stage COMPLETED).",
        "acceptance": ["MR9-uncertain-create/retry reaches a final status and the requester gets one confirmation.",
                       "MR9-uncertain-mail/retry ends WAITING_FOR_RESPONSE with a follow-up.",
                       "SCN-uncertain-product needs no advance from the client.",
                       "ADV-int-effect-landed proposes the confirmation after recovery.",
                       "In every one of them the booking is still applied exactly once (it is today)."],
        "where": "backend/desk_overlay/execution.py: _reconcile, recover_stale",
    },
    "RC-CHAT-NOT-DRIVEN": {
        "title": "Work that starts in chat cannot be run through the evaluation routes",
        "expected": "A chat turn ('remind me tomorrow at 9...') is run like an email.",
        "suggestion": "Known and documented by Agent 1 (conversation_input_unsupported). Counted here as not completed, in "
                      "every denominator.",
        "acceptance": ["SEM-chat-01 to -04 run."],
        "where": "backend/desk_overlay/eval_api.py",
    },
    "RC-CONTEXT-EXTENSION-IGNORED": {
        "title": "This backend version ignores a context field the case depends on",
        "expected": "context.unreadableCalendars and context.faults (mode uncertain) take effect in the case's world.",
        "suggestion": "Not a defect of the current engine: an older commit does not implement the extension. The lab scores "
                      "such a case 'unsupported' instead of judging a condition that never existed.",
        "acceptance": ["The case runs on a backend that implements the field."],
        "where": "backend/desk_overlay/eval_api.py: build_world",
    },
    "RC-OTHER-MISREAD": {"title": "Other misreadings (see each trace)", "suggestion": "See the witness trace."},
    "RC-OTHER-JOB-NOT-DONE": {"title": "Other jobs not done (see each trace)", "suggestion": "See the witness trace."},
}
