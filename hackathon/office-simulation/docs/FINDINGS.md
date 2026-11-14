# What the simulation found

Observed on the Desk engine at backend revision `0282558`
(`agent1/autonomous-engine`, overlay 0.3.0), **rules only, in the sandbox**.
Every item names the evidence that shows it. Nothing here was fixed in the
backend or the frontend: those belong to their owners. The requests that
follow from these findings are in [INTEGRATION_REQUESTS.md](INTEGRATION_REQUESTS.md).

No model was run. Several items under "Reading the message" are what a
rule-based reader does with ordinary prose and may look different with a
model; that has not been measured.

## What held up

| Property | Evidence |
| --- | --- |
| Mail became runs with no client open, one run per message, through a duplicate notification, a repeated intake, a manual sweep and a worker restart | `evidence/robustness/robustness.md`; `unreliable` steps 10 and 16 |
| Nothing was sent or written without a recorded approval, on any of the eight days, in either executive mode | Invariant `no_write_without_approval`: 0 violations |
| No real provider client was reached | Invariant `sandbox_isolation`: 0 violations; `isolationViolations` empty in every final world |
| No double booking and no duplicate event, including when two proposals for one slot were both approved (the second was held as `calendar_conflict`) | Invariants `no_double_booking`, `no_duplicate_event`; robustness case "a duplicate email, both proposals approved" |
| A conflict on another provider's calendar was seen: a Gmail request for a time busy only on Outlook, and one busy only on the second Google account, were not booked | `multi_provider`: Greta "Holiday shipping plan", Daniel "Pricing annex" |
| Events went to the calendar of the mailbox that received the request (Outlook, and the second Google account), and replies left from that mailbox | `multi_provider`: Hannah, Nora |
| A reschedule moved the original event; a cancellation cancelled the right one; the confirmation followed only after the change took effect | `normal`: Priya, Tomas; `compound` check `confirmation_only_after_the_booking_took_effect` |
| With one calendar unreadable nothing was booked or offered | `unreliable` step 2; robustness "a calendar that is missing" |
| A failed write was retried and succeeded; an uncertain write was settled by reading the world back, not by writing twice; an interrupted action was settled without being run and took effect once after the retry | `unreliable` checks |
| A partial failure was reported as partial, with the event kept | `unreliable` check `partial_success_reported_as_partial` |
| Text addressed to the assistant produced no proposal | `surprise`: "Meeting request" from an unknown sender |
| A request repeated after it was booked was held (`already_scheduled`) | `unreliable` step 15; robustness |
| A client's answer to an offer was booked, and the follow-up closed | `normal`, `multi_provider`, `human_in_loop`, `follow_up` |
| The executive's rejection blocked the dependent confirmation; invalid approvals changed nothing | `compound` step 3; `human_in_loop` check `invalid_approvals_change_nothing` |
| The same seed reproduced the same day, entry for entry | Robustness "replaying a complete day reproduces it" |

## Defects

Ordered by what they would cost in use.

### 1. An edit at approval is not carried into the confirmation, and the Desk then reports its own correct event as unverified

The executive changed a proposed meeting from 14:00 to 14:30 in the approve
request. The event was created at 14:30. The confirmation the Desk then
proposed told the client "14:00 to 14:30". The card's input still shows the
unedited time (the edit sits in `output.approved_overrides`), the Desk's
verification compared the world against that, recorded `start_differs`, and
the run went to `ESCALATED (verification_failed)`.

- With an executive who reads: she stopped the confirmation; the request
  ended "partly done" with no confirmation sent.
- With an executive who does not: the client was told the wrong time.
- Evidence: `evidence/human_in_loop/report.md`, message "Cold-chain lanes:
  intro call"; `evidence/human_in_loop-trusting/report.md`.

### 2. A repeated cancellation is aimed at a different meeting

After "1:1 Priya Nair" was cancelled, the same message arrived again. The
Desk proposed cancelling **the Leadership stand-up**: the only meeting the
sender was still on, and one that had already taken place that morning.

- Evidence: `evidence/busy/report.md`, second "Today's 1:1". Stopped by the
  executive; executed in `evidence/busy-trusting/`.

### 3. A request to move a meeting can be read as a new meeting

"Could we move tomorrow's contract negotiation to 15:00?" produced a
proposal to create a second event rather than move the existing one. The
phrase "move tomorrow's" is not one the reader recognises as a change.

- Evidence: `evidence/busy/report.md`, "Tomorrow's negotiation";
  `evidence/busy-trusting/report.md` shows the second event created.

### 4. Offered times start at the very second the reply is written

When the executive is free now, the first time offered begins now, to the
second (for example `15:00:31`), with no lead time and no rounding. The
reply text reads "15:00 to 15:30" and is written at 15:00:31. Separately,
the times offered are the earliest free ones from now, not times near the
day that was asked for (a request for tomorrow at 14:30 was answered with
three times this morning).

