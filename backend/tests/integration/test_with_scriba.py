"""The overlay mounted on the real Scriba application.

Storage is in memory (Scriba's own contract harness) and providers are
replaced at their SDK boundary, so these prove the integration with Scriba's
code, not with live Google or Microsoft data.
"""
import datetime as dt
from pathlib import Path
from unittest.mock import patch

import pytest

from desk_overlay import install
from desk_overlay.install import uninstall
from desk_overlay.gateway import CalendarReadError, DeskUser, ScribaGateway
from desk_overlay.triage import triage

UTC = dt.timezone.utc
START = dt.datetime(2026, 11, 16, 0, 0, tzinfo=UTC)
END = dt.datetime(2026, 11, 17, 0, 0, tzinfo=UTC)
USER = DeskUser(id=7, email="exec@example.test")
RANGE = {"start": "2026-11-16T00:00:00Z", "end": "2026-11-16T23:00:00Z"}


@pytest.fixture()
def desk():
    from contract_harness import auth_app, login_as

    with auth_app() as (client, users):
        install(client.app, env={"DESK_CLAIMS": "memory"})
        try:
            yield client, users, login_as
        finally:
            uninstall(client.app)       # Scriba's app object is shared by every test


# ── transferred code stays identical to Scriba's ───────────────────────────

@pytest.mark.parametrize("name", ["availability.py", "time_rules.py"])
def test_transferred_files_match_scriba(scriba_path, name):
    ours = (Path(__file__).resolve().parents[2] / "desk_overlay" / "scriba_transferred" / name)
    theirs = scriba_path / "packages" / "domain" / "calendar_read" / name
    body = ours.read_text(encoding="utf-8").splitlines()[3:]  # after the provenance header
    assert body == theirs.read_text(encoding="utf-8").splitlines()


# ── Scriba's own guards cover /desk ────────────────────────────────────────

def test_desk_routes_sit_behind_scribas_session_guard(desk):
    client, _, _ = desk
    response = client.get("/desk/health")
    assert response.status_code == 401
    assert response.json()["errorCode"] == "unauthenticated"


def test_a_signed_in_user_reaches_the_overlay(desk):
    client, users, login_as = desk
    login_as(client, users, "exec@example.test")
    body = client.get("/desk/health").json()
    assert body["ok"] is True and body["service"] == "scriba-desk-overlay" and body["writes"] is False


def test_scribas_cross_site_guard_covers_desk_posts(desk):
    client, users, login_as = desk
    login_as(client, users, "exec@example.test")
    blocked = client.post("/desk/slots/check", json=RANGE, headers={"Origin": "https://elsewhere.example.test"})
    assert blocked.status_code == 403 and blocked.json()["errorCode"] == "cross_site_blocked"
    allowed = client.post("/desk/slots/check", json=RANGE, headers={"Origin": "http://localhost:5173"})
    assert allowed.status_code == 200


def test_another_users_account_is_refused_by_scribas_rule(desk):
    client, users, login_as = desk
    login_as(client, users, "exec@example.test")
    users.add(email="other@example.test")
    assert client.get("/desk/connections", params={"account": "other@example.test"}).status_code == 403


def test_installing_twice_does_not_duplicate_routes(desk):
    client, _, _ = desk
    before = len(client.app.router.routes)
    install(client.app)
    assert len(client.app.router.routes) == before


# ── real provider status, real preferences ─────────────────────────────────

def test_connections_come_from_scribas_provider_status(desk):
    client, users, login_as = desk
    login_as(client, users, "exec@example.test")
    body = client.get("/desk/connections").json()
    assert [c["id"] for c in body["capabilities"]] == [
        "gmail", "google_calendar", "outlook_mail", "outlook_calendar"]
    assert body["ready"] is False
    assert {c["loginPath"] for c in body["capabilities"]} == {"/auth/login", "/auth/outlook/login"}
    text = str(body).lower()
    assert "slack" not in text and "jira" not in text and "teams" not in text


