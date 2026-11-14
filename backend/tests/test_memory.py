"""The Desk's memory is a read of records, and a repeated request is
recognised from it.
"""
import datetime as dt

import pytest

from desk_overlay import memory
from desk_overlay.sandbox import SandboxWorld

from .test_engine import EXEC, NOW, OTHER, SOFIA, TUE10, Desk, book_plan, meeting_mail
from .test_plans import modelled

UTC = dt.timezone.utc
ASK = "Could we meet Tuesday at 10:00 for 30 minutes to go over the launch plan?"
AGAIN = "Hi,\n\nResending in case this got buried: could we meet Tuesday at 10:00 for 30 minutes to go over the launch plan?\n\nThanks"


@pytest.fixture()
def desk():
    return Desk()


def first_request(desk):
    meeting_mail(desk, body=ASK)
    desk.plan(book_plan())
    return desk.intake("m1").json()


def second(desk, body=AGAIN, sender=SOFIA, message_id="m2"):
    desk.world().deliver(message_id=message_id, from_addr=sender, subject="Re: Intro call next week?", body=body,
                         thread_id="T-m1", received_at=NOW + dt.timedelta(hours=2))
    return desk.intake(message_id).json()


# ── a request that was already made ─────────────────────────────────────────

def test_the_same_request_again_while_the_first_waits_becomes_no_second_card(desk):
    first = first_request(desk)
    assert [a["status"] for a in first["actions"]] == ["awaiting_approval"]
    again = second(desk)
    assert again["actions"] == [] and again["flags"] == ["duplicate"]
    assert again["held"]["reason"] == "already_in_progress" and again["held"]["target"]["runId"] == first["runId"]
    assert again["lifecycle"]["stage"] == "COMPLETED" and again["lifecycle"]["reason"] == "already_in_progress"
    assert len(desk.gateway.cards) == 1


def test_after_the_first_was_done_the_repeat_is_reported_as_handled(desk):
    first = first_request(desk)
    desk.gateway.settle(first["actions"][0]["toolCallId"], "executed")
    done = desk.post(f"/runs/{first['runId']}/advance").json()
    desk.gateway.settle(done["actions"][1]["toolCallId"], "executed")
    again = second(desk)
    assert again["actions"] == [] and "duplicate" in again["flags"]
    assert again["held"]["reason"] in ("already_handled", "already_in_progress", "already_scheduled")


def test_asking_again_after_a_rejection_is_a_new_request(desk):
    first = first_request(desk)
    desk.gateway.settle(first["actions"][0]["toolCallId"], "cancelled")
    again = second(desk)
    assert [a["tool_name"] for a in again["actions"]] == ["create_calendar_event"]
    assert again["flags"] == []


def test_a_different_request_in_the_same_conversation_is_not_a_repeat(desk):
    first_request(desk)
    desk.plan({"calendar_action": "create", "requested_start": "2026-11-19T15:00:00+00:00",
               "requested_end": "2026-11-19T15:30:00+00:00"})
    other = second(desk, body="Separately: could we also meet Thursday at 15:00 for 30 minutes about the budget?")
    assert [a["tool_name"] for a in other["actions"]] == ["create_calendar_event"] and other["flags"] == []


def test_the_same_words_from_someone_else_are_not_a_repeat(desk):
    first_request(desk)
    other = second(desk, sender="Omar <omar@client.example>")
    assert other["flags"] == [] and other["held"] is None or other["held"]["reason"] != "already_in_progress"


def test_a_repeat_of_a_message_the_desk_never_took_in_is_handled_normally(desk):
    meeting_mail(desk, body=ASK)                     # delivered, never taken in
    desk.plan(book_plan())
    again = second(desk)
    assert [a["tool_name"] for a in again["actions"]] == ["create_calendar_event"] and again["flags"] == []


def test_words_that_carry_the_request():
    assert memory.same_request(ASK, AGAIN)
    assert memory.same_request(ASK, AGAIN + "\n\nOn Mon, Sofia wrote:\n> something entirely different and long")
    assert not memory.same_request(ASK, "Could we meet Thursday at 15:00 for an hour about the budget review?")
    assert not memory.same_request("Thanks!", "Thanks!")            # too little to call a request


# ── the snapshot ────────────────────────────────────────────────────────────

