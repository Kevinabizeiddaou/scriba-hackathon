"""``/desk/*`` routes. Read-only: nothing here sends mail or writes a calendar.

The secretary workflow is INCOMING WORK, UNDERSTAND, GATHER CONTEXT, PLAN,
APPROVE, EXECUTE, VERIFY, FOLLOW UP. These routes cover the first three for
the Desk:

- ``/desk/inbox``         incoming work across Gmail and Outlook, triaged
- ``/desk/inbox/item``    one message understood, with its thread and, for a
                          meeting request, the calendar context
- ``/desk/availability``  both calendars combined into free slots
- ``/desk/slots/check``   one proposed time checked against both calendars

Approval, execution and verification stay with Scriba's existing chat and
action routes; see docs/BACKEND_CONTRACT.md.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from . import __version__
from .availability import (
    Busy,
    InvalidAvailabilityRequest,
    WorkingHours,
    cross_calendar_conflicts,
    merge_intervals,
    parse_instant,
    parse_time_text,
    resolve_zone,
    slot_conflicts,
    suggest_slots,
)
from .briefing import build_briefing
from .capabilities import (
    MAIL_PROVIDERS,
    capabilities_from,
    google_calendar_accounts,
    secretary_ready,
    state_of,
)
from .gateway import CalendarReadError
from .triage import summarize, triage

MAX_RANGE_DAYS = 31
DESK_CAPABILITIES = ["connections", "inbox", "triage", "availability", "slot_check", "briefing"]


class SlotCheckBody(BaseModel):
    start: str
    end: str
    timezone: Optional[str] = None
    buffer_minutes: Optional[int] = None


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _draft_context(triage_record: Dict[str, Any], calendar: Optional[Dict[str, Any]]) -> str:
    """Instructions for Scriba's draft writer, stating only what was verified."""
    if triage_record.get("category") != "meeting_request":
        return "Draft a concise, professional reply for the executive to review."
    intent = triage_record.get("meeting_intent") or "new"
    if not calendar or not calendar.get("complete"):
        return (
            f"This is a meeting request ({intent}). The executive's calendars could not be "
            "fully checked, so do not confirm or propose any specific time. Acknowledge the "
            "request and say a time will be confirmed shortly."
        )
    slots = calendar.get("slots") or []
    if not slots:
        return (
            f"This is a meeting request ({intent}). The executive has no free time in the "
            "next working days. Do not confirm any time. Apologise and ask for options "
            "further out."
        )
    listed = "; ".join(f"{slot['start']} to {slot['end']}" for slot in slots[:3])
    return (
        f"This is a meeting request ({intent}). Times verified free on every connected "
        f"calendar ({calendar.get('timezone')}): {listed}. If the sender asked for a time "
        "that is not in this list, do not confirm it; offer these times instead. Never "
        "state that a meeting has been booked."
    )