def test_availability_with_nothing_connected_uses_scribas_default_preferences(desk):
    client, users, login_as = desk
    login_as(client, users, "exec@example.test")
    body = client.get("/desk/availability", params=RANGE).json()
    assert body["complete"] is False and body["reason"] == "no_calendar_connected"
    assert body["slots"] == [] and body["calendars"] == []
    # Defaults read from Scriba's preferences service, not invented here.
    assert body["working_hours"]["start"] == "09:00" and body["working_hours"]["end"] == "17:00"
    assert body["duration_minutes"] == 30 and body["timezone"]


def test_inbox_with_nothing_connected_reads_no_mailbox(desk):
    client, users, login_as = desk
    login_as(client, users, "exec@example.test")
    body = client.get("/desk/inbox").json()
    assert body["items"] == []
    assert {s["provider"]: s["ok"] for s in body["sources"]} == {"gmail": False, "outlook": False}


# ── the gateway against Scriba's real client modules ───────────────────────

class _FreeBusy:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.body = response, error, None

    def freebusy(self):
        return self

    def query(self, body):
        self.body = body
        return self

    def execute(self):
        if self.error:
            raise self.error
        return self.response


def test_google_busy_uses_the_named_accounts_credentials_and_scribas_parser():
    from app import calendar_client

    service = _FreeBusy({"calendars": {"primary": {"busy": [
        {"start": "2026-11-16T09:00:00Z", "end": "2026-11-16T10:00:00Z"},
        {"start": "2026-11-16T15:00:00+02:00", "end": "2026-11-16T16:00:00+02:00"},
    ]}}})
    with patch.object(calendar_client, "calendar_service", return_value=service) as factory:
        busy = ScribaGateway().google_busy(USER, "side@gmail.example", START, END, "UTC")
    factory.assert_called_once_with("exec@example.test", provider_account_id="side@gmail.example")
    assert service.body["items"] == [{"id": "primary"}] and service.body["timeZone"] == "UTC"
    assert [(b.start.astimezone(UTC).hour, b.end.astimezone(UTC).hour) for b in busy] == [(9, 10), (13, 14)]
    assert {(b.provider, b.account) for b in busy} == {("google", "side@gmail.example")}


def test_google_missing_calendar_permission_is_reported():
    from app import calendar_client

    with patch.object(calendar_client, "calendar_service",
                      side_effect=calendar_client.CalendarAccessError("scope missing")):
        with pytest.raises(CalendarReadError) as raised:
            ScribaGateway().google_busy(USER, "exec@gmail.example", START, END, "UTC")
    assert raised.value.code == "permission_missing"


def test_google_revoked_grant_is_reconnect_required():
    from app import calendar_client
    from app.gmail_client import GmailCredentialsMissing

    with patch.object(calendar_client, "calendar_service", side_effect=GmailCredentialsMissing("revoked")):
        with pytest.raises(CalendarReadError) as raised:
            ScribaGateway().google_busy(USER, "exec@gmail.example", START, END, "UTC")
    assert raised.value.code == "reconnect_required"


def test_google_api_failure_is_a_provider_error():
    from app import calendar_client

    with patch.object(calendar_client, "calendar_service", return_value=_FreeBusy(error=TimeoutError("slow"))):
        with pytest.raises(CalendarReadError) as raised:
            ScribaGateway().google_busy(USER, "exec@gmail.example", START, END, "UTC")
    assert raised.value.code == "provider_error"


