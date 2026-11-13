# Transferred unchanged from Scriba: Gmail/packages/domain/calendar_read/availability.py @ 3ae3a2aa.
# Standard library only. Keep byte-identical below this header; the integration
# test backend/tests/integration/test_with_scriba.py checks it against Scriba's copy.
"""Pure availability mathematics — byte-parity with the slotting loop in
``app.calendar_client.find_free_slots`` (parity-locked by tests).

The provider boundary stays outside: callers fetch busy intervals from the
ONE freebusy query (Google-only today, per the capability matrix) and hand
them here. This module never touches SDKs, clocks, or credentials.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, List, Optional, Tuple

from .time_rules import safe_zoneinfo

BusyInterval = Tuple[dt.datetime, dt.datetime]


def slot_is_free(busy: List[BusyInterval]) -> bool:
    """The freebusy semantics: free iff no busy interval was returned."""
    return len(busy) == 0


def compute_free_slots(
    busy: List[BusyInterval],
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
    timezone: str,
    duration_minutes: int,
    workday_start_hour: int,
    workday_end_hour: int,
    max_slots: int = 3,
    default_slot_minutes: int = 30,
    format_slot: Optional[Callable[[dt.datetime, dt.datetime, str], str]] = None,
) -> List[dict]:
    """The legacy working-hours slotting: 30-minute steps aligned to the half
    hour, per-day iteration bounded by the workday, overlap avoidance against
    the sorted busy set, stopping at ``max_slots``."""
    duration = dt.timedelta(minutes=max(int(duration_minutes or default_slot_minutes), 15))
    if window_end <= window_start:
        return []

    ordered = sorted(
        [(start, end) for start, end in busy if start and end and end > start],
        key=lambda pair: pair[0],
    )

    slots: List[dict] = []
    tzinfo = safe_zoneinfo(timezone)
    step = dt.timedelta(minutes=30)
    cursor_day = window_start.astimezone(tzinfo).date()
    last_day = window_end.astimezone(tzinfo).date()

    while cursor_day <= last_day and len(slots) < max_slots:
        day_start = dt.datetime.combine(cursor_day, dt.time(hour=workday_start_hour), tzinfo=tzinfo)
        day_end = dt.datetime.combine(cursor_day, dt.time(hour=workday_end_hour), tzinfo=tzinfo)
        cursor = max(day_start, window_start.astimezone(tzinfo))
        if cursor.minute % 30:
            cursor += dt.timedelta(minutes=(30 - cursor.minute % 30))
            cursor = cursor.replace(second=0, microsecond=0)
        while cursor + duration <= min(day_end, window_end.astimezone(tzinfo)) and len(slots) < max_slots:
            candidate_end = cursor + duration
            overlaps = any(cursor < busy_end and candidate_end > busy_start
                           for busy_start, busy_end in ordered)
            if not overlaps:
                slots.append({
                    "start": cursor.isoformat(),
                    "end": candidate_end.isoformat(),
                    "label": format_slot(cursor, candidate_end, timezone)
                    if format_slot else None,
                })
                cursor += duration
            else:
                cursor += step
        cursor_day += dt.timedelta(days=1)

    return slots
