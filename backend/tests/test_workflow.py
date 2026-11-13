"""The Desk workflow for one incoming email, against a scripted gateway.

Approval and execution are simulated here (``gateway.settle``): these tests
cover what the Desk decides to propose and when. The real approve route and
execution engine are exercised in tests/integration/test_workflow_with_scriba.py.
"""
import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from desk_overlay.availability import Busy
from desk_overlay.routes import build_router

from .fakes import FakeGateway, at, email

MON = "2026-11-16"
TUE = "2026-11-17"
EXEC = "exec@example.test"
OTHER = "other@example.test"
NOW = dt.datetime(2026, 11, 16, 6, 0, tzinfo=dt.timezone.utc)
MEETING = email("m1", "Intro call next week?", "Could we meet Tuesday at 11:00 for 30 minutes?",
                from_addr="Sofia Marchetti <sofia@client.example>", thread="T-m1")
PLAN = {"calendar_action": "create", "summary": "Intro call: Lumen Events",
        "requested_start": f"{TUE}T11:00:00+00:00", "requested_end": f"{TUE}T11:30:00+00:00",
        "attendees": ["sofia@client.example", "boss@elsewhere.example"]}


@pytest.fixture()
def world():
    gateway = FakeGateway()
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example", gmail_mail=True)
    gateway.add_user(2, OTHER, google=["other@gmail.example"], gmail_mail=True)
    app = FastAPI()
    app.include_router(build_router(gateway, now=lambda: NOW))
    return gateway, TestClient(app)


def intake(client, item_id, user=EXEC, provider="gmail"):
    return client.post("/desk/intake", json={"provider": provider, "id": item_id},
                       headers={"x-test-user": user})


def get_run(client, run_id, user=EXEC):
    return client.get(f"/desk/runs/{run_id}", headers={"x-test-user": user})


def advance(client, run_id, user=EXEC):
    return client.post(f"/desk/runs/{run_id}/advance", headers={"x-test-user": user})


# ── case 2: actionable email -> task proposal ──────────────────────────────