def test_outlook_busy_reads_graph_times_in_their_own_zone_and_skips_free_time():
    from app import outlook_client

    events = {"value": [
        {"subject": "Standup", "showAs": "busy", "isCancelled": False,
         "start": {"dateTime": "2026-11-16T09:00:00.0000000", "timeZone": "UTC"},
         "end": {"dateTime": "2026-11-16T09:30:00.0000000", "timeZone": "UTC"}},
        {"subject": "Cancelled", "showAs": "busy", "isCancelled": True,
         "start": {"dateTime": "2026-11-16T11:00:00.0000000", "timeZone": "UTC"},
         "end": {"dateTime": "2026-11-16T12:00:00.0000000", "timeZone": "UTC"}},
        {"subject": "Holiday", "showAs": "free", "isAllDay": True,
         "start": {"dateTime": "2026-11-16T00:00:00.0000000", "timeZone": "UTC"},
         "end": {"dateTime": "2026-11-17T00:00:00.0000000", "timeZone": "UTC"}},
        {"subject": "Tentative lunch", "showAs": "tentative",
         "start": {"dateTime": "2026-11-16T14:00:00.0000000", "timeZone": "Europe/Paris"},
         "end": {"dateTime": "2026-11-16T15:00:00.0000000", "timeZone": "Europe/Paris"}},
    ]}
    with patch.object(outlook_client, "get_access_token", return_value="token") as token, \
            patch.object(outlook_client, "graph_get", return_value=events) as graph:
        busy = ScribaGateway().outlook_busy(USER, "exec@contoso.example", START, END)
    token.assert_called_once_with(7)
    path = graph.call_args.args[0]
    assert path.startswith("/me/calendarView?startDateTime=2026-11-16T00:00:00Z&endDateTime=2026-11-17T00:00:00Z")
    assert "showAs" in path
    assert [b.title for b in busy] == ["Standup", "Tentative lunch"]
    assert busy[0].start == dt.datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
    assert busy[1].start.astimezone(UTC) == dt.datetime(2026, 11, 16, 13, 0, tzinfo=UTC)  # 14:00 in Paris
    assert {(b.provider, b.account) for b in busy} == {("outlook", "exec@contoso.example")}


def test_outlook_without_a_token_is_reconnect_required():
    from app import outlook_client

    with patch.object(outlook_client, "get_access_token", return_value=None):
        with pytest.raises(CalendarReadError) as raised:
            ScribaGateway().outlook_busy(USER, "exec@contoso.example", START, END)
    assert raised.value.code == "reconnect_required"


@pytest.mark.parametrize("status,code", [(401, "reconnect_required"), (403, "permission_missing"),
                                         (503, "provider_error")])
def test_outlook_graph_failures_are_classified(status, code):
    from app import outlook_client

    with patch.object(outlook_client, "get_access_token", return_value="token"), \
            patch.object(outlook_client, "graph_get", side_effect=outlook_client.GraphAPIError(status, "x")):
        with pytest.raises(CalendarReadError) as raised:
            ScribaGateway().outlook_busy(USER, "exec@contoso.example", START, END)
    assert raised.value.code == code


def test_outlook_truncated_page_is_not_treated_as_complete():
    from app import outlook_client

    with patch.object(outlook_client, "get_access_token", return_value="token"), \
            patch.object(outlook_client, "graph_get",
                         return_value={"value": [], "@odata.nextLink": "https://graph.example.test/next"}):
        with pytest.raises(CalendarReadError) as raised:
            ScribaGateway().outlook_busy(USER, "exec@contoso.example", START, END)
    assert raised.value.code == "range_too_large"


# ── Scriba's real classifier behind the Desk triage ────────────────────────

@pytest.mark.parametrize("subject,snippet,sender,category", [
    ("Intro call next week?", "Could we schedule a meeting on Tuesday at 11:00?",
     "Sofia <sofia@client.example>", "meeting_request"),
    ("Contract", "Can you send me the signed copy?", "Dana <dana@client.example>", "needs_reply"),
    ("Your weekly digest", "View in browser. Unsubscribe from this list.",
     "News <newsletter@news.example>", "automated"),
    ("FYI: minutes attached", "Sharing the notes from yesterday.", "Omar <omar@client.example>",
     "informational"),
])
def test_triage_on_scribas_classifier(subject, snippet, sender, category):
    verdict = ScribaGateway().classify(from_addr=sender, subject=subject, body=snippet)
    record = triage({"subject": subject, "snippet": snippet}, verdict)
    assert record["category"] == category, (verdict, record)
