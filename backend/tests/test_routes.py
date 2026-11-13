"""The /desk routes against a scripted gateway. No Scriba checkout needed."""
import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from desk_overlay.availability import Busy
from desk_overlay.routes import build_router

from .fakes import FakeGateway, at, email

MON = "2026-11-16"
EXEC = "exec@example.test"
OTHER = "other@example.test"
NOW = dt.datetime(2026, 11, 16, 6, 0, tzinfo=dt.timezone.utc)
RANGE = {"start": f"{MON}T00:00:00Z", "end": f"{MON}T23:00:00Z"}


def google(start: str, end: str, account: str = "exec@gmail.example") -> Busy:
    return Busy(at(f"{MON}T{start}"), at(f"{MON}T{end}"), "google", account)


def outlook(start: str, end: str, title: str = "Outlook meeting") -> Busy:
    return Busy(at(f"{MON}T{start}"), at(f"{MON}T{end}"), "outlook", "exec@contoso.example", title)


@pytest.fixture()
def world():
    gateway = FakeGateway()
    app = FastAPI()
    app.include_router(build_router(gateway, now=lambda: NOW))
    return gateway, TestClient(app)


def get(client, path, user=EXEC, **params):
    return client.get(path, params=params, headers={"x-test-user": user} if user else {})


# ── session and isolation ──────────────────────────────────────────────────

def test_every_route_requires_a_session(world):
    _, client = world
    for path in ("/desk/health", "/desk/connections", "/desk/inbox"):
        assert client.get(path).status_code == 401
    assert client.get("/desk/availability", params=RANGE).status_code == 401
    assert client.post("/desk/slots/check", json=RANGE).status_code == 401


def test_naming_another_users_account_is_refused(world):
    gateway, client = world
    gateway.add_user(1, EXEC)
    assert get(client, "/desk/connections", account=OTHER).status_code == 403


def test_one_user_never_sees_anothers_calendar_or_mail(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], gmail_mail=True)
    gateway.add_user(2, OTHER, google=["other@gmail.example"], gmail_mail=True)
    gateway.world(OTHER)["google_busy"]["other@gmail.example"] = [google("09:00", "17:00", "other@gmail.example")]
    gateway.world(OTHER)["emails"]["gmail"] = [email("o1", "Private", "For the other user")]

    availability = get(client, "/desk/availability", **RANGE).json()
    assert availability["busy"] == []
    assert [c["account"] for c in availability["calendars"]] == ["exec@gmail.example"]
    assert get(client, "/desk/inbox").json()["items"] == []
    # Every provider read was made for the session user and their own account.
    assert all(call[1] == EXEC for call in gateway.calls)
    assert ("google_busy", EXEC, "other@gmail.example") not in gateway.calls


# ── health and connections ─────────────────────────────────────────────────

def test_health_says_the_overlay_is_read_only(world):
    gateway, client = world
    gateway.add_user(1, EXEC)
    body = get(client, "/desk/health").json()
    assert body["ok"] is True and body["writes"] is False
    assert "availability" in body["capabilities"]


def test_connections_lists_four_capabilities_and_no_excluded_integration(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], gmail_mail=True)
    body = get(client, "/desk/connections").json()
    assert [c["id"] for c in body["capabilities"]] == [
        "gmail", "google_calendar", "outlook_mail", "outlook_calendar"]
    assert body["ready"] is True
    assert "slack" not in str(body).lower() and "jira" not in str(body).lower()


# ── availability: the connection matrix ────────────────────────────────────

def test_google_only_user(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"])
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("09:00", "10:00")]
    body = get(client, "/desk/availability", **RANGE).json()
    assert body["complete"] is True
    assert [(c["provider"], c["ok"]) for c in body["calendars"]] == [("google", True)]
    assert body["slots"][0]["start"] == f"{MON}T10:00:00+00:00"
    assert body["busy"][0]["provider"] == "google" and body["busy"][0]["account"] == "exec@gmail.example"


