"""Desk chat tools and the availability gate, without Scriba.

The gate decides whether a proposed calendar event may reach approval. These
tests drive it directly; tests/integration/test_chat_scope_with_scriba.py
proves it is wired into Scriba's real validation and approve path.
"""
import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pytest

from desk_overlay.availability import Busy, InvalidAvailabilityRequest
from desk_overlay.chat_scope import OVERRIDE_FLAG, availability_gate, run_desk_tool
from desk_overlay.service import AppContext, DeskService

from .fakes import FakeGateway, at

MON = "2026-11-16"
EXEC = "exec@example.test"
OTHER = "other@example.test"
NOW = dt.datetime(2026, 11, 16, 6, 0, tzinfo=dt.timezone.utc)
CTX = AppContext(app=None)


@dataclass
class Validation:
    """Shaped like Scriba's ToolValidation."""

    status: str
    input: Dict[str, Any] = field(default_factory=dict)
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


def make(status, data, output, error):
    return Validation(status=status, input=data, output=output, error=error)


@pytest.fixture()
def desk():
    gateway = FakeGateway()
    gateway.add_user(1, EXEC, google=["exec@gmail.example"], outlook="exec@contoso.example")
    gateway.add_user(2, OTHER, google=["other@gmail.example"])
    gateway.acting_as = EXEC
    return gateway, DeskService(gateway, clock=lambda: NOW), gateway.world(EXEC)["user"]


def google(start, end, account="exec@gmail.example"):
    return Busy(at(f"{MON}T{start}"), at(f"{MON}T{end}"), "google", account)


def outlook(start, end, title="Board call"):
    return Busy(at(f"{MON}T{start}"), at(f"{MON}T{end}"), "outlook", "exec@contoso.example", title)


def proposed(start="10:00", end="10:30", **extra):
    return Validation("awaiting_approval", {"title": "Intro call", "start": f"{MON}T{start}:00+00:00",
                                            "end": f"{MON}T{end}:00+00:00", **extra})


def gate(desk, validation, user_confirmed=False):
    gateway, service, user = desk
    return availability_gate(service, CTX, user, validation, user_confirmed=user_confirmed, make=make)


# ── read tools ─────────────────────────────────────────────────────────────

def test_check_availability_reports_a_conflict_on_either_provider(desk):
    gateway, service, user = desk
    gateway.world(EXEC)["outlook_busy"] = [outlook("10:00", "11:00")]
    result = run_desk_tool(service, CTX, user, "check_availability",
                           {"start": f"{MON}T10:15:00Z", "end": f"{MON}T10:45:00Z"})
    assert result["free"] is False
    assert result["conflicts"][0]["provider"] == "outlook"
    assert result["conflicts"][0]["account"] == "exec@contoso.example"
    assert {c["provider"] for c in result["calendars"]} == {"google", "outlook"}


def test_check_availability_is_unknown_not_free_when_a_calendar_is_unreadable(desk):
    gateway, service, user = desk
    gateway.world(EXEC)["google_error"]["exec@gmail.example"] = "reconnect_required"
    result = run_desk_tool(service, CTX, user, "check_availability",
                           {"start": f"{MON}T10:00:00Z", "end": f"{MON}T10:30:00Z"})
    assert result["free"] is None and result["complete"] is False


def test_check_availability_needs_both_times(desk):
    _, service, user = desk
    with pytest.raises(InvalidAvailabilityRequest):
        run_desk_tool(service, CTX, user, "check_availability", {"start": f"{MON}T10:00:00Z"})


def test_find_free_slots_defaults_to_the_coming_days_and_merges_both_calendars(desk):
    gateway, service, user = desk
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("09:00", "10:00")]
    gateway.world(EXEC)["outlook_busy"] = [outlook("10:00", "12:00")]
    result = run_desk_tool(service, CTX, user, "find_free_slots", {"max_slots": 1})
    assert result["complete"] is True
    assert result["slots"] == [{"start": f"{MON}T12:00:00+00:00", "end": f"{MON}T12:30:00+00:00"}]
    assert "busy" not in result  # compact: the merged view is enough for the model


def test_find_free_slots_offers_nothing_when_a_calendar_is_unreadable(desk):
    gateway, service, user = desk
    gateway.world(EXEC)["outlook_error"] = "permission_missing"
    result = run_desk_tool(service, CTX, user, "find_free_slots", {})
    assert result["slots"] == [] and result["reason"] == "calendar_unreadable"


def test_find_free_slots_respects_a_requested_time_zone(desk):
    _, service, user = desk
    result = run_desk_tool(service, CTX, user, "find_free_slots",
                           {"timezone": "Asia/Beirut", "duration_minutes": 60, "max_slots": 1})
    assert result["timezone"] == "Asia/Beirut" and result["slots"][0]["start"].endswith("+02:00")


def test_find_free_slots_rejects_a_non_numeric_duration(desk):
    _, service, user = desk
    with pytest.raises(InvalidAvailabilityRequest):
        run_desk_tool(service, CTX, user, "find_free_slots", {"duration_minutes": "an hour"})


def test_provider_status_tool_lists_only_desk_capabilities(desk):
    _, service, user = desk
    result = run_desk_tool(service, CTX, user, "provider_status", {})
    assert [c["id"] for c in result["capabilities"]] == [
        "gmail", "google_calendar", "outlook_mail", "outlook_calendar"]
    assert "slack" not in str(result).lower()


