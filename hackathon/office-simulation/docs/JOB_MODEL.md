# The job, and the office it is simulated in

The index card names one job: **Executive Inbox-to-Action Management**: turn
an executive's incoming correspondence into verified administrative
outcomes. This document says what that job consists of, how the simulator
models it, and who is in the fictional office. It is the basis of every
scenario, measurement and demonstration in this folder.

The job-holder on the index card is still a placeholder to be supplied by
the project lead. Nothing here was observed from a real job-holder.

## What an executive assistant does with incoming work

Scheduling is one part of it. For every message, the assistant does ten
things, in this order. `officesim/jobmodel.py` holds the same list; every
scenario step names the ones it exercises.

| # | Step | What the person does | The part of the Desk that is meant to do it |
| --- | --- | --- | --- |
| 1 | Detect incoming work | Notices a new message in any of the executive's mailboxes | Background intake worker over Gmail and Outlook; one run per message |
| 2 | Understand what is required | Reads the message and its thread; decides what kind of request it is | Triage and intent reading (rules; a model when configured) |
| 3 | Prioritize | Decides what is urgent and what can wait | Triage priority; deadline urgency on the task |
| 4 | Gather information | Opens the calendars, the task list, earlier mail | Read steps recorded on the run: thread, every calendar, open tasks |
| 5 | Coordinate people and time | Finds a time that works everywhere; finds the meeting a change is about | Cross-calendar availability, conflict detection, free-slot search, target-event search |
| 6 | Prepare decisions | Puts a ready-to-approve action in front of the executive, with the reason | The typed plan and approval cards, with facts, assumptions and holds |
| 7 | Execute authorized actions | Sends the reply; books, moves or cancels; writes the task | Scriba's approve path behind the Desk's execution gate |
| 8 | Record commitments | Notes deadlines, tasks and promises | Tasks, reminders, follow-ups, the run's evidence timeline |
| 9 | Chase outstanding replies | Tracks who has not answered and reminds them | Follow-ups on replies the Desk sent: waiting, satisfied, overdue, proposed reminder |
| 10 | Report | Tells the executive what was done, what waits, what is overdue | The Desk briefing, run list and lifecycle stages |

How well each step is done today, on rules alone, is measured in
[../evidence/RESULTS.md](../evidence/RESULTS.md) and discussed in
[FINDINGS.md](FINDINGS.md). In short: steps 1, 4, 5, 6 and 7 are the Desk's
strong part; step 2 is brittle to wording; steps 9 and 10 have gaps.

## What "done" means for one message

Taken from the index card and made checkable:

- The message ends in exactly one recorded outcome: replied, scheduled,
  turned into a task or reminder, tracked as a follow-up, or deliberately
  left alone.
- A reply goes to the person who wrote, in the original thread, from the
  mailbox that received the message, and says what was really done.
- The calendar shows exactly the agreed event or change, on the right
  account, with no double booking across Google and Outlook.
- Nothing is sent and no calendar is written without the executive's approval.
- Each action is verified against the provider's state.
- Nobody has to repair anything afterwards. An approval is not a repair.

The oracle (`officesim/oracle.py`) checks each of these against the sandbox
world's state. The last one is measured through the simulated executive's
decision log.

## Who decides what

| Decision | Who |
| --- | --- |
| What a message asks for, which meeting it is about, which times are free | The Desk |
| Whether anything is sent or a calendar is changed | The executive, per action |
| Declining a meeting, preferring another time or deadline | The executive (her own choice; not an agent failure) |
| Catching a wrong proposal | The executive (counted against the agent as a manual rescue) |
| Retrying after a provider failure | The executive (counted separately) |
| Anything the Desk cannot verify or tie to one meeting | Handed to the executive by the Desk |

## The fictional office

Defined in `officesim/office.py`, with deterministic ids. The same seed and
week always give the same office (its fingerprint is recorded in every
evidence file). The week is anchored on Monday 16 November 2026 in
`Europe/Paris`; working hours 09:00 to 18:00, Monday to Friday; default
meeting length 30 minutes.

**Meridian Freight Partners**, a mid-sized European freight forwarder.

| Role | Who |
| --- | --- |
| The executive | Layla Mansour, Chief Executive Officer |
| The role being automated | Executive Assistant to the CEO |
| Colleagues | Omar Haddad (CFO), Priya Nair (COO), Jonas Weber (Head of Sales), Elena Petrova (General Counsel), Sam Okoye (Chief of Staff) |
| Clients | Greta Lindqvist (Nordlicht Retail), Daniel Okafor (Atlas Pharma), Mei Tanaka (Brightwave Foods) |
| Suppliers and partners | Karim Saad (Harbor Crane Services), Ingrid Solberg (Bluewater Shipping), Tomas Vega (Kestrel Insurance), Rafael Costa (Lumen Audit), Hannah Schmidt (Port Alliance), Nora Aziz (Verde Mobility), Yusuf Demir (Anatolia Cargo, a prospect) |
| Not people | A trade newsletter, a travel booking system, an unknown outreach sender, an opposing lawyer |

**Three mailboxes and three calendars:**

| Account | Provider | Used for |
| --- | --- | --- |
| `layla.mansour@meridianfreight.example` | Gmail, Google Calendar | The company |
| `layla@mansour-advisory.example` | Gmail, Google Calendar (second Google account) | Advisory work |
| `layla.mansour@portalliance.example` | Outlook Mail, Outlook Calendar | A board seat at Port Alliance |

The Desk is signed in as Scriba's seeded test user (`alice@example.com`);
the three accounts above are that user's connected mailboxes in the sandbox.

**The week's calendar at 08:00 on Monday** (eleven meetings):

| When | Meeting | With | Calendar |
| --- | --- | --- | --- |
| Mon 09:00 | Leadership stand-up | Omar, Priya, Jonas | Google, company |
| Mon 11:00 | Nordlicht quarterly review | Greta | Google, company |
| Mon 15:00 | 1:1 Priya Nair | Priya | Google, company |
| Tue 10:00 | Atlas Pharma contract negotiation | Daniel, Elena | Google, company |
| Tue 14:00 | Budget review FY27 | Omar | Google, company |
| Tue 16:00 | Port Alliance board meeting (organized by Hannah) | Hannah | Outlook |
| Wed 09:30 | Sales pipeline review | Jonas | Google, company |
| Wed 16:00 | Advisory session: Verde Mobility | Nora | Google, advisory |
| Thu 09:00 | Port Alliance safety committee | Hannah | Outlook |
| Thu 13:00 | Bluewater partnership sync | Ingrid | Google, company |
| Fri 10:00 | Insurance renewal call | Tomas | Google, company |

**Also in place:** three open tasks with deadlines and one finished task, one
reminder, and two replies the executive is already waiting for (a crane
maintenance quote from Karim, audit documents from Rafael), each with the
message she sent in the world's sent mail.

Identity is preserved throughout a day: a person is one address, a meeting
is one event id, a conversation is one thread id. A request to move a
meeting must move that event; the oracle checks that no second one appears.
