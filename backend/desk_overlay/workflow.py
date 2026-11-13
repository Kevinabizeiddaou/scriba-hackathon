"""The Desk workflow for one incoming email.

    incoming email -> classify -> gather thread -> gather calendar context
        -> propose actions -> wait for approval -> execute -> verify -> log

The Desk owns the first five steps. Approval, execution, verification of the
provider result and the action record are Scriba's: every proposal is a
Scriba chat action card, created through Scriba's own validation gate and
approved through Scriba's existing ``/chat/tool-calls/{id}/approve`` route,
which claims the card atomically and runs it through Scriba's execution
engine and delivery ledgers. A run is a Scriba chat conversation, so its
history is Scriba's.

Nothing here sends mail or writes a calendar. Two cases are handled:

1. Meeting request: the requested time is checked against every connected
   calendar. Free: a calendar-event card is proposed. Not free or unknown:
   nothing is proposed for booking and the verified free times are offered
   for a reply instead. The confirmation reply is proposed only AFTER the
   event card has executed.
2. Actionable email: a task card is proposed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import threading
from typing import Any, Dict, List, Optional

from .availability import InvalidAvailabilityRequest
from .service import DeskService, NotFound

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_DONE = ("executed", "partially_executed")
_OPEN = ("pending", "needs_info", "draft", "awaiting_approval", "approved", "executing")


def sender_address(from_addr: str) -> Optional[str]:
    """The address in a From header. The only attendee the Desk adds on its own."""
    match = _EMAIL_RE.search(str(from_addr or ""))
    return match.group(0).lower() if match else None


def run_key(user_id: int, provider: str, account: Optional[str], item_id: str) -> str:
    """Identity of one inbound message for one user: the same message is one run."""
    raw = f"{int(user_id)}|{provider}|{(account or '').strip().lower()}|{item_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class DeskWorkflow:
    def __init__(self, service: DeskService, gateway: Any) -> None:
        self.service = service
        self.gateway = gateway
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    # ── intake ──────────────────────────────────────────────────────────────
    def intake(self, ctx: Any, user: Any, *, provider: str, item_id: str,
               mailbox: Optional[str] = None) -> Dict[str, Any]:
        detail = self.service.inbox_item(ctx, user, provider=provider, item_id=item_id, mailbox=mailbox)
        item = detail["item"]
        key = run_key(user.id, provider, item.get("provider_account_id"), item_id)

        # One run per inbound message. The lock covers this process; the Desk
        # runs as a single process (see backend/README.md).
        with self._lock(key):
            existing = self.gateway.find_run(user, key)
            if existing is not None:
                return self.view(ctx, user, existing["id"], duplicate=True)

            triage = item["triage"]
            meta: Dict[str, Any] = {
                "key": key,
                "provider": provider,
                "email_id": item.get("id"),
                "thread_id": item.get("threadId"),
                "provider_account_id": item.get("provider_account_id"),
                "from_addr": item.get("from_addr"),
                "subject": item.get("subject"),
                "category": triage["category"],
                "outcome": triage["outcome"],
                "created_at": self.service.clock().isoformat(),
                "held": None,
                "draft_request": detail.get("draftRequest"),
            }
            proposals: List[Dict[str, Any]] = []
            if triage["category"] == "action_item":
                proposals.append({"tool_name": "create_task", "tool_input": {
                    "title": str(item.get("subject") or "Follow up on email").strip()[:160],
                    "description": f"From {item.get('from_addr')}. {item.get('snippet') or ''}".strip(),
                    "priority": triage.get("priority") or "medium",
                }})
            elif triage["category"] == "meeting_request":
                event, held = self._plan_meeting(ctx, user, item, detail.get("calendar"))
                meta["held"] = held
                if event:
                    proposals.append({"tool_name": "create_calendar_event", "tool_input": event})

            run = self.gateway.open_run(
                user, title=f"Desk: {str(item.get('subject') or 'incoming email')[:80]}", meta=meta,
                summary=_summary(meta, proposals))
            for proposal in proposals:
                self.gateway.propose_action(
                    user, run, tool_name=proposal["tool_name"], tool_input=proposal["tool_input"],
                    email_id=item.get("id"), thread_id=item.get("threadId"), provider=provider)
        return self.view(ctx, user, run["id"])

    def _plan_meeting(self, ctx: Any, user: Any, item: Dict[str, Any],
                      calendar: Optional[Dict[str, Any]]) -> Any:
        """(event card input, None) when the requested time is verified free;
        otherwise (None, why nothing is proposed for booking)."""
        offered = {"slots": (calendar or {}).get("slots") or [],
                   "calendars": (calendar or {}).get("calendars") or []}
        if (item.get("triage") or {}).get("meeting_intent") != "new":
            return None, {"reason": "change_request", **offered,
                          "message": "This asks to move or cancel a meeting. That is not proposed "
                                     "automatically yet; handle it from chat."}
        try:
            zone_name, _, _, duration = self.service.working_context(user, None, None, None)
        except InvalidAvailabilityRequest:
            return None, {"reason": "invalid_preferences", **offered,
                          "message": "The time zone in your preferences is not valid."}
        plan = self.gateway.extract_meeting(user, item, zone_name)
        start = str((plan or {}).get("requested_start") or "").strip()
        if not plan or not start:
            return None, {"reason": "time_not_understood", **offered,
                          "message": "No specific time could be read from the message, so no "
                                     "event is proposed. Offer the free times in a reply."}
        end = str(plan.get("requested_end") or "").strip()
        if not end:
            try:
                minutes = int(plan.get("duration_minutes") or duration)
                from .availability import parse_instant, resolve_zone

                end = (parse_instant(start, resolve_zone(zone_name))
                       + dt.timedelta(minutes=max(15, min(minutes, 480)))).isoformat()
            except (InvalidAvailabilityRequest, TypeError, ValueError):
                return None, {"reason": "time_not_understood", **offered,
                              "message": "The requested time could not be read."}
        try:
            check = self.service.slot_check(ctx, user, start=start, end=end, timezone=zone_name)
        except InvalidAvailabilityRequest:
            return None, {"reason": "time_not_understood", **offered,
                          "message": "The requested time could not be read."}
        if check["free"] is not True:
            reason = "calendar_conflict" if check["free"] is False else "availability_unknown"
            return None, {
                "reason": reason, **offered, "requested": check["slot"],
                "conflicts": check["conflicts"], "calendars": check["calendars"],
                "message": ("The requested time conflicts with an existing commitment. "
                            if reason == "calendar_conflict" else
                            "A calendar could not be read, so the requested time is not verified. ")
                           + "No event is proposed. Offer verified free times in a reply.",
            }
        # Attendees: the sender, taken from the message's From header. Names or
        # addresses that appear only in the message text are not added.
        sender = sender_address(str(item.get("from_addr") or ""))
        return {
            "title": str(plan.get("summary") or item.get("subject") or "Meeting").strip()[:160],
            "start": check["slot"]["start"],
            "end": check["slot"]["end"],
            "timezone": zone_name,
            "attendees": [sender] if sender else [],
            "description": f"Requested by {item.get('from_addr')} by email.",
        }, None

    # ── advancing after approval ────────────────────────────────────────────
    def advance(self, ctx: Any, user: Any, run_id: int) -> Dict[str, Any]:
        """Propose what may only follow an executed step: the confirmation
        reply, once the calendar event exists."""
        run = self._run(user, run_id)
        meta = run["meta"]
        with self._lock(meta["key"]):
            cards = self.gateway.run_cards(user, run)
            event = next((c for c in cards if c["tool_name"] == "create_calendar_event"), None)
            has_reply = any(c["tool_name"] == "send_email" for c in cards)
            recipient = sender_address(str(meta.get("from_addr") or ""))
            if event and event["status"] in _DONE and not has_reply and recipient:
                when = f"{event['input'].get('start')} to {event['input'].get('end')}"
                reply: Dict[str, Any] = {
                    "provider": meta["provider"],
                    "mode": "reply",
                    "to": recipient,
                    "subject": _reply_subject(str(meta.get("subject") or "")),
                    "body": (f"Thank you for your message. I have scheduled "
                             f"\"{event['input'].get('title')}\" for {when} "
                             f"({event['input'].get('timezone')}). You should receive a calendar "
                             "invitation separately."),
                    "thread_id": meta.get("thread_id"),
                    "provider_account_id": meta.get("provider_account_id"),
                }
                # Name the message being answered in the field each provider uses.
                reply["email_id" if meta["provider"] == "gmail" else "message_id"] = meta.get("email_id")
                self.gateway.propose_action(
                    user, run, tool_name="send_email", tool_input=reply,
                    email_id=meta.get("email_id"), thread_id=meta.get("thread_id"),
                    provider=meta["provider"])
        return self.view(ctx, user, run_id)

    # ── reading a run ───────────────────────────────────────────────────────
    def _run(self, user: Any, run_id: int) -> Dict[str, Any]:
        run = self.gateway.get_run(user, int(run_id))
        if run is None:
            raise NotFound("Run not found.")
        return run

    def view(self, ctx: Any, user: Any, run_id: int, *, duplicate: bool = False) -> Dict[str, Any]:
        run = self._run(user, run_id)
        meta = run["meta"]
        cards = self.gateway.run_cards(user, run)
        actions = [_action_view(card) for card in cards]
        statuses = [action["status"] for action in actions]
        done = [s for s in statuses if s in _DONE]
        failed = [s for s in statuses if s == "failed"]
        waiting = [s for s in statuses if s in _OPEN]

        if not actions:
            state = "no_action_proposed"
        elif waiting:
            state = "awaiting_approval" if any(s in ("awaiting_approval", "needs_info") for s in waiting) \
                else "executing"
        elif done and failed:
            state = "partial"
        elif failed:
            state = "failed"
        elif done:
            state = "completed"
        else:
            state = "cancelled"

        event = next((a for a in actions if a["tool_name"] == "create_calendar_event"), None)
        has_reply = any(a["tool_name"] == "send_email" for a in actions)
        next_steps: List[str] = []
        if event and event["status"] in _DONE and not has_reply:
            next_steps.append("advance")          # POST /desk/runs/{id}/advance
        if meta.get("draft_request") and not has_reply and not (event and event["status"] in _DONE):
            next_steps.append("draft_reply")      # POST the draft_request to Scriba
        return {
            "runId": run["id"],
            "duplicate": duplicate,
            "state": state,
            "email": {key: meta.get(key) for key in (
                "provider", "email_id", "thread_id", "provider_account_id", "from_addr", "subject")},
            "category": meta.get("category"),
            "outcome": meta.get("outcome"),
            "createdAt": meta.get("created_at"),
            "held": meta.get("held"),
            "draftRequest": meta.get("draft_request"),
            "actions": actions,
            "next": next_steps,
        }

    def list_runs(self, user: Any, limit: int = 50) -> List[Dict[str, Any]]:
        return [{"runId": run["id"], **{key: run["meta"].get(key) for key in (
            "provider", "email_id", "subject", "from_addr", "category", "created_at")}}
            for run in self.gateway.list_runs(user, limit)]


def _reply_subject(subject: str) -> str:
    text = subject.strip()
    return text if text.lower().startswith("re:") else f"Re: {text}"


def _summary(meta: Dict[str, Any], proposals: List[Dict[str, Any]]) -> str:
    parts = [f"Incoming {meta['provider']} message from {meta.get('from_addr')}: "
             f"\"{meta.get('subject')}\". Classified as {meta['category']}."]
    if proposals:
        parts.append("Proposed for your approval: "
                     + ", ".join(p["tool_name"] for p in proposals) + ".")
    elif meta.get("held"):
        parts.append(str(meta["held"].get("message") or ""))
    else:
        parts.append("No action is proposed.")
    return " ".join(part for part in parts if part)


def _action_view(card: Dict[str, Any]) -> Dict[str, Any]:
    """One proposed action. ``verified`` is true only when Scriba recorded
    the executed action; it is never inferred."""
    status = str(card.get("status") or "")
    output = card.get("output") or {}
    return {
        "toolCallId": card.get("id"),
        "tool_name": card.get("tool_name"),
        "status": status,
        "requiresApproval": True,
        "input": card.get("input") or {},
        "message": output.get("message"),
        "error": card.get("error"),
        "availability": output.get("availability"),
        # Scriba links an executed card to the action row its engine recorded.
        "assistantActionId": card.get("assistant_action_id"),
        "verified": bool(status in _DONE and card.get("assistant_action_id")),
        "approve": {"method": "POST", "path": f"/chat/tool-calls/{card.get('id')}/approve"}
        if status in ("awaiting_approval", "needs_info") else None,
    }
