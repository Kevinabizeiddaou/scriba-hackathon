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

    def provider_status(self, request: Any) -> Dict[str, Any]:
        return self.users[request.headers["x-test-user"]]["status"]

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
