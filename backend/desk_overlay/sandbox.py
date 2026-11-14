"""Isolated provider worlds: synthetic mailboxes and calendars the Desk can
read AND write without any provider.

A ``SandboxWorld`` is a complete stand-in for one person's Gmail, Outlook
Mail, Google Calendar and Outlook Calendar, plus their tasks and reminders.
It is used in two places:

- the evaluation routes (``/desk/eval/v1``) build one world per case;
- the local demo server (``backend/dev/seeded_desk_server.py --demo``) gives
  each seeded user a world, so the whole workflow can be watched end to end.

A world is NOT a flag on a real provider call. When a world is in force the
Desk's gateway answers every provider read from the world and Scriba's
execution engine is never reached: the approved action is applied to the
world (``SandboxWorld.execute``) and recorded in its operation log. Reaching
a real provider client while a world is in force is a defect; the tripwire in
``execution.py`` raises ``SandboxIsolationError`` and counts it.

Pure: standard library only, no Scriba import, no network, no wall clock
unless the world was built without a fixed one.
"""
from __future__ import annotations

import contextvars
import datetime as dt
import hashlib
import itertools
import threading
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional

from .availability import Busy

UTC = dt.timezone.utc

# Canonical operation names, shared with the evaluation contract's tools.
OP_SEND_EMAIL = "email.send"
OP_DRAFT_EMAIL = "email.draft"
OP_CREATE_EVENT = "calendar.create_event"
OP_UPDATE_EVENT = "calendar.update_event"
OP_CANCEL_EVENT = "calendar.cancel_event"
OP_CREATE_TASK = "task.create"
OP_CREATE_REMINDER = "reminder.create"
# Files the Desk creates in the person's own records. Never a mailbox, a
# calendar or anyone else's storage.
OP_CREATE_DOCUMENT = "document.create"
OP_CREATE_SPREADSHEET = "spreadsheet.create"
FILE_OPS = (OP_CREATE_DOCUMENT, OP_CREATE_SPREADSHEET)
WRITE_OPS = (OP_SEND_EMAIL, OP_DRAFT_EMAIL, OP_CREATE_EVENT, OP_UPDATE_EVENT, OP_CANCEL_EVENT,
             OP_CREATE_TASK, OP_CREATE_REMINDER)
# Faults a world can be told to produce. ``uncertain`` applies the effect and
# then reports a timeout: the caller cannot know whether it happened.
FAULT_MODES = ("fail_times", "fail_always", "uncertain")


class SandboxIsolationError(RuntimeError):
    """A real provider client was reached while a sandbox world was in force."""


class SandboxFault(Exception):
    """An injected provider failure. ``uncertain`` means the effect may have happened."""

    def __init__(self, code: str, *, uncertain: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


def parse_time(value: Any, default_zone: dt.tzinfo = UTC) -> Optional[dt.datetime]:
    """An aware datetime from ISO text; a value without an offset is in ``default_zone``."""
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=default_zone)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=default_zone)


def _zone(name: str) -> dt.tzinfo:
    from zoneinfo import ZoneInfo

    try:
        return ZoneInfo(name)
    except Exception:
        return UTC


def _addresses(value: Any) -> List[str]:
    from .safeguards import addresses_in

    return addresses_in(value)


