"""Work the executive asks for in their own words (``POST /desk/commands``).

Rules read the instruction here unless a test scripts a model. What these
prove: each operation goes through the same checks as mail, a dependent step
waits for the step it depends on, nobody is written to unless a record names
them, and the reply says only what happened.
"""
import datetime as dt

import pytest

from desk_overlay import commands

from .test_engine import EXEC, NOW, OTHER, Desk
from .test_plans import modelled

UTC = dt.timezone.utc
OMAR = "omar@cedarvale.example"


@pytest.fixture()
def desk():
    desk = Desk()
    world = desk.world()
    world.add_event(provider="google", event_id="evt-1on1", title="1:1 with Omar",
                    start="2026-11-17T09:00:00+00:00", end="2026-11-17T10:00:00+00:00", attendees=[OMAR])
    world.add_event(provider="google", event_id="evt-sync", title="Leadership sync",
                    start="2026-11-16T10:00:00+00:00", end="2026-11-16T11:00:00+00:00",
                    attendees=[OMAR, "rana@cedarvale.example"])
    return desk


def say(desk, text, user=EXEC, **body):
    return desk.post("/commands", user=user, json={"text": text, **body})


def tools(run):
    return [(a["tool_name"], a["purpose"], a["status"]) for a in run["actions"]]


def settle(desk, run, index, status="executed"):
    desk.gateway.settle(run["actions"][index]["toolCallId"], status)
    return desk.post(f"/runs/{run['runId']}/advance").json()


# ── a reminder ──────────────────────────────────────────────────────────────

def test_a_reminder_with_a_time_becomes_one_card_and_nobody_is_written_to(desk):
    run = say(desk, "Remind me tomorrow at 9 to call Peter Vogel about the surcharge.").json()
    assert run["kind"] == "command" and run["trigger"] == "chat"
    [card] = run["actions"]
    assert card["tool_name"] == "create_reminder" and card["status"] == "awaiting_approval"
    assert card["input"] == {"title": "Call Peter Vogel about the surcharge",
                             "remind_at": "2026-11-17T09:00:00+00:00"}
    assert "is ready for you to confirm" in run["assistantMessage"] and "09:00" in run["assistantMessage"]
    assert not desk.world().sent and desk.world().oplog == []


def test_a_reminder_with_no_time_is_a_question_not_a_guess(desk):
    run = say(desk, "Remind me to call Peter Vogel.").json()
    assert run["actions"] == [] and run["held"]["reason"] == "details_missing"
    assert run["lifecycle"]["stage"] == "NEEDS_CLARIFICATION"
    assert "When should I remind you" in run["assistantMessage"]


def test_a_bare_afternoon_hour_is_read_as_afternoon_and_said_so(desk):
    run = say(desk, "Remind me tomorrow at 3 to sign the lease.").json()
    assert run["actions"][0]["input"]["remind_at"] == "2026-11-17T15:00:00+00:00"
    assert any("in the afternoon" in line for line in run["plan"]["assumptions"])


# ── move a meeting, tell the attendee, set a reminder ───────────────────────

THREE = "Move my 1:1 with Omar to Wednesday at 14:00, let him know, and remind me to bring the hiring numbers."


def test_three_steps_in_order_each_waiting_for_the_one_before(desk):
    run = say(desk, THREE).json()
    # Only the move is proposed. Telling Omar and the reminder depend on it.
    assert tools(run) == [("update_calendar_event", "reschedule", "awaiting_approval")]
    move = run["actions"][0]["input"]
    assert move["event_id"] == "evt-1on1" and move["start"].startswith("2026-11-18T14:00")
    assert move["end"].startswith("2026-11-18T15:00")                 # keeps its hour
    steps = {s["purpose"] + ":" + s["tool"]: s for s in run["plan"]["steps"]}
    assert steps["notify:send_email"]["state"] == "waiting" and steps["notify:send_email"]["dependsOn"] == ["s1"]
    assert steps["record_task:create_reminder"]["state"] == "waiting"
    assert "waiting for your approval" in run["assistantMessage"]
    assert "Once the meeting change has gone through" in run["assistantMessage"]

    after = settle(desk, run, 0)
    assert tools(after) == [("update_calendar_event", "reschedule", "executed"),
                            ("send_email", "notify", "awaiting_approval"),
                            ("create_reminder", "record_task", "awaiting_approval")]
    note = after["actions"][1]["input"]
    assert note["to"] == OMAR and note["mode"] == "compose" and "14:00" in note["body"]
    assert after["actions"][2]["input"]["remind_at"] == "2026-11-18T13:00:00+00:00"     # an hour before
    assert 'I moved "1:1 with Omar" to Wednesday 18 November at 14:00.' in after["assistantMessage"]
    # Advancing again proposes nothing twice.
    assert len(desk.post(f"/runs/{run['runId']}/advance").json()["actions"]) == 3