def test_the_snapshot_is_read_from_records(desk):
    world = desk.world()
    world.add_event(provider="google", title="Launch review", start=TUE10[0], end=TUE10[1],
                    attendees=["sofia@client.example"])
    world.tasks.append({"id": "t1", "title": "Sign the lease", "status": "open", "due_at": "2026-11-14T17:00:00+00:00"})
    world.follow_ups.append({"id": "fu-1", "subject": "Terms", "threadId": "T-x", "status": "waiting",
                             "waitingOn": {"email": "peter@altamira.example"},
                             "expectedBy": "2026-11-13T17:00:00+00:00"})
    desk.plan({"calendar_action": "create", "requested_start": "2026-11-18T09:00:00+00:00",
               "requested_end": "2026-11-18T09:30:00+00:00"})
    meeting_mail(desk, body="Could we meet Wednesday at 09:00 for 30 minutes?")
    run = desk.intake("m1").json()

    snapshot = desk.get("/memory").json()
    assert [m["title"] for m in snapshot["meetings"]["items"]] == ["Launch review"]
    assert snapshot["tasks"]["items"] == [{"id": "t1", "title": "Sign the lease",
                                           "dueAt": "2026-11-14T17:00:00+00:00", "overdue": True}]
    assert [(w["id"], w["state"]) for w in snapshot["waiting"]["items"]] == [("fu-1", "overdue")]
    assert [(p["runId"], p["tool"]) for p in snapshot["pending"]["items"]] == [(run["runId"], "create_calendar_event")]
    assert snapshot["done"]["items"] == []

    desk.gateway.settle(run["actions"][0]["toolCallId"], "executed")
    after = desk.get("/memory", ).json()
    assert [d["tool"] for d in after["done"]["items"]] == ["create_calendar_event"] and after["pending"]["items"] == []
    by_thread = desk.client.get("/desk/memory", params={"thread": "T-other"}, headers={"x-test-user": EXEC}).json()
    assert by_thread["runs"]["items"] == [] and by_thread["scope"]["threadId"] == "T-other"
    by_sender = desk.client.get("/desk/memory", params={"sender": "Sofia@Client.example"},
                                headers={"x-test-user": EXEC}).json()
    assert [m["title"] for m in by_sender["meetings"]["items"]] == ["Launch review"]


def test_a_part_that_cannot_be_read_is_unknown_not_empty(desk):
    desk.world().tasks.append({"id": "t1", "title": "Sign the lease", "status": "open"})

    def broken(*args, **kwargs):
        raise RuntimeError("tasks unavailable")
    desk.router.desk["gateway"].open_tasks = broken
    snapshot = desk.get("/memory").json()
    assert snapshot["tasks"] == {"ok": False, "items": [], "error": "RuntimeError"}
    assert snapshot["meetings"]["ok"] is True


def test_memory_is_per_user_and_per_world(desk):
    first_request(desk)
    assert desk.get("/memory", user=OTHER).json()["runs"]["items"] == []
    assert len(desk.get("/memory").json()["runs"]["items"]) == 1
    # The same person in another world sees none of this world's history.
    user = desk.gateway.users[EXEC]["user"]
    other_world = desk.registry.add(SandboxWorld("elsewhere", owner_email=EXEC, now=NOW,
                                                 gmail_accounts=["exec@gmail.example"]))
    with desk.registry.using(other_world):
        assert desk.workflow.runs_in_scope(user) == []
        assert desk.workflow.follow_ups(None, user, refresh=False)["followUps"] == []


def test_the_model_step_is_shown_the_records_as_facts():
    from .test_agent import Desk as AgentDesk, EXEC as AGENT_EXEC

    desk = AgentDesk()
    desk.world.tasks.append({"id": "t1", "title": "Send the cut-off dates to Hannah", "status": "open"})
    desk.world.add_event(provider="google", title="Rates call", start="2026-11-17T10:00:00+00:00",
                         end="2026-11-17T10:30:00+00:00", attendees=["hannah@nordhavn.example"])
    desk.script({"step": "final", "explanation": "x", "proposals": []})
    desk.mail("Could you confirm whether the revised payment terms are acceptable?")
    content = desk.gateway.model_calls[0]["messages"][1]["content"]
    assert '"records"' in content and "Send the cut-off dates to Hannah" in content and "Rates call" in content
    assert AGENT_EXEC


def test_understanding_and_memory_do_not_break_when_the_model_reads_several_things(desk):
    modelled(desk, {"intents": []})
    assert first_request(desk)["actions"]


def test_a_resend_after_the_first_attempt_was_only_handed_over_is_handled_afresh(desk):
    """Found by Agent 4's simulation: the first request met an unreadable
    calendar and was handed over with nothing proposed. The resend, when the
    calendar could be read again, was dismissed as "already in progress"."""
    account = f"google:{desk.world().gmail_accounts[0]}"
    desk.world().unreadable[account] = "calendar_unavailable"
    meeting_mail(desk, body=ASK)
    desk.plan(book_plan())
    first = desk.intake("m1").json()
    assert first["actions"] == [] and first["lifecycle"]["stage"] in ("ESCALATED", "NEEDS_CLARIFICATION")
    desk.world().unreadable.clear()
    again = second(desk)
    assert [a["tool_name"] for a in again["actions"]] == ["create_calendar_event"]
    assert again["flags"] == [] and again["held"] is None