def build_router(gateway: Any, *, now: Any = None) -> APIRouter:
    """``gateway`` is the Scriba seam; ``now`` is injectable for tests."""
    router = APIRouter(prefix="/desk", tags=["desk"])
    clock = now or (lambda: dt.datetime.now(dt.timezone.utc))

    # ── shared helpers ──────────────────────────────────────────────────────
    def working_context(user: Any, timezone: Optional[str], buffer_minutes: Optional[int],
                        duration_minutes: Optional[int]) -> Tuple[str, WorkingHours, int, int]:
        """Request parameters win; the user's Scriba preferences are the default."""
        prefs = gateway.preferences(user) or {}
        zone_name = (timezone or prefs.get("timezone") or "").strip()
        resolve_zone(zone_name)
        hours = WorkingHours(
            start_minutes=parse_time_text(prefs.get("workday_start_time"), 9 * 60),
            end_minutes=parse_time_text(prefs.get("workday_end_time"), 17 * 60),
            weekdays=tuple(int(day) for day in (prefs.get("preferred_weekdays") or [])
                           if isinstance(day, int) and 0 <= day <= 6),
        )
        buffer_value = prefs.get("meeting_buffer_minutes") if buffer_minutes is None else buffer_minutes
        duration_value = (prefs.get("default_meeting_duration_minutes")
                          if duration_minutes is None else duration_minutes)
        return zone_name, hours, max(int(buffer_value or 0), 0), int(duration_value or 30)

    def read_calendars(request: Request, user: Any, start: dt.datetime, end: dt.datetime,
                       timezone: str) -> Tuple[List[Dict[str, Any]], List[Busy]]:
        """Every connected calendar, each reported on its own.

        A calendar that fails to read is listed with ``ok: false`` and its
        busy time is unknown. It is never treated as free.
        """
        status = gateway.provider_status(request)
        capabilities = capabilities_from(status)
        calendars: List[Dict[str, Any]] = []
        busy: List[Busy] = []

        targets: List[Tuple[str, str]] = []
        if state_of(capabilities, "google_calendar") in ("connected", "reconnect_required"):
            for account in google_calendar_accounts(status) or []:
                targets.append(("google", account))
            if not any(provider == "google" for provider, _ in targets):
                # Calendar is connected but no account list was reported: the
                # primary account, addressed by the capability's own email.
                email = next((c.get("email") for c in capabilities if c["id"] == "google_calendar"), None)
                targets.append(("google", str(email or user.email).lower()))
        if state_of(capabilities, "outlook_calendar") in ("connected", "reconnect_required"):
            email = next((c.get("email") for c in capabilities if c["id"] == "outlook_calendar"), None)
            targets.append(("outlook", str(email or status.get("outlookEmail") or user.email).lower()))

        for provider, account in targets:
            entry: Dict[str, Any] = {"provider": provider, "account": account, "ok": True,
                                     "error": None, "busy_count": 0}
            try:
                if provider == "google":
                    found = gateway.google_busy(user, account, start, end, timezone)
                else:
                    found = gateway.outlook_busy(user, account, start, end)
                entry["busy_count"] = len(found)
                busy.extend(found)
            except CalendarReadError as exc:
                entry.update(ok=False, error=exc.code)
            except Exception:  # an unexpected failure is still "unknown", never "free"
                entry.update(ok=False, error="provider_error")
            calendars.append(entry)
        return calendars, busy

    def parse_range(start: str, end: str, zone_name: str) -> Tuple[dt.datetime, dt.datetime]:
        zone = resolve_zone(zone_name)
        range_start, range_end = parse_instant(start, zone), parse_instant(end, zone)
        if range_end <= range_start:
            raise InvalidAvailabilityRequest("The end of the range must be after its start.")
        if range_end - range_start > dt.timedelta(days=MAX_RANGE_DAYS):
            raise InvalidAvailabilityRequest(f"The range may not exceed {MAX_RANGE_DAYS} days.")
        return range_start, range_end

    def completeness(calendars: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        if not calendars:
            return False, "no_calendar_connected"
        if not all(calendar["ok"] for calendar in calendars):
            return False, "calendar_unreadable"
        return True, None

    def triaged(item: Dict[str, Any]) -> Dict[str, Any]:
        verdict = gateway.classify(
            from_addr=str(item.get("from_addr") or ""),
            subject=str(item.get("subject") or ""),
            body=str(item.get("snippet") or ""),
        )
        return {**item, "triage": triage(item, verdict)}

    def read_mail(request: Request, user: Any, wanted: List[str], limit: int,
                  mailbox: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        capabilities = capabilities_from(gateway.provider_status(request))
        sources: List[Dict[str, Any]] = []
        items: List[Dict[str, Any]] = []
        for provider in wanted:
            state = state_of(capabilities, MAIL_PROVIDERS[provider])
            source: Dict[str, Any] = {"provider": provider, "state": state, "ok": True,
                                      "error": None, "count": 0, "hasMore": False}
            if state != "connected":
                source.update(ok=False, error=state)
                sources.append(source)
                continue
            try:
                page = gateway.list_emails(request, user, provider=provider, limit=limit,
                                           mailbox=mailbox if provider == "gmail" else None)
                # Only rows of the provider that was asked for: identity is
                # checked here, not assumed.
                rows = [row for row in (page.get("items") or [])
                        if isinstance(row, dict) and row.get("provider") == provider]
                source.update(count=len(rows), hasMore=bool(page.get("hasMore")))
                items.extend(rows)
            except HTTPException:
                raise
            except Exception:
                source.update(ok=False, error="provider_error")
            sources.append(source)
        return sources, items

    # ── routes ──────────────────────────────────────────────────────────────
    @router.get("/health")
    def desk_health(request: Request) -> Dict[str, Any]:
        gateway.current_user(request)
        return {
            "ok": True,
            "service": "scriba-desk-overlay",
            "version": __version__,
            "scribaCommit": gateway.scriba_commit(),
            "capabilities": DESK_CAPABILITIES,
            "writes": False,
        }

    @router.get("/connections")
    def desk_connections(request: Request) -> Dict[str, Any]:
        user = gateway.current_user(request)
        status = gateway.provider_status(request)
        capabilities = capabilities_from(status)
        mailboxes = [
            {key: account.get(key) for key in ("provider", "email", "label", "providerAccountId", "isPrimary")}
            for account in (status.get("emailAccounts") or [])
            if isinstance(account, dict) and account.get("provider") in MAIL_PROVIDERS
        ]
        return {
            "email": user.email,
            "capabilities": capabilities,
            "ready": secretary_ready(capabilities),
            "mailboxes": mailboxes,
        }

    @router.get("/inbox")
    def desk_inbox(
        request: Request,
        provider: str = Query(default="all", pattern="^(all|gmail|outlook)$"),
        limit: int = Query(default=25, ge=1, le=100),
        mailbox: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = gateway.current_user(request)
        wanted = list(MAIL_PROVIDERS) if provider == "all" else [provider]
        sources, rows = read_mail(request, user, wanted, limit, mailbox)
        items = [triaged(row) for row in rows]
        items.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
        items = items[:limit]
        return {
            "account": user.email,
            "items": items,
            "sources": sources,
            "counts": summarize([row["triage"] for row in items]),
            # False when a connected mailbox could not be read: the list is
            # then known to be missing mail.
            "complete": all(source["ok"] or source["state"] != "connected" for source in sources),
        }

    @router.get("/inbox/item")
    def desk_inbox_item(
        request: Request,
        provider: str = Query(pattern="^(gmail|outlook)$"),
        id: str = Query(min_length=1),
        mailbox: Optional[str] = None,
        days: int = Query(default=5, ge=1, le=14),
    ) -> Dict[str, Any]:
        """One message understood, with the context a secretary gathers next."""
        user = gateway.current_user(request)
        _, rows = read_mail(request, user, [provider], 100, mailbox)
        row = next((item for item in rows if str(item.get("id")) == id), None)
        if row is None:
            raise HTTPException(status_code=404, detail="Message not found in the recent inbox.")
        item = triaged(row)
        thread_id = item.get("threadId")
        thread = sorted(
            (other for other in rows if thread_id and other.get("threadId") == thread_id),
            key=lambda other: str(other.get("timestamp") or ""),
        )
        result: Dict[str, Any] = {
            "item": item,
            "thread": {"id": thread_id, "messages": thread, "count": len(thread)},
            # The mailbox any reply must be sent from.
            "replyFrom": {"provider": provider, "providerAccountId": item.get("provider_account_id")},
            "calendar": None,
            "draftRequest": None,
        }
        if item["triage"]["category"] == "meeting_request":
            try:
                zone_name, hours, buffer_minutes, duration = working_context(user, None, None, None)
                zone = resolve_zone(zone_name)
                start = clock().astimezone(zone)
                end = start + dt.timedelta(days=days)
                calendars, busy = read_calendars(request, user, start, end, zone_name)
                complete, reason = completeness(calendars)
                result["calendar"] = {
                    "timezone": zone_name,
                    "range": {"start": start.isoformat(), "end": end.isoformat()},
                    "duration_minutes": duration,
                    "calendars": calendars,
                    "complete": complete,
                    "reason": reason,
                    "slots": suggest_slots(
                        [(b.start, b.end) for b in busy], range_start=start, range_end=end,
                        timezone=zone_name, duration_minutes=duration, buffer_minutes=buffer_minutes,
                        hours=hours, max_slots=5, not_before=start,
                    ) if complete else [],
                }
            except InvalidAvailabilityRequest as exc:
                result["calendar"] = {"complete": False, "reason": "invalid_preferences",
                                      "detail": str(exc), "calendars": [], "slots": []}
        if item["triage"]["needs_reply"]:
            # The body for Scriba's EXISTING POST /drafts/create, which writes a
            # reply draft for review (stored in Scriba; nothing is sent). For a
            # meeting request the draft is told which times are really free.
            result["draftRequest"] = {
                "method": "POST",
                "path": "/drafts/create",
                "body": {
                    "provider": provider,
                    "email_id": item.get("id"),
                    "thread_id": thread_id,
                    "provider_account_id": item.get("provider_account_id"),
                    "user_context": _draft_context(item["triage"], result["calendar"]),
                },
            }
        return result

    @router.get("/briefing")
    def desk_briefing(request: Request, limit: int = Query(default=50, ge=1, le=100)) -> Dict[str, Any]:
        """What arrived, what needs the executive, and what is on today."""
        user = gateway.current_user(request)
        sources, rows = read_mail(request, user, list(MAIL_PROVIDERS), limit, None)
        items = [triaged(row) for row in rows]
        sections: Dict[str, Any] = {"agenda": {}, "tasks": [], "reminders": []}
        unavailable: List[str] = []
        for name, load in (
            ("agenda", lambda: gateway.agenda_today(request, user)),
            ("tasks", lambda: gateway.open_tasks(request, user, 100)),
            ("reminders", lambda: gateway.upcoming_reminders(user, 20)),
        ):
            try:
                sections[name] = load()
            except HTTPException:
                raise
            except Exception:  # one missing section must not hide the others
                unavailable.append(name)
        briefing = build_briefing(
            inbox_items=items,
            inbox_counts=summarize([row["triage"] for row in items]),
            inbox_complete=all(source["ok"] or source["state"] != "connected" for source in sources),
            agenda=sections["agenda"] or {},
            tasks=sections["tasks"] or [],
            reminders=sections["reminders"] or [],
        )
        return {"account": user.email, "generated_at": clock().isoformat(), **briefing,
                "sources": sources, "unavailable": unavailable}

    @router.get("/availability")
    def desk_availability(
        request: Request,
        start: str,
        end: str,
        duration_minutes: Optional[int] = Query(default=None, ge=15, le=480),
        buffer_minutes: Optional[int] = Query(default=None, ge=0, le=180),
        timezone: Optional[str] = None,
        max_slots: int = Query(default=5, ge=1, le=20),
    ) -> Dict[str, Any]:
        user = gateway.current_user(request)
        try:
            zone_name, hours, buffer_value, duration = working_context(
                user, timezone, buffer_minutes, duration_minutes)
            zone = resolve_zone(zone_name)
            range_start, range_end = parse_range(start, end, zone_name)
        except InvalidAvailabilityRequest as exc:
            raise _bad_request(exc)

        calendars, busy = read_calendars(request, user, range_start, range_end, zone_name)
        complete, reason = completeness(calendars)
        try:
            slots = suggest_slots(
                [(item.start, item.end) for item in busy],
                range_start=range_start, range_end=range_end, timezone=zone_name,
                duration_minutes=duration, buffer_minutes=buffer_value, hours=hours,
                max_slots=max_slots, not_before=clock(),
            ) if complete else []
        except InvalidAvailabilityRequest as exc:
            raise _bad_request(exc)

        return {
            "timezone": zone_name,
            "range": {"start": range_start.astimezone(zone).isoformat(),
                      "end": range_end.astimezone(zone).isoformat()},
            "duration_minutes": duration,
            "buffer_minutes": buffer_value,
            "working_hours": hours.as_dict(),
            "calendars": calendars,
            # Slots are offered only when EVERY connected calendar was read.
            "complete": complete,
            "reason": reason,
            "busy": [item.as_dict(zone) for item in sorted(busy, key=lambda b: b.start)],
            "busy_merged": [
                {"start": s.astimezone(zone).isoformat(), "end": e.astimezone(zone).isoformat()}
                for s, e in merge_intervals((item.start, item.end) for item in busy)
            ],
            "existing_conflicts": [
                {
                    "start": conflict["start"].astimezone(zone).isoformat(),
                    "end": conflict["end"].astimezone(zone).isoformat(),
                    "between": [item.as_dict(zone) for item in conflict["between"]],
                }
                for conflict in cross_calendar_conflicts(busy)
            ],
            "slots": slots,
        }

    @router.post("/slots/check")
    def desk_slot_check(request: Request, body: SlotCheckBody) -> Dict[str, Any]:
        """Reads calendars only. POST because the question has a body."""
        user = gateway.current_user(request)
        try:
            zone_name, hours, buffer_value, _ = working_context(
                user, body.timezone, body.buffer_minutes, None)
            zone = resolve_zone(zone_name)
            slot_start, slot_end = parse_range(body.start, body.end, zone_name)
        except InvalidAvailabilityRequest as exc:
            raise _bad_request(exc)

        pad = dt.timedelta(minutes=buffer_value)
        calendars, busy = read_calendars(request, user, slot_start - pad, slot_end + pad, zone_name)
        complete, reason = completeness(calendars)
        conflicts = slot_conflicts(busy, slot_start, slot_end, buffer_value)

        local_start, local_end = slot_start.astimezone(zone), slot_end.astimezone(zone)
        start_minutes = local_start.hour * 60 + local_start.minute
        end_minutes = local_end.hour * 60 + local_end.minute
        within_hours = (
            local_start.date() == local_end.date()
            and start_minutes >= hours.start_minutes
            and end_minutes <= hours.end_minutes
            and (not hours.weekdays or local_start.weekday() in hours.weekdays)
        )
        # A conflict is certain even when another calendar failed. "Free" is
        # only claimed when every connected calendar was read.
        free: Optional[bool] = False if conflicts else (True if complete else None)
        return {
            "timezone": zone_name,
            "slot": {"start": local_start.isoformat(), "end": local_end.isoformat()},
            "buffer_minutes": buffer_value,
            "free": free,
            "complete": complete,
            "reason": reason,
            "within_working_hours": within_hours,
            "conflicts": [item.as_dict(zone) for item in conflicts],
            "calendars": calendars,
        }

    return router