- Evidence: `evidence/normal/report.md`, "Brightwave pricing prep" and
  "Peak-season forecast"; `busy` "Thursday sync"; `surprise` two cases.

### 5. The reminder for an overdue follow-up is proposed with no recipient

Two days after an unanswered offer, the Desk marked the follow-up overdue
and proposed a reminder. The card was `needs_info` ("I still need a
recipient email"): it could not be approved as it stood, and it was not
flagged as held, so the run sat in `AWAITING_APPROVAL`. The simulated
executive typed the recipient in, which is counted as a completion by hand.

- Evidence: `evidence/follow_up/report.md`, step 7 and its check.

### 6. An awaited reply is only recognised when the message opens a run

Awaited replies are closed during intake. A reply the classifier files as
informational never reaches intake, so the reply the executive was waiting
for arrived and stayed "waiting".

- Evidence: `evidence/normal/report.md` and `evidence/follow_up/report.md`,
  Karim's "Re: Crane maintenance quote for Q1" (missed).
- When the reply did open a run (Rafael's), the awaited reply was closed
  correctly, and a reply offering meeting times was proposed as well.

### 7. Replies awaited from before the Desk never become overdue

An awaited reply that does not belong to a Desk run is not listed by
`/desk/follow-ups`, is never marked overdue and never leads to a reminder.

- Evidence: `evidence/normal/report.md`, check
  `overdue_awaited_reply_is_surfaced`.

### 8. The briefing does not report on the day

`/desk/briefing` has no section for work that was done, none for awaited
replies and none for overdue tasks. Its headline counts every message in the
inbox, handled or not: at the end of the normal day, with every meeting
request dealt with, it read "7 meeting requests, 1 message needs a reply".
Its meetings carry no start or end time (`start_time: null`), so the
frontend shows them as "All day".

- Evidence: every day's `briefing.json` and the two briefing checks;
  `follow_up` check `overdue_task_is_reported`.

## Reading the message (rules only)

| What was written | What the Desk did | Evidence |
| --- | --- | --- |
| A confirmation asking to bring figures ("Wednesday is confirmed ... please have the figures to hand") | Read as a new meeting request; proposed a reply offering times | `normal`, Mei's second message |
| A deadline, with a meeting mentioned in passing ("comments by Wednesday. The investor meeting is on Thursday") | Read as a meeting request; no task | `multi_provider`, Nora |
| "Please send us the signed term sheet by Friday" | Filed as needing a reply in the executive's words; no task | `normal`, Ingrid |
| A time with two day words ("today at 17:30 ... before tomorrow") | Time not read; proposed a reply asking for a time | `busy`, Mei |
| A message with two requests, or a meeting plus a date in passing | One reading at most; all four compound messages needed a person | `compound` |
| Colloquial English, French | Handed over without a proposal (safe) | `surprise` |
| A formal legal notice; a reply with no context | Filed as informational: no run, so the executive is not told | `surprise` |
| A second person named only in the text | Not invited (by design); the executive added her at approval | `surprise`, Jonas |

## Smaller observations

- `step_blocked` is recorded only once a client calls
  `POST /desk/runs/{id}/advance`; the dependent step is never proposed
  either way (`compound` step 3).
- After an interrupted action is recovered and retried, the execution and
  the verification are each recorded twice; the world shows one effect
  (`unreliable` step 17: three execution records).
- A meeting booked from a reply is titled "Re: ..." (`normal`, Greta).
- Tasks and reminders need an approval in the product; a task is a full
  human decision for something that only writes the executive's own records.

## The frontend against this backend

Seen while capturing `evidence/demo/screenshots/` with the frontend at
`origin/agent2/frontend-excellence` (`d60b892`), unmodified. It runs against
the engine with no console or network errors, approvals are enabled in
sandbox mode ("Approve in sandbox"), and the run detail shows the plan, the
evidence and the read-back verification. What does not line up:

| Screen | What it shows |
| --- | --- |
| Calendar | An empty week. It reads Scriba's `GET /calendar/events`, which is not answered from the sandbox world. "Find a time" reads `/desk/availability` and is correct |
| Tasks and follow-ups | Scriba's seeded tasks, not the world's; a task the Desk created in the sandbox does not appear |
| Overview, "Today" | "All day" for timed meetings (finding 8) |
| Overview, Approval center, Activity | Scriba's own seeded cards beside the Desk's, which inflates the counters |
| Every card | "Updated Wed 15 Jul": the seeded store's fixed timestamps, not the sandbox clock |
| Cancel card | "No title on the card", though the backend sends the event title |
| Run detail after one of two actions executed | The top panel still says nothing has happened |
| Sidebar | "Live: Scriba" in green, with the sandbox note in small type beneath |
| Sign-in identity | "Alice" (the seeded Scriba user), not the fictional executive |

For this reason the demonstration captures only the screens that read the
sandbox world: overview, inbox, work queue, run detail, approval center and
find a time.
