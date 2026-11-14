"""Deterministic pieces of planning. Pure: no network, no clock, no Scriba import.

The workflow decides WHAT to propose from verified facts (the triage record,
the calendars as read, the event as found). These helpers do the parts that
need no model: reading a deadline that is written out, finding the meeting a
change request is about, spotting text that tries to instruct the Desk, and
writing the two fixed replies (times offered, clarification asked).

A model, when one is available, may improve on the wording of a reply. It
never widens what these functions allow.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")\b", re.I)
_MONTH_DAY = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
_BY_WEEKDAY = re.compile(
    r"\b(?:by|before|on|due|until|deadline(?:\s+is)?|no later than)\s+(?:on\s+)?(?:this\s+|next\s+)?("
    + "|".join(_WEEKDAYS) + r")\b", re.I)
_CLOCK = re.compile(r"\b(?:at|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)

# Text that addresses the assistant rather than the executive. Mail is data:
# finding this never makes the Desk do what it says. It makes the Desk stop.
_INJECTION = re.compile(
    r"(ignore (?:all |any |your )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)"
    r"|disregard (?:your|all|the) (?:instructions|rules|guidelines)"
    r"|you are (?:now )?(?:an? )?(?:ai|assistant|language model)"
    r"|system prompt|as an ai\b"
    r"|(?:auto(?:matically)?[- ]?approve|approve (?:this|it) (?:automatically|without (?:asking|review)))"
    r"|without (?:asking|telling|notifying) (?:the |your )?(?:user|executive|principal|boss)"
    r"|do not (?:ask|tell|notify) (?:the |your )?(?:user|executive|principal|boss)"
    r"|forward (?:all|every|this entire) (?:emails?|mail|messages?|inbox))",
    re.I)


def injection_suspected(*texts: Any) -> bool:
    return any(_INJECTION.search(str(text or "")) for text in texts)


def deadline_from(text: str, now: dt.datetime) -> Optional[dt.datetime]:
    """A deadline that is written out, in the zone of ``now``. None when the
    text names no day: the Desk does not guess one.

    A day with no time means the end of the working day (17:00).
    """
    lowered = str(text or "").lower()
    day: Optional[dt.date] = None
    match = _ISO_DATE.search(lowered)
    if match:
        try:
            day = dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            day = None
    if day is None:
        found = _DAY_MONTH.search(lowered)
        other = _MONTH_DAY.search(lowered)
        parts: Optional[Tuple[int, str]] = None
        if found:
            parts = (int(found.group(1)), found.group(2))
        elif other:
            parts = (int(other.group(2)), other.group(1))
        if parts:
            month = _MONTHS.index(parts[1].lower()) + 1
            for year in (now.year, now.year + 1):
                try:
                    candidate = dt.date(year, month, parts[0])
                except ValueError:
                    continue
                if candidate >= now.date():
                    day = candidate
                    break
    if day is None:
        if re.search(r"\b(?:by |before )?(?:eod|end of (?:the )?day|today|tonight)\b", lowered):
            day = now.date()
        elif re.search(r"\btomorrow\b", lowered):
            day = now.date() + dt.timedelta(days=1)
        elif re.search(r"\bend of (?:the |this )?week\b", lowered):
            day = now.date() + dt.timedelta(days=(4 - now.weekday()) % 7)
        else:
            weekday = _BY_WEEKDAY.search(lowered)
            if not weekday and re.search(r"\b(?:deadline|due)\b", lowered):
                # "the deadline for the board pack is Friday": a deadline is
                # named and exactly one weekday appears in the text.
                named = {m.group(2).lower() for m in _ANY_WEEKDAY.finditer(lowered)}
                if len(named) == 1:
                    weekday = re.search(r"(" + next(iter(named)) + r")", lowered)
            if weekday:
                target = _WEEKDAYS.index(weekday.group(1).lower())
                ahead = (target - now.weekday()) % 7
                # "by Friday", said on a Friday, means today; "next Friday" a week on.
                if "next " + weekday.group(1).lower() in lowered and ahead < 7:
                    ahead = ahead + 7 if ahead == 0 else ahead
                day = now.date() + dt.timedelta(days=ahead)
    if day is None:
        return None
    hour, minute = 17, 0
    clock = _CLOCK.search(lowered)
    if clock:
        hour = int(clock.group(1)) % 12 + (12 if clock.group(3).lower() == "pm" else 0)
        minute = int(clock.group(2) or 0)
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=now.tzinfo)


_HHMM = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\s*(am|pm)?\b", re.I)
_H_AMPM = re.compile(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", re.I)
_DURATION = re.compile(r"\bfor\s+(?:(\d{1,3})\s*(?:min|mins|minutes)|(an?|one|two|1|2)\s+hours?|half an hour)\b", re.I)
_ANY_WEEKDAY = re.compile(r"\b(?:(this|next)\s+)?(" + "|".join(_WEEKDAYS) + r")\b", re.I)
# A zone named in the text, or "my time": the hour then is not the reader's
# hour, and the Desk does not convert on a guess.
_OTHER_ZONE = re.compile(r"\b(?:[ECMP][SD]T|GMT|UTC|CET|CEST|EET|EEST|BST|IST|my time|your time|"
                         r"local time|o'clock (?:in|at) )\b", re.I)


def explicit_request(text: str, now: dt.datetime) -> Optional[Dict[str, Any]]:
    """A time that is written out in full: exactly one day and exactly one
    clock time, read in the zone of ``now``. For use when no model is
    configured. None unless the text is unambiguous:

    - the day is a weekday name, "tomorrow", or a date;
    - the time is ``HH:MM`` or an hour with am/pm ("3pm"); a bare "at 3" is
      not enough;
    - two different days or two different times mean a choice is being
      offered, which this does not make;
    - a time zone named in the text means the hour is someone else's.
    """
    lowered = " ".join(str(text or "").lower().split())
    if not lowered or _OTHER_ZONE.search(text or ""):
        return None
    days = set()
    for match in _ISO_DATE.finditer(lowered):
        try:
            days.add(dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            return None
    for pattern, order in ((_DAY_MONTH, (1, 2)), (_MONTH_DAY, (2, 1))):
        for match in pattern.finditer(lowered):
            month = _MONTHS.index(match.group(order[1]).lower()) + 1
            for year in (now.year, now.year + 1):
                try:
                    candidate = dt.date(year, month, int(match.group(order[0])))
                except ValueError:
                    continue
                if candidate >= now.date():
                    days.add(candidate)
                    break
    if re.search(r"\btomorrow\b", lowered):
        days.add(now.date() + dt.timedelta(days=1))
    if not days:      # a weekday name counts only when no date was written
        for match in _ANY_WEEKDAY.finditer(lowered):
            ahead = (_WEEKDAYS.index(match.group(2).lower()) - now.weekday()) % 7
            # A bare weekday means the next one to come; today's name means a week on.
            ahead = ahead or 7
            if match.group(1) == "next" and ahead < 7 and now.weekday() < _WEEKDAYS.index(match.group(2).lower()):
                ahead += 7
            days.add(now.date() + dt.timedelta(days=ahead))
    times = set()
    for match in _HHMM.finditer(lowered):
        hour, minute, half = int(match.group(1)), int(match.group(2)), (match.group(3) or "").lower()
        if half and hour <= 12:
            hour = hour % 12 + (12 if half == "pm" else 0)
        times.add((hour, minute))
    spans = [m.span() for m in _HHMM.finditer(lowered)]
    for match in _H_AMPM.finditer(lowered):
        if any(start <= match.start() < end for start, end in spans):
            continue
        times.add((int(match.group(1)) % 12 + (12 if match.group(2).lower() == "pm" else 0), 0))
    if len(days) != 1 or len(times) != 1:
        return None
    hour, minute = next(iter(times))
    start = dt.datetime.combine(next(iter(days)), dt.time(hour, minute), tzinfo=now.tzinfo)
    if start <= now:
        return None
    found: Dict[str, Any] = {"requested_start": start.isoformat(), "source": "rules"}
    duration = _DURATION.search(lowered)
    if duration:
        if duration.group(1):
            found["duration_minutes"] = int(duration.group(1))
        elif duration.group(2):
            found["duration_minutes"] = 120 if duration.group(2) in ("two", "2") else 60
        else:
            found["duration_minutes"] = 30
    return found


def _words(text: str) -> set:
    stop = {"re", "fwd", "fw", "the", "a", "an", "our", "of", "for", "to", "and", "on", "at", "with",
            "meeting", "call", "reschedule", "rescheduling", "cancel", "cancellation", "move", "moving",
            "request", "please", "need", "can", "we", "you", "i", "is", "this", "that", "next", "week"}
    return {word for word in re.findall(r"[a-z0-9]+", str(text or "").lower()) if word not in stop}


def find_target_events(events: List[Mapping[str, Any]], *, sender: Optional[str], subject: str,
                       hint: str = "") -> Dict[str, Any]:
    """Which existing meeting a change request is about.

    Only meetings the SENDER is part of are considered (an attendee or the
    organizer, by address): a request to move or cancel a meeting from someone
    who is not on it is not acted on. When several of the sender's meetings
    qualify, the title must agree with the subject or the model's hint, and
    exactly one must stand out; otherwise the result is ambiguous.
    """
    sender = str(sender or "").strip().lower()
    theirs = []
    for event in events:
        people = {str(a).lower() for a in (event.get("attendees") or [])}
        people.add(str(event.get("organizer_email") or "").lower())
        if sender and sender in people:
            theirs.append(event)
    if not theirs:
        return {"status": "sender_not_on_any_event", "candidates": []}
    if len(theirs) == 1:
        return {"status": "found", "event": theirs[0], "candidates": theirs}
    wanted = _words(subject) | _words(hint)
    scored = sorted(((len(wanted & _words(str(e.get("title") or ""))), e) for e in theirs),
                    key=lambda pair: pair[0], reverse=True)
    if scored[0][0] > 0 and scored[0][0] > scored[1][0]:
        return {"status": "found", "event": scored[0][1], "candidates": theirs}
    return {"status": "ambiguous", "candidates": theirs}


def reply_subject(subject: str) -> str:
    text = str(subject or "").strip()
    return text if text.lower().startswith("re:") else f"Re: {text}"


def slot_label(slot: Mapping[str, Any]) -> str:
    """"Tuesday 17 November, 10:00 to 10:30" from a slot's ISO times."""
    try:
        start = dt.datetime.fromisoformat(str(slot.get("start")))
        end = dt.datetime.fromisoformat(str(slot.get("end")))
    except ValueError:
        return f"{slot.get('start')} to {slot.get('end')}"
    return f"{start.strftime('%A')} {start.day} {start.strftime('%B')}, {start.strftime('%H:%M')} to {end.strftime('%H:%M')}"


