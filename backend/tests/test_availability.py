"""Pure availability mathematics: no Scriba, no network."""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from desk_overlay.availability import (
    Busy,
    InvalidAvailabilityRequest,
    WorkingHours,
    cross_calendar_conflicts,
    merge_intervals,
    parse_instant,
    parse_time_text,
    resolve_zone,
    slot_conflicts,
    suggest_slots,
    with_buffer,
    working_windows,
)

UTC = dt.timezone.utc


def t(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text).replace(tzinfo=UTC)


MON = "2026-11-16"  # a Monday


def test_merge_joins_overlapping_and_touching_intervals():
    merged = merge_intervals([
        (t(f"{MON}T10:00"), t(f"{MON}T11:00")),
        (t(f"{MON}T10:30"), t(f"{MON}T11:30")),
        (t(f"{MON}T11:30"), t(f"{MON}T12:00")),
        (t(f"{MON}T14:00"), t(f"{MON}T15:00")),
    ])
    assert merged == [(t(f"{MON}T10:00"), t(f"{MON}T12:00")), (t(f"{MON}T14:00"), t(f"{MON}T15:00"))]


def test_merge_drops_empty_and_inverted_intervals():
    assert merge_intervals([(t(f"{MON}T10:00"), t(f"{MON}T10:00")),
                            (t(f"{MON}T12:00"), t(f"{MON}T11:00"))]) == []


def test_buffer_widens_both_sides():
    assert with_buffer([(t(f"{MON}T10:00"), t(f"{MON}T11:00"))], 15) == [
        (t(f"{MON}T09:45"), t(f"{MON}T11:15"))]


def test_slots_avoid_busy_time_from_every_calendar():
    slots = suggest_slots(
        [(t(f"{MON}T09:00"), t(f"{MON}T10:00")),      # one calendar
         (t(f"{MON}T10:00"), t(f"{MON}T11:30"))],     # the other
        range_start=t(f"{MON}T00:00"), range_end=t(f"{MON}T23:59"), timezone="UTC",
        duration_minutes=30, max_slots=2,
    )
    assert [s["start"] for s in slots] == [f"{MON}T11:30:00+00:00", f"{MON}T12:00:00+00:00"]


def test_buffer_keeps_a_gap_after_a_meeting():
    slots = suggest_slots(
        [(t(f"{MON}T09:00"), t(f"{MON}T10:00"))],
        range_start=t(f"{MON}T00:00"), range_end=t(f"{MON}T23:59"), timezone="UTC",
        duration_minutes=30, buffer_minutes=15, max_slots=1,
    )
    # 10:00 would touch the meeting; with a 15 minute buffer the first aligned start is 10:30.
    assert slots[0]["start"] == f"{MON}T10:30:00+00:00"


def test_working_hours_to_the_minute():
    slots = suggest_slots(
        [], range_start=t(f"{MON}T00:00"), range_end=t(f"{MON}T23:59"), timezone="UTC",
        duration_minutes=60, hours=WorkingHours(start_minutes=9 * 60 + 30, end_minutes=11 * 60 + 30),
        max_slots=10,
    )
    assert [s["start"][11:16] for s in slots] == ["09:30", "10:30"]
    assert slots[-1]["end"][11:16] == "11:30"


def test_only_working_weekdays_are_offered():
    slots = suggest_slots(
        [], range_start=t("2026-11-14T00:00"), range_end=t("2026-11-17T00:00"), timezone="UTC",
        duration_minutes=60, hours=WorkingHours(weekdays=(0, 1, 2, 3, 4)), max_slots=1,
    )
    # 14 and 15 November 2026 are a Saturday and a Sunday.
    assert slots[0]["start"].startswith("2026-11-16T09:00")


def test_time_zone_decides_the_working_day():
    # 09:00 to 17:00 in Beirut (UTC+2 in November) is 07:00 to 15:00 UTC.
    slots = suggest_slots(
        [], range_start=t(f"{MON}T00:00"), range_end=t(f"{MON}T23:00"), timezone="Asia/Beirut",
        duration_minutes=30, max_slots=1,
    )
    assert slots[0]["start"] == f"{MON}T09:00:00+02:00"
    assert dt.datetime.fromisoformat(slots[0]["start"]).astimezone(UTC) == t(f"{MON}T07:00")


def test_busy_time_given_in_another_zone_still_blocks():
    new_york = ZoneInfo("America/New_York")
    busy_start = dt.datetime(2026, 11, 16, 4, 0, tzinfo=new_york)   # 09:00 UTC
    slots = suggest_slots(
        [(busy_start, busy_start + dt.timedelta(hours=2))],
        range_start=t(f"{MON}T00:00"), range_end=t(f"{MON}T23:59"), timezone="UTC",
        duration_minutes=30, max_slots=1,
    )
    assert slots[0]["start"] == f"{MON}T11:00:00+00:00"


