# Final presentation outline (draft)

Nine slides, about five minutes plus the two-minute demo. Confirm the time limit and any required sections against the challenge brief; this outline assumes none beyond what we were told.

Every number on a slide comes from a live evaluation report. Where one does not exist yet, the slide says "not measured yet". Bracketed items are to be filled in on the day.

| # | Slide | What it says | Source |
| --- | --- | --- | --- |
| 1 | Title | Scriba Executive Desk: an AI executive secretary that does the scheduling work and asks before it acts. Team names. | |
| 2 | The job | One sentence from the index card. A real example of a scheduling thread that took too long. | `INDEX_CARD.md`. The example comes from a customer voice note, or is labelled as illustrative. |
| 3 | Customer voice | Play 20 to 30 seconds of a real voice note. One line on what it changed in the product. | `VOICE_NOTE_QUESTIONS.md`. If there is no recording, say so and skip to slide 4. |
| 4 | How it works | Trigger, seven steps, done criteria. One diagram: request, read calendar, propose, approve, execute, record. | `INDEX_CARD.md` |
| 5 | Demo | The two-minute recording. | `DEMO_STORYBOARD.md` |
| 6 | Human in the loop | What needs approval (every email, every calendar change) and what the approver sees: the reason, the exact email, the exact event. What the agent refuses to do. | Approval Center screenshot, back of the index card |
| 7 | Evidence | Twenty cases across ten categories. Pass rate, rescues, mandatory approvals (separately), errors. Friday, Saturday, Sunday progress. | Evaluation Dashboard snapshots: [Fri], [Sat], [Sun] |
| 8 | Cost and speed | AI cost per run, cost per unassisted pass, median and p95 time to final status. Method in one line. | `COST_PER_RUN.md`, evaluation report: [cost], [latency] |
| 9 | Limits and next steps | What it does not handle yet, what failed in evaluation and why, what we would build next. | Failed cases from the Sunday report |

## Slide 7 in detail

Show these, in this order, straight from the Sunday snapshot:

1. Cases executed out of 20.
2. Passed with no human rescue, as a count and a percentage.
3. Passed only with a rescue.
4. Failed, with the case ids.
5. Could not be scored (API or model errors), with the case ids.
6. Mandatory approvals, labelled as expected and by design.
7. The three-day trend, if all three snapshots exist.

Then one failed case opened up: what was expected, what the agent did, and the trace. A failure explained honestly is stronger evidence than a clean table.

## Slide 9: say these plainly

- Which of the twenty cases the agent fails today.
- That the cases are synthetic and written by us, so they test what we thought of.
- That availability is checked on the principal's calendar only.
- That a human cannot yet edit a proposed email before approving it (if that is still true).
- Anything the demo skipped.

## Before presenting

- [ ] Every number matches the Sunday snapshot file.
- [ ] No screenshot shows the "Mock data" label next to a claim about the agent.
- [ ] The voice note is from a real person who agreed to its use.
- [ ] The harness self-test is not quoted as a result anywhere.
- [ ] The demo recording is of the real backend, or is captioned as sample data.

## Likely questions

| Question | Where the answer is |
| --- | --- |
| What stops it sending something wrong? | The approval gate, checked on every case (`approval_gate`), and the Approval Center |
| What about prompt injection? | EVAL-019 and EVAL-020, and their results |
| How do you know the evaluation itself is right? | The harness self-test: twelve planted defects, each caught by the intended check |
| What does a run cost? | Slide 8 and the method in `COST_PER_RUN.md` |
| What happens when Google's API is down? | EVAL-017 (retry, exactly one event) and EVAL-018 (stop, no false confirmation) |
| How much of this is real versus mocked? | The data-source label in the app, and `INTEGRATION_HANDOFF.md` section 1 |
