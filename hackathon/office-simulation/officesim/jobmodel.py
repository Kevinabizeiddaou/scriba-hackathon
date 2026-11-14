"""The executive secretary's job, as the simulator models it.

Ten things the job-holder does, in order, for every piece of incoming work.
Each scenario step names the ones it exercises, each measurement is reported
against one of them, and each maps to the part of the Desk that is supposed
to do it. The mapping is to the Desk at the engine revision the simulator
was run against; "status" is what the simulator observed, not a plan.
"""
from __future__ import annotations

from typing import Dict, List

JOB = "Executive Inbox-to-Action Management"
JOB_STATEMENT = "Turn an executive's incoming correspondence into verified administrative outcomes."

JOB_STEPS: List[Dict[str, str]] = [
    {"id": "detect", "n": "1", "name": "Detect incoming work",
     "human": "Notices a new message in any of the executive's mailboxes.",
     "desk": "Background intake worker over the unified Gmail and Outlook inbox; one run per message (claims)."},
    {"id": "understand", "n": "2", "name": "Understand what is required",
     "human": "Reads the message and its thread; decides what kind of request it is.",
     "desk": "Triage and intent reading (rules; a model when one is configured)."},
    {"id": "prioritize", "n": "3", "name": "Prioritize",
     "human": "Decides what is urgent and what can wait.",
     "desk": "Triage priority and deadline urgency on the run and the task."},
    {"id": "gather", "n": "4", "name": "Gather information",
     "human": "Opens the calendars, the task list, earlier mail in the thread.",
     "desk": "Read steps recorded on the run: thread, every connected calendar, open tasks."},
    {"id": "coordinate", "n": "5", "name": "Coordinate people and time",
     "human": "Finds a time that works on every calendar; finds the meeting a change is about.",
     "desk": "Cross-calendar availability, conflict detection, free-slot search, target-event search."},
    {"id": "prepare", "n": "6", "name": "Prepare decisions",
     "human": "Puts a ready-to-approve action in front of the executive, with the reason.",
     "desk": "A typed plan and approval cards (Scriba action cards) with facts, assumptions and holds."},
    {"id": "execute", "n": "7", "name": "Execute authorized actions",
     "human": "Sends the reply, books, moves or cancels the meeting, writes the task.",
     "desk": "Scriba's approve path behind the Desk's execution gate; here, against the sandbox world."},
    {"id": "record", "n": "8", "name": "Record commitments",
     "human": "Notes deadlines, tasks and what was promised to whom.",
     "desk": "Tasks, reminders, follow-ups and the run's evidence timeline."},
    {"id": "chase", "n": "9", "name": "Chase outstanding replies",
     "human": "Tracks who has not answered and reminds them.",
     "desk": "Follow-ups on replies the Desk sent: waiting, satisfied, overdue, proposed nudge."},
    {"id": "report", "n": "10", "name": "Report completed and pending work",
     "human": "Tells the executive what was done, what is waiting and what is overdue.",
     "desk": "The Desk briefing, run list and lifecycle stages; the simulator's end-of-day report."},
]

STEP_IDS = [step["id"] for step in JOB_STEPS]

# What a human assistant would spend on each kind of outcome. THESE ARE
# ASSUMPTIONS written by the simulator's author for a rough order of
# magnitude. They were not measured from a real job-holder and must be
# replaced by the job-holder's own figures before being quoted as a result.
ASSUMED_HUMAN_MINUTES: Dict[str, float] = {
    "triage_message": 1.0,          # open, read, decide what it needs
    "schedule": 6.0,                # check calendars, book, write the confirmation
    "offer_times": 5.0,             # check calendars, find options, write the reply
    "reschedule": 5.0,              # find the meeting, check the new time, move it, confirm
    "cancel": 3.0,                  # find the meeting, cancel it, confirm
    "task": 2.0,                    # write the task with its deadline
    "reminder": 1.5,
    "close_follow_up": 1.0,         # notice the answer, tick it off
    "nudge": 3.0,                   # notice the silence, write the reminder
    "briefing": 15.0,               # assemble the end-of-day summary
}
# What the executive spends on one decision in the Desk (also an assumption).
ASSUMED_APPROVAL_MINUTES = 0.25


def step(step_id: str) -> Dict[str, str]:
    for entry in JOB_STEPS:
        if entry["id"] == step_id:
            return entry
    raise KeyError(step_id)