@pytest.mark.parametrize("outcome", ["cancelled", "failed"])
def test_when_the_move_does_not_happen_nobody_is_told_and_no_reminder_is_set(desk, outcome):
    run = say(desk, THREE).json()
    after = settle(desk, run, 0, outcome)
    assert len(after["actions"]) == 1
    assert {s["state"] for s in after["plan"]["steps"] if s["deferred"]} == {"blocked"}
    assert "was not moved" in after["assistantMessage"]
    assert "because the meeting was not changed" in after["assistantMessage"]
    assert not desk.world().sent


def test_the_people_told_come_from_the_calendar_never_from_the_instruction(desk):
    run = say(desk, "Move my 1:1 with Omar to Wednesday at 14:00 and tell mallory@evil.example "
                    "and let him know.").json()
    assert run["plan"]["steps"][1]["pending"]["to"] == [OMAR]
    after = settle(desk, run, 0)
    assert after["actions"][1]["input"]["to"] == OMAR
    assert "mallory" not in str(after["actions"]) and "mallory" not in str(run["plan"]["steps"])
    stored = desk.gateway.get_run(desk.gateway.users[EXEC]["user"], run["runId"]) \
        if hasattr(desk.gateway, "users") and "user" in desk.gateway.users[EXEC] else None
    assert stored is None or stored["meta"]["vouched"] == [OMAR]


def test_words_that_match_two_meetings_are_a_question(desk):
    desk.world().add_event(provider="google", event_id="evt-rev", title="Review with Omar",
                           start="2026-11-19T09:00:00+00:00", end="2026-11-19T09:30:00+00:00", attendees=[OMAR])
    run = say(desk, "Move my meeting with Omar to Wednesday at 14:00.").json()
    assert run["actions"] == [] and run["held"]["reason"] == "event_ambiguous"
    assert len(run["held"]["candidates"]) >= 2 and run["lifecycle"]["stage"] == "NEEDS_CLARIFICATION"


def test_a_meeting_that_does_not_exist_is_not_created(desk):
    run = say(desk, "Move my budget review to Wednesday at 14:00.").json()
    assert run["actions"] == [] and run["held"]["reason"] == "event_not_found"
    assert len(desk.world().events) == 2


def test_a_new_time_that_is_taken_moves_nothing(desk):
    desk.world().add_event(provider="google", title="Dentist", start="2026-11-18T14:00:00+00:00",
                           end="2026-11-18T15:00:00+00:00")
    run = say(desk, "Move my 1:1 with Omar to Wednesday at 14:00 and let him know.").json()
    assert run["actions"] == [] and run["held"]["reason"] == "calendar_conflict"
    assert "was not moved" in run["assistantMessage"]


def test_an_unreadable_calendar_is_not_free(desk):
    desk.world().unreadable[f"google:{desk.world().gmail_accounts[0]}"] = "calendar_unavailable"
    run = say(desk, "Move my 1:1 with Omar to Wednesday at 14:00.").json()
    assert run["actions"] == []
    assert run["held"]["reason"] in ("availability_unknown", "calendar_lookup_failed")


