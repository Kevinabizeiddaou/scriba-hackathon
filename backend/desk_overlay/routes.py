"""``/desk/*`` routes. Read-only: nothing here sends mail or writes a calendar.

The secretary workflow is INCOMING WORK, UNDERSTAND, GATHER CONTEXT, PLAN,
APPROVE, EXECUTE, VERIFY, FOLLOW UP. These routes cover the first stages:

- ``/desk/inbox``         incoming work across Gmail and Outlook, triaged
- ``/desk/inbox/item``    one message understood, with its thread and, for a
                          meeting request, the calendar context
- ``/desk/availability``  both calendars combined into free slots
- ``/desk/slots/check``   one proposed time checked against both calendars
- ``/desk/briefing``      what needs the executive today

The logic lives in ``service.py`` and is shared with the chat tools.
Approval, execution and verification stay with Scriba's existing chat and
action routes; see docs/BACKEND_CONTRACT.md.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from . import __version__
from .availability import InvalidAvailabilityRequest
from .service import DeskService, NotFound

DESK_CAPABILITIES = ["connections", "inbox", "triage", "availability", "slot_check", "briefing"]


class SlotCheckBody(BaseModel):
    start: str
    end: str
    timezone: Optional[str] = None
    buffer_minutes: Optional[int] = None


def build_router(gateway: Any, *, now: Any = None, extra_health: Any = None) -> APIRouter:
    """``gateway`` is the Scriba seam; ``now`` is injectable for tests."""
    router = APIRouter(prefix="/desk", tags=["desk"])
    service = DeskService(gateway, clock=now)

    def guarded(call: Any) -> Dict[str, Any]:
        try:
            return call()
        except InvalidAvailabilityRequest as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/health")
    def desk_health(request: Request) -> Dict[str, Any]:
        gateway.current_user(request)
        body: Dict[str, Any] = {
            "ok": True,
            "service": "scriba-desk-overlay",
            "version": __version__,
            "scribaCommit": gateway.scriba_commit(),
            "capabilities": DESK_CAPABILITIES,
            "writes": False,
        }
        if callable(extra_health):
            body.update(extra_health(request) or {})
        return body

    @router.get("/connections")
    def desk_connections(request: Request) -> Dict[str, Any]:
        return service.connections(request, gateway.current_user(request))

    @router.get("/inbox")
    def desk_inbox(
        request: Request,
        provider: str = Query(default="all", pattern="^(all|gmail|outlook)$"),
        limit: int = Query(default=25, ge=1, le=100),
        mailbox: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = gateway.current_user(request)
        return service.inbox(request, user, provider=provider, limit=limit, mailbox=mailbox)

    @router.get("/inbox/item")
    def desk_inbox_item(
        request: Request,
        provider: str = Query(pattern="^(gmail|outlook)$"),
        id: str = Query(min_length=1),
        mailbox: Optional[str] = None,
        days: int = Query(default=5, ge=1, le=14),
    ) -> Dict[str, Any]:
        user = gateway.current_user(request)
        return guarded(lambda: service.inbox_item(
            request, user, provider=provider, item_id=id, mailbox=mailbox, days=days))

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
        return guarded(lambda: service.availability(
            request, user, start=start, end=end, duration_minutes=duration_minutes,
            buffer_minutes=buffer_minutes, timezone=timezone, max_slots=max_slots))

    @router.post("/slots/check")
    def desk_slot_check(request: Request, body: SlotCheckBody) -> Dict[str, Any]:
        """Reads calendars only. POST because the question has a body."""
        user = gateway.current_user(request)
        return guarded(lambda: service.slot_check(
            request, user, start=body.start, end=body.end, timezone=body.timezone,
            buffer_minutes=body.buffer_minutes))

    @router.get("/briefing")
    def desk_briefing(request: Request, limit: int = Query(default=50, ge=1, le=100)) -> Dict[str, Any]:
        return service.briefing(request, gateway.current_user(request), limit=limit)

    return router