def test_an_actionable_email_becomes_one_task_proposal_awaiting_approval(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [
        email("a1", "Board pack", "Please note the deadline is Friday.", from_addr="Omar <omar@client.example>")]
    run = intake(client, "a1").json()
    assert run["category"] == "action_item" and run["state"] == "awaiting_approval"
    assert [a["tool_name"] for a in run["actions"]] == ["create_task"]
    action = run["actions"][0]
    assert action["input"]["title"] == "Board pack" and "omar@client.example" in action["input"]["description"]
    assert action["requiresApproval"] is True and action["verified"] is False
    assert action["approve"] == {"method": "POST", "path": f"/chat/tool-calls/{action['toolCallId']}/approve"}


def test_the_task_is_verified_only_after_scriba_records_the_executed_action(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [email("a1", "Board pack", "The deadline is Friday.")]
    run = intake(client, "a1").json()
    gateway.settle(run["actions"][0]["toolCallId"], "executed")
    after = get_run(client, run["runId"]).json()
    assert after["state"] == "completed"
    assert after["actions"][0]["verified"] is True and after["actions"][0]["assistantActionId"]
    assert after["actions"][0]["approve"] is None


def test_a_rejected_proposal_leaves_nothing_done(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [email("a1", "Board pack", "The deadline is Friday.")]
    run = intake(client, "a1").json()
    gateway.settle(run["actions"][0]["toolCallId"], "cancelled")
    after = get_run(client, run["runId"]).json()
    assert after["state"] == "cancelled" and after["actions"][0]["verified"] is False


def test_a_failed_execution_is_reported_as_failed_not_done(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [email("a1", "Board pack", "The deadline is Friday.")]
    run = intake(client, "a1").json()
    gateway.settle(run["actions"][0]["toolCallId"], "failed")
    assert get_run(client, run["runId"]).json()["state"] == "failed"


# ── duplicate inbound messages ─────────────────────────────────────────────

def test_the_same_inbound_message_twice_is_one_run_and_one_proposal(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [email("a1", "Board pack", "The deadline is Friday.")]
    first, second = intake(client, "a1").json(), intake(client, "a1").json()
    assert second["runId"] == first["runId"] and second["duplicate"] is True and first["duplicate"] is False
    assert len(gateway.cards) == 1 and len(gateway.runs) == 1


def test_the_same_message_id_in_another_mailbox_is_a_different_run(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [
        email("x1", "Board pack", "The deadline is Friday.", account="exec@gmail.example")]
    first = intake(client, "x1").json()
    gateway.world(EXEC)["emails"]["gmail"] = [
        email("x1", "Board pack", "The deadline is Friday.", account="side@gmail.example")]
    second = intake(client, "x1").json()
    assert second["runId"] != first["runId"]
    assert second["email"]["provider_account_id"] == "side@gmail.example"


# ── case 1: meeting request ────────────────────────────────────────────────

def test_a_free_requested_time_becomes_an_event_proposal_with_only_the_sender_invited(world):
    gateway, client = world
    data = gateway.world(EXEC)
    data["emails"]["gmail"] = [MEETING]
    data["meeting_plan"] = PLAN
    run = intake(client, "m1").json()
    assert run["held"] is None and [a["tool_name"] for a in run["actions"]] == ["create_calendar_event"]
    event = run["actions"][0]["input"]
    assert (event["start"], event["end"]) == (f"{TUE}T11:00:00+00:00", f"{TUE}T11:30:00+00:00")
    # The sender comes from the From header. An address that only appears in
    # the extracted plan (i.e. in the message text) is not invited.
    assert event["attendees"] == ["sofia@client.example"]
    assert "boss@elsewhere.example" not in str(run)
    # No confirmation is proposed while the event does not exist.
    assert "advance" not in run["next"]


def test_a_conflict_on_either_calendar_means_no_event_is_proposed(world):
    gateway, client = world
    data = gateway.world(EXEC)
    data["emails"]["gmail"] = [MEETING]
    data["meeting_plan"] = PLAN
    data["outlook_busy"] = [Busy(at(f"{TUE}T10:30"), at(f"{TUE}T11:30"), "outlook",
                                 "exec@contoso.example", "Board call")]
    run = intake(client, "m1").json()
    assert run["actions"] == [] and run["state"] == "no_action_proposed"
    assert run["held"]["reason"] == "calendar_conflict"
    assert run["held"]["conflicts"][0]["title"] == "Board call"
    assert run["held"]["conflicts"][0]["provider"] == "outlook"
    assert run["held"]["slots"], "verified free times are offered instead"
    assert run["next"] == ["draft_reply"]


def test_an_unreadable_calendar_means_no_event_is_proposed(world):
    gateway, client = world
    data = gateway.world(EXEC)
    data["emails"]["gmail"] = [MEETING]
    data["meeting_plan"] = PLAN
    data["outlook_error"] = "reconnect_required"
    run = intake(client, "m1").json()
    assert run["actions"] == [] and run["held"]["reason"] == "availability_unknown"
    assert run["held"]["slots"] == []
    assert "do not confirm or propose any specific time" in run["draftRequest"]["body"]["user_context"]


def test_no_event_is_guessed_when_the_time_cannot_be_extracted(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [MEETING]       # no meeting_plan: the model gave nothing
    run = intake(client, "m1").json()
    assert run["actions"] == [] and run["held"]["reason"] == "time_not_understood"


def test_a_reschedule_request_is_not_auto_proposed(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [
        email("m2", "Our call", "Can we reschedule our meeting to Thursday?", thread="T-m2")]
    gateway.world(EXEC)["meeting_plan"] = PLAN
    run = intake(client, "m2").json()
    assert run["actions"] == [] and run["held"]["reason"] == "change_request"
    assert ("extract_meeting", EXEC, "m2") not in gateway.calls


def test_the_confirmation_reply_is_proposed_only_after_the_event_is_executed(world):
    gateway, client = world
    data = gateway.world(EXEC)
    data["emails"]["gmail"] = [MEETING]
    data["meeting_plan"] = PLAN
    run = intake(client, "m1").json()
    event_id = run["actions"][0]["toolCallId"]

    # Advancing before approval proposes nothing.
    assert [a["tool_name"] for a in advance(client, run["runId"]).json()["actions"]] == ["create_calendar_event"]

    gateway.settle(event_id, "executed")
    assert get_run(client, run["runId"]).json()["next"] == ["advance"]
    after = advance(client, run["runId"]).json()
    reply = next(a for a in after["actions"] if a["tool_name"] == "send_email")
    assert reply["status"] == "awaiting_approval" and after["state"] == "awaiting_approval"
    # The reply answers the original message, in its thread, from the mailbox that received it.
    assert reply["input"]["mode"] == "reply" and reply["input"]["to"] == "sofia@client.example"
    assert reply["input"]["email_id"] == "m1" and reply["input"]["thread_id"] == "T-m1"
    assert reply["input"]["provider_account_id"] == "exec@gmail.example"
    assert reply["input"]["subject"] == "Re: Intro call next week?"
    assert f"{TUE}T11:00:00+00:00" in reply["input"]["body"]

    # Advancing again does not propose a second reply.
    again = advance(client, run["runId"]).json()
    assert sum(a["tool_name"] == "send_email" for a in again["actions"]) == 1


def test_an_outlook_reply_names_the_message_in_outlooks_field(world):
    gateway, client = world
    gateway.add_user(3, "ms@example.test", outlook="ms@contoso.example", outlook_mail=True)
    data = gateway.world("ms@example.test")
    data["emails"]["outlook"] = [email("AAMk-1", "Intro call?", "Could we meet Tuesday at 11:00?",
                                       provider="outlook", account="ms@contoso.example",
                                       from_addr="Sofia <sofia@client.example>", thread="conv-1")]
    data["meeting_plan"] = PLAN
    run = intake(client, "AAMk-1", user="ms@example.test", provider="outlook").json()
    gateway.settle(run["actions"][0]["toolCallId"], "executed")
    reply = next(a for a in advance(client, run["runId"], user="ms@example.test").json()["actions"]
                 if a["tool_name"] == "send_email")
    assert reply["input"]["provider"] == "outlook" and reply["input"]["message_id"] == "AAMk-1"
    assert "email_id" not in reply["input"]


def test_event_done_but_reply_failed_is_a_partial_run(world):
    gateway, client = world
    data = gateway.world(EXEC)
    data["emails"]["gmail"] = [MEETING]
    data["meeting_plan"] = PLAN
    run = intake(client, "m1").json()
    gateway.settle(run["actions"][0]["toolCallId"], "executed")
    after = advance(client, run["runId"]).json()
    gateway.settle(next(a for a in after["actions"] if a["tool_name"] == "send_email")["toolCallId"], "failed")
    final = get_run(client, run["runId"]).json()
    assert final["state"] == "partial"
    assert [(a["tool_name"], a["status"], a["verified"]) for a in final["actions"]] == [
        ("create_calendar_event", "executed", True), ("send_email", "failed", False)]


# ── other mail, isolation, errors ──────────────────────────────────────────

def test_a_plain_question_proposes_no_card_and_offers_a_draft_request(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [email("q1", "Contract", "Where are we on it?")]
    run = intake(client, "q1").json()
    assert run["actions"] == [] and run["next"] == ["draft_reply"]
    assert run["draftRequest"]["path"] == "/drafts/create"


def test_automated_mail_proposes_nothing(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [
        email("n1", "Digest", "Unsubscribe", from_addr="News <no-reply@news.example>")]
    run = intake(client, "n1").json()
    assert run["actions"] == [] and run["next"] == [] and run["state"] == "no_action_proposed"


def test_a_run_is_invisible_to_another_user(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [email("a1", "Board pack", "The deadline is Friday.")]
    run = intake(client, "a1").json()
    assert get_run(client, run["runId"], user=OTHER).status_code == 404
    assert advance(client, run["runId"], user=OTHER).status_code == 404
    assert client.get("/desk/runs", headers={"x-test-user": OTHER}).json()["runs"] == []
    assert [r["runId"] for r in client.get("/desk/runs", headers={"x-test-user": EXEC}).json()["runs"]] == [
        run["runId"]]


def test_one_users_message_cannot_be_taken_in_by_another(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [email("a1", "Board pack", "The deadline is Friday.")]
    assert intake(client, "a1", user=OTHER).status_code == 404
    assert gateway.cards == []


def test_intake_requires_a_session_and_a_known_provider(world):
    _, client = world
    assert client.post("/desk/intake", json={"provider": "gmail", "id": "a1"}).status_code == 401
    assert intake(client, "a1", provider="slack").status_code == 422
    assert intake(client, "missing").status_code == 404


# ── sweep: recent mail becomes runs without a click per message ────────────

def sweep(client, user=EXEC, **body):
    return client.post("/desk/intake/sweep", json=body, headers={"x-test-user": user})


def _mixed_inbox(gateway):
    gateway.world(EXEC)["emails"]["gmail"] = [
        email("a1", "Board pack", "Please note the deadline is Friday.", from_addr="Omar <omar@client.example>"),
        email("n1", "Weekly digest", "Unsubscribe here.", from_addr="News <no-reply@news.example>"),
        email("i1", "FYI", "The office is closed on Monday.", from_addr="Lina <lina@client.example>"),
        email("q1", "Quick question", "Did you get my invoice?", from_addr="Rami <rami@client.example>"),
    ]


def test_a_sweep_opens_runs_only_for_mail_that_needs_one(world):
    gateway, client = world
    _mixed_inbox(gateway)
    body = sweep(client).json()
    assert body["status"] == "completed" and body["examined"] == 4
    opened = {row["id"]: row for row in body["opened"]}
    assert "n1" not in opened and "i1" not in opened
    assert set(opened) == {row["id"] for row in body["opened"]} and len(opened) + body["skipped"] == 4
    assert all(isinstance(row["runId"], int) for row in opened.values())
    assert len(client.get("/desk/runs", headers={"x-test-user": EXEC}).json()["runs"]) == len(opened)


def test_a_repeated_sweep_opens_nothing_new(world):
    gateway, client = world
    _mixed_inbox(gateway)
    first = sweep(client).json()
    second = sweep(client).json()
    assert second["opened"] == [] and second["existing"] == len(first["opened"])
    assert len(client.get("/desk/runs", headers={"x-test-user": EXEC}).json()["runs"]) == len(first["opened"])


def test_a_sweep_is_bounded_and_defers_the_rest_to_the_next_call(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [
        email(f"a{n}", f"Report {n}", "Please note the deadline is Friday.",
              from_addr="Omar <omar@client.example>") for n in range(4)]
    first = sweep(client, max_new=2).json()
    assert len(first["opened"]) == 2 and len(first["deferred"]) == 2
    second = sweep(client, max_new=2).json()
    assert len(second["opened"]) == 2 and second["existing"] == 2 and second["deferred"] == []
    assert {r["id"] for r in first["opened"]}.isdisjoint({r["id"] for r in second["opened"]})


def test_one_failing_message_does_not_stop_the_sweep(world, monkeypatch):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [
        email("a1", "Board pack", "Please note the deadline is Friday.", from_addr="Omar <omar@client.example>"),
        email("a2", "Contract", "Please note the deadline is Monday.", from_addr="Omar <omar@client.example>"),
    ]
    real = gateway.open_run

    def flaky(user, *, title, meta, summary):
        if meta["email_id"] == "a1":
            raise RuntimeError("store unavailable")
        return real(user, title=title, meta=meta, summary=summary)

    monkeypatch.setattr(gateway, "open_run", flaky)
    body = sweep(client).json()
    assert [row["id"] for row in body["failed"]] == ["a1"] and body["failed"][0]["error"] == "RuntimeError"
    assert [row["id"] for row in body["opened"]] == ["a2"]


def test_a_sweep_says_when_a_mailbox_could_not_be_read(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example",
                     gmail_mail=True, outlook_mail=True)
    _mixed_inbox(gateway)
    gateway.world(EXEC)["mail_error"]["outlook"] = True
    body = sweep(client).json()
    assert body["complete"] is False and body["opened"]


def test_a_sweep_never_opens_runs_from_another_users_mail(world):
    gateway, client = world
    _mixed_inbox(gateway)
    body = sweep(client, user=OTHER).json()
    assert body["examined"] == 0 and body["opened"] == []
    assert client.get("/desk/runs", headers={"x-test-user": EXEC}).json()["runs"] == []


def test_sweep_rejects_out_of_range_bounds(world):
    _, client = world
    assert sweep(client, max_new=50).status_code == 422
    assert sweep(client, provider="slack").status_code == 422