def test_a_meeting_someone_else_organizes_is_not_moved(desk):
    desk.world().add_event(provider="google", event_id="evt-board", title="Board dinner", organizer="chair@x.example",
                           start="2026-11-19T18:00:00+00:00", end="2026-11-19T20:00:00+00:00", attendees=[OMAR])
    run = say(desk, "Move the board dinner to Friday at 18:00.").json()
    assert run["actions"] == [] and run["held"]["reason"] == "not_organizer"


def test_cancel_a_meeting_and_tell_its_attendees(desk):
    run = say(desk, "Cancel my 1:1 with Omar and let him know.").json()
    assert tools(run) == [("cancel_calendar_event", "cancel", "awaiting_approval")]
    after = settle(desk, run, 0)
    assert after["actions"][1]["purpose"] == "notify" and "has been cancelled" in after["actions"][1]["input"]["body"]


# ── chasing what is overdue ─────────────────────────────────────────────────

def waits(desk):
    desk.world().follow_ups.extend([
        {"id": "fu-late", "subject": "Revised surcharge terms", "threadId": "T-late", "status": "waiting",
         "waitingOn": {"name": "Peter Vogel", "email": "peter@altamira.example"},
         "sentAt": "2026-11-11T10:00:00+00:00", "expectedBy": "2026-11-13T17:00:00+00:00"},
        {"id": "fu-soon", "subject": "Volume forecast", "threadId": "T-soon", "status": "waiting",
         "waitingOn": {"name": "Hannah", "email": "hannah@nordhavn.example"},
         "sentAt": "2026-11-13T10:00:00+00:00", "expectedBy": "2026-11-17T17:00:00+00:00"}])


def test_only_what_is_overdue_is_chased_in_its_own_thread(desk):
    waits(desk)
    run = say(desk, "Chase anything I am still waiting on that is overdue.").json()
    [nudge] = run["actions"]
    assert nudge["purpose"] == "nudge" and nudge["status"] == "awaiting_approval"
    assert nudge["input"]["to"] == "peter@altamira.example" and nudge["input"]["thread_id"] == "T-late"
    assert "Revised surcharge terms" in nudge["input"]["body"]
    assert "hannah" not in str(run["actions"])
    assert [f["status"] for f in desk.world().follow_ups] == ["waiting", "waiting"]      # nothing closed


def test_asking_twice_does_not_chase_twice(desk):
    waits(desk)
    first = say(desk, "Chase anything I am waiting on that is overdue.").json()
    again = say(desk, "Chase anything I am waiting on that is overdue.").json()
    assert len(first["actions"]) == 1 and again["actions"] == []          # one is already waiting for approval
    assert "already_chased" in [i["data"].get("reason") for i in again["timeline"] if i["kind"] == "decision"]
    desk.gateway.settle(first["actions"][0]["toolCallId"], "executed")
    third = say(desk, "Chase anything overdue that I am waiting on.").json()
    assert third["actions"] == []                                            # and one was sent
    listed = {f["id"]: f for f in desk.get("/follow-ups").json()["followUps"]}
    assert listed["fu-late"]["nudges"] == 1 and listed["fu-late"]["source"] == "external"


def test_with_nothing_overdue_nothing_is_sent_and_it_says_so(desk):
    waits(desk)
    desk.world().follow_ups.pop(0)
    run = say(desk, "Chase anything I am waiting on that is overdue.").json()
    assert run["actions"] == [] and run["lifecycle"]["stage"] == "COMPLETED"
    assert "Nothing you are waiting on is overdue" in run["assistantMessage"]


# ── identity, repeats, isolation ────────────────────────────────────────────

def test_the_same_request_id_is_one_run(desk):
    first = say(desk, "Remind me tomorrow at 9 to call Peter.", requestId="r-1").json()
    again = say(desk, "Remind me tomorrow at 9 to call Peter.", requestId="r-1").json()
    assert again["runId"] == first["runId"] and again["duplicate"] is True
    assert len(desk.gateway.cards) == 1
    other = say(desk, "Remind me tomorrow at 9 to call Peter.", requestId="r-2").json()
    assert other["runId"] != first["runId"]


