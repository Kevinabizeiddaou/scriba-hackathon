"""Desk safeguards on proposed actions.

Checks the Desk applies itself, on top of Scriba's own validation, before an
action card may be approved. They do not depend on any particular version of
Scriba's validation, so the Desk is safe to run against Scriba as it is.

Each check answers one question and holds the card (``needs_info``) when the
answer is not a clear yes:

- ``structural_issue``     Is the action complete enough to execute at all?
- ``unverified_recipients`` Did every recipient or attendee come from the
                            user, from the email being answered, or from the
                            user's own accounts, rather than from content?
- ``reply_target_issue``   Is the message being answered still the latest in
                            its thread, so the reply reaches its sender?

Pure apart from the reads it is handed. Nothing here sends or writes.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
VERIFIED_KEY = "desk_verified_recipients"     # set by the Desk when a card is proposed
CONFIRMED_KEY = "desk_confirmed_recipients"   # set by the user, at approval only
RECIPIENT_FIELDS = {
    "send_email": ("to", "cc", "bcc"),
    "create_calendar_event": ("attendees",),
    "update_calendar_event": ("attendees", "add_attendees"),
}


def addresses_in(value: Any) -> List[str]:
    """Every email address in a field, whatever its shape (string or list)."""
    if isinstance(value, (list, tuple, set)):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value or "")
    seen: List[str] = []
    for match in EMAIL_RE.findall(text):
        address = match.lower()
        if address not in seen:
            seen.append(address)
    return seen


def recipients_of(tool_name: str, data: Dict[str, Any]) -> List[str]:
    found: List[str] = []
    for field in RECIPIENT_FIELDS.get(tool_name, ()):
        for address in addresses_in(data.get(field)):
            if address not in found:
                found.append(address)
    return found


def structural_issue(tool_name: str, data: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """(code, message) when the action cannot be executed as written."""
    if tool_name == "send_email":
        entries = data.get("to")
        raw = entries if isinstance(entries, (list, tuple)) else re.split(r"[;,]", str(entries or ""))
        parts = [str(part).strip() for part in raw if str(part).strip()]
        if not parts or not all(EMAIL_RE.search(part) for part in parts):
            return "recipient_required", "This email has no valid recipient address yet."
        if not str(data.get("body") or data.get("text") or "").strip():
            return "body_required", "This email has no text yet."
    elif tool_name == "create_task":
        if not str(data.get("title") or "").strip():
            return "title_required", "This task has no title yet."
    elif tool_name == "create_reminder":
        if not str(data.get("title") or "").strip() or not str(data.get("remind_at") or "").strip():
            return "reminder_incomplete", "This reminder needs a title and a time."
    elif tool_name in ("create_calendar_event", "update_calendar_event"):
        if tool_name == "create_calendar_event" and not str(
                data.get("start") or data.get("start_time") or "").strip():
            return "start_required", "This event has no start time yet."
    return None


def unverified_recipients(tool_name: str, data: Dict[str, Any], *, user_message: Optional[str],
                          vouched: Iterable[str]) -> List[str]:
    """Recipients nobody vouched for.

    An address is accepted when the user wrote it in this message, the Desk
    verified it when the card was proposed, the user confirmed it at
    approval, or it is in ``vouched`` (the user's own mailboxes and the
    sender of the email being answered).
    """
    accepted: Set[str] = {str(address).lower() for address in vouched if address}
    accepted.update(addresses_in(user_message))
    accepted.update(addresses_in(data.get(VERIFIED_KEY)))
    accepted.update(addresses_in(data.get(CONFIRMED_KEY)))
    return [address for address in recipients_of(tool_name, data) if address not in accepted]


def is_gmail_reply(tool_name: str, data: Dict[str, Any]) -> bool:
    return (tool_name == "send_email"
            and str(data.get("mode") or "").lower() == "reply"
            and str(data.get("provider") or "gmail").lower() == "gmail"
            and bool(str(data.get("thread_id") or "").strip()))


def reply_target_issue(data: Dict[str, Any], *, inbox_rows: List[Dict[str, Any]],
                       sent_rows: Optional[List[Dict[str, Any]]]) -> Optional[Tuple[str, str]]:
    """(code, message) unless the message being answered is verifiably the
    latest in its thread.

    A Gmail reply is addressed from the thread's most recent message. So if
    anything was written after the message the user means to answer, a newer
    inbound message or the user's own later reply, the reply could go to the
    wrong person. ``sent_rows`` is None when the sent list could not be read:
    that is unknown, and unknown is not "nothing newer".
    """
    thread_id = str(data.get("thread_id") or "").strip()
    target = str(data.get("email_id") or data.get("message_id") or "").strip()
    if not target:
        return "reply_target_missing", "This reply does not name the message it answers."
    thread = [row for row in inbox_rows if str(row.get("threadId") or "") == thread_id]
    answered = next((row for row in thread if str(row.get("id")) == target), None)
    if answered is None:
        return ("reply_target_unverified",
                "The message this reply answers could not be found in the recent inbox, so the "
                "reply was not prepared for sending. Open the message and reply from there.")
    answered_at = str(answered.get("timestamp") or "")
    if any(str(row.get("timestamp") or "") > answered_at for row in thread if row is not answered):
        return ("reply_target_changed",
                "A newer message has arrived in this conversation. Review it before replying.")
    if sent_rows is None:
        return ("reply_target_unverified",
                "Your sent mail could not be read, so it is not certain this is still the latest "
                "message in the conversation. Try again in a moment.")
    if any(str(row.get("thread_id") or "") == thread_id
           and str(row.get("sent_at") or "") > answered_at for row in sent_rows):
        return ("reply_target_changed",
                "You have already written in this conversation since that message. Review the "
                "thread before replying again.")
    return None
