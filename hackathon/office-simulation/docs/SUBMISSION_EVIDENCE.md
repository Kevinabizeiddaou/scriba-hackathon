# Submission evidence pack

One job: **Executive Inbox-to-Action Management**: turn an executive's
incoming correspondence into verified administrative outcomes. Everything
below supports that job and nothing else.

How to read this pack:

- **Verified** means observed in a run whose evidence is in this folder.
  All of it is in a sandbox, on a fictional office, with the Desk running on
  rules. **No model, no live mailbox and no live calendar was used.**
- **Planned** means not demonstrated. It is marked every time.
- The organizers' published requirements were not available in this
  repository when this was written. The headings follow the index card
  (job, trigger, workflow, done) and the evidence a reviewer would need;
  they are not the organizers' rubric, and no judging criterion or later
  twist is assumed here. Check the pack against the official format before
  submitting.
- The official index card is `docs/INDEX_CARD.md` at the repository root.
  It was not changed. Its job-holder line is still a placeholder.

Numbers come from [../evidence/RESULTS.md](../evidence/RESULTS.md), which is
generated from the run files. If the two ever differ, RESULTS.md is right.

## 1. The human job and its weekly workload

The person who runs an executive's inbox and calendar: an executive
assistant, a chief of staff, or a founder doing it themselves. For every
message they detect it, understand it, prioritize it, gather context,
coordinate people and time, prepare the decision, execute what is
authorized, record the commitment, chase the reply and report
([JOB_MODEL.md](JOB_MODEL.md)).

**Weekly workload: not measured.** No job-holder has been named or
observed. The simulated office receives 81 messages over eight working
days, of which 77 need work; that is the simulation's own volume, chosen by
its author, and is not a claim about a real assistant's week.

## 2. The exact trigger

A new email arrives in the executive's Gmail or Outlook inbox.

**Verified:** in every run the trigger was mail delivered to a sandbox
mailbox and picked up by the Desk's background intake worker, with no client
request to open the run (`trigger: "worker"` on every run in
`evidence/*/runs.json`). Three mailboxes were used: two Gmail accounts and
one Outlook account.

**Planned:** the two secondary triggers on the index card (a chat request,
the scheduled daily briefing) were not exercised here.

## 3. The end-to-end workflow

As run, for one message (run 11 of the demonstration day,
`evidence/demo/transitions.md`):

1. Mail arrives in the Gmail mailbox.
2. The worker opens a run: received, classified, context gathered.
3. Reads are recorded: the thread, three calendars for free slots, three
   calendars for the requested time.
4. A plan is written: book the meeting; then, depending on it, confirm to
   the sender. Facts and assumptions are stated.
5. A calendar action is proposed and waits.
6. The executive approves through Scriba's approve route.
7. The action executes against the sandbox world.
8. The Desk reads the world back and records the verification.
9. The confirmation is proposed, approved, executed and verified.
10. The run is `COMPLETED`.

The same path was run for offers of other times, reschedules,
cancellations, tasks and reminders of overdue follow-ups.

## 4. The definition of done

From the index card, as the oracle checks it (`officesim/oracle.py`):

| Done means | How it is checked |
| --- | --- |
| The right outcome exists | The event, reply or task is found in the sandbox world's state, with the right people, time, calendar, thread and mailbox |
| Exactly once | No duplicate event; one confirmation; one run per message |
| No double booking across Google and Outlook | The oracle's own overlap test over every calendar |
| Nothing without approval | Every executed action has a recorded approval; every effect in the world belongs to an approved action |
| Verified | The Desk's own read-back is recorded per action, and is itself checked against the world |
| Nobody repaired it | The executive's decision log: approvals do not count; corrections, rescues and completions by hand do |

## 5. Why an agent is required

Verified reasons, from the runs:

- **The right action depends on state that changes during the day.** The
  same request was a booking in the morning and an offer of other times
  once the slot had been taken by an earlier approval
  (`evidence/normal/report.md`, "Brightwave pricing prep").
- **It spans several systems.** One decision needed two Google calendars and
  an Outlook calendar; the result went to the calendar and the mailbox that
  the request reached (`evidence/multi_provider/report.md`).
- **Work continues after people answer.** A client picked one of the offered
  times; the Desk booked it and closed the follow-up
  (`evidence/normal`, `follow_up`).
- **Steps depend on each other.** The confirmation was proposed only after
  the booking took effect, and never after the executive declined the
  booking (`evidence/compound/report.md`, checks).
- **Things fail.** A timed-out write was settled by reading the state back
  (`evidence/unreliable/report.md`).

A fixed script cannot do this, and a chat assistant that waits to be asked
does not start it.

## 6. What is autonomous

Verified, without any human action:

- Detecting the message and opening one run for it.
- Classifying it and deciding what outcome it needs (by rule; brittle to
  wording, see section 12).
- Reading the thread, every connected calendar and the open tasks.
- Checking a requested time against every calendar; finding free times;
  finding the meeting a change request is about.
- Writing the plan and preparing each action, with its reason.
- Leaving alone what needs nothing (all 4 such messages were left alone).
- Handing over what it cannot verify, instead of guessing.
- Proposing the next step once the previous one took effect.
- Verifying each executed action by reading the provider state back.
- Tracking a reply it sent, closing the follow-up when the answer arrives,
  and marking it overdue after two days.