def offer_times_reply(*, slots: List[Mapping[str, Any]], timezone: str, reason: str) -> str:
    """The fixed reply that offers verified free times. ``reason`` says why
    the requested time is not simply confirmed."""
    opening = {
        "calendar_conflict": "Thank you for your message. Unfortunately that time is not available.",
        "time_not_understood": "Thank you for your message. I would be glad to find a time.",
        "reschedule": "Thank you for letting me know. That time does not work, but these would:",
    }.get(reason, "Thank you for your message.")
    listed = "\n".join(f"- {slot_label(slot)}" for slot in slots[:3])
    return (f"{opening}\n\nThe following times are free ({timezone}):\n{listed}\n\n"
            "Please let me know which suits you, or suggest another.")


def confirmation_reply(*, title: str, start: str, end: str, timezone: str, moved: bool = False) -> str:
    when = slot_label({"start": start, "end": end})
    verb = "moved" if moved else "scheduled"
    return (f"Thank you for your message. I have {verb} \"{title}\" {'to' if moved else 'for'} {when} "
            f"({timezone}). You should receive a calendar "
            f"{'update' if moved else 'invitation'} separately.")


def cancellation_reply(*, title: str) -> str:
    return (f"Thank you for letting me know. \"{title}\" has been cancelled, and a calendar "
            "cancellation has been sent separately.")


def nudge_reply(*, subject: str) -> str:
    return (f"I am following up on my earlier message about \"{subject}\". "
            "Could you let me know when you have a moment?")
