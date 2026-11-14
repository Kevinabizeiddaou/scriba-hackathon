"""A scripted stand-in for the Scriba seam, for tests that need no Scriba checkout."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from desk_overlay.availability import Busy
from desk_overlay.gateway import CalendarReadError, DeskUser

UTC = dt.timezone.utc


def at(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text).replace(tzinfo=UTC) if "+" not in text and "Z" not in text \
        else dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def provider_row(connected: bool = False, **extra: Any) -> Dict[str, Any]:
    row = {"active": connected, "connected": connected, "available": True, "configured": True,
           "status": "connected" if connected else "disconnected", "reason": None}
    row.update(extra)
    return row


def email(item_id: str, subject: str, snippet: str, *, provider: str = "gmail",
          from_addr: str = "Dana Client <dana@client.example>", thread: Optional[str] = None,
          account: str = "exec@gmail.example", timestamp: str = "2026-11-16T08:00:00+00:00",
          priority: Optional[str] = None) -> Dict[str, Any]:
    return {"id": item_id, "threadId": thread or f"t-{item_id}", "from_addr": from_addr,
            "subject": subject, "snippet": snippet, "timestamp": timestamp, "provider": provider,
            "is_read": False, "reply_supported": True, "provider_account_id": account,
            "account_email": account, "source_item_id": None, "priority": priority}


class FakeGateway:
    """Per-user worlds, so a test can prove one user never sees another's data."""

    def __init__(self) -> None:
        self.users: Dict[str, Dict[str, Any]] = {}
        self.calls: List[tuple] = []
        self.acting_as: Optional[str] = None
        self.runs: Dict[int, Dict[str, Any]] = {}
        self.cards: List[Dict[str, Any]] = []
        self.events: Dict[int, List[Dict[str, Any]]] = {}
        self.receipts: Dict[tuple, Dict[str, Any]] = {}
        self.production = False
        # A model exists by default; what it answers is ``meeting_plan``.
        self.model_available = True
        self.model_calls: List[Dict[str, Any]] = []

    def add_user(self, user_id: int, address: str, *, google: Optional[List[str]] = None,
                 outlook: Optional[str] = None, gmail_mail: bool = False, outlook_mail: bool = False,
                 prefs: Optional[Dict[str, Any]] = None) -> None:
        google = google or []
        self.users[address] = {
            "user": DeskUser(id=user_id, email=address),
            "status": {
                "authorized": True, "email": address, "outlookEmail": outlook,
                "gmailAccounts": [{"providerAccountId": a, "email": a, "connected": True,
                                   "isPrimary": i == 0} for i, a in enumerate(google)],
                "emailAccounts": [],
                "providers": {
                    "gmail": provider_row(gmail_mail, email=google[0] if google else None,
                                          loginPath="/auth/login"),
                    "google_calendar": provider_row(bool(google), email=google[0] if google else None,
                                                    loginPath="/auth/login"),
                    "outlook": provider_row(outlook_mail, email=outlook, loginPath="/auth/outlook/login"),
                    "outlook_calendar": provider_row(bool(outlook), email=outlook,
                                                     loginPath="/auth/outlook/login"),
                    "slack": provider_row(True, email="slack-user"),
                    "jira": provider_row(True, email="jira-user"),
                },
            },
            "prefs": {"timezone": "UTC", "workday_start_time": "09:00:00", "workday_end_time": "17:00:00",
                      "preferred_weekdays": [], "meeting_buffer_minutes": 0,
                      "default_meeting_duration_minutes": 30, **(prefs or {})},
            "google_busy": {}, "outlook_busy": [], "google_error": {}, "outlook_error": None,
            "emails": {"gmail": [], "outlook": []}, "mail_error": {},
            "agenda": {"timezone": "UTC", "days": [{"date": "2026-11-16", "entries": []}]},
            "tasks": [], "reminders": [], "section_error": set(),
        }

    def world(self, address: str) -> Dict[str, Any]:
        return self.users[address]

    # ── the gateway interface ───────────────────────────────────────────────
    def current_user(self, request: Any) -> DeskUser:
        address = request.headers.get("x-test-user")
        if not address or address not in self.users:
            raise HTTPException(status_code=401, detail="Authentication required.")
        requested = (request.query_params.get("account") or "").strip().lower()
        if requested and requested != address:
            raise HTTPException(status_code=403, detail="Cross-user account access is forbidden.")
        return self.users[address]["user"]

    def scriba_commit(self) -> Optional[str]:
        return "test"

    def is_production(self) -> bool:
        return self.production

    def model_configured(self) -> bool:
        return self.model_available

    def session_email(self, request: Any) -> Optional[str]:
        from desk_overlay.gateway import acting_user

        acting = acting_user()
        if acting is not None:
            return acting.email
        headers = getattr(request, "headers", None)
        return headers.get("x-test-user") if headers is not None else self.acting_as

    def provider_status_for(self, user: DeskUser) -> Dict[str, Any]:
        return self.users[user.email]["status"]

    def acting_status(self) -> Optional[Dict[str, Any]]:
        from desk_overlay.gateway import acting_user

        acting = acting_user()
        return self.users[acting.email]["status"] if acting is not None else None

    def enrolled_users(self, addresses: List[str]) -> List[DeskUser]:
        return [self.users[a]["user"] for a in addresses if a in self.users]

    # Scriba's receipt ledger: UNIQUE (user_id, action_key), the same outcomes.
    def claim_receipt(self, user_id: int, key: str, kind: str) -> Dict[str, Any]:
        row = self.receipts.get((int(user_id), key))
        if row is None:
            row = {"id": len(self.receipts) + 1, "status": "pending", "object_id": None,
                   "updated_at": dt.datetime.now(UTC)}
            self.receipts[(int(user_id), key)] = row
            return {"claimed": True, "receipt": dict(row)}
        if row["status"] == "succeeded":
            return {"claimed": False, "receipt": dict(row)}
        if row["status"] == "failed":
            row.update(status="pending", updated_at=dt.datetime.now(UTC))
            return {"claimed": True, "receipt": dict(row)}
        return {"claimed": False, "unknown": True, "receipt": dict(row)}

    def finish_receipt(self, receipt_id: Any, status: str, object_id: Optional[str] = None) -> None:
        for row in self.receipts.values():
            if row["id"] == receipt_id:
                row.update(status=status, object_id=object_id or row["object_id"],
                           updated_at=dt.datetime.now(UTC))

    def calendar_events(self, user: DeskUser, start: dt.datetime, end: dt.datetime) -> List[Dict[str, Any]]:
        world = self.users[user.email]
        if world.get("events_error"):
            raise RuntimeError("calendar unavailable")
        return list(world.get("events", []))

    def user_for_email(self, address: str) -> Optional[DeskUser]:
        world = self.users.get(str(address or "").strip().lower())
        return world["user"] if world else None

    def provider_status(self, request: Any) -> Dict[str, Any]:
        # A chat tool has no request: the session user is ambient there, and
        # tests name it with ``acting_as``. A worker names its user itself.
        from desk_overlay.gateway import acting_user

        acting = acting_user()
        if acting is not None:
            self.calls.append(("provider_status_for", acting.email))
            return self.users[acting.email]["status"]
        headers = getattr(request, "headers", None)
        address = headers["x-test-user"] if headers is not None else self.acting_as
        return self.users[address]["status"]

    def preferences(self, user: DeskUser) -> Dict[str, Any]:
        return self.users[user.email]["prefs"]

    def list_emails(self, request: Any, user: DeskUser, *, provider: str, limit: int,
                    mailbox: Optional[str] = None) -> Dict[str, Any]:
        self.calls.append(("list_emails", user.email, provider, mailbox))
        world = self.users[user.email]
        if provider in world["mail_error"]:
            raise RuntimeError("mail provider down")
        rows = world["emails"][provider][:limit]
        return {"items": rows, "hasMore": False}

    def list_sent(self, request: Any, user: DeskUser, provider: str,
                  mailbox: Optional[str] = None) -> List[Dict[str, Any]]:
        world = self.users[user.email]
        if world.get("sent_error"):
            raise RuntimeError("sent mail unavailable")
        return list(world.get("sent", []))

    def classify(self, *, from_addr: str, subject: str, body: str) -> Dict[str, Any]:
        text = f"{subject}\n{body}".lower()
        if "unsubscribe" in text or "no-reply" in from_addr.lower():
            return {"classification": "automated/promotional", "priority": "low", "reasons": ["bulk"]}
        reasons = []
        if "?" in text:
            reasons.append("question")
        if any(word in text for word in ("meet", "call", "schedule", "calendar")):
            reasons.append("meeting_request")
        if reasons:
            return {"classification": "requires_reply", "priority": "high", "reasons": reasons}
        return {"classification": "informational", "priority": "low", "reasons": ["no_question_or_request"]}

    # ── workflow runs (a stand-in for Scriba's chat conversations and cards) ─
    def list_runs(self, user: DeskUser, limit: int = 50,
                  include_evaluation: bool = False) -> List[Dict[str, Any]]:
        rows = [run for run in self.runs.values() if run["user_id"] == user.id
                and (include_evaluation or not run["meta"].get("evaluation"))]
        return sorted(rows, key=lambda run: run["id"], reverse=True)[:limit]

    def find_run(self, user: DeskUser, key: str) -> Optional[Dict[str, Any]]:
        return next((run for run in self.list_runs(user, 500, include_evaluation=True)
                     if run["meta"]["key"] == key), None)

    def record_event(self, user: DeskUser, run: Dict[str, Any], item: Dict[str, Any],
                     summary: str) -> None:
        owned = self.runs.get(int(run["id"]))
        assert owned and owned["user_id"] == user.id, "an event may only be written to the user's own run"
        self.events.setdefault(int(run["id"]), []).append({**item, "summary": summary})

    def run_events(self, user: DeskUser, run: Dict[str, Any]) -> List[Dict[str, Any]]:
        owned = self.runs.get(int(run["id"]))
        if not owned or owned["user_id"] != user.id:
            return []
        return list(self.events.get(int(run["id"]), []))

    def get_run(self, user: DeskUser, run_id: int) -> Optional[Dict[str, Any]]:
        run = self.runs.get(int(run_id))
        return run if run and run["user_id"] == user.id else None

    def open_run(self, user: DeskUser, *, title: str, meta: Dict[str, Any],
                 summary: str) -> Dict[str, Any]:
        run = {"id": len(self.runs) + 1, "user_id": user.id, "title": title, "meta": meta,
               "summary": summary}
        self.runs[run["id"]] = run
        return run

    def propose_action(self, user: DeskUser, run: Dict[str, Any], *, tool_name: str,
                       tool_input: Dict[str, Any], email_id: Optional[str],
                       thread_id: Optional[str], provider: Optional[str]) -> Dict[str, Any]:
        card = {"id": len(self.cards) + 1, "run_id": run["id"], "user_id": user.id,
                "tool_name": tool_name, "status": "awaiting_approval", "input": dict(tool_input),
                "output": {}, "error": None, "assistant_action_id": None,
                "context": {"email_id": email_id, "thread_id": thread_id, "provider": provider}}
        self.cards.append(card)
        return card

    def approve_card(self, user: DeskUser, tool_call_id: Any,
                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        card = next(c for c in self.cards if c["id"] == int(tool_call_id) and c["user_id"] == user.id)
        if card["status"] in ("awaiting_approval", "needs_info"):
            self.settle(card["id"], "executed")
        return {"tool_call": dict(card)}

    def cancel_card(self, user: DeskUser, tool_call_id: Any) -> Dict[str, Any]:
        card = next(c for c in self.cards if c["id"] == int(tool_call_id) and c["user_id"] == user.id)
        if card["status"] in ("awaiting_approval", "needs_info"):
            card["status"] = "cancelled"
        return {"tool_call": dict(card)}

    def run_cards(self, user: DeskUser, run: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [card for card in self.cards if card["run_id"] == run["id"] and card["user_id"] == user.id]

    def settle(self, card_id: int, status: str = "executed") -> None:
        """What Scriba's approve route does to a card, for workflow tests."""
        card = next(card for card in self.cards if card["id"] == card_id)
        card["status"] = status
        card["assistant_action_id"] = 900 + card_id if status in ("executed", "partially_executed") else None

    def extract_meeting(self, user: DeskUser, item: Dict[str, Any], timezone: str) -> Optional[Dict[str, Any]]:
        self.calls.append(("extract_meeting", user.email, item.get("id")))
        return self.users[user.email].get("meeting_plan")

    def _section(self, user: DeskUser, name: str) -> Any:
        world = self.users[user.email]
        if name in world["section_error"]:
            raise RuntimeError(f"{name} unavailable")
        return world[name]

    def agenda_today(self, request: Any, user: DeskUser) -> Dict[str, Any]:
        return self._section(user, "agenda")

    def open_tasks(self, request: Any, user: DeskUser, limit: int) -> List[Dict[str, Any]]:
        return self._section(user, "tasks")[:limit]

    def upcoming_reminders(self, user: DeskUser, limit: int) -> List[Dict[str, Any]]:
        return self._section(user, "reminders")[:limit]

    def google_busy(self, user: DeskUser, account: str, start: dt.datetime, end: dt.datetime,
                    timezone: str) -> List[Busy]:
        self.calls.append(("google_busy", user.email, account))
        world = self.users[user.email]
        if account in world["google_error"]:
            raise CalendarReadError(world["google_error"][account])
        return [b for b in world["google_busy"].get(account, []) if b.start < end and b.end > start]

    def outlook_busy(self, user: DeskUser, account: str, start: dt.datetime,
                     end: dt.datetime) -> List[Busy]:
        self.calls.append(("outlook_busy", user.email, account))
        world = self.users[user.email]
        if world["outlook_error"]:
            if world["outlook_error"] == "crash":
                raise RuntimeError("unexpected")
            raise CalendarReadError(world["outlook_error"])
        return [b for b in world["outlook_busy"] if b.start < end and b.end > start]