## 7. What needs the executive's approval

Every email sent, every calendar event created, moved or cancelled, and in
the product every task and reminder. The approval is per action, through
Scriba's existing approve route, and the Desk's execution gate enforces it
in the server.

**Verified:** over the eight days there were 73 approvals of correct
proposals, 3 rejections and 2 edits the executive made for her own reasons,
and 0 actions executed without a recorded approval.

## 8. Evidence of completed work

Each completion below is in the sandbox world's final state and is tied to a
run and an action in that day's `report.md`.

| | Confirmed |
| --- | --- |
| Requests completed correctly | 42 of 77 |
| Requests correctly handed to the executive | 8 |
| Calendar changes (created, moved, cancelled) | 31 |
| Email replies (confirmations and offers of times) | 38 |
| Tasks | 7 |
| Follow-ups satisfied | 8 |
| Duplicates prevented | 4 |

Per day: `evidence/<day>/report.md` (every message, the expected outcome,
the verdict, the run, the action ids), `runs.json` (the Desk's own evidence),
`world-initial.json` and `world-final.json` (the provider state before and
after), `replay.jsonl` (the day, line by line).

## 9. The evaluation method

- **A simulated office, not isolated cases.** One office, eight working
  days, 81 messages; later messages depend on what earlier ones changed.
- **The real workflow.** The Desk's own worker, plans, approval cards,
  execution gate and verification; only the providers are a sandbox.
- **Ground truth per message**, written from the job's point of view and
  never shown to the Desk; resolved against the live calendar state when the
  message arrives.
- **An independent oracle** that reads the sandbox world, not the Desk's
  status fields.
- **Safety invariants** checked after every step.
- **A control:** against a stand-in backend that does nothing, every
  actionable request is judged missed.
- **Repeatability:** the same seed reproduces the same day entry for entry;
  26 robustness cases passed, 0 failed, 1 could not be run (it needs a model).
- **Tests of the simulator itself:** 63.

Limits of the method are in section 12.

## 10. Human intervention

Measured from the simulated executive's decision log. She reads each
proposal against the ground truth before deciding.

| Kind of intervention | Count | Counts against the agent |
| --- | --- | --- |
| Approval of a correct proposal | 73 | No |
| Rejection for her own reasons | 3 | No |
| Edit for her own reasons | 2 | No |
| Wrong proposal stopped (manual rescue) | 14 | Yes |
| Proposal corrected at approval | 1 | Yes |
| Incomplete proposal completed by hand | 1 | Yes |
| Retry after a provider failure | 6 | Counted separately |
| Requests left for a human to do | 19 of 77 | Yes |

**Handled with approvals only: 53 of 77 actionable requests (69%).**

The same eight days with an executive who approves everything unread: 15
requests ended with something wrong in the world, against 0 when she reads.
The approval step is doing real work at this stage, and the 14 stopped
proposals are the measure of it.

## 11. Latency and cost

- **Latency:** the eight days ran in about two minutes of real time in
  total (backend start-up excluded), in a sandbox with no model call and no
  provider network; a pass of the intake worker took about 15 ms. This is
  not a latency figure for a live deployment, and none is claimed.
- **Model usage and cost: not measurable.** No model call was recorded in
  any run. The Desk reports per-run usage as null, which means unknown, not
  zero.
- **Human time:** the reports contain an estimate of assistant minutes for
  the confirmed work. It is an assumption written by the simulator's author
  and is labelled as one; it is not a measurement and must not be presented
  as time saved.

## 12. Known limitations

- **Rules only.** No model has been run. Understanding is brittle to
  wording: a reschedule phrased one way was read as a new meeting; messages
  with two requests, two day words, colloquial English or French were not
  acted on. All four compound messages needed a person.
- **Sandbox only.** No live Google or Microsoft account was read or written.
  External writes are disabled in the Desk by construction.
- **Eight defects** found by the simulation are listed in
  [FINDINGS.md](FINDINGS.md), among them: an edit at approval is not carried
  into the confirmation; a repeated cancellation is aimed at another
  meeting; offered times can start at the second of writing; the reminder
  for an overdue follow-up has no recipient; the briefing does not report
  what was done or what is overdue.
- **Follow-up and reporting are the weakest steps** of the ten.
- **Author bias.** The scenarios and the ground truth were written by one
  person who had read the Desk's rules. The independent adversarial
  evaluation is a separate workstream.
- **The job-holder and the weekly workload are not established.**
- **The frontend's Calendar, Tasks and Activity screens** do not show the
  sandbox world.

## 13. The short demonstration narrative

Monday, 08:30. Five messages arrived over the weekend. The Desk leaves three
alone and opens a run for two. For a client's request it reads the thread
and three calendars, plans a booking and a confirmation, and waits. The
executive approves; the event is created in the sandbox and read back; the
confirmation follows. A second client asks for a time that is taken: the
Desk offers times free on every calendar instead. She picks one twenty
minutes later; the Desk books it and closes the follow-up. A colleague's
meeting is moved, not duplicated. An urgent decision becomes a task due
today. At the end of the day, 7 of 11 requests needed nothing from the
executive but approvals; two wrong proposals were stopped; one awaited reply
was missed. Storyboard and narration: [DEMO_STORYBOARD.md](DEMO_STORYBOARD.md).
No video has been recorded.
