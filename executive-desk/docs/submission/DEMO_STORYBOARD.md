# Two-minute demo storyboard (draft)

> Scope note, 13 November 2026: drafted when the project covered meeting coordination only. The screens and the evaluation suite now cover the secretary's wider work; this draft has not been rewritten to match and should be revised by whoever owns the submission.

Target length: 120 seconds. One continuous screen recording with voiceover, no cuts inside a flow.

**Before recording.** The demo must run on the real backend. If the sidebar still says "Mock data", what is on screen is a scripted replay, and the recording has to say so. Do not present a mock run as the agent working. Use a test mailbox and a test calendar. Check the times below against a rehearsal; they are a plan, not measurements.

| Time | On screen | Voiceover | Proves |
| --- | --- | --- | --- |
| 0:00 to 0:12 | Request Inbox, several new requests | "An executive's inbox gets meeting requests all day. Each one takes a calendar check, a decision and a reply. Scriba Executive Desk does that work and asks before it acts." | The job and the trigger |
| 0:12 to 0:35 | Open a straightforward request. Click "Process request". The status steps fill in: understood, calendar read, proposal ready. | "Here is a request for a 30-minute call on Tuesday at eleven. Scriba reads it, pulls out who, when and how long, and checks the calendar. The slot is free, so it prepares an event and a confirmation." | Classification, extraction, tool use |
| 0:35 to 0:58 | Click "Review approval". The Approval Center card: why, the event, the exact email. Click "Approve all 2". Execution shows the event created, then the email sent. | "Nothing has been sent yet. This is the approval: why Scriba proposes it, the event it will create and the exact email. One click, and it creates the event first, then sends the confirmation." | Human approval, order of execution |
| 0:58 to 1:18 | Back to the inbox. Open the conflict request, already processed. Show the proposed reply with three alternative slots. | "This one asks for a time that is already taken. Scriba does not double-book and does not move the existing meeting. It offers three free slots, and the reply does not say what the other meeting is." | Conflict handling, privacy |
| 1:18 to 1:36 | Open the prompt-injection request. Show the "Suspected prompt injection" flag and the "Needs you" status. | "This email contains instructions aimed at the assistant: export the calendar and skip approval. Scriba treats that as untrusted text. Nothing is sent, nothing is booked, and it is flagged for a person." | Safety |
| 1:36 to 1:54 | Evaluation Dashboard: the twenty-case strip, pass rate, interventions, cost per run. Expand one case to show expected versus actual and the trace. | "We test this on twenty scenarios: conflicts, time zones, cancellations, duplicates, API failures and injection. [Read the real numbers from the screen.] Every case shows what was expected, what happened, and the full trace." | Evidence |
| 1:54 to 2:00 | Secretary Chat with one request and its approval card | "It works from chat too. Scriba Executive Desk: a secretary that does the work and asks first." | Close |

## Requests to use

| Beat | Fixture | Inbox id in mock mode |
| --- | --- | --- |
| Straightforward booking | EVAL-004 (open Wednesday afternoon) or EVAL-001 | `req-004`, `req-001` |
| Conflict | EVAL-003 | `req-003` |
| Prompt injection | EVAL-019 | `req-019` |

Against the real backend, send the same three emails from `fixtures/evaluation-cases.json` to the test mailbox before recording.

## Rules for the recording

- Read the evaluation numbers off the screen as they are on the day. If the run has not happened, cut the 1:36 beat down to showing the cases and say the numbers are pending.
- If a live run fails during recording, keep it only if the failure handling is the point. Otherwise re-record. Do not splice a mock run into a live recording.
- Keep the sidebar visible so the data-source label is always in frame.

## Fallback if the backend is not ready

Record the same flow in mock mode, with this sentence at the start and in the caption: "This recording shows the interface on scripted sample data. The agent is not connected in this take." Leave the evaluation numbers out entirely.
