"""Availability across several calendars. Pure: no network, no clock, no Scriba import.

The slot search itself is Scriba's own ``compute_free_slots`` (transferred
unchanged into ``scriba_transferred``). This module adds what a secretary
needs around it and Scriba's single-calendar helper does not have: busy time
from more than one calendar, buffers around meetings, working hours to the
minute, working weekdays, and conflict reporting that keeps the provider and
account of every interval.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from .scriba_transferred.availability import compute_free_slots

Interval = Tuple[dt.datetime, dt.datetime]

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$")
# Scriba's slot search takes whole workday hours; a workday may not end after this.
_LATEST_END_MINUTES = 23 * 60


class InvalidAvailabilityRequest(ValueError):
    """The caller asked for something that cannot be answered (bad range, zone, duration)."""


@dataclass(frozen=True)
class Busy:
    """One busy interval and where it came from. Identity is never dropped."""

    start: dt.datetime
    end: dt.datetime
    provider: str
    account: str
    title: Optional[str] = None

    def as_dict(self, tz: dt.tzinfo) -> dict:
        return {
            "start": self.start.astimezone(tz).isoformat(),
            "end": self.end.astimezone(tz).isoformat(),
            "provider": self.provider,
            "account": self.account,
            "title": self.title,
        }


@dataclass(frozen=True)
class WorkingHours:
    start_minutes: int = 9 * 60
    end_minutes: int = 17 * 60
    # Python weekday numbers, Monday = 0 (Scriba's preference format). Empty = every day.
    weekdays: Tuple[int, ...] = ()

    def as_dict(self) -> dict:
        return {
            "start": minutes_to_text(self.start_minutes),
            "end": minutes_to_text(self.end_minutes),
            "weekdays": list(self.weekdays),
        }


def resolve_zone(name: Optional[str]) -> ZoneInfo:
    """A real IANA zone or an error. Never a silent fallback to another zone."""
    text = (name or "").strip()
    if not text:
        raise InvalidAvailabilityRequest("A time zone is required.")
    try:
        return ZoneInfo(text)
    except Exception as exc:  # ZoneInfoNotFoundError, ValueError, ...
        raise InvalidAvailabilityRequest(f"Unknown time zone: {text}") from exc


def parse_time_text(value: Optional[str], default_minutes: int) -> int:
    """'HH:MM' or 'HH:MM:SS' to minutes after midnight."""
    match = _TIME_RE.match(str(value or ""))
    if not match:
        return default_minutes
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return default_minutes
    return hour * 60 + minute


def minutes_to_text(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_instant(value: Optional[str], tz: dt.tzinfo) -> dt.datetime:
    """ISO 8601 to an aware datetime. A value without an offset is read in ``tz``."""
    text = str(value or "").strip()
    if not text:
        raise InvalidAvailabilityRequest("A start and an end are required.")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidAvailabilityRequest(f"Not an ISO 8601 date-time: {text}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def merge_intervals(intervals: Iterable[Interval]) -> List[Interval]:
    """Union of intervals: sorted, with overlapping and touching ones joined."""
    ordered = sorted((s, e) for s, e in intervals if s and e and e > s)
    merged: List[Interval] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def with_buffer(intervals: Iterable[Interval], buffer_minutes: int) -> List[Interval]:
    """Widen each busy interval so a suggested slot keeps a gap on both sides."""
    pad = dt.timedelta(minutes=max(int(buffer_minutes or 0), 0))
    return merge_intervals((start - pad, end + pad) for start, end in intervals)


def cross_calendar_conflicts(busy: Sequence[Busy]) -> List[dict]:
    """Pairs of busy intervals on DIFFERENT calendars that overlap: existing double bookings."""
    ordered = sorted(busy, key=lambda item: item.start)
    conflicts: List[dict] = []
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if second.start >= first.end:
                break
            if (first.provider, first.account) == (second.provider, second.account):
                continue
            conflicts.append({
                "start": max(first.start, second.start),
                "end": min(first.end, second.end),
                "between": [first, second],
            })
    return conflicts


def slot_conflicts(
    busy: Sequence[Busy], start: dt.datetime, end: dt.datetime, buffer_minutes: int = 0,
) -> List[Busy]:
    """Every busy interval a proposed slot collides with, buffer included."""
    pad = dt.timedelta(minutes=max(int(buffer_minutes or 0), 0))
    return [item for item in busy if start < item.end + pad and end > item.start - pad]


def working_windows(
    range_start: dt.datetime, range_end: dt.datetime, tz: dt.tzinfo, hours: WorkingHours,
) -> List[Interval]:
    """The working part of each local day inside the range."""
    if hours.end_minutes <= hours.start_minutes:
        return []
    windows: List[Interval] = []
    day = range_start.astimezone(tz).date()
    last = range_end.astimezone(tz).date()
    while day <= last:
        if not hours.weekdays or day.weekday() in hours.weekdays:
            midnight = dt.datetime.combine(day, dt.time.min, tzinfo=tz)
            start = max(midnight + dt.timedelta(minutes=hours.start_minutes), range_start)
            end = min(midnight + dt.timedelta(minutes=hours.end_minutes), range_end)
            if end > start:
                windows.append((start, end))
        day += dt.timedelta(days=1)
    return windows


def suggest_slots(
    busy: Iterable[Interval],
    *,
    range_start: dt.datetime,
    range_end: dt.datetime,
    timezone: str,
    duration_minutes: int,
    buffer_minutes: int = 0,
    hours: WorkingHours = WorkingHours(),
    max_slots: int = 5,
    not_before: Optional[dt.datetime] = None,
) -> List[dict]:
    """Free slots inside working hours that avoid every busy interval.

    ``busy`` is the union across all calendars. ``not_before`` (normally "now")
    keeps suggestions out of the past.
    """
    tz = resolve_zone(timezone)
    if duration_minutes < 15 or duration_minutes > 8 * 60:
        raise InvalidAvailabilityRequest("Duration must be between 15 and 480 minutes.")
    if range_end <= range_start:
        raise InvalidAvailabilityRequest("The end of the range must be after its start.")
    if not_before and not_before > range_start:
        range_start = not_before
    if range_end <= range_start:
        return []

    hours = WorkingHours(
        start_minutes=hours.start_minutes,
        end_minutes=min(hours.end_minutes, _LATEST_END_MINUTES),
        weekdays=hours.weekdays,
    )
    blocked = with_buffer(busy, buffer_minutes)
    slots: List[dict] = []
    for window_start, window_end in working_windows(range_start, range_end, tz, hours):
        remaining = max_slots - len(slots)
        if remaining <= 0:
            break
        # Scriba's slot search, one working day at a time. The exact window
        # bounds carry the minutes; the hour arguments only bracket them.
        found = compute_free_slots(
            blocked,
            window_start=window_start,
            window_end=window_end,
            timezone=timezone,
            duration_minutes=duration_minutes,
            workday_start_hour=hours.start_minutes // 60,
            workday_end_hour=-(-hours.end_minutes // 60),
            max_slots=remaining,
        )
        slots.extend({"start": slot["start"], "end": slot["end"]} for slot in found)
    return slots