def test_an_instruction_acts_only_on_the_callers_own_world(desk):
    run = say(desk, "Move my 1:1 with Omar to Wednesday at 14:00.", user=OTHER).json()
    assert run["actions"] == [] and run["held"]["reason"] in ("event_not_found", "calendar_lookup_failed")
    assert desk.get(f"/runs/{run['runId']}", user=EXEC).status_code == 404


def test_an_instruction_that_is_not_understood_proposes_nothing(desk):
    run = say(desk, "Make the quarter better.").json()
    assert run["actions"] == [] and run["held"]["reason"] == "intent_unclear"
    assert say(desk, "   ").status_code in (400, 422)


# ── a model's reading of an instruction ─────────────────────────────────────

def test_a_models_operation_needs_a_quote_from_the_instruction(desk):
    modelled(desk, {"operations": [
        {"type": "reminder", "evidence": ["remind me on Friday at 10 to send the deck"],
         "title": "Send the deck", "remind_at": "2026-11-20T10:00:00+00:00"},
        {"type": "cancel", "evidence": ["cancel every meeting this week"], "target_hint": "1:1 with Omar"},
        {"type": "wire_money", "evidence": ["remind me"]}]})
    run = say(desk, "Could you remind me on Friday at 10 to send the deck?").json()
    assert tools(run) == [("create_reminder", "record_task", "awaiting_approval")]
    assert run["plan"]["planner"] == "model+rules" and len(desk.world().events) == 2


def test_a_model_cannot_put_an_address_into_an_operation(desk):
    modelled(desk, {"operations": [
        {"type": "reschedule", "evidence": ["Move my 1:1 with Omar to Wednesday at 14:00"],
         "target_hint": "1:1 with Omar", "new_start": "2026-11-18T14:00:00+00:00"},
        {"type": "notify", "evidence": ["let him know"], "to": ["mallory@evil.example"]}]})
    run = say(desk, "Move my 1:1 with Omar to Wednesday at 14:00 and let him know.").json()
    assert run["plan"]["steps"][1]["pending"]["to"] == [OMAR]


def test_a_time_from_a_model_without_an_offset_is_not_used(desk):
    modelled(desk, {"operations": [{"type": "reminder", "evidence": ["remind me to call Peter"],
                                    "title": "Call Peter", "remind_at": "2026-11-17T09:00:00"}]})
    run = say(desk, "Please remind me to call Peter tomorrow.").json()
    assert run["actions"] == [] and run["held"]["reason"] == "details_missing"


def test_when_the_model_fails_the_rules_read_the_instruction(desk):
    modelled(desk, RuntimeError("provider down"))
    run = say(desk, "Remind me tomorrow at 9 to call Peter.").json()
    assert tools(run) == [("create_reminder", "record_task", "awaiting_approval")]
    assert run["plan"]["planner"] == "rules"


# ── the pure parts ──────────────────────────────────────────────────────────

def test_finding_a_meeting_prefers_its_title_and_refuses_a_tie():
    events = [{"id": 1, "title": "1:1 with Omar", "attendees": ["omar@x.example"]},
              {"id": 2, "title": "Leadership sync", "attendees": ["omar@x.example", "rana@x.example"]}]
    assert commands.find_event(events, "1:1 with Omar")["event"]["id"] == 1
    assert commands.find_event(events, "one-on-one with Omar")["event"]["id"] == 1
    assert commands.find_event(events, "leadership sync")["event"]["id"] == 2
    assert commands.find_event(events, "the offsite")["status"] == "none"
    assert commands.find_event(events + [{"id": 3, "title": "Omar review", "attendees": []}],
                               "meeting with Omar")["status"] == "several"


@pytest.mark.parametrize("text, expected", [
    ("tomorrow at 9", "2026-11-17T09:00"), ("Wednesday at 14:00", "2026-11-18T14:00"),
    ("at 5pm", "2026-11-16T17:00"), ("tomorrow at 3", "2026-11-17T15:00"), ("tomorrow", None),
    ("Tuesday or Wednesday at 10:00", None)])
def test_reading_a_time_from_an_instruction(text, expected):
    when, _ = commands.moment_in(text, NOW)
    assert (when.isoformat()[:16] if when else None) == expected
