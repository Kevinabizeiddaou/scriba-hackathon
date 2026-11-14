# Mutation check on the safety guards

Run 14 November 2026 on `agent1/autonomous-engine`. One defect at a time is planted in a guard
(`backend/dev/mutation_check.py`), the suite is run, and the defect is removed. A defect the
suite does not notice is a guard no test stands behind.

    cd backend
    python dev/mutation_check.py . <path to Scriba>/Gmail

**First pass: 30 planted, 28 caught, 2 survived.** Both survivors got a test and are caught now
(re-run of those two: 2 of 2). This is a check of the tests, not a result about the agent.

| Planted defect | First pass | Now |
| --- | --- | --- |
| gate: external writes not held | caught | caught |
| gate: executor does not fail closed either | **survived** | caught |
| gate: tripwire does not raise | caught | caught |
| gate: unknown outcome reported as plain failure | caught | caught |
| gate: unknown outcome retried without a read-back | caught | caught |
| gate: a gone sandbox falls through | caught | caught |
| readiness: env alone enables writes | caught | caught |
| readiness: lead switch not required | caught | caught |
| claims: memory store hands out a held key | caught | caught |
| workflow: in-flight claim not respected | caught | caught |
| workflow: injection not held | caught | caught |
| workflow: busy time booked anyway | caught | caught |
| workflow: non-organizer change proposed | caught | caught |
| workflow: stranger's change request acted on | caught | caught |
| workflow: overdue follow-up sends repeated reminders | caught | caught |
| workflow: unreadable mailbox treated as no answer | caught | caught |
| workflow: partial counted as verified | caught | caught |
| worker: starts in production | caught | caught |
| worker: overlapping ticks allowed | caught | caught |
| worker: hourly limit ignored | caught | caught |
| agent: any tool allowed | caught | caught |
| agent: step limit removed | caught | caught |
| agent: proposal type not checked | **survived** | caught |
| sandbox: default world answers for anyone | caught | caught |
| sandbox: organizer not required for a change | caught | caught |
| sandbox: same event created twice | caught | caught |
| eval: another user's run visible | caught | caught |
| eval: contradicting decision accepted | caught | caught |
| gateway: placeholder key treated as a model | caught | caught |
| reading: ambiguous zone converted anyway | caught | caught |

## The two survivors

- **The executor's own refusal of a real write.** The approve wrapper holds a mail or calendar
  card before Scriba's executor is reached, so removing the executor's second check changed
  nothing a test could see. It is defence in depth and is now tested directly
  (`test_the_executor_itself_refuses_a_real_write_if_the_approve_gate_were_passed`).
- **The model step's proposal-type check.** Without it an unknown type fell through to the
  reminder branch and was refused there for missing fields, so nothing changed. A proposal
  shaped like a reminder but named as something else would have been accepted. Now tested
  (`test_an_unknown_proposal_type_is_refused_even_when_it_looks_like_a_reminder`).

## Second pass: the guards added afterwards

8 planted, 8 caught.

| Planted defect | Result |
| --- | --- |
| binding: a changed action is approved anyway | caught |
| retry: runs the unedited proposal | caught |
| recovery: settles an action still in flight | caught |
| plan: a blocked step counts as ready | caught |
| understanding: an unquoted intent is kept | caught |
| understanding: low confidence acted on | caught |
| lifecycle: failed verification not escalated | caught |
| understanding: a time without an offset is used | caught |

## What it does not cover

Thirty-eight defects in the guards I judged most important: the write gate, the tripwire, unknown
outcomes, readiness, claims, the worker's limits, the model step's bounds, sandbox ownership,
the evaluation routes and time-zone reading. It is not exhaustive, and it says nothing about
Scriba's own code.