def test_microsoft_only_user(world):
    gateway, client = world
    gateway.add_user(1, EXEC, outlook="exec@contoso.example")
    gateway.world(EXEC)["outlook_busy"] = [outlook("09:00", "09:30", "Standup")]
    body = get(client, "/desk/availability", **RANGE).json()
    assert body["complete"] is True
    assert [(c["provider"], c["account"]) for c in body["calendars"]] == [("outlook", "exec@contoso.example")]
    assert body["busy"][0]["title"] == "Standup"
    assert body["slots"][0]["start"] == f"{MON}T09:30:00+00:00"


def test_both_providers_are_combined(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example")
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("09:00", "10:00")]
    gateway.world(EXEC)["outlook_busy"] = [outlook("10:00", "11:00")]
    body = get(client, "/desk/availability", max_slots=1, **RANGE).json()
    assert {c["provider"] for c in body["calendars"]} == {"google", "outlook"}
    assert body["busy_merged"] == [{"start": f"{MON}T09:00:00+00:00", "end": f"{MON}T11:00:00+00:00"}]
    assert body["slots"] == [{"start": f"{MON}T11:00:00+00:00", "end": f"{MON}T11:30:00+00:00"}]


def test_several_google_accounts_are_each_read(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example", "side@gmail.example"])
    gateway.world(EXEC)["google_busy"]["side@gmail.example"] = [google("09:00", "12:00", "side@gmail.example")]
    body = get(client, "/desk/availability", max_slots=1, **RANGE).json()
    assert [c["account"] for c in body["calendars"]] == ["exec@gmail.example", "side@gmail.example"]
    assert body["slots"][0]["start"] == f"{MON}T12:00:00+00:00"


def test_no_calendar_connected(world):
    gateway, client = world
    gateway.add_user(1, EXEC)
    body = get(client, "/desk/availability", **RANGE).json()
    assert body["calendars"] == [] and body["slots"] == []
    assert body["complete"] is False and body["reason"] == "no_calendar_connected"


def test_existing_double_booking_across_providers_is_reported(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example")
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("10:00", "11:00")]
    gateway.world(EXEC)["outlook_busy"] = [outlook("10:30", "11:30", "Board call")]
    conflicts = get(client, "/desk/availability", **RANGE).json()["existing_conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["start"] == f"{MON}T10:30:00+00:00" and conflicts[0]["end"] == f"{MON}T11:00:00+00:00"
    assert {b["provider"] for b in conflicts[0]["between"]} == {"google", "outlook"}


# ── availability: failures are never "free" ────────────────────────────────

@pytest.mark.parametrize("code", ["reconnect_required", "permission_missing", "provider_error"])
def test_an_unreadable_calendar_blocks_suggestions(world, code):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example")
    gateway.world(EXEC)["outlook_error"] = code
    body = get(client, "/desk/availability", **RANGE).json()
    failed = next(c for c in body["calendars"] if c["provider"] == "outlook")
    assert failed["ok"] is False and failed["error"] == code
    assert body["complete"] is False and body["reason"] == "calendar_unreadable"
    assert body["slots"] == []


def test_an_unexpected_provider_crash_is_reported_not_raised(world):
    gateway, client = world
    gateway.add_user(1, EXEC, outlook="exec@contoso.example")
    gateway.world(EXEC)["outlook_error"] = "crash"
    response = get(client, "/desk/availability", **RANGE)
    assert response.status_code == 200
    assert response.json()["calendars"][0] == {
        "provider": "outlook", "account": "exec@contoso.example", "ok": False,
        "error": "provider_error", "busy_count": 0}


def test_fully_booked_day_has_no_slots_but_is_complete(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"])
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("00:00", "23:00")]
    body = get(client, "/desk/availability", **RANGE).json()
    assert body["complete"] is True and body["slots"] == []


# ── availability: preferences, zones and validation ────────────────────────

def test_preferences_set_zone_hours_buffer_and_duration(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], prefs={
        "timezone": "Asia/Beirut", "workday_start_time": "10:00:00", "workday_end_time": "12:00:00",
        "meeting_buffer_minutes": 15, "default_meeting_duration_minutes": 45})
    body = get(client, "/desk/availability", **RANGE).json()
    assert body["timezone"] == "Asia/Beirut"
    assert body["working_hours"] == {"start": "10:00", "end": "12:00", "weekdays": []}
    assert (body["duration_minutes"], body["buffer_minutes"]) == (45, 15)
    assert body["slots"][0] == {"start": f"{MON}T10:00:00+02:00", "end": f"{MON}T10:45:00+02:00"}


def test_request_parameters_override_preferences(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"])
    body = get(client, "/desk/availability", timezone="America/New_York", duration_minutes=60,
               buffer_minutes=0, start=f"{MON}T00:00:00-05:00", end=f"{MON}T23:00:00-05:00").json()
    assert body["timezone"] == "America/New_York"
    assert body["slots"][0]["start"] == f"{MON}T09:00:00-05:00"


def test_slots_are_never_in_the_past(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"])
    # The injected clock says 06:00 UTC; ask about a range that started earlier.
    body = get(client, "/desk/availability", start="2026-11-15T00:00:00Z", end=f"{MON}T23:00:00Z").json()
    assert body["slots"][0]["start"] == f"{MON}T09:00:00+00:00"


@pytest.mark.parametrize("params", [
    {"start": "not-a-date", "end": f"{MON}T23:00:00Z"},
    {"start": f"{MON}T23:00:00Z", "end": f"{MON}T00:00:00Z"},
    {"start": "2026-11-01T00:00:00Z", "end": "2026-12-31T00:00:00Z"},
    {**RANGE, "timezone": "Mars/Olympus"},
])
def test_invalid_requests_are_400(world, params):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"])
    assert get(client, "/desk/availability", **params).status_code == 400


def test_out_of_range_numbers_are_rejected(world):
    gateway, client = world
    gateway.add_user(1, EXEC)
    assert get(client, "/desk/availability", duration_minutes=5, **RANGE).status_code == 422


# ── slot check ─────────────────────────────────────────────────────────────

def check(client, start, end, **extra):
    return client.post("/desk/slots/check", headers={"x-test-user": EXEC},
                       json={"start": f"{MON}T{start}:00Z", "end": f"{MON}T{end}:00Z", **extra}).json()


def test_slot_check_free_and_conflicting(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example")
    gateway.world(EXEC)["outlook_busy"] = [outlook("14:00", "15:00", "Board call")]
    free = check(client, "10:00", "10:30")
    assert free["free"] is True and free["conflicts"] == [] and free["within_working_hours"] is True
    busy = check(client, "14:30", "15:30")
    assert busy["free"] is False
    assert busy["conflicts"] == [{"start": f"{MON}T14:00:00+00:00", "end": f"{MON}T15:00:00+00:00",
                                  "provider": "outlook", "account": "exec@contoso.example",
                                  "title": "Board call"}]


def test_slot_check_does_not_claim_free_when_a_calendar_is_unreadable(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example")
    gateway.world(EXEC)["outlook_error"] = "reconnect_required"
    result = check(client, "10:00", "10:30")
    assert result["free"] is None and result["complete"] is False


def test_slot_check_reports_a_certain_conflict_even_when_another_calendar_failed(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example")
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("10:00", "11:00")]
    gateway.world(EXEC)["outlook_error"] = "provider_error"
    assert check(client, "10:00", "10:30")["free"] is False


def test_slot_check_flags_times_outside_working_hours(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"])
    late = check(client, "21:00", "21:30")
    assert late["free"] is True and late["within_working_hours"] is False


def test_slot_check_applies_the_buffer(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"])
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("10:00", "11:00")]
    assert check(client, "11:00", "11:30")["free"] is True
    assert check(client, "11:00", "11:30", buffer_minutes=15)["free"] is False


# ── inbox and triage ───────────────────────────────────────────────────────

def test_inbox_merges_both_mailboxes_newest_first_with_triage(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example",
                     gmail_mail=True, outlook_mail=True)
    gateway.world(EXEC)["emails"]["gmail"] = [
        email("g1", "Intro call next week?", "Could we meet Tuesday at 11?", timestamp="2026-11-16T08:10:00+00:00"),
        email("g2", "Weekly digest", "Unsubscribe here", from_addr="News <no-reply@news.example>",
              timestamp="2026-11-16T07:00:00+00:00"),
    ]
    gateway.world(EXEC)["emails"]["outlook"] = [
        email("o1", "Contract status", "Where are we on the contract?", provider="outlook",
              account="exec@contoso.example", timestamp="2026-11-16T08:30:00+00:00"),
    ]
    body = get(client, "/desk/inbox").json()
    assert [item["id"] for item in body["items"]] == ["o1", "g1", "g2"]
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id["g1"]["triage"]["category"] == "meeting_request"
    assert by_id["g1"]["triage"]["outcome"] == "schedule" and by_id["g1"]["triage"]["meeting_intent"] == "new"
    assert by_id["o1"]["triage"]["category"] == "needs_reply"
    assert by_id["g2"]["triage"] == {**by_id["g2"]["triage"], "category": "automated", "priority": "low",
                                     "outcome": "none", "needs_reply": False}
    # Provider and receiving account survive the merge.
    assert (by_id["o1"]["provider"], by_id["o1"]["provider_account_id"]) == ("outlook", "exec@contoso.example")
    assert body["counts"] == {"meeting_request": 1, "needs_reply": 1, "action_item": 0,
                              "informational": 0, "automated": 1}
    assert body["complete"] is True


def test_inbox_reports_a_mailbox_that_could_not_be_read(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example",
                     gmail_mail=True, outlook_mail=True)
    gateway.world(EXEC)["mail_error"]["outlook"] = True
    body = get(client, "/desk/inbox").json()
    assert body["complete"] is False
    assert next(s for s in body["sources"] if s["provider"] == "outlook")["error"] == "provider_error"


def test_inbox_skips_a_mailbox_that_is_not_connected(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], gmail_mail=True)
    body = get(client, "/desk/inbox").json()
    assert ("list_emails", EXEC, "outlook", None) not in gateway.calls
    assert next(s for s in body["sources"] if s["provider"] == "outlook")["error"] == "disconnected"
    assert body["complete"] is True


def test_a_row_from_another_provider_is_dropped(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], gmail_mail=True)
    gateway.world(EXEC)["emails"]["gmail"] = [email("x1", "Stray", "wrong provider", provider="slack")]
    assert get(client, "/desk/inbox", provider="gmail").json()["items"] == []


def test_inbox_item_gathers_thread_and_calendar_context_for_a_meeting_request(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example", gmail_mail=True)
    gateway.world(EXEC)["emails"]["gmail"] = [
        email("g1", "Intro call next week?", "Could we meet Tuesday?", thread="T1",
              timestamp="2026-11-16T08:10:00+00:00"),
        email("g0", "Intro", "Nice to meet you at the forum", thread="T1",
              timestamp="2026-11-15T08:00:00+00:00"),
    ]
    gateway.world(EXEC)["outlook_busy"] = [outlook("09:00", "12:00")]
    body = get(client, "/desk/inbox/item", provider="gmail", id="g1").json()
    assert body["item"]["triage"]["category"] == "meeting_request"
    assert [m["id"] for m in body["thread"]["messages"]] == ["g0", "g1"]
    assert body["replyFrom"] == {"provider": "gmail", "providerAccountId": "exec@gmail.example"}
    assert body["calendar"]["complete"] is True
    assert body["calendar"]["slots"][0]["start"] == f"{MON}T12:00:00+00:00"


def test_inbox_item_has_no_calendar_section_for_ordinary_mail(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], gmail_mail=True)
    gateway.world(EXEC)["emails"]["gmail"] = [email("g1", "FYI", "Report attached.")]
    body = get(client, "/desk/inbox/item", provider="gmail", id="g1").json()
    assert body["calendar"] is None
    assert not any(call[0].endswith("_busy") for call in gateway.calls)


def test_inbox_item_unknown_id_is_404(world):
    gateway, client = world
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], gmail_mail=True)
    assert get(client, "/desk/inbox/item", provider="gmail", id="nope").status_code == 404
