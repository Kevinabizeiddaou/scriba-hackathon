"""Secretary triage for an incoming message. Pure: no network, no Scriba import.

Scriba already decides whether a message needs a reply, whether it is bulk
or automated, and how urgent it is (its reply classifier, reached through
the gateway). This module turns that verdict into the question a secretary
asks: what outcome does this message need?
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping

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
    has_deadline = bool(_DEADLINE_RE.search(f"{subject}\n{text}"))

    if classification == "automated/promotional":
        category = "automated"
    elif "meeting_request" in reasons:
        category = "meeting_request"
    elif classification == "requires_reply":
        category = "needs_reply"
    elif has_deadline:
        category = "action_item"
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
        record["meeting_intent"] = meeting_intent(subject, text)
    return record


def summarize(records: List[Mapping[str, Any]]) -> Dict[str, int]:
    counts = {category: 0 for category in CATEGORIES}
    for record in records:
        category = str(record.get("category") or "")
        if category in counts:
            counts[category] += 1
    return counts
