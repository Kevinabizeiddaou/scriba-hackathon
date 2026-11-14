"""A time is read in full or not at all; an instruction taken back is not
carried out; a change is aimed at the meeting it names, or at none; a
reminder is not a meeting. Pure functions: no Scriba, no network."""
import datetime as dt

import pytest

from desk_overlay import planning, reading
from desk_overlay.triage import triage

UTC = dt.timezone.utc
MONDAY = dt.datetime(2026, 3, 9, 9, 0, tzinfo=UTC)


def start(text, now=MONDAY, **kw):
    found = reading.explicit_request(text, now, **kw)
    return found["requested_start"] if found else None


# ── a word beside the day or the zone ───────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Could we meet the day after tomorrow at noon?",
    "Could we meet the day before Thursday at 10:00?",
    "Could we meet on Thursday week at 10:00?",
    "Could we meet a week on Thursday at 10:00?",
    "Could we meet Tuesday after next at 10:00?",
    "Could we meet in two weeks on Tuesday at 10:00?",
    "Could we meet a fortnight from Tuesday at 10:00?",
    "Could we meet the following Tuesday at 10:00?",
    "Could we meet on Tuesday next week at 10:00?",
    "Could we meet at the end of the month, Tuesday at 10:00?",
])
def test_a_day_changed_by_a_word_beside_it_is_not_read(text):
    assert start(text) is None, text


def test_the_plain_forms_are_still_read():
    assert start("Could we meet tomorrow at 12:00?") == "2026-03-10T12:00:00+00:00"
    assert start("Could we meet on Thursday at 10:00?") == "2026-03-12T10:00:00+00:00"
    assert start("Could we meet next Thursday at 10:00?") == "2026-03-19T10:00:00+00:00"
    # A written date settles the week: "next week" beside it changes nothing.
    assert start("Could we meet next week, on 17 March at 10:00?") == "2026-03-17T10:00:00+00:00"


def test_an_offset_beside_a_zone_is_part_of_the_zone():
    assert start("Could we meet on Thursday at 11:00 GMT+3?") == "2026-03-12T11:00:00+03:00"
    assert start("Could we meet on Thursday at 11:00 UTC-5?") == "2026-03-12T11:00:00-05:00"
    assert start("Could we meet on Thursday at 11:00 GMT?") == "2026-03-12T11:00:00+00:00"
    assert start("Could we meet on Thursday at 11:00 UTC+0?") == "2026-03-12T11:00:00+00:00"
    # A half-hour offset has no zone this reader can name: the hour is not guessed.
    assert start("Could we meet on Thursday at 11:00 GMT+5:30?") is None
    assert reading.stated_zone("11:00 GMT+3") == ("Etc/GMT-3", False)


def test_a_weekday_that_does_not_match_its_date_is_not_read():
    assert start("Could we meet on Wednesday 10 March at 10:00?") is None      # the 10th is a Tuesday
    assert start("Could we meet on Wednesday, March 10 at 10:00?") is None
    assert start("Could we meet on Tuesday 10 March at 10:00?") == "2026-03-10T10:00:00+00:00"
    assert reading.weekday_contradicts_date("wednesday 10 march", MONDAY.date()) is True
    assert reading.weekday_contradicts_date("tuesday 10 march", MONDAY.date()) is False
    # A weekday elsewhere in the message is not a contradiction.
    assert start("I am away Monday. Could we meet on 10 March at 10:00?") == "2026-03-10T10:00:00+00:00"


# ── an instruction taken back ───────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Please cancel Thursday's call. On second thought, keep it.",
    "Cancel the review. Actually, keep it as planned.",
    "Move it to Friday. Scratch that.",
    "Please cancel the workshop. Never mind, I can make it.",
    "Cancel tomorrow's call. I changed my mind, please do not cancel it.",
])
def test_a_retraction_is_seen(text):
    assert reading.retracted(text) is True, text


@pytest.mark.parametrize("text", [
    "Please cancel Thursday's call.",
    "Could we move our review to Friday at 10:00?",
    "Keep me posted on the contract.",
    "I actually prefer Friday at 10:00.",
])
def test_an_ordinary_request_is_not_a_retraction(text):
    assert reading.retracted(text) is False, text


# ── new, or a change to a meeting that exists ───────────────────────────────

def test_a_message_that_speaks_of_an_existing_meeting_is_recognised():
    yes = ["Can we push Thursday's call back to Friday 13 March at 15:30?", "Would 11:00 work for the quarterly review instead?",
           "Could we shift our session to 14:00?", "Tomorrow's sync: can we do 16:00 rather than 10:00?"]
    no = ["Could we meet on Thursday at 10:00 for 30 minutes?", "Are you free on Friday at 14:00 for a quick chat?"]
    for text in yes:
        assert reading.refers_to_existing("", text) is True, text
    for text in no:
        assert reading.refers_to_existing("Intro", text) is False, text


