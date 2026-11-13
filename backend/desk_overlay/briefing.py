"""The executive briefing: what arrived, what needs the executive, what is on today.

Pure. Built from data Scriba already holds (triaged mail, today's agenda,
open tasks, upcoming reminders). It makes no model call, so every line can be
traced to a record. Scriba's own narrative brief (``POST /daily-brief``) can
be layered on top by a client.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

_EXCLUDED_SOURCES = ("slack", "teams", "jira", "drive", "onedrive")
_PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "normal": 2, "low": 3}


def _is_excluded(entry: Mapping[str, Any]) -> bool:
    """Calendar and task rows that only exist because of an excluded integration."""
    text = " ".join(str(entry.get(key) or "") for key in (
        "provider", "source_platform", "source_type", "calendar_provider")).lower()
    return any(name in text for name in _EXCLUDED_SOURCES)


def _mail_line(item: Mapping[str, Any]) -> Dict[str, Any]:
    triage = item.get("triage") or {}
    return {
        "id": item.get("id"),
        "provider": item.get("provider"),
        "provider_account_id": item.get("provider_account_id"),
        "from_addr": item.get("from_addr"),
        "subject": item.get("subject"),
        "timestamp": item.get("timestamp"),
        "category": triage.get("category"),
        "outcome": triage.get("outcome"),
        "priority": triage.get("priority"),
    }


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def build_briefing(
    *,
    inbox_items: Sequence[Mapping[str, Any]],
    inbox_counts: Mapping[str, int],
    inbox_complete: bool,
    agenda: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    reminders: Sequence[Mapping[str, Any]],
    max_items: int = 5,
) -> Dict[str, Any]:
    actionable = [item for item in inbox_items if (item.get("triage") or {}).get("needs_reply")
                  or (item.get("triage") or {}).get("category") == "action_item"]
    # Highest priority first; newest first within a priority (two stable sorts).
    actionable.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    actionable.sort(key=lambda item: _PRIORITY_ORDER.get(
        str((item.get("triage") or {}).get("priority") or "low"), 3))

    meetings: List[Dict[str, Any]] = []
    for day in agenda.get("days") or []:
        for entry in (day or {}).get("entries") or []:
            if not isinstance(entry, Mapping) or _is_excluded(entry):
                continue
            if str(entry.get("type") or "") in ("task", "reminder"):
                continue
            meetings.append({key: entry.get(key) for key in (
                "event_id", "title", "start_time", "end_time", "provider",
                "calendar_provider", "provider_account_id", "attendee_emails", "meeting_link")})

    open_tasks = [task for task in tasks
                  if str(task.get("status") or "active") in ("active", "open", "pending")
                  and not _is_excluded(task)]
    due_today = [task for task in open_tasks if task.get("due_today")]

    counts = {
        "meeting_requests": int(inbox_counts.get("meeting_request", 0)),
        "needs_reply": int(inbox_counts.get("needs_reply", 0)),
        "action_items": int(inbox_counts.get("action_item", 0)),
        "meetings_today": len(meetings),
        "open_tasks": len(open_tasks),
        "tasks_due_today": len(due_today),
        "reminders": len(reminders),
    }
    parts = [
        _plural(counts["meeting_requests"], "meeting request", "meeting requests"),
        _plural(counts["needs_reply"], "message needs a reply", "messages need a reply"),
        _plural(counts["meetings_today"], "meeting today", "meetings today"),
        _plural(counts["tasks_due_today"], "task due today", "tasks due today"),
    ]
    return {
        "headline": ", ".join(parts) + ".",
        "counts": counts,
        "needs_attention": [_mail_line(item) for item in actionable[:max_items]],
        "meetings_today": meetings,
        "tasks_due_today": [{key: task.get(key) for key in ("id", "title", "due_at", "effective_priority")}
                            for task in due_today[:max_items]],
        "open_tasks": [{key: task.get(key) for key in ("id", "title", "due_at", "effective_priority")}
                       for task in open_tasks[:max_items]],
        "reminders": list(reminders[:max_items]),
        "timezone": agenda.get("timezone"),
        # False when a connected mailbox could not be read: counts are a floor.
        "inbox_complete": inbox_complete,
    }
