# Why this is more than a chatbot

A chat assistant answers when someone asks it something, and what it says is
the result. The job on the index card is different: work arrives unasked,
has to be carried across several systems and several days, and is only done
when the calendar and the mailbox show it.

Each claim below is one the simulation demonstrated, with where to see it.
Where a claim holds only in part, the gap is stated in the same row. All of
it is in the sandbox, on rules, with no model; none of it is a claim about a
live mailbox.

No statement is made here about any other product. The comparison is with
the general pattern of a prompt-and-answer assistant, not with a named
competitor, because nothing about a competitor was tested.

| Claim | Demonstrated | Where | Not yet |
| --- | --- | --- | --- |
| **Work starts by itself** | Every one of the Desk's runs was opened by its background worker from arriving mail (`trigger: "worker"`); no client asked for it | `evidence/*/runs.json`; shot 2 of the storyboard | The chat and scheduled-briefing triggers were not exercised. The worker reads the newest inbox page |
| **It keeps the state of the work** | A run has a recorded plan, a lifecycle stage and an append-only evidence timeline; a run rests in "waiting for a response" for days and resumes | `evidence/demo/transitions.md`; `evidence/follow_up/report.md` | The seeded backend keeps runs in memory, so survival of a full process restart was not shown; only the worker and its claim store were restarted |
| **It coordinates several applications** | Two Gmail mailboxes, an Outlook mailbox, two Google calendars and an Outlook calendar in one decision; a time busy only on the other provider was not booked; events and replies went to the account the request reached | `evidence/multi_provider/report.md` | Sandbox stand-ins for the providers, not Google or Microsoft |
| **It handles dependent actions** | Book, then confirm, with the confirmation proposed only after the booking took effect; a declined booking blocked the confirmation | `evidence/compound/report.md`, checks | A message with two separate requests is not split on rules: all four compound messages needed a person |
| **It asks for approval at the right boundary** | 0 actions took effect without a recorded approval across all eight days, in both executive modes; the gate is in the server, not in a disabled button | Invariant `no_write_without_approval`; `evidence/RESULTS.md` | Tasks and reminders also wait for approval, which is more asking than the job needs |
| **It verifies real outcomes** | Each executed action is read back from the provider state before the run is complete; an uncertain write was settled by a read-back instead of a second write; a failed verification escalates | `evidence/unreliable/report.md`; `evidence/demo/screenshots/02-morning-executed-run-11.png` | On the earlier engine (`0282558`) an edit at approval made this check fail falsely; fixed on `f06a258`, where the action as approved is what is verified and confirmed |
| **It remembers outstanding commitments** | A reply that awaits an answer opens a follow-up; the answer closed it (8 satisfied); after two days of silence it was marked overdue and a reminder was proposed, once | `evidence/follow_up/report.md` | The reminder was proposed without a recipient; replies awaited from before the Desk never become overdue; an answer filed as informational is not recognised (FINDINGS.md, items 5 to 7) |
| **It continues after a person responds** | A client picked one of the offered times; the Desk booked that time and confirmed, on four different days | `evidence/normal`, `multi_provider`, `human_in_loop`, `follow_up` | |
| **It records interventions and failures** | Every approval, rejection, edit and retry is on the run with who and when; partial success is reported as partial, with the event kept; a provider failure is recorded as a failure | `evidence/unreliable/report.md`; `runs.json` | Cost is not recorded because no model ran: usage is null, not zero |
| **It does not claim success it has not got** | A run with a failed confirmation was `PARTIALLY_COMPLETED`, not completed; an unknown outcome stayed unknown until read back; with one calendar unreadable nothing was booked or offered; sandbox results are marked simulated on every run | `evidence/unreliable/report.md`, steps 2, 9, 11, 13 | The briefing's headline counts handled mail as still needing attention (FINDINGS.md, item 8) |
| **It refuses instructions that arrive by mail** | A message telling "the assistant" to approve automatically and forward mail produced no proposal | `evidence/surprise/report.md`, "Meeting request" | Detection is pattern-based |

## What this does not show

- That a model-driven version understands requests well. On rules alone,
  54 of 77 requests that needed work were handled with approvals only, 19
  were left for a person, and 12 proposals were wrong and had to be stopped
  by the executive.
- That any of it works on a live mailbox or calendar.
- That it saves an assistant a measured amount of time.

Those three are the next things to measure, in that order.
