# Transferred unchanged from Scriba: Gmail/packages/domain/calendar_read/time_rules.py @ 3ae3a2aa.
# Standard library only. Keep byte-identical below this header; the integration
# test backend/tests/integration/test_with_scriba.py checks it against Scriba's copy.
"""Canonical time rules for calendar reads — byte-parity with the legacy
helpers in ``app.agenda_service`` (parity-locked by tests).

- timestamps are timezone-aware internally; naive inputs assume the
  provided zone; ``Z`` normalizes to ``+00:00``;
- "today" is the USER-LOCAL calendar day, half-open ``[00:00, next-00:00)``
  — never a rolling 24-hour window; "week" is seven such days;
- the zone resolver falls back ``requested → Asia/Beirut → UTC`` (with a
  fixed +02 offset as the last resort for Asia/Beirut when tzdata is
  absent);
- the clock is always injectable (``now=``) — business logic never reads
  wall time implicitly.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo


def safe_zoneinfo(name: Optional[str]) -> dt.tzinfo:
    timezone_name = (name or "").strip() or "UTC"
    for candidate in (timezone_name, "Asia/Beirut", "UTC"):
        try:
            return ZoneInfo(candidate)
        except Exception:
            continue
    if timezone_name == "Asia/Beirut":
        return dt.timezone(dt.timedelta(hours=2), name="Asia/Beirut")
    return dt.timezone.utc


def local_now(timezone: str, now: Optional[dt.datetime] = None) -> dt.datetime:
    tzinfo = safe_zoneinfo(timezone)
    current = now or dt.datetime.now(tzinfo)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tzinfo)
    return current.astimezone(tzinfo)


def day_window(timezone: str, now: Optional[dt.datetime] = None) -> Tuple[dt.datetime, dt.datetime]:
    current = local_now(timezone, now=now)
    start = dt.datetime.combine(current.date(), dt.time.min, tzinfo=current.tzinfo)
    return start, start + dt.timedelta(days=1)


def week_window(timezone: str, now: Optional[dt.datetime] = None) -> Tuple[dt.datetime, dt.datetime]:
    current = local_now(timezone, now=now)
    start = dt.datetime.combine(current.date(), dt.time.min, tzinfo=current.tzinfo)
    return start, start + dt.timedelta(days=7)


def is_due_today(due_at: Any, timezone: str, *, now: Optional[dt.datetime] = None) -> bool:
    text = str(due_at or "").strip()
    if not text:
        return False
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    tzinfo = safe_zoneinfo(timezone)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tzinfo)
    parsed = parsed.astimezone(tzinfo)
    start, end = day_window(timezone, now=now)
    return start <= parsed < end


def parse_iso_flexible(value: Any, timezone: str) -> Optional[dt.datetime]:
    """The legacy ``_parse_datetime`` semantics: datetimes/dates/ISO strings,
    Z-normalization, naive→assume the given zone, then convert to it."""
    if value is None:
        return None
    tzinfo = safe_zoneinfo(timezone)
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        parsed = dt.datetime.combine(value, dt.time.min)
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tzinfo)
    return parsed.astimezone(tzinfo)
