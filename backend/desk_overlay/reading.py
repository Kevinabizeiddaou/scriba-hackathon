"""Reading a message by rule. Pure: no network, no clock, no Scriba import.

Scriba's classifier answers "does this need a reply?". A secretary also has
to see three things it does not look for, and to read a time that is written
out in full when no model is available:

- ``meeting_signal``    a request to meet, move a meeting or cancel one, even
                        when the word "meeting" never appears;
- ``action_signal``     something the executive is asked to decide, approve
                        or sign off, usually by a time;
- ``explicit_request``  one day and one time (or one range), in the zone it
                        was written in.

Every function here refuses rather than guesses: an ambiguous text returns
None and the workflow asks or escalates.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, available_timezones

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december")
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\b", re.I)
_MONTH_DAY = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
_WEEKDAY = re.compile(r"\b(?:(this|next)\s+)?(" + "|".join(WEEKDAYS) + r")\b", re.I)
# A colon only: "3.50" is a price as often as a time.
_HHMM = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\s*(am|pm)?\b", re.I)
_H_AMPM = re.compile(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", re.I)
_NAMED_TIME = re.compile(r"\b(noon|midday)\b", re.I)
_RANGE = re.compile(
    r"\b(?:from\s+)?((?:[01]?\d|2[0-3]):[0-5]\d\s*(?:am|pm)?|(?:1[0-2]|0?[1-9])\s*(?:am|pm))\s*(?:to|until|-|–)\s*"
    r"((?:[01]?\d|2[0-3]):[0-5]\d\s*(?:am|pm)?|(?:1[0-2]|0?[1-9])\s*(?:am|pm))", re.I)
_DURATION = re.compile(
    r"\b(?:for\s+|a\s+|take\s+)?(?:(\d{1,3})[\s-]*(?:min|mins|minutes?)|(an?|one|two|1|2)[\s-]+hours?|half an hour)\b",
    re.I)

# Zone abbreviations with one meaning. IST and CST are left out: they name
# more than one zone, and a wrong conversion books the wrong hour.
ZONE_ABBREVIATIONS = {
    "ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York",
    "CT": "America/Chicago", "CDT": "America/Chicago", "MT": "America/Denver",
    "MST": "America/Denver", "MDT": "America/Denver", "PT": "America/Los_Angeles",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles", "GMT": "UTC", "UTC": "UTC",
    "BST": "Europe/London", "CET": "Europe/Paris", "CEST": "Europe/Paris", "EET": "Europe/Athens",
    "EEST": "Europe/Athens",
}
# Written in capitals only: "et", "est" and "cet" are ordinary words elsewhere.
_ABBREVIATION = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(ZONE_ABBREVIATIONS, key=len, reverse=True))
                           + r")(?![A-Za-z])")
# Spelled out, and only when followed by "time": "eastern Mediterranean" is not a zone.
_ZONE_WORDS = {"eastern": "America/New_York", "central": "America/Chicago",
               "mountain": "America/Denver", "pacific": "America/Los_Angeles"}
_ZONE_WORD = re.compile(r"\b(eastern|central|mountain|pacific)\s+(?:standard\s+|daylight\s+)?time\b", re.I)
_AMBIGUOUS_ZONE = re.compile(r"(?<![A-Za-z])(?:IST|CST)(?![A-Za-z])|\b(?:my time|our time|local time)\b")
_CITY_TIME = re.compile(r"\b([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?)\s+time\b")
_CITIES: Dict[str, str] = {}

_REQUEST_CUE = re.compile(
    r"\b(could we|can we|shall we|let'?s|are you (?:free|available)|do you have (?:time|\d+)|"
    r"would you (?:be free|have time|be available)|i'?d like to (?:schedule|set up|arrange|book)|"
    r"we'?d like to (?:schedule|set up|arrange|book)|may we|how about|would .{0,20} work)\b", re.I)
_MEETING_NOUN = re.compile(
    r"\b(meeting|call|demo|catch[- ]?up|chat|coffee|lunch|session|review|sync|workshop|interview|"
    r"appointment|1:1|one[- ]on[- ]one|intro|briefing|walk[- ]?through|stand[- ]?up)\b", re.I)
_MEET_VERB = re.compile(r"\b(meet|schedule|book|set up|arrange)\b", re.I)
_CANCEL = re.compile(r"\b(cancel\w*|call(?:ing)? off|won'?t be able to (?:make|attend|join)|"
                     r"can(?:no|')t make (?:it|the|our|today)|have to drop)\b", re.I)
_MOVE = re.compile(r"\b(reschedul\w*|postpon\w*|(?:move|push|shift|bring forward|delay)\s+(?:our|the|my|it|this|that)|"
                   r"another time|different time)\b", re.I)
_ACTION = re.compile(
    r"\b(?:i\s+)?(?:need|require|am waiting (?:for|on)|await(?:ing)?|would appreciate|please (?:send|give|provide))\s+"
    r"(?:\w+\s+){0,2}?your\s+(decision|approval|sign[- ]?off|signature|answer|input|confirmation|feedback|go[- ]?ahead)\b"
    r"|\bplease (?:approve|sign|review and (?:approve|sign)|confirm) (?:the|this|it)\b"
    r"|\bfor your (?:approval|sign[- ]?off|signature|decision)\b", re.I)
# ── what must be read in full or not at all ────────────────────────────────
# A day or a zone is read from a pattern. Words beside the pattern can change
# what it means ("the day AFTER tomorrow", "Thursday WEEK", "GMT+3"). When
# such a word is there and this reader cannot compute it, the time is not
# read: a fragment of a phrase is never booked.
_WD = "|".join(WEEKDAYS)
_MN = "|".join(MONTHS)
_UNREAD_DAY = re.compile(
    r"\bday after tomorrow\b|\bthe day (?:after|before)\b|\bday before\b|\bafter next\b|"
    r"\b(?:a|one|two|three|\d+) weeks? (?:from|on|after)\b|\bweek (?:on|from|after)\b|"
    r"\b(?:" + _WD + r")\s+(?:week|fortnight)\b|\bfortnight\b|"
    r"\bin (?:a|one|two|three|four|five|six|\d+) (?:days?|weeks?|months?)\b|"
    r"\b(?:end|start|beginning|middle) of (?:the|this|next) (?:week|month)\b|"
    r"\b(?:the )?(?:following|coming) (?:" + _WD + r")\b", re.I)
_RELATIVE_WEEK = re.compile(r"\b(?:next|following|coming) week\b|\bthe week after\b", re.I)
# "GMT+3", "UTC-05": a zone abbreviation with an offset is a different zone.
_OFFSET_ZONE = re.compile(r"(?<![A-Za-z])(?:GMT|UTC)\s*([+-])\s*(\d{1,2})(?::?([0-5]\d))?(?!\d)")
_WEEKDAY_WITH_DATE = re.compile(
    r"\b(" + _WD + r")\b[,\s]+(?:the\s+)?"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:" + _MN + r")|(?:" + _MN + r")\s+\d{1,2}(?:st|nd|rd|th)?|20\d{2}-\d{2}-\d{2})",
    re.I)
# An instruction taken back in the same message.
_RETRACT = re.compile(
    r"\bon second thou?ghts?\b|\bscratch that\b|\bnever ?mind\b|\bdisregard\b|\bas you were\b|"
    r"\bignore (?:that|this|the above|my (?:last|previous|earlier))\b|"
    r"\bactually,? (?:let'?s )?(?:keep|leave|don'?t|do not)\b|\b(?:let'?s )?keep it (?:as (?:it )?is|as planned|where it is|in)\b|"
    r"\b(?:please )?(?:don'?t|do not) (?:cancel|move|reschedule|book|change) (?:it|that|this|anything)\b|"
    r"\bchanged my mind\b|\bforget (?:that|it|what i said)\b", re.I)
# The message speaks of a meeting that already exists, or of moving one.
_EXISTING = re.compile(
    r"\b(?:" + _WD + r"|today|tomorrow|this (?:morning|afternoon|evening)|next week)'s\b|"
    r"\b(?:our|the|my|that|this)\s+(?:\w+\s+){0,2}?(?:meeting|call|demo|catch[- ]?up|session|review|sync|workshop|"
    r"interview|appointment|1:1|one[- ]on[- ]one|briefing|stand[- ]?up|lunch|coffee)\b|"
    r"\b(?:push|move|shift|bring|swap|switch|change|bump|slide)\b.{0,40}?\b(?:back|forward|to|until|from|instead)\b|"
    r"\binstead\b|\brather than\b", re.I)

_URGENT = re.compile(r"\b(urgent(?:ly)?|asap|as soon as possible|immediately|right away|today)\b", re.I)


def _city_zone(name: str) -> Optional[str]:
    """``Beirut`` -> ``Asia/Beirut``, from the system's own zone list."""
    if not _CITIES:
        for zone in available_timezones():
            city = zone.rsplit("/", 1)[-1].replace("_", " ").lower()
            _CITIES.setdefault(city, zone)
    return _CITIES.get(name.strip().lower())