def meeting(event_id, title, start_at, end_at, who="noor@client.example", status="confirmed"):
    return {"id": event_id, "title": title, "start": start_at, "end": end_at, "attendees": [who], "status": status}


NOW = dt.datetime(2026, 3, 9, 9, 0, tzinfo=UTC)
REVIEW = meeting("e1", "Quarterly review", "2026-03-11T10:00:00+00:00", "2026-03-11T11:00:00+00:00")
STANDUP_DONE = meeting("e2", "Leadership stand-up", "2026-03-09T07:30:00+00:00", "2026-03-09T08:00:00+00:00")
ONE_TO_ONE_CANCELLED = meeting("e3", "1:1 Priya", "2026-03-09T15:00:00+00:00", "2026-03-09T15:30:00+00:00", status="cancelled")
LAUNCH = meeting("e4", "Launch sync", "2026-03-12T10:00:00+00:00", "2026-03-12T10:30:00+00:00")


def target(events, subject, text="", **kw):
    return planning.find_target_events(events, sender="noor@client.example", subject=subject, text=text, now=NOW, **kw)


def test_a_meeting_that_is_over_or_cancelled_is_never_the_target():
    assert target([STANDUP_DONE], "Stand-up")["status"] == "target_gone"
    assert target([ONE_TO_ONE_CANCELLED], "Today's 1:1")["status"] == "target_gone"
    # The repeated cancellation of the office simulation: the 1:1 is gone and the
    # sender's only other meeting has already taken place. Neither is touched.
    found = target([ONE_TO_ONE_CANCELLED, STANDUP_DONE], "Today's 1:1")
    assert found["status"] == "target_gone" and found["candidates"] == []
    # A meeting still ahead does not stand in for the cancelled one the message names.
    found = target([ONE_TO_ONE_CANCELLED, REVIEW], "Today's 1:1")
    assert found["status"] == "target_gone" and [e["id"] for e in found["gone"]] == ["e3"]


def test_a_meeting_still_ahead_is_found_as_before():
    assert target([REVIEW], "Quarterly review")["event"]["id"] == "e1"
    assert target([REVIEW, STANDUP_DONE], "Running late")["event"]["id"] == "e1"
    assert target([REVIEW, LAUNCH], "Quarterly review")["event"]["id"] == "e1"
    assert target([REVIEW, LAUNCH], "Hello")["status"] == "ambiguous"
    assert target([], "Hello")["status"] == "sender_not_on_any_event"
    # Without a clock nothing is called over on time alone; cancelled is still cancelled.
    assert planning.find_target_events([STANDUP_DONE], sender="noor@client.example", subject="x")["status"] == "found"
    assert planning.find_target_events([ONE_TO_ONE_CANCELLED], sender="noor@client.example", subject="x")["status"] == "target_gone"


def test_a_named_meeting_that_is_not_on_the_calendar_is_not_replaced_by_another():
    found = target([LAUNCH], "Thursday", "Unfortunately I have to cancel our pricing workshop on Thursday.")
    assert found["status"] == "named_not_found" and found["named"] == ["pricing"]
    # The name is on the calendar: found.
    assert target([LAUNCH], "Thursday", "I have to cancel our launch sync on Thursday.")["event"]["id"] == "e4"
    # Days, times and generic words name nothing, so the sender's one meeting is still the one.
    for text in ("Please cancel our call.", "Please cancel our Thursday call.", "Please cancel the 10:00 meeting.",
                 "Please cancel our weekly sync.", "I can't make it tomorrow."):
        assert target([LAUNCH], "Change", text)["status"] == "found", text
    assert planning.named_meeting("our pricing workshop and the budget review") == {"pricing", "budget"}


# ── a reminder is not a meeting ─────────────────────────────────────────────

def test_a_request_to_be_reminded_is_work_to_record_not_a_meeting_with_the_writer():
    item = {"subject": "Chairman", "body": "Please remind yourself on Wednesday at 09:00 to call the chairman."}
    record = triage(item, {"classification": "requires_reply", "priority": "medium", "reasons": ["meeting_request"]})
    assert record["category"] == "action_item" and "meeting_intent" not in record
    assert "desk_reminder_requested" in record["reasons"] and "meeting_request" not in record["reasons"]
    plain = triage({"subject": "Intro", "body": "Could we meet on Wednesday at 09:00 for 30 minutes?"},
                   {"classification": "requires_reply", "priority": "medium", "reasons": []})
    assert plain["category"] == "meeting_request" and plain["meeting_intent"] == "new"