class SandboxWorld:
    """One person's synthetic accounts. Thread-safe; every write is logged."""

    def __init__(self, world_id: str, *, owner_email: str, principal_email: Optional[str] = None,
                 principal_name: str = "", timezone: str = "UTC",
                 gmail_accounts: Optional[List[str]] = None, outlook_account: Optional[str] = None,
                 now: Optional[dt.datetime] = None, preferences: Optional[Mapping[str, Any]] = None,
                 label: str = "sandbox", evaluation: bool = False) -> None:
        self.id = str(world_id)
        self.label = label
        # An evaluation world belongs to one case and is hidden from the product screens.
        self.evaluation = bool(evaluation)
        # Whether writes to the person's OWN records (tasks, reminders) run
        # without an approval in this world. Mail and calendar writes never do.
        self.auto_internal_writes = False
        self.owner_email = owner_email.strip().lower()
        self.principal_email = (principal_email or owner_email).strip().lower()
        self.principal_name = principal_name
        self.timezone = timezone
        self.gmail_accounts = [a.strip().lower() for a in (gmail_accounts
                               if gmail_accounts is not None else [self.principal_email])]
        self.outlook_account = (outlook_account or "").strip().lower() or None
        self._fixed_now = now
        self.preferences = {
            "timezone": timezone, "workday_start_time": "09:00:00", "workday_end_time": "17:00:00",
            "preferred_weekdays": [0, 1, 2, 3, 4], "meeting_buffer_minutes": 0,
            "default_meeting_duration_minutes": 30, **dict(preferences or {}),
        }
        self.mail: Dict[str, List[Dict[str, Any]]] = {"gmail": [], "outlook": []}
        self.sent: List[Dict[str, Any]] = []
        self.drafts: List[Dict[str, Any]] = []
        self.events: Dict[str, Dict[str, Any]] = {}
        self.tasks: List[Dict[str, Any]] = []
        self.reminders: List[Dict[str, Any]] = []
        self.follow_ups: List[Dict[str, Any]] = []
        # Files of this world: attachments that arrived with mail, and files the
        # Desk generated. Bytes live here only; nothing is written to disk.
        # An attachment is never changed or removed: a generated file is new.
        self.files: Dict[str, Dict[str, Any]] = {}
        self.faults: List[Dict[str, Any]] = []
        self.unreadable: Dict[str, str] = {}       # "google:<account>" / "outlook" / "gmail_mail" -> code
        self.oplog: List[Dict[str, Any]] = []
        self.violations: List[str] = []            # real provider clients reached (must stay empty)
        self._ids = itertools.count(1)
        self._lock = threading.RLock()

    # ── clock ───────────────────────────────────────────────────────────────
    def now(self) -> dt.datetime:
        return self._fixed_now or dt.datetime.now(UTC)

    def set_now(self, value: dt.datetime) -> None:
        self._fixed_now = value

    def _next(self, prefix: str) -> str:
        return f"{prefix}-{self.id}-{next(self._ids)}"

    # ── seeding ─────────────────────────────────────────────────────────────
    def deliver(self, *, provider: str = "gmail", message_id: Optional[str] = None,
                from_addr: str, subject: str, body: str, thread_id: Optional[str] = None,
                received_at: Optional[dt.datetime] = None, account: Optional[str] = None,
                labels: Optional[List[str]] = None, to: Optional[List[str]] = None,
                attachments: Optional[List[Mapping[str, Any]]] = None) -> Dict[str, Any]:
        """A message arrives in one of the world's mailboxes. Returns the stored row,
        in the shape of a row of Scriba's ``GET /emails``. ``attachments`` are
        ``{filename, content (bytes), mime?}``; the row lists them by id, name
        and size, never with their bytes."""
        if provider not in self.mail:
            raise ValueError(f"unknown mail provider: {provider}")
        mailbox = (account or (self.gmail_accounts[0] if provider == "gmail" and self.gmail_accounts
                               else self.outlook_account) or self.principal_email).lower()
        with self._lock:
            row_id = message_id or self._next("msg")
            row = {
                "id": row_id, "threadId": thread_id or f"thread-{row_id}", "from_addr": from_addr,
                "subject": subject, "snippet": " ".join(str(body or "").split())[:240],
                "body": str(body or ""),
                "timestamp": (received_at or self.now()).astimezone(UTC).isoformat(),
                "provider": provider, "is_read": False, "reply_supported": True,
                "provider_account_id": mailbox, "account_email": mailbox, "source_item_id": None,
                "priority": None, "labels": list(labels or ["INBOX"]), "to": list(to or [mailbox]),
            }
            listed = []
            for index, attachment in enumerate(attachments or [], start=1):
                content = bytes(attachment.get("content") or b"")
                file_id = f"att-{row_id}-{index}"
                self.files[file_id] = {
                    "id": file_id, "origin": "attachment", "messageId": row_id,
                    "filename": str(attachment.get("filename") or f"attachment-{index}"),
                    "mimeType": attachment.get("mime"), "sizeBytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(), "content": content,
                    "createdAt": row["timestamp"]}
                listed.append({key: self.files[file_id][key] for key in ("id", "filename", "sizeBytes", "mimeType")})
            if listed:
                row["attachments"] = listed
            self.mail[provider] = [r for r in self.mail[provider] if r["id"] != row_id] + [row]
            return dict(row)

    def add_event(self, *, provider: str, title: str, start: Any, end: Any,
                  event_id: Optional[str] = None, account: Optional[str] = None,
                  attendees: Optional[List[str]] = None, organizer: Optional[str] = None,
                  location: Optional[str] = None, description: str = "",
                  show_as: str = "busy") -> Dict[str, Any]:
        if provider not in ("google", "outlook"):
            raise ValueError(f"unknown calendar provider: {provider}")
        zone = _zone(self.timezone)
        start_dt, end_dt = parse_time(start, zone), parse_time(end, zone)
        if not start_dt or not end_dt or end_dt <= start_dt:
            raise ValueError("an event needs a start and a later end")
        owner = (account or (self.gmail_accounts[0] if provider == "google" and self.gmail_accounts
                             else self.outlook_account) or self.principal_email).lower()
        with self._lock:
            event = {
                "id": event_id or self._next("evt"), "provider": provider, "account": owner,
                "title": title, "start": start_dt, "end": end_dt,
                "attendees": [a.lower() for a in (attendees or [])],
                "organizer": (organizer or owner).lower(), "location": location,
                "description": description, "status": "confirmed", "show_as": show_as,
                "updated_at": self.now(),
            }
            self.events[event["id"]] = event
            return dict(event)

    def add_fault(self, tool: str, mode: str = "fail_always", times: int = 1,
                  error: str = "provider_error") -> None:
        if mode not in FAULT_MODES:
            raise ValueError(f"unknown fault mode: {mode}")
        self.faults.append({"tool": tool, "mode": mode, "remaining": max(1, int(times or 1)),
                            "error": str(error or "provider_error")})

    def _check_fault(self, op: str) -> Optional[Dict[str, Any]]:
        """The fault to apply to this call, consumed when it is counted."""
        for fault in self.faults:
            if fault["tool"] != op:
                continue
            if fault["mode"] == "fail_always":
                return fault
            if fault["remaining"] > 0:
                fault["remaining"] -= 1
                return fault
        return None

    # ── reads (the shapes Scriba's own runtimes return) ─────────────────────
    def provider_status(self) -> Dict[str, Any]:
        def row(connected: bool, email: Optional[str], path: str) -> Dict[str, Any]:
            return {"active": connected, "connected": connected, "available": True, "configured": True,
                    "status": "connected" if connected else "disconnected", "reason": None,
                    "email": email, "loginPath": path}

        primary = self.gmail_accounts[0] if self.gmail_accounts else None
        accounts = [{"provider": "gmail", "email": a, "label": "Gmail", "providerAccountId": a,
                     "isPrimary": i == 0} for i, a in enumerate(self.gmail_accounts)]
        if self.outlook_account:
            accounts.append({"provider": "outlook", "email": self.outlook_account, "label": "Outlook",
                             "providerAccountId": self.outlook_account, "isPrimary": not accounts})
        return {
            "authorized": True, "email": self.owner_email, "name": self.principal_name,
            "outlookEmail": self.outlook_account, "gmailEmail": primary,
            "gmailAccounts": [{"providerAccountId": a, "email": a, "connected": True,
                               "isPrimary": i == 0} for i, a in enumerate(self.gmail_accounts)],
            "emailAccounts": accounts,
            "providers": {
                "gmail": row(bool(primary), primary, "/auth/login"),
                "google_calendar": row(bool(primary), primary, "/auth/login"),
                "outlook": row(bool(self.outlook_account), self.outlook_account, "/auth/outlook/login"),
                "outlook_calendar": row(bool(self.outlook_account), self.outlook_account,
                                        "/auth/outlook/login"),
            },
            "sandbox": {"id": self.id, "label": self.label},
        }

    def list_emails(self, provider: str, limit: int, mailbox: Optional[str] = None) -> Dict[str, Any]:
        if self.unreadable.get(f"{provider}_mail"):
            raise RuntimeError(f"sandbox mailbox unreadable: {provider}")
        with self._lock:
            rows = [dict(r) for r in self.mail.get(provider, [])
                    if not mailbox or r["provider_account_id"] == mailbox.strip().lower()]
        rows.sort(key=lambda r: r["timestamp"], reverse=True)
        return {"items": rows[:limit], "hasMore": len(rows) > limit}

    def list_sent(self, provider: str, mailbox: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.sent if r["provider"] == provider
                    and (not mailbox or r.get("provider_account_id") in (None, mailbox.strip().lower()))]

    def busy(self, provider: str, account: str, start: dt.datetime, end: dt.datetime) -> List[Busy]:
        code = self.unreadable.get(f"{provider}:{account}") or self.unreadable.get(provider)
        if code:
            from .gateway import CalendarReadError

            raise CalendarReadError(code)
        with self._lock:
            events = [e for e in self.events.values()
                      if e["provider"] == provider and e["account"] == account
                      and e["status"] != "cancelled" and e["show_as"] not in ("free", "workingelsewhere")
                      and e["start"] < end and e["end"] > start]
        # Google's free/busy gives no titles; the world mirrors that.
        return [Busy(e["start"], e["end"], provider, account,
                     title=e["title"] if provider == "outlook" else None) for e in events]

    def find_events(self, *, start: Optional[dt.datetime] = None,
                    end: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
        with self._lock:
            found = [dict(e) for e in self.events.values() if e["status"] != "cancelled"
                     and (start is None or e["end"] > start) and (end is None or e["start"] < end)]
        return sorted(found, key=lambda e: e["start"])

    def meetings(self, start: Optional[dt.datetime] = None,
                 end: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
        """Events in the shape of Scriba's mirrored calendar meetings."""
        own = set(self.own_addresses())
        return [{
            "id": e["id"], "calendar_event_id": e["id"], "event_id": e["id"],
            "title": e["title"], "summary": e["title"],
            "start": e["start"].isoformat(), "end": e["end"].isoformat(),
            "start_time": e["start"].isoformat(), "end_time": e["end"].isoformat(),
            "provider": e["provider"], "calendar_provider": e["provider"],
            "provider_account_id": e["account"], "attendees": list(e["attendees"]),
            "organizer_email": e["organizer"], "is_organizer": e["organizer"] in own,
            "location": e["location"], "status": e["status"],
        } for e in self.find_events(start=start, end=end)]

    def own_addresses(self) -> List[str]:
        return sorted({self.owner_email, self.principal_email, *self.gmail_accounts,
                       *([self.outlook_account] if self.outlook_account else [])} - {""})

    def google_event(self, event_id: str) -> Dict[str, Any]:
        """A Google Calendar event resource (``events.get``)."""
        event = self._event(event_id, "google")
        own = set(self.own_addresses())
        return {
            "id": event["id"], "summary": event["title"], "location": event["location"],
            "status": event["status"],
            "start": {"dateTime": event["start"].isoformat(), "timeZone": self.timezone},
            "end": {"dateTime": event["end"].isoformat(), "timeZone": self.timezone},
            "organizer": {"email": event["organizer"], "self": event["organizer"] in own},
            "attendees": [{"email": a, "self": a in own, "responseStatus": "needsAction"}
                          for a in event["attendees"]],
        }

    def outlook_event(self, event_id: str) -> Dict[str, Any]:
        """A Microsoft Graph event resource."""
        event = self._event(event_id, "outlook")
        own = set(self.own_addresses())

        def moment(value: dt.datetime) -> Dict[str, str]:
            return {"dateTime": value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.0000000"),
                    "timeZone": "UTC"}

        return {
            "id": event["id"], "subject": event["title"],
            "isCancelled": event["status"] == "cancelled", "isAllDay": False,
            "isOrganizer": event["organizer"] in own,
            "start": moment(event["start"]), "end": moment(event["end"]),
            "location": {"displayName": event["location"] or ""},
            "organizer": {"emailAddress": {"address": event["organizer"]}},
            "attendees": [{"type": "required", "emailAddress": {"address": a},
                           "status": {"response": "none"}} for a in event["attendees"]],
        }

    def _event(self, event_id: str, provider: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            event = self.events.get(str(event_id))
            if not event or (provider and event["provider"] != provider):
                raise LookupError("calendar_event_not_found")
            return dict(event)

    def provider_of_event(self, event_id: str) -> Optional[str]:
        with self._lock:
            event = self.events.get(str(event_id))
            return event["provider"] if event else None

    # ── writes: what Scriba's execution engine would have done at a provider ─
    def execute(self, action: Mapping[str, Any]) -> Dict[str, Any]:
        """Apply one of Scriba's ``execute_action`` dicts to this world.

        Returns the engine's result shape. A failure is a result with
        ``status: "failed"``; an uncertain outcome raises ``SandboxFault``
        with ``uncertain=True`` AFTER the effect was applied, exactly as a
        timed-out provider call behaves.
        """
        action_type = str(action.get("action_type") or "")
        payload = dict(action.get("payload") or {})
        inner = dict(payload.get("action") or {})
        if action_type == "create_calendar_event":
            kind = str(inner.get("type") or "create")
            op = {"create": OP_CREATE_EVENT, "reschedule": OP_UPDATE_EVENT,
                  "cancel": OP_CANCEL_EVENT}.get(kind)
        else:
            op = {"send_email": OP_SEND_EMAIL, "draft_email_reply": OP_DRAFT_EMAIL,
                  "create_task": OP_CREATE_TASK, "create_reminder": OP_CREATE_REMINDER}.get(action_type)
        if op is None:
            return self._log(op or action_type, action, status="failed", error="unsupported_action")

        with self._lock:
            fault = self._check_fault(op)
            if fault and fault["mode"] != "uncertain":
                return self._log(op, action, status="failed", error=fault["error"])
            try:
                result, object_id = self._apply(op, action, payload, inner)
            except LookupError as exc:
                return self._log(op, action, status="failed", error=str(exc))
            except ValueError as exc:
                return self._log(op, action, status="failed", error=f"invalid_action: {exc}")
            if fault:  # uncertain: it happened, and the caller is not told
                self._log(op, action, status="unknown", object_id=object_id, error=fault["error"])
                raise SandboxFault(fault["error"], uncertain=True)
            return self._log(op, action, status="executed", object_id=object_id, result=result)

    def _apply(self, op: str, action: Mapping[str, Any], payload: Dict[str, Any],
               inner: Dict[str, Any]) -> Any:
        zone = _zone(self.timezone)
        if op == OP_CREATE_EVENT:
            spec = dict(inner.get("event") or {})
            provider = "outlook" if str(action.get("provider")) == "outlook" else "google"
            account = (str(payload.get("provider_account_id") or "").lower()
                       or (self.outlook_account if provider == "outlook" else
                           (self.gmail_accounts[0] if self.gmail_accounts else None)))
            if not account:
                raise ValueError("that calendar is not connected")
            event_zone = _zone(str(spec.get("timezone") or self.timezone))
            start, end = parse_time(spec.get("start"), event_zone), parse_time(spec.get("end"), event_zone)
            if not start or not end or end <= start:
                raise ValueError("the event has no valid time")
            title = str(spec.get("summary") or "Meeting")
            attendees = _addresses(spec.get("attendees"))
            # The same event asked for twice is one event: providers offer this
            # through request ids, and Scriba's leaf reports ``already_booked``.
            for existing in self.events.values():
                if (existing["status"] != "cancelled" and existing["provider"] == provider
                        and existing["account"] == account and existing["start"] == start
                        and existing["end"] == end and existing["title"] == title):
                    body = {"id": existing["id"], "start": start.isoformat(), "end": end.isoformat()}
                    return {"event": body, "calendar_result": {"event": body, "already_booked": True}}, \
                        existing["id"]
            event = self.add_event(provider=provider, title=title, start=start, end=end,
                                   account=account, attendees=attendees, organizer=account,
                                   location=spec.get("location"), description=str(spec.get("description") or ""))
            body = {"id": event["id"], "start": start.isoformat(), "end": end.isoformat(),
                    "attendees": attendees}
            return {"event": body, "calendar_result": {"event": body}}, event["id"]

        if op in (OP_UPDATE_EVENT, OP_CANCEL_EVENT):
            event_id = str(inner.get("target_event_id") or "")
            event = self.events.get(event_id)
            if not event or event["status"] == "cancelled":
                raise LookupError("calendar_event_not_found")
            if event["organizer"] not in self.own_addresses():
                raise ValueError("only the organizer can change this meeting")
            if op == OP_CANCEL_EVENT:
                event["status"] = "cancelled"
            else:
                spec = dict(inner.get("event") or {})
                event_zone = _zone(str(spec.get("timezone") or self.timezone))
                if "start" in spec:
                    moved = parse_time(spec.get("start"), event_zone)
                    if not moved:
                        raise ValueError("the new start time is not valid")
                    length = event["end"] - event["start"]
                    event["start"] = moved
                    event["end"] = parse_time(spec.get("end"), event_zone) or moved + length
                elif "end" in spec:
                    event["end"] = parse_time(spec.get("end"), event_zone) or event["end"]
                if "summary" in spec:
                    event["title"] = str(spec["summary"])
                if "attendees" in spec:
                    event["attendees"] = _addresses(spec["attendees"])
                if "location" in spec:
                    event["location"] = spec["location"]
            event["updated_at"] = self.now()
            body = {"id": event_id, "start": event["start"].isoformat(), "end": event["end"].isoformat(),
                    "status": event["status"]}
            return {"event": body, "calendar_result": {"event": body}}, event_id

        if op in (OP_SEND_EMAIL, OP_DRAFT_EMAIL):
            provider = str(payload.get("provider") or action.get("provider") or "gmail")
            text = str(payload.get("text") or payload.get("draft_text") or "")
            recipients = _addresses(payload.get("to"))
            if op == OP_SEND_EMAIL and (not recipients or not text.strip()):
                raise ValueError("an email needs a recipient and a body")
            row = {
                "id": self._next("sent" if op == OP_SEND_EMAIL else "draft"), "provider": provider,
                "provider_account_id": str(payload.get("provider_account_id") or "").lower() or None,
                "to": recipients, "subject": str(payload.get("subject") or ""), "text": text,
                "thread_id": payload.get("thread_id"), "mode": payload.get("mode") or "compose",
                "in_reply_to": payload.get("email_id") or payload.get("message_id"),
                "sent_at": self.now().astimezone(UTC).isoformat(),
            }
            (self.sent if op == OP_SEND_EMAIL else self.drafts).append(row)
            return {"message_id": row["id"], "thread_id": row["thread_id"], "to": recipients}, row["id"]

        if op == OP_CREATE_TASK:
            task = {"id": self._next("task"), "title": str(payload.get("title") or ""),
                    "description": str(payload.get("description") or ""),
                    "due_at": payload.get("due_at"), "priority": payload.get("priority") or "medium",
                    "status": "open", "created_at": self.now().isoformat()}
            if not task["title"].strip():
                raise ValueError("a task needs a title")
            self.tasks.append(task)
            return {"task": dict(task)}, task["id"]

        reminder = {"id": self._next("rem"), "title": str(payload.get("title") or ""),
                    "remind_at": payload.get("remind_at"), "timezone": payload.get("timezone"),
                    "status": "scheduled", "created_at": self.now().isoformat()}
        if not reminder["title"].strip() or not parse_time(reminder["remind_at"], zone):
            raise ValueError("a reminder needs a title and a time")
        self.reminders.append(reminder)
        return {"reminder": dict(reminder)}, reminder["id"]

    def _log(self, op: str, action: Mapping[str, Any], *, status: str, object_id: Optional[str] = None,
             result: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> Dict[str, Any]:
        entry = {"seq": len(self.oplog) + 1, "at": self.now().astimezone(UTC).isoformat(), "op": op,
                 "status": status, "object_id": object_id, "error": error, "simulated": True}
        self.oplog.append(entry)
        if status == "executed":
            return {"status": "executed", "result": dict(result or {}), "error": None,
                    "action": {"id": 500000 + entry["seq"], "source_item_id": None,
                               "sandbox": {"world": self.id, "op": op, "seq": entry["seq"],
                                           "object_id": object_id}}}
        return {"status": "failed", "result": {}, "error": error or "provider_error",
                "error_code": error or "provider_error", "action": {}}

    # ── files ───────────────────────────────────────────────────────────────
    def attachments_of(self, message_id: str) -> List[Dict[str, Any]]:
        """The attachments of one message: id, name and size. No bytes."""
        with self._lock:
            return [{key: f[key] for key in ("id", "filename", "sizeBytes", "mimeType", "sha256")}
                    for f in self.files.values()
                    if f["origin"] == "attachment" and f["messageId"] == str(message_id)]

    def file(self, file_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            found = self.files.get(str(file_id))
            return dict(found) if found else None

    def store_generated(self, *, filename: str, content: bytes, mime_type: str, extension: str) -> Dict[str, Any]:
        """Keep a file the Desk generated. The stand-in for Scriba's private
        generated-documents store. Always a NEW file: an existing one, an
        attachment least of all, is never replaced."""
        op = OP_CREATE_SPREADSHEET if str(extension).lower() in (".xlsx", ".csv") else OP_CREATE_DOCUMENT
        with self._lock:
            fault = self._check_fault(op)
            if fault is not None:
                self._log(op, {}, status="failed", error=fault["error"])
                raise SandboxFault(fault["error"], uncertain=fault["mode"] == "uncertain")
            file_id = self._next("file")
            content = bytes(content or b"")
            self.files[file_id] = {
                "id": file_id, "origin": "generated", "messageId": None, "filename": str(filename),
                "mimeType": mime_type, "extension": str(extension), "sizeBytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(), "content": content,
                "createdAt": self.now().astimezone(UTC).isoformat()}
            self._log(op, {}, status="executed", object_id=file_id)
            # The shape of a row of Scriba's ``generated_documents`` table.
            return {"id": file_id, "filename": str(filename), "mime_type": mime_type, "size_bytes": len(content)}

    # ── verification: read the world back ───────────────────────────────────
    def verify(self, op: str, object_id: Optional[str], expected: Mapping[str, Any]) -> Dict[str, Any]:
        """Whether the world's state shows the effect. Reads only."""
        with self._lock:
            if op in (OP_CREATE_EVENT, OP_UPDATE_EVENT, OP_CANCEL_EVENT):
                event = self.events.get(str(object_id or ""))
                if not event:
                    return {"ok": False, "reason": "event_not_found"}
                if op == OP_CANCEL_EVENT:
                    return {"ok": event["status"] == "cancelled", "reason": None
                            if event["status"] == "cancelled" else "event_still_scheduled"}
                if event["status"] == "cancelled":
                    return {"ok": False, "reason": "event_cancelled"}
                zone = _zone(str(expected.get("timezone") or self.timezone))
                wanted = parse_time(expected.get("start"), zone)
                if wanted and abs((event["start"] - wanted).total_seconds()) >= 60:
                    return {"ok": False, "reason": "start_differs",
                            "found": event["start"].isoformat()}
                return {"ok": True, "reason": None, "found": event["start"].isoformat()}
            if op == OP_SEND_EMAIL:
                row = next((r for r in self.sent if r["id"] == object_id), None)
                if not row:
                    return {"ok": False, "reason": "message_not_in_sent"}
                wanted_thread = expected.get("thread_id")
                if wanted_thread and row.get("thread_id") != wanted_thread:
                    return {"ok": False, "reason": "wrong_thread"}
                return {"ok": True, "reason": None}
            if op == OP_CREATE_TASK:
                return {"ok": any(t["id"] == object_id for t in self.tasks), "reason": None}
            if op == OP_CREATE_REMINDER:
                return {"ok": any(r["id"] == object_id for r in self.reminders), "reason": None}
            if op == OP_DRAFT_EMAIL:
                return {"ok": any(d["id"] == object_id for d in self.drafts), "reason": None}
            if op in FILE_OPS:
                # That the file is there. Whether it is the RIGHT file is
                # decided by reopening it (files.verify_generated), which the
                # gateway does with these bytes.
                found = self.files.get(str(object_id or ""))
                if not found or found["origin"] != "generated":
                    return {"ok": False, "reason": "file_not_found"}
                if hashlib.sha256(found["content"]).hexdigest() != found["sha256"]:
                    return {"ok": False, "reason": "file_changed_after_it_was_written"}
                return {"ok": True, "reason": None, "content": found["content"], "filename": found["filename"]}
        return {"ok": False, "reason": "unknown_operation"}

    def snapshot(self) -> Dict[str, Any]:
        """The world's state, for a status route and for tests. No secrets exist here."""
        with self._lock:
            return {
                "id": self.id, "label": self.label, "now": self.now().isoformat(),
                "fixedClock": self._fixed_now is not None,
                "accounts": {"gmail": list(self.gmail_accounts), "outlook": self.outlook_account},
                "counts": {"inbox": sum(len(v) for v in self.mail.values()), "sent": len(self.sent),
                           "events": sum(1 for e in self.events.values() if e["status"] != "cancelled"),
                           "tasks": len(self.tasks), "reminders": len(self.reminders),
                           "attachments": sum(1 for f in self.files.values() if f["origin"] == "attachment"),
                           "generatedFiles": sum(1 for f in self.files.values() if f["origin"] == "generated")},
                "operations": [dict(entry) for entry in self.oplog],
                "isolationViolations": list(self.violations),
            }


# ── which world, if any, is in force ────────────────────────────────────────

_active: contextvars.ContextVar[Optional[SandboxWorld]] = contextvars.ContextVar("desk_world", default=None)


class WorldRegistry:
    """Worlds by owner. ``current`` answers "is a world in force for this call?".

    A world set for the context (an evaluation case) wins. Otherwise a user's
    default world, when the process gave them one (the demo server). No world
    means the real providers, through Scriba.
    """

    def __init__(self) -> None:
        self._defaults: Dict[str, SandboxWorld] = {}
        self._worlds: Dict[str, SandboxWorld] = {}
        self._lock = threading.Lock()

    def add(self, world: SandboxWorld, *, default: bool = False) -> SandboxWorld:
        with self._lock:
            self._worlds[world.id] = world
            if default:
                self._defaults[world.owner_email] = world
        return world

    def get(self, world_id: str) -> Optional[SandboxWorld]:
        return self._worlds.get(str(world_id))

    def remove(self, world_id: str) -> None:
        with self._lock:
            world = self._worlds.pop(str(world_id), None)
            if world and self._defaults.get(world.owner_email) is world:
                del self._defaults[world.owner_email]

    def default_for(self, email: Optional[str]) -> Optional[SandboxWorld]:
        return self._defaults.get(str(email or "").strip().lower())

    def current(self, email: Optional[str] = None) -> Optional[SandboxWorld]:
        return _active.get() or self.default_for(email)

    def defaults(self) -> List[SandboxWorld]:
        return list(self._defaults.values())

    def any_active(self) -> bool:
        return bool(self._worlds)

    @contextmanager
    def using(self, world: Optional[SandboxWorld]) -> Iterator[Optional[SandboxWorld]]:
        """Put ``world`` in force for the calls made inside the block."""
        token = _active.set(world)
        try:
            yield world
        finally:
            _active.reset(token)

    def bind(self, world: Optional[SandboxWorld], call: Callable[..., Any]) -> Callable[..., Any]:
        """``call`` wrapped to run with ``world`` in force (for a worker thread)."""
        def bound(*args: Any, **kwargs: Any) -> Any:
            with self.using(world):
                return call(*args, **kwargs)
        return bound


def active_world() -> Optional[SandboxWorld]:
    """The world set for this context only (not a user's default)."""
    return _active.get()


class RoutedGateway:
    """A gateway whose provider reads come from the world in force, if any.

    Wraps the real ``ScribaGateway`` (or a test fake). Identity, runs, cards
    and the classifier are always the inner gateway's: a sandbox replaces the
    providers, not the Desk or Scriba's own machinery.
    """

    def __init__(self, inner: Any, registry: WorldRegistry) -> None:
        self.inner = inner
        self.registry = registry

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def world_for(self, user: Any = None, ctx: Any = None) -> Optional[SandboxWorld]:
        world = _active.get()
        if world is not None:
            return world
        email = getattr(user, "email", None)
        if email is None and ctx is not None:
            try:
                email = self.inner.session_email(ctx)
            except Exception:
                email = None
        return self.registry.default_for(email)

    def key_namespace(self, user: Any) -> str:
        """Keeps one case's messages apart from another's with the same ids."""
        world = self.world_for(user)
        return f"sandbox:{world.id}" if world is not None and world.evaluation else ""

    def clock_for(self, user: Any) -> Optional[dt.datetime]:
        world = self.world_for(user)
        return world.now() if world is not None else None

    def propose_action(self, user: Any, run: Any, **kwargs: Any) -> Any:
        """Create the card with the user's world in force, so Scriba's own
        validation (its provider status, its clock) sees the same world."""
        with self.registry.using(self.world_for(user)):
            return self.inner.propose_action(user, run, **kwargs)

    # ── provider reads ──────────────────────────────────────────────────────
    def provider_status(self, request: Any) -> Dict[str, Any]:
        world = self.world_for(ctx=request)
        return world.provider_status() if world is not None else self.inner.provider_status(request)

    def provider_status_for(self, user: Any) -> Dict[str, Any]:
        world = self.world_for(user)
        return world.provider_status() if world is not None else self.inner.provider_status_for(user)

    def preferences(self, user: Any) -> Dict[str, Any]:
        world = self.world_for(user)
        return dict(world.preferences) if world is not None else self.inner.preferences(user)

    def list_emails(self, request: Any, user: Any, *, provider: str, limit: int,
                    mailbox: Optional[str] = None) -> Dict[str, Any]:
        world = self.world_for(user)
        if world is not None:
            return world.list_emails(provider, limit, mailbox)
        return self.inner.list_emails(request, user, provider=provider, limit=limit, mailbox=mailbox)

    def list_sent(self, request: Any, user: Any, provider: str,
                  mailbox: Optional[str] = None) -> List[Dict[str, Any]]:
        world = self.world_for(user)
        if world is not None:
            # The Desk's reply-target check reads these two fields.
            return [{**row, "thread_id": row.get("thread_id"), "sent_at": row.get("sent_at")}
                    for row in world.list_sent(provider, mailbox)]
        return self.inner.list_sent(request, user, provider, mailbox)

    def google_busy(self, user: Any, account: str, start: dt.datetime, end: dt.datetime,
                    timezone: str) -> List[Busy]:
        world = self.world_for(user)
        if world is not None:
            return world.busy("google", account, start, end)
        return self.inner.google_busy(user, account, start, end, timezone)

    def outlook_busy(self, user: Any, account: str, start: dt.datetime, end: dt.datetime) -> List[Busy]:
        world = self.world_for(user)
        if world is not None:
            return world.busy("outlook", account, start, end)
        return self.inner.outlook_busy(user, account, start, end)

    def calendar_events(self, user: Any, start: dt.datetime, end: dt.datetime) -> List[Dict[str, Any]]:
        world = self.world_for(user)
        if world is not None:
            return world.meetings(start, end)
        return self.inner.calendar_events(user, start, end)

    def agenda_today(self, request: Any, user: Any) -> Dict[str, Any]:
        world = self.world_for(user)
        if world is None:
            return self.inner.agenda_today(request, user)
        zone = _zone(world.timezone)
        today = world.now().astimezone(zone).date()
        day_start = dt.datetime.combine(today, dt.time.min, tzinfo=zone)
        entries = [{"id": m["id"], "title": m["title"], "start": m["start"], "end": m["end"],
                    "provider": m["provider"], "provider_account_id": m["provider_account_id"]}
                   for m in world.meetings(day_start, day_start + dt.timedelta(days=1))]
        return {"timezone": world.timezone, "days": [{"date": today.isoformat(), "entries": entries}]}

    def open_tasks(self, request: Any, user: Any, limit: int) -> List[Dict[str, Any]]:
        world = self.world_for(user)
        if world is None:
            return self.inner.open_tasks(request, user, limit)
        return [dict(t) for t in world.tasks if t.get("status") == "open"][:limit]

    def complete_task(self, request: Any, user: Any, task_id: Any) -> Dict[str, Any]:
        world = self.world_for(user)
        if world is None:
            return self.inner.complete_task(request, user, task_id)
        with world._lock:
            task = next((t for t in world.tasks if str(t.get("id")) == str(task_id)), None)
            if task is None:
                raise LookupError("task_not_found")
            already = task.get("status") != "open"
            task["status"] = "done"
            task["completed_at"] = world.now().isoformat()
            world.oplog.append({"seq": len(world.oplog) + 1, "at": world.now().isoformat(),
                                "op": "task.complete", "status": "executed", "object_id": str(task_id),
                                "error": None, "simulated": True})
        return {"task": dict(task), "already_done": already}

    def upcoming_reminders(self, user: Any, limit: int) -> List[Dict[str, Any]]:
        world = self.world_for(user)
        if world is None:
            return self.inner.upcoming_reminders(user, limit)
        return [dict(r) for r in world.reminders if r.get("status") == "scheduled"][:limit]

    # ── replies the person was already waiting for ──────────────────────────
    def waiting_follow_ups(self, user: Any) -> List[Dict[str, Any]]:
        """Follow-ups that exist outside any Desk run (a world can be seeded
        with them). A real Scriba backend has none: there they live on runs."""
        world = self.world_for(user)
        if world is None:
            return []
        return [dict(f) for f in world.follow_ups if f.get("status") == "waiting"]

    def close_waiting_follow_up(self, user: Any, follow_id: str) -> bool:
        world = self.world_for(user)
        if world is None:
            return False
        with world._lock:
            for follow in world.follow_ups:
                if follow.get("id") == follow_id and follow.get("status") == "waiting":
                    follow["status"] = "closed"
                    world.oplog.append({"seq": len(world.oplog) + 1, "at": world.now().isoformat(),
                                        "op": "followup.close", "status": "executed",
                                        "object_id": follow_id, "error": None, "simulated": True})
                    return True
        return False

    def auto_internal_writes(self, user: Any) -> bool:
        world = self.world_for(user)
        return bool(world is not None and world.auto_internal_writes)

    # ── verification ────────────────────────────────────────────────────────
    def verify_effect(self, user: Any, op: str, object_id: Optional[str],
                      expected: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """A read-back of the provider state, where one is possible. None when
        only Scriba's own action record is available (a real provider)."""
        world = self.world_for(user)
        if world is None:
            return None
        found = world.verify(op, object_id, expected)
        if op in FILE_OPS:
            # A file that exists is not yet the file that was asked for: it is
            # reopened with Scriba's own reader and checked against what was approved.
            if found.get("ok"):
                from . import files

                found = files.verify_generated(found["content"], found["filename"], expected)
            found.pop("content", None)
            return {**found, "method": "file_reopened"}
        return {**found, "method": "sandbox_readback"}

    # ── files ───────────────────────────────────────────────────────────────
    def attachments(self, user: Any, item: Mapping[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """The attachments of a message, or None where this backend cannot
        read them (a real mailbox: not connected to the Desk yet)."""
        world = self.world_for(user)
        if world is None:
            return None
        return world.attachments_of(str(item.get("id") or ""))

    def attachment_content(self, user: Any, file_id: str) -> Optional[bytes]:
        world = self.world_for(user)
        found = world.file(file_id) if world is not None else None
        return found["content"] if found and found["origin"] == "attachment" else None

    def stored_file(self, user: Any, file_id: str) -> Optional[Dict[str, Any]]:
        """A file of the caller's own world, with its bytes. None for anyone else's."""
        world = self.world_for(user)
        return world.file(file_id) if world is not None else None