def stated_zone(text: str) -> Tuple[Optional[str], bool]:
    """(zone the time was written in, is the text ambiguous about it).

    None with False means no zone was named: the reader's own zone applies
    ("your time" says the same thing). True means a zone was named that
    cannot be resolved to exactly one zone; the time is then not read.
    """
    raw = str(text or "")
    if _AMBIGUOUS_ZONE.search(raw):
        return None, True
    found: List[str] = []
    for match in _OFFSET_ZONE.finditer(raw):
        hours = int(match.group(2))
        if match.group(3) not in (None, "00") or hours > 14:
            return None, True           # a half-hour offset has no name this reader can use
        # IANA writes these with the sign reversed: GMT+3 is "Etc/GMT-3".
        found.append("UTC" if hours == 0 else f"Etc/GMT{'-' if match.group(1) == '+' else '+'}{hours}")
    raw = _OFFSET_ZONE.sub(" ", raw)
    for match in _CITY_TIME.finditer(raw):
        if match.group(1).split()[-1].lower() in _ZONE_WORDS:
            continue                    # "Pacific time": handled as a zone word below
        zone = _city_zone(match.group(1)) or _city_zone(match.group(1).split()[-1])
        if zone:
            found.append(zone)
    for match in _ABBREVIATION.finditer(raw):
        found.append(ZONE_ABBREVIATIONS[match.group(1)])
    for match in _ZONE_WORD.finditer(raw):
        found.append(_ZONE_WORDS[match.group(1).lower()])
    zones = set(found)
    if len(zones) > 1:
        return None, True
    return (next(iter(zones)) if zones else None), False


