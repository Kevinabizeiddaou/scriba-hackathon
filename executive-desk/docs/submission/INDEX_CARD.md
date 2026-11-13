# Index card (draft)

Draft for the private AlphaHack simulation. Check the wording against the challenge's own index-card format before using it; this follows the four headings we were given: job, trigger, steps, done criteria.

## Front of the card

**Scriba Executive Desk**

**Job.** Turn a meeting request into the right calendar outcome and the right reply, with a person approving everything that is sent or changed.

**Trigger.** A meeting-related email arrives in the principal's inbox, or the principal types a request in the Secretary Chat.

**Steps.**

1. Read the request and classify it: new meeting, reschedule, cancellation, or unclear.
2. Extract the details: who, how long, when, which time zone, which existing event.
3. Read the calendar. Never assume availability.
4. Decide: book it, offer alternatives, ask a clarifying question, or hand it to the principal.
5. Draft the calendar change and the email, and ask for approval with a plain explanation.
6. After approval, make the calendar change first, then send the email.
7. Record what was done.

**Done when.**

- The calendar matches what was agreed: one event, right time in every time zone, no double booking.
- The requester has a reply that says what happens next.
- Nothing was sent or changed without an approved request.
- The run is in the activity log with its steps.
- No person had to fix anything. An approval click is not a fix.

## Back of the card: how we know

| Measure | Source | Current value |
| --- | --- | --- |
| Cases passed unassisted, out of 20 | Evaluation Dashboard, "Pass rate" | Not measured yet |
| Human rescues | Evaluation Dashboard, "Human interventions" | Not measured yet |
| Mandatory approvals (expected, reported separately) | Evaluation report | Not measured yet |
| AI cost per run | Evaluation report, see COST_PER_RUN.md | Not measured yet |
| Median time from request to final status | Evaluation report | Not measured yet |

Fill the last column from the Sunday snapshot. Do not fill it from the harness self-test: that runs a scripted mock and says nothing about the agent.

## What the agent will not do

- Send an email or change the calendar without approval, even when an email claims approval was already given (EVAL-020).
- Follow instructions written inside an incoming email (EVAL-019).
- Book over an existing meeting, or move one to make room, on its own.
- Guess a date or time zone that the request leaves ambiguous (EVAL-007, EVAL-010).
- Confirm a meeting that was not actually created (EVAL-018).
