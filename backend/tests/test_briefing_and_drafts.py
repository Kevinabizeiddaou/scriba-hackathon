"""The executive briefing and the draft request, against a scripted gateway."""
import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from desk_overlay.availability import Busy
from desk_overlay.routes import build_router
from desk_overlay.triage import triage

from .fakes import FakeGateway, at, email

MON = "2026-11-16"
EXEC = "exec@example.test"
NOW = dt.datetime(2026, 11, 16, 6, 0, tzinfo=dt.timezone.utc)


@pytest.fixture()
def world():
    gateway = FakeGateway()
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example",
                     gmail_mail=True, outlook_mail=True)
    app = FastAPI()
    app.include_router(build_router(gateway, now=lambda: NOW))
    return gateway, TestClient(app)


def get(client, path, **params):
    return client.get(path, params=params, headers={"x-test-user": EXEC})


# ── triage rules ───────────────────────────────────────────────────────────

REQUIRES_REPLY = {"classification": "requires_reply", "priority": "high"}


@pytest.mark.parametrize("subject,snippet,intent", [
    ("Intro call", "Could we meet on Tuesday?", "new"),
    ("Our call", "Can we reschedule to Thursday?", "reschedule"),
    ("Tomorrow", "I need to cancel our meeting.", "cancel"),
])
def test_meeting_intent(subject, snippet, intent):
    record = triage({"subject": subject, "snippet": snippet},
                    {**REQUIRES_REPLY, "reasons": ["question", "meeting_request"]})
    assert record["category"] == "meeting_request" and record["meeting_intent"] == intent


def test_a_deadline_without_a_question_is_an_action_item():
    record = triage({"subject": "Board pack", "snippet": "Please note the deadline is Friday."},
                    {"classification": "informational", "priority": "low", "reasons": []})
    assert (record["category"], record["outcome"], record["has_deadline"]) == ("action_item", "task", True)


def test_automated_mail_is_never_actionable_even_if_scriba_stored_a_high_priority():
    record = triage({"subject": "Sale", "snippet": "50% off", "priority": "high"},
                    {"classification": "automated/promotional", "priority": "low", "reasons": ["bulk"]})
    assert (record["category"], record["priority"], record["needs_reply"]) == ("automated", "low", False)


def test_scribas_stored_priority_wins_over_the_classifier():
    record = triage({"subject": "Q", "snippet": "Thoughts?", "effective_priority": "medium"},
                    {**REQUIRES_REPLY, "reasons": ["question"]})
    assert record["priority"] == "medium"


# ── briefing ───────────────────────────────────────────────────────────────

def test_briefing_reports_only_what_the_records_say(world):
    gateway, client = world
    data = gateway.world(EXEC)
    data["emails"]["gmail"] = [
        email("g1", "Intro call?", "Could we meet Tuesday?", timestamp=f"{MON}T05:00:00+00:00"),
        email("g2", "Digest", "Unsubscribe", from_addr="N <no-reply@news.example>"),
    ]
    data["emails"]["outlook"] = [
        email("o1", "Contract", "Where are we?", provider="outlook", account="exec@contoso.example",
              timestamp=f"{MON}T05:30:00+00:00"),
    ]
    data["agenda"]["days"][0]["entries"] = [
        {"type": "meeting", "title": "Board call", "start_time": f"{MON}T10:00:00+00:00",
         "end_time": f"{MON}T11:00:00+00:00", "provider": "outlook", "provider_account_id": "exec@contoso.example"},
        {"type": "meeting", "title": "Standup thread", "provider": "slack"},
        {"type": "task", "title": "A task shown on the agenda"},
    ]
    data["tasks"] = [
        {"id": 1, "title": "Send deck", "status": "active", "due_today": True, "effective_priority": "high"},
        {"id": 2, "title": "Old", "status": "completed", "due_today": True},
        {"id": 3, "title": "Later", "status": "active", "due_today": False},
    ]
    data["reminders"] = [{"id": 9, "title": "Call bank"}]

    body = get(client, "/desk/briefing").json()
    assert body["counts"] == {"meeting_requests": 1, "needs_reply": 1, "action_items": 0,
                              "meetings_today": 1, "open_tasks": 2, "tasks_due_today": 1, "reminders": 1}
    assert body["headline"] == ("1 meeting request, 1 message needs a reply, 1 meeting today, "
                                "1 task due today.")
    # Newest first within the same priority; automated mail is not there.
    assert [line["id"] for line in body["needs_attention"]] == ["o1", "g1"]
    assert body["needs_attention"][0]["provider_account_id"] == "exec@contoso.example"
    # The meeting from an excluded integration and the task row are not meetings.
    assert [m["title"] for m in body["meetings_today"]] == ["Board call"]
    assert [t["id"] for t in body["tasks_due_today"]] == [1]
    assert body["inbox_complete"] is True and body["unavailable"] == []
    assert body["generated_at"].startswith(f"{MON}T06:00")