def _days(lowered: str, today: dt.date) -> List[dt.date]:
    days: List[dt.date] = []

    def add(day: dt.date) -> None:
        if day not in days:
            days.append(day)

    for match in _ISO_DATE.finditer(lowered):
        try:
            add(dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            pass
    for pattern, order in ((_DAY_MONTH, (1, 2)), (_MONTH_DAY, (2, 1))):
        for match in pattern.finditer(lowered):
            month = MONTHS.index(match.group(order[1]).lower()) + 1
            for year in (today.year, today.year + 1):
                try:
                    candidate = dt.date(year, month, int(match.group(order[0])))
                except ValueError:
                    continue
                if candidate >= today:
                    add(candidate)
                    break
    if re.search(r"\btomorrow\b", lowered):
        add(today + dt.timedelta(days=1))
    if re.search(r"\b(?:today|tonight|this (?:morning|afternoon|evening))\b|\btoday's\b", lowered):
        add(today)
    if not days:      # a weekday name counts only when no date was written
        for match in _WEEKDAY.finditer(lowered):
            target = WEEKDAYS.index(match.group(2).lower())
            ahead = (target - today.weekday()) % 7 or 7
            if match.group(1) == "next" and today.weekday() < target:
                ahead += 7
            add(today + dt.timedelta(days=ahead))
    return days


def _clock(text: str) -> Tuple[int, int]:
    """A clock time written as ``HH:MM`` or ``H am/pm``."""
    match = _HHMM.search(text)
    if match:
        hour, minute, half = int(match.group(1)), int(match.group(2)), (match.group(3) or "").lower()
        if half and hour <= 12:
            hour = hour % 12 + (12 if half == "pm" else 0)
        return hour, minute
    match = _H_AMPM.search(text)
    return int(match.group(1)) % 12 + (12 if match.group(2).lower() == "pm" else 0), 0


def _times(lowered: str) -> Tuple[List[Tuple[int, int]], Optional[Tuple[Tuple[int, int], Tuple[int, int]]]]:
    """(distinct clock times, the one written range if there is exactly one)."""
    ranges = [(_clock(m.group(1)), _clock(m.group(2))) for m in _RANGE.finditer(lowered)]
    stripped = _RANGE.sub(" ", lowered) if len(ranges) == 1 else lowered
    times: List[Tuple[int, int]] = []
    spans = [m.span() for m in _HHMM.finditer(stripped)]
    for match in _HHMM.finditer(stripped):
        value = _clock(match.group(0))
        if value not in times:
            times.append(value)
    for match in _H_AMPM.finditer(stripped):
        if any(start <= match.start() < end for start, end in spans):
            continue
        value = _clock(match.group(0))
        if value not in times:
            times.append(value)
    if _NAMED_TIME.search(stripped) and (12, 0) not in times:
        times.append((12, 0))
    return times, (ranges[0] if len(ranges) == 1 else None)


def _duration(lowered: str) -> Optional[int]:
    match = _DURATION.search(lowered)
    if not match:
        return None
    if match.group(1):
        return int(match.group(1))
    if match.group(2):
        return 120 if match.group(2) in ("two", "2") else 60
    return 30


def _one(text: str, now: dt.datetime) -> Optional[Dict[str, Any]]:
    lowered = " ".join(str(text or "").lower().split())
    if not lowered:
        return None
    if _UNREAD_DAY.search(lowered):
        return None                      # a word that moves the day, which this reader does not compute
    zone_name, ambiguous = stated_zone(text)
    if ambiguous:
        return None
    zone = ZoneInfo(zone_name) if zone_name else now.tzinfo
    today = now.astimezone(zone).date() if zone_name else now.date()
    written_date = bool(_ISO_DATE.search(lowered) or _DAY_MONTH.search(lowered) or _MONTH_DAY.search(lowered))
    if not written_date and _RELATIVE_WEEK.search(lowered):
        return None                      # "Tuesday next week" is not the coming Tuesday
    if weekday_contradicts_date(lowered, today):
        return None                      # "Wednesday 9 March" when the 9th is a Tuesday: ask, never pick
    days = _days(lowered, today)
    times, written_range = _times(lowered)
    if len(days) != 1:
        return None
    if written_range and not times:
        (hour, minute), end_clock = written_range
    elif len(times) == 1 and not written_range:
        (hour, minute), end_clock = times[0], None
    else:
        return None
    start = dt.datetime.combine(days[0], dt.time(hour, minute), tzinfo=zone)
    if start <= now:
        return None
    found: Dict[str, Any] = {"requested_start": start.isoformat(), "source": "rules",
                             "requester_timezone": zone_name}
    if end_clock:
        end = dt.datetime.combine(days[0], dt.time(*end_clock), tzinfo=zone)
        if end <= start:
            return None
        found["requested_end"] = end.isoformat()
    else:
        minutes = _duration(lowered)
        if minutes:
            found["duration_minutes"] = minutes
    return found


def weekday_contradicts_date(text: str, today: dt.date) -> bool:
    """A weekday written beside a date that falls on another weekday."""
    lowered = " ".join(str(text or "").lower().split())
    for match in _WEEKDAY_WITH_DATE.finditer(lowered):
        dates = _days(match.group(2), today)
        if len(dates) == 1 and WEEKDAYS[dates[0].weekday()] != match.group(1).lower():
            return True
    return False


def days_named(text: str, now: dt.datetime) -> List[dt.date]:
    """The days a text names (dates, today, tomorrow, weekday names)."""
    return _days(" ".join(str(text or "").lower().split()), now.date())


def retracted(text: str) -> bool:
    """The message takes an instruction back ("cancel it. On second thought,
    keep it"). Which of the two stands is the writer's to say, not a rule's."""
    return bool(_RETRACT.search(str(text or "")))


_REMINDER = re.compile(r"\bremind (?:me|yourself|you|us)\b|\bset (?:me |yourself )?a reminder\b", re.I)


def reminder_request(text: str) -> bool:
    """The message asks to be reminded of something. A reminder with a time
    is not a meeting with whoever wrote it."""
    return bool(_REMINDER.search(str(text or "")))


def refers_to_existing(subject: str, text: str) -> bool:
    """The message speaks of a meeting that exists ("Thursday's call", "our
    review") or of moving one ("push ... back to Friday"). Whether the sender
    really has such a meeting is for the calendar to say."""
    return bool(_EXISTING.search(f"{subject or ''}\n{text or ''}"))


def explicit_request(text: str, now: dt.datetime, *, change: bool = False) -> Optional[Dict[str, Any]]:
    """A time that is written out in full, read in the zone it was written in.

    Exactly one day and exactly one clock time (``HH:MM``, ``H am/pm`` or
    "noon"), or exactly one range ("from 14:00 to 15:00"). A bare "at 3" is
    not enough; two days or two separate times are a choice being offered,
    which this does not make; a zone that cannot be resolved to one zone
    ("IST", "my time") means the hour is somebody else's and is not read.

    ``change`` is for a request to move a meeting. Such a message often names
    the old time and the new one ("move our 10:00 call to Friday at 11:00").
    The new time is what follows the last "to"; when the whole text is
    ambiguous, that clause alone is read.
    """
    found = _one(text, now)
    if found is None and change:
        clauses = re.split(r"\bto\b", str(text or ""))
        if len(clauses) > 1:
            found = _one(clauses[-1], now)
            if found is not None and "duration_minutes" not in found and "requested_end" not in found:
                minutes = _duration(" ".join(str(text or "").lower().split()))
                if minutes:
                    found["duration_minutes"] = minutes
    return found


def meeting_signal(subject: str, text: str) -> Optional[str]:
    """``new``, ``reschedule`` or ``cancel`` when the message asks for one of
    those; None otherwise. Read from the text, whatever a classifier said.

    - cancel: a cancelling phrase about something scheduled (a meeting word,
      or a time).
    - reschedule: a moving phrase about something scheduled.
    - new: a request ("could we", "are you free") together with a time, a
      length or a meeting word; or a meeting verb with a day.
    """
    body = str(text or "")
    combined = f"{subject or ''}\n{body}"
    lowered = " ".join(combined.lower().split())
    scheduled = bool(_MEETING_NOUN.search(combined) or _HHMM.search(lowered) or _H_AMPM.search(lowered))
    if _CANCEL.search(combined) and scheduled:
        return "cancel"
    if _MOVE.search(combined) and scheduled:
        return "reschedule"
    has_day = bool(_WEEKDAY.search(lowered) or _DAY_MONTH.search(lowered) or _MONTH_DAY.search(lowered)
                   or _ISO_DATE.search(lowered) or re.search(r"\b(?:tomorrow|next week|this week)\b", lowered))
    has_time = bool(_HHMM.search(lowered) or _H_AMPM.search(lowered) or _RANGE.search(lowered))
    if _REQUEST_CUE.search(body):
        if (has_time and has_day) or (_duration(lowered) and (has_day or has_time)):
            return "new"
        if _MEETING_NOUN.search(body) and (has_day or has_time):
            return "new"
    if _MEET_VERB.search(body) and has_day and (has_time or _MEETING_NOUN.search(body)):
        return "new"
    return None


def action_signal(text: str) -> bool:
    """The executive is asked to decide, approve, sign or confirm something."""
    return bool(_ACTION.search(str(text or "")))


def urgency(text: str, due: Optional[dt.datetime], now: dt.datetime) -> Optional[str]:
    """``urgent`` when the text says so or the deadline is today; ``high``
    when it is within two days; None when nothing indicates urgency."""
    if due is not None:
        if due.date() <= now.date():
            return "urgent"
        if due - now <= dt.timedelta(days=2):
            return "high"
    if _URGENT.search(str(text or "")):
        return "urgent" if due is None else "high"
    return None
