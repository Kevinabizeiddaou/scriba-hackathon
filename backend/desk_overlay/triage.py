"""Secretary triage for an incoming message. Pure: no network, no Scriba import.

Scriba already decides whether a message needs a reply, whether it is bulk
or automated, and how urgent it is (its reply classifier, reached through
the gateway). This module turns that verdict into the question a secretary
asks: what outcome does this message need?
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping

from . import reading

# The outcome a message needs. One per message.
CATEGORIES = ("meeting_request", "needs_reply", "action_item", "informational", "automated")
OUTCOMES = {
    "meeting_request": "schedule",
    "needs_reply": "reply",
    "action_item": "task",
    "informational": "none",
    "automated": "none",
}

_CHANGE_RE = re.compile(r"\b(reschedul\w*|move (?:our|the)|push (?:our|the)|postpone\w*|another time)\b", re.I)
_CANCEL_RE = re.compile(r"\b(cancel\w*|call off|won't be able to (?:make|attend)|can(?:no|')t make it)\b", re.I)
_DEADLINE_RE = re.compile(
    r"\b(by (?:eod|end of (?:day|week)|tomorrow|monday|tuesday|wednesday|thursday|friday)|"
    r"deadline|due (?:on|by|date)|no later than|asap|as soon as possible)\b",
    re.I,
)


# The one reason Scriba's classifier gives that is a resemblance, not a sign.
WEAK_AUTOMATED = frozenset({"weak_automated_subject"})


def meeting_intent(subject: str, text: str) -> str:
    """new, reschedule or cancel. Only meaningful for a meeting request."""
    combined = f"{subject}\n{text}"
    if _CANCEL_RE.search(combined):
        return "cancel"
    if _CHANGE_RE.search(combined):
        return "reschedule"
    return "new"


def triage(item: Mapping[str, Any], verdict: Mapping[str, Any]) -> Dict[str, Any]:
    """Combine Scriba's classifier verdict with the message into a triage record.

    ``verdict`` is the dict Scriba's ``classify_reply_candidate`` returns:
    ``classification`` (requires_reply | informational | automated/promotional),
    ``priority`` and ``reasons``.
    """
    subject = str(item.get("subject") or "")
    text = str(item.get("body") or item.get("snippet") or item.get("text") or "")
    reasons: List[str] = [str(reason) for reason in (verdict.get("reasons") or [])]
    classification = str(verdict.get("classification") or "")
    # Only the classifier's own reasons count here, before the Desk adds its own.
    weak_only = bool(reasons) and set(reasons) <= WEAK_AUTOMATED
    has_deadline = bool(_DEADLINE_RE.search(f"{subject}\n{text}"))

    # The Desk's own reading of the text. Scriba's classifier asks whether a
    # reply is needed; a cancellation stated as news, or a request to meet
    # that never says "meeting", is still scheduling work.
    signal = reading.meeting_signal(subject, text)
    asks_action = reading.action_signal(text)
    reminder = reading.reminder_request(text)
    if reminder:
        # "Remind yourself on Wednesday at 09:00 to call the chairman" has a
        # day and a time and is not a request to meet the writer.
        signal = None
        reasons = [reason for reason in reasons if reason != "meeting_request"]
        reasons.append("desk_reminder_requested")
    if signal and "meeting_request" not in reasons:
        reasons.append(f"desk_meeting_{signal}")
    if asks_action:
        reasons.append("desk_action_requested")

    # Mail is filed as automated on a sign (the sender, the content, bulk
    # headers, an unmistakable subject, a blocked sender). When the ONLY
    # reason is that the subject line resembles a newsletter's, that is not
    # established: a person's "Investor update" must not disappear.
    automated = classification == "automated/promotional" and not weak_only
    if classification == "automated/promotional" and not automated:
        reasons.append("desk_automated_not_established")
    if automated:
        category = "automated"
    elif "meeting_request" in reasons or signal:
        category = "meeting_request"
    elif asks_action or reminder or (has_deadline and classification != "requires_reply"):
        category = "action_item"
    elif classification == "requires_reply":
        category = "needs_reply"
    else:
        category = "informational"

    # Scriba's own stored priority for the message wins when it has one; the
    # classifier's is the fallback for rows Scriba has not scored.
    priority = str(item.get("effective_priority") or item.get("priority")
                   or verdict.get("priority") or "low").lower()
    if category == "automated":
        priority = "low"

    record: Dict[str, Any] = {
        "category": category,
        "outcome": OUTCOMES[category],
        "priority": priority,
        "needs_reply": category in ("meeting_request", "needs_reply"),
        "has_deadline": has_deadline,
        "reasons": reasons,
    }
    if category == "meeting_request":
        record["meeting_intent"] = signal or meeting_intent(subject, text)
    return record


def summarize(records: List[Mapping[str, Any]]) -> Dict[str, int]:
    counts = {category: 0 for category in CATEGORIES}
    for record in records:
        category = str(record.get("category") or "")
        if category in counts:
            counts[category] += 1
    return counts
