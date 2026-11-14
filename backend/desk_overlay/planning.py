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
_CLOCK = re.compile(r"\b(?:at|by)\s+(?:\w+\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)
_CLOCK_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_NOON = re.compile(r"\b(noon|midday)\b", re.I)
_EVENING = re.compile(r"\b(evening|tonight|end of (?:the )?day|eod|close of business|cob)\b", re.I)
_MORNING = re.compile(r"\b(?:first thing|morning)\b", re.I)

# Text that addresses the assistant rather than the executive. Mail is data:
# finding this never makes the Desk do what it says. It makes the Desk stop.
_INJECTION = re.compile(
    r"(ignore (?:all |any |your )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)"
    r"|disregard (?:your|all|the) (?:instructions|rules|guidelines)"
    r"|you are (?:now )?(?:an? )?(?:ai|assistant|language model)"
    r"|system prompt|as an ai\b"
    r"|(?:system|developer|admin(?:istrator)?)\s+(?:note|message|instruction|notice|override)"
    r"|(?:note|message|instructions?)\s+(?:to|for)\s+(?:the\s+)?(?:ai|assistant|agent|bot)"
    r"|\bai\s+(?:assistant|agent|model)\b|pre-?authori[sz]ed"
    r"|do not (?:mention|disclose|reveal|show) (?:this|these|it)"
    r"|(?:auto(?:matically)?[- ]?approve|approve (?:this|it) (?:automatically|without (?:asking|review)))"
    r"|without (?:asking|telling|notifying) (?:the |your )?(?:user|executive|principal|boss)"
    r"|do not (?:ask|tell|notify) (?:the |your )?(?:user|executive|principal|boss)"
    r"|forward (?:all|every|this entire) (?:emails?|mail|messages?|inbox)"
    # Asking for the approval to be left out, in whatever words.
    r"|(?:skip|bypass|omit|disable|leave out|do away with)\s+(?:the\s+|any\s+|your\s+)?"
    r"(?:approval|sign-?off|review|confirmation|human|manual)(?:\s+(?:step|check|stage|process))?"
    # Asking for the executive's data wholesale.
    r"|(?:send|mail|e-?mail|forward|export|share|upload)\s+(?:me\s+|us\s+|over\s+)?"
    r"(?:the\s+|your\s+|her\s+|his\s+|their\s+)?(?:full|entire|whole|complete)\s+"
    r"(?:calendar|inbox|mailbox|contact list|contacts|address book|diary)"
    # Addressing whatever software reads the mail.
    r"|(?:whichever|whatever|any)\s+(?:tool|system|software|program|automation|bot|assistant)\s+"
    r"(?:handles|reads|processes|manages|is reading))",
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
                named = set(re.findall("|".join(_WEEKDAYS), lowered))
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
    clock, clock_24 = _CLOCK.search(lowered), _CLOCK_24.search(lowered)
    if clock:
        hour = int(clock.group(1)) % 12 + (12 if clock.group(3).lower() == "pm" else 0)
        minute = int(clock.group(2) or 0)
    elif clock_24:
        hour, minute = int(clock_24.group(1)), int(clock_24.group(2))
    elif _NOON.search(lowered):
        hour, minute = 12, 0
    elif _MORNING.search(lowered):
        hour, minute = 9, 0
    elif re.search(r"\b(evening|tonight)\b", lowered):
        hour, minute = 18, 0
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=now.tzinfo)


def explicit_request(text: str, now: dt.datetime, *, change: bool = False) -> Optional[Dict[str, Any]]:
    """See ``reading.explicit_request``."""
    from . import reading

    return reading.explicit_request(text, now, change=change)


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


def confirmation_reply(*, title: str, start: str, end: str, timezone: str, moved: bool = False,
                       other_timezone: Optional[str] = None) -> str:
    """``other_timezone`` is the zone the sender wrote the time in, when it
    is not the executive's: the confirmation then states the time in both,
    so neither side has to convert."""
    when = slot_label({"start": start, "end": end})
    verb = "moved" if moved else "scheduled"
    both = ""
    if other_timezone:
        try:
            from zoneinfo import ZoneInfo

            zone = ZoneInfo(other_timezone)
            theirs = {"start": dt.datetime.fromisoformat(start).astimezone(zone).isoformat(),
                      "end": dt.datetime.fromisoformat(end).astimezone(zone).isoformat()}
            place = other_timezone.split("/")[-1].replace("_", " ")
            both = f", which is {slot_label(theirs)} {place} time ({other_timezone})"
        except Exception:
            both = ""
    return (f"Thank you for your message. I have {verb} \"{title}\" {'to' if moved else 'for'} {when} "
            f"({timezone}){both}. You should receive a calendar "
            f"{'update' if moved else 'invitation'} separately.")


def cancellation_reply(*, title: str) -> str:
    return (f"Thank you for letting me know. \"{title}\" has been cancelled, and a calendar "
            "cancellation has been sent separately.")


def nudge_reply(*, subject: str) -> str:
    return (f"I am following up on my earlier message about \"{subject}\". "
            "Could you let me know when you have a moment?")


# ── work reported as finished ───────────────────────────────────────────────

_DONE_WORDS = re.compile(
    r"\b(done|completed?|finished|finali[sz]ed|signed|countersigned|filed|submitted|delivered|paid|settled|"
    r"resolved|closed|approved|received|taken care of|sorted|"
    r"no (?:further )?action (?:is )?(?:needed|required))\b", re.I)
# A message that still asks for something, or says it is not there yet, does
# not report finished work, whatever else it says.
_NOT_DONE = re.compile(
    r"\b(not yet|still|pending|awaiting|waiting|will be|to be|delayed|please|could you|can you|"
    r"need(?:s)? (?:you|your))\b|n't\b|\?", re.I)
_TASK_STOP = frozenset("""
    the a an and or of to for with on in at by from your our my their his her its this that these those
    get send make do have has had be is are was were will can could would should please new all any off
    task tasks follow up re fwd about into out per via not yet
""".split())


def _stem(word: str) -> str:
    for ending in ("ing", "ed", "es", "s"):
        if len(word) > len(ending) + 3 and word.endswith(ending):
            return word[: -len(ending)]
    return word


def _tokens(text: Any) -> set:
    return {_stem(word) for word in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(word) >= 2 and word not in _TASK_STOP and not word.isdigit()}


def work_reported_done(text: str) -> bool:
    """The text says something is finished and asks for nothing."""
    without_closing = re.sub(r"no (?:further )?action (?:is )?(?:needed|required)", "noaction", str(text or ""), flags=re.I)
    return bool(_DONE_WORDS.search(str(text or ""))) and not _NOT_DONE.search(without_closing)


def match_open_task(text: str, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Which open task a message is about. ``one`` only when exactly one task
    has most of its title's words in the message and no other task comes
    close; otherwise ``none`` or ``several``. Nothing is guessed."""
    said = _tokens(text)
    scored = []
    for task in tasks:
        title = _tokens(task.get("title"))
        shared = title & said
        if len(title) >= 2 and len(shared) >= 2 and len(shared) / len(title) >= 0.6:
            scored.append((len(shared) / len(title), len(shared), task, sorted(shared)))
    if not scored:
        return {"status": "none", "task": None, "candidates": []}
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    best = scored[0]
    if len(scored) > 1 and scored[1][0] >= best[0] - 0.15:
        return {"status": "several", "task": None, "candidates": [entry[2] for entry in scored[:5]]}
    return {"status": "one", "task": best[2], "matched": best[3], "candidates": [best[2]]}