def test_fully_booked_calendar_returns_no_slots():
    assert suggest_slots(
        [(t(f"{MON}T00:00"), t("2026-11-17T00:00"))],
        range_start=t(f"{MON}T00:00"), range_end=t(f"{MON}T23:59"), timezone="UTC",
        duration_minutes=30,
    ) == []


def test_slots_never_start_in_the_past():
    slots = suggest_slots(
        [], range_start=t(f"{MON}T00:00"), range_end=t(f"{MON}T23:59"), timezone="UTC",
        duration_minutes=30, max_slots=1, not_before=t(f"{MON}T13:10"),
    )
    assert slots[0]["start"] == f"{MON}T13:30:00+00:00"


def test_a_slot_must_fit_before_the_working_day_ends():
    slots = suggest_slots(
        [], range_start=t(f"{MON}T16:00"), range_end=t(f"{MON}T23:59"), timezone="UTC",
        duration_minutes=90, max_slots=5,
    )
    assert slots == []


def test_bad_requests_are_refused_not_guessed():
    with pytest.raises(InvalidAvailabilityRequest):
        resolve_zone("Mars/Olympus")
    with pytest.raises(InvalidAvailabilityRequest):
        resolve_zone("")
    with pytest.raises(InvalidAvailabilityRequest):
        parse_instant("next tuesday", UTC)
    with pytest.raises(InvalidAvailabilityRequest):
        suggest_slots([], range_start=t(f"{MON}T10:00"), range_end=t(f"{MON}T09:00"),
                      timezone="UTC", duration_minutes=30)
    with pytest.raises(InvalidAvailabilityRequest):
        suggest_slots([], range_start=t(f"{MON}T09:00"), range_end=t(f"{MON}T10:00"),
                      timezone="UTC", duration_minutes=5)


def test_a_time_without_an_offset_is_read_in_the_given_zone():
    assert parse_instant("2026-11-16T09:00:00", ZoneInfo("Asia/Beirut")).utcoffset() == dt.timedelta(hours=2)
    assert parse_instant("2026-11-16T09:00:00Z", ZoneInfo("Asia/Beirut")).utcoffset() == dt.timedelta(0)


def test_time_text_parsing_has_safe_defaults():
    assert parse_time_text("08:30:00", 0) == 510
    assert parse_time_text("8:05", 0) == 485
    assert parse_time_text("nonsense", 540) == 540
    assert parse_time_text("25:00", 540) == 540


def test_working_windows_clip_to_the_range():
    windows = working_windows(t(f"{MON}T10:15"), t(f"{MON}T12:00"), UTC, WorkingHours())
    assert windows == [(t(f"{MON}T10:15"), t(f"{MON}T12:00"))]


def test_cross_calendar_conflicts_keep_provider_and_account():
    google = Busy(t(f"{MON}T10:00"), t(f"{MON}T11:00"), "google", "exec@gmail.example")
    outlook = Busy(t(f"{MON}T10:30"), t(f"{MON}T11:30"), "outlook", "exec@contoso.example", "Board call")
    same_calendar = Busy(t(f"{MON}T10:15"), t(f"{MON}T10:45"), "google", "exec@gmail.example")
    conflicts = cross_calendar_conflicts([google, outlook, same_calendar])
    pairs = [{(b.provider, b.account) for b in c["between"]} for c in conflicts]
    assert {("google", "exec@gmail.example"), ("outlook", "exec@contoso.example")} in pairs
    # Two events on the SAME calendar are not a cross-calendar conflict.
    assert all(len(pair) == 2 for pair in pairs)
    first = next(c for c in conflicts if google in c["between"] and outlook in c["between"])
    assert (first["start"], first["end"]) == (t(f"{MON}T10:30"), t(f"{MON}T11:00"))


def test_slot_conflicts_respect_the_buffer():
    meeting = Busy(t(f"{MON}T10:00"), t(f"{MON}T11:00"), "outlook", "exec@contoso.example")
    assert slot_conflicts([meeting], t(f"{MON}T11:00"), t(f"{MON}T11:30")) == []
    assert slot_conflicts([meeting], t(f"{MON}T11:00"), t(f"{MON}T11:30"), buffer_minutes=10) == [meeting]
    assert slot_conflicts([meeting], t(f"{MON}T10:30"), t(f"{MON}T11:30")) == [meeting]