def test_tools_read_only_the_calling_users_calendars(desk):
    gateway, service, user = desk
    gateway.world(OTHER)["google_busy"]["other@gmail.example"] = [google("00:00", "23:00", "other@gmail.example")]
    result = run_desk_tool(service, CTX, user, "check_availability",
                           {"start": f"{MON}T10:00:00Z", "end": f"{MON}T10:30:00Z"})
    assert result["free"] is True
    assert all(call[1] == EXEC for call in gateway.calls)


# ── the gate ───────────────────────────────────────────────────────────────

def test_a_free_time_stays_approvable_and_records_what_was_checked(desk):
    result = gate(desk, proposed())
    assert result.status == "awaiting_approval"
    assert result.output["availability"]["free"] is True
    assert {c["provider"] for c in result.output["availability"]["calendars"]} == {"google", "outlook"}


def test_a_conflict_on_the_other_provider_holds_the_card(desk):
    gateway, _, _ = desk
    gateway.world(EXEC)["outlook_busy"] = [outlook("10:00", "11:00", "Board call")]
    result = gate(desk, proposed())
    assert result.status == "needs_info" and result.error == "calendar_conflict"
    assert "Board call" in result.output["message"] and "outlook" in result.output["message"]
    assert result.output["availability"]["conflicts"][0]["account"] == "exec@contoso.example"


def test_an_unreadable_calendar_holds_the_card_as_unknown(desk):
    gateway, _, _ = desk
    gateway.world(EXEC)["outlook_error"] = "reconnect_required"
    result = gate(desk, proposed())
    assert result.status == "needs_info" and result.error == "availability_unknown"
    assert result.output["blocked"] is True
    assert "outlook (exec@contoso.example): reconnect_required" in result.output["message"]


def test_no_connected_calendar_is_unknown_too(desk):
    gateway, service, _ = desk
    gateway.add_user(3, "lonely@example.test")
    gateway.acting_as = "lonely@example.test"
    result = availability_gate(service, CTX, gateway.world("lonely@example.test")["user"], proposed(),
                               user_confirmed=False, make=make)
    assert result.error == "availability_unknown"


def test_the_users_confirmation_books_despite_a_conflict_and_is_recorded(desk):
    gateway, _, _ = desk
    gateway.world(EXEC)["outlook_busy"] = [outlook("10:00", "11:00")]
    result = gate(desk, proposed(**{OVERRIDE_FLAG: True}), user_confirmed=True)
    assert result.status == "awaiting_approval"
    assert result.output["availability"]["overridden_by_user"] is True
    assert result.output["availability"]["free"] is False


def test_an_override_the_user_did_not_give_changes_nothing(desk):
    gateway, _, _ = desk
    gateway.world(EXEC)["outlook_busy"] = [outlook("10:00", "11:00")]
    result = gate(desk, proposed(**{OVERRIDE_FLAG: True}), user_confirmed=False)
    assert result.status == "needs_info" and OVERRIDE_FLAG not in result.input


def test_an_event_without_an_end_uses_the_default_length(desk):
    gateway, _, _ = desk
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("10:20", "10:40")]
    validation = Validation("awaiting_approval", {"title": "Call", "start": f"{MON}T10:00:00+00:00"})
    assert gate(desk, validation).error == "calendar_conflict"  # 10:00 to 10:30 by default


def test_a_time_in_another_zone_is_compared_as_the_same_instant(desk):
    gateway, _, _ = desk
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("10:00", "11:00")]
    # 12:15 in Beirut is 10:15 UTC.
    validation = Validation("awaiting_approval", {"title": "Call", "start": f"{MON}T12:15:00+02:00",
                                                  "end": f"{MON}T12:45:00+02:00"})
    assert gate(desk, validation).error == "calendar_conflict"


def test_a_start_without_an_offset_is_read_in_the_events_time_zone(desk):
    gateway, _, _ = desk
    gateway.world(EXEC)["google_busy"]["exec@gmail.example"] = [google("10:00", "11:00")]
    validation = Validation("awaiting_approval", {"title": "Call", "start": f"{MON}T12:15:00",
                                                  "end": f"{MON}T12:45:00", "timezone": "Asia/Beirut"})
    assert gate(desk, validation).error == "calendar_conflict"


def test_a_failure_inside_the_gate_fails_closed(desk):
    gateway, service, user = desk
    gateway.preferences = lambda user: (_ for _ in ()).throw(RuntimeError("preferences down"))
    result = availability_gate(service, CTX, user, proposed(), user_confirmed=True, make=make)
    assert result.status == "needs_info" and result.error == "availability_unknown"
    assert result.output["blocked"] is True


def test_an_unparseable_start_fails_closed(desk):
    result = gate(desk, Validation("awaiting_approval", {"title": "Call", "start": "tomorrow at 3"}))
    assert result.status == "needs_info" and result.error == "availability_unknown"


def test_another_users_calendar_never_blocks_or_frees_this_card(desk):
    gateway, _, _ = desk
    gateway.world(OTHER)["google_busy"]["other@gmail.example"] = [google("10:00", "11:00", "other@gmail.example")]
    assert gate(desk, proposed()).status == "awaiting_approval"
    assert ("google_busy", EXEC, "other@gmail.example") not in gateway.calls