def test_briefing_survives_a_missing_section_and_says_so(world):
    gateway, client = world
    gateway.world(EXEC)["section_error"] = {"tasks", "reminders"}
    body = get(client, "/desk/briefing").json()
    assert sorted(body["unavailable"]) == ["reminders", "tasks"]
    assert body["counts"]["open_tasks"] == 0


def test_briefing_flags_an_incomplete_inbox(world):
    gateway, client = world
    gateway.world(EXEC)["mail_error"]["gmail"] = True
    assert get(client, "/desk/briefing").json()["inbox_complete"] is False


def test_briefing_requires_a_session(world):
    _, client = world
    assert client.get("/desk/briefing").status_code == 401


# ── draft request for Scriba's existing POST /drafts/create ────────────────

def item(client, item_id):
    return get(client, "/desk/inbox/item", provider="gmail", id=item_id).json()


def test_a_meeting_request_draft_is_told_the_verified_free_times(world):
    gateway, client = world
    data = gateway.world(EXEC)
    data["emails"]["gmail"] = [email("g1", "Intro call?", "Could we meet Tuesday?", thread="T1")]
    data["outlook_busy"] = [Busy(at(f"{MON}T09:00"), at(f"{MON}T12:00"), "outlook", "exec@contoso.example")]
    request = item(client, "g1")["draftRequest"]
    assert (request["method"], request["path"]) == ("POST", "/drafts/create")
    assert request["body"]["provider"] == "gmail" and request["body"]["email_id"] == "g1"
    assert request["body"]["thread_id"] == "T1"
    # The reply is drafted from the mailbox that received the message.
    assert request["body"]["provider_account_id"] == "exec@gmail.example"
    context = request["body"]["user_context"]
    assert f"{MON}T12:00:00+00:00 to {MON}T12:30:00+00:00" in context
    assert "Never state that a meeting has been booked" in context


def test_no_time_is_offered_when_a_calendar_could_not_be_read(world):
    gateway, client = world
    data = gateway.world(EXEC)
    data["emails"]["gmail"] = [email("g1", "Intro call?", "Could we meet Tuesday?")]
    data["outlook_error"] = "reconnect_required"
    context = item(client, "g1")["draftRequest"]["body"]["user_context"]
    assert "do not confirm or propose any specific time" in context
    assert MON not in context


def test_a_fully_booked_executive_does_not_confirm_a_time(world):
    gateway, client = world
    data = gateway.world(EXEC)
    data["emails"]["gmail"] = [email("g1", "Intro call?", "Could we meet Tuesday?")]
    data["google_busy"]["exec@gmail.example"] = [
        Busy(at("2026-11-16T00:00"), at("2026-11-30T00:00"), "google", "exec@gmail.example")]
    context = item(client, "g1")["draftRequest"]["body"]["user_context"]
    assert "no free time" in context and "Do not confirm any time" in context


def test_an_ordinary_question_gets_a_plain_draft_request(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [email("g1", "Contract", "Where are we on it?")]
    body = item(client, "g1")
    assert body["calendar"] is None
    assert "meeting" not in body["draftRequest"]["body"]["user_context"].lower()


def test_mail_that_needs_no_reply_has_no_draft_request(world):
    gateway, client = world
    gateway.world(EXEC)["emails"]["gmail"] = [email("g1", "FYI", "Minutes attached.")]
    assert item(client, "g1")["draftRequest"] is None
