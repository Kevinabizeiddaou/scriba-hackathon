"""``/desk/*`` routes. Nothing here sends mail or writes a calendar.

The secretary workflow is INCOMING WORK, UNDERSTAND, GATHER CONTEXT, PLAN,
APPROVE, EXECUTE, VERIFY, FOLLOW UP. These routes cover the first stages:

- ``/desk/inbox``         incoming work across Gmail and Outlook, triaged
- ``/desk/inbox/item``    one message understood, with its thread and, for a
                          meeting request, the calendar context
- ``/desk/availability``  both calendars combined into free slots
- ``/desk/slots/check``   one proposed time checked against both calendars
- ``/desk/briefing``      what needs the executive today

- ``/desk/intake``, ``/desk/runs``   the workflow: one message to proposed,
                          approvable actions, with its evidence
- ``/desk/worker``        the background intake worker's status
- ``/desk/follow-ups``    replies the executive is waiting for
- ``/desk/sandbox``       the isolated provider world, when this process has one

The logic lives in ``service.py`` and ``workflow.py`` and is shared with the
chat tools. Approval and execution stay with Scriba's existing chat and
action routes, behind the Desk's execution gate; see docs/BACKEND_CONTRACT.md.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import __version__, readiness
from .availability import InvalidAvailabilityRequest
from .claims import MemoryClaims
from .sandbox import RoutedGateway, WorldRegistry
from .service import DeskService, NotFound
from .workflow import DeskWorkflow, IntakeBusy

DESK_CAPABILITIES = ["connections", "inbox", "triage", "availability", "slot_check", "briefing",
                     "intake", "intake_sweep", "runs", "run_state", "run_lifecycle", "follow_ups",
                     "worker_status", "external_write_readiness", "sandbox_execution"]


class SlotCheckBody(BaseModel):
    start: str
    end: str
    timezone: Optional[str] = None
    buffer_minutes: Optional[int] = None


class IntakeBody(BaseModel):
    provider: str = Field(pattern="^(gmail|outlook)$")
    id: str = Field(min_length=1)
    mailbox: Optional[str] = None


class CommandBody(BaseModel):
    """An instruction from the signed-in person, in their own words."""

    text: str = Field(min_length=1, max_length=2000)
    # The same requestId sent again returns the same run: nothing is planned twice.
    requestId: Optional[str] = Field(default=None, max_length=120)


class DeliverBody(BaseModel):
    """A synthetic message for the caller's own sandbox mailbox."""

    provider: str = Field(default="gmail", pattern="^(gmail|outlook)$")
    from_addr: str = Field(min_length=3, max_length=200)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=8000)
    thread_id: Optional[str] = Field(default=None, max_length=200)


class SweepBody(BaseModel):
    provider: str = Field(default="all", pattern="^(all|gmail|outlook)$")
    limit: int = Field(default=25, ge=1, le=50)
    max_new: int = Field(default=5, ge=1, le=10)
    mailbox: Optional[str] = None


def build_router(gateway: Any, *, now: Any = None, extra_health: Any = None,
                 registry: Optional[WorldRegistry] = None, claims: Any = None,
                 env: Optional[Mapping[str, str]] = None, agent: Any = None) -> APIRouter:
    """``gateway`` is the Scriba seam; ``now`` is injectable for tests.

    The pieces the router builds are kept on ``router.desk`` so the process
    that mounts it can attach the execution gate, the worker and the
    evaluation routes to the same workflow.
    """
    router = APIRouter(prefix="/desk", tags=["desk"])
    env = env if env is not None else os.environ
    registry = registry or getattr(gateway, "registry", None) or WorldRegistry()
    if not isinstance(gateway, RoutedGateway):
        gateway = RoutedGateway(gateway, registry)
    service = DeskService(gateway, clock=now)
    workflow = DeskWorkflow(service, gateway, claims=claims or MemoryClaims(clock=now), agent=agent)
    desk: Dict[str, Any] = {"gateway": gateway, "registry": registry, "service": service,
                            "workflow": workflow, "worker": None, "gate": None, "env": env}
    router.desk = desk  # type: ignore[attr-defined]

    def guarded(call: Any) -> Dict[str, Any]:
        try:
            return call()
        except InvalidAvailabilityRequest as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except IntakeBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    def guards_installed() -> bool:
        from . import chat_scope

        return chat_scope.is_enabled() and bool(desk["gate"] is not None and desk["gate"].installed)

    def worker_status(user: Any) -> Dict[str, Any]:
        worker = desk["worker"]
        if worker is None:
            return {"enabled": False, "running": False, "reason": "not_installed",
                    "claims": {"store": getattr(workflow.claims, "kind", "unknown"),
                               "durable": bool(getattr(workflow.claims, "durable", False))}}
        return worker.status(user)

    @router.get("/health")
    def desk_health(request: Request) -> Dict[str, Any]:
        user = gateway.current_user(request)
        world = gateway.world_for(user)
        body: Dict[str, Any] = {
            "ok": True,
            "service": "scriba-desk-overlay",
            "version": __version__,
            "scribaCommit": gateway.scriba_commit(),
            "capabilities": DESK_CAPABILITIES,
            **readiness.readiness(env, guards_installed=guards_installed(),
                                  scriba_commit=gateway.scriba_commit(),
                                  sandbox_worlds=len(registry.defaults())),
            # What executing an approved mail or calendar action does for THIS
            # user: "sandbox" (isolated world), "external" (real provider) or
            # "held" (refused by the execution gate).
            "executionMode": "sandbox" if world is not None else (
                "external" if readiness.is_enabled(env, guards_installed=guards_installed(),
                                                   scriba_commit=gateway.scriba_commit()) else "held"),
            "sandbox": {"id": world.id, "label": world.label} if world is not None else None,
            "worker": {key: value for key, value in worker_status(user).items()
                       if key in ("enabled", "running", "reason", "intervalSeconds", "lastTickAt")},
            "model": {"configured": bool(gateway.model_configured())},
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

    # ── workflow: one incoming email to proposed, approvable actions ────────
    # These create a run (a Scriba chat conversation) and action cards in
    # Scriba. They send no mail and write no calendar; every card is approved
    # through Scriba's existing POST /chat/tool-calls/{id}/approve.
    @router.post("/intake")
    def desk_intake(request: Request, body: IntakeBody) -> Dict[str, Any]:
        user = gateway.current_user(request)
        return guarded(lambda: workflow.intake(
            request, user, provider=body.provider, item_id=body.id, mailbox=body.mailbox))

    @router.post("/commands")
    def desk_command(request: Request, body: CommandBody) -> Dict[str, Any]:
        """Open a run for an instruction ("remind me...", "move my 1:1...",
        "chase what is overdue"). It proposes cards; it sends nothing."""
        user = gateway.current_user(request)
        return guarded(lambda: workflow.command(request, user, body.text, request_id=body.requestId))

    @router.post("/intake/sweep")
    def desk_intake_sweep(request: Request, body: Optional[SweepBody] = None) -> Dict[str, Any]:
        """Open runs for recent messages that need one. Bounded and idempotent."""
        user = gateway.current_user(request)
        body = body or SweepBody()
        return guarded(lambda: workflow.sweep(
            request, user, provider=body.provider, limit=body.limit, max_new=body.max_new,
            mailbox=body.mailbox))

    @router.get("/runs")
    def desk_runs(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> Dict[str, Any]:
        """Each row says where the run stands: no second request per run."""
        user = gateway.current_user(request)
        return {"account": user.email, "runs": workflow.list_runs(request, user, limit)}

    # ── the worker, follow-ups and the sandbox ──────────────────────────────
    @router.get("/worker")
    def desk_worker(request: Request) -> Dict[str, Any]:
        user = gateway.current_user(request)
        return {"account": user.email, "worker": worker_status(user),
                "runs": workflow.counts(request, user)}

    @router.get("/follow-ups")
    def desk_follow_ups(request: Request, refresh: bool = True,
                        limit: int = Query(default=50, ge=1, le=200)) -> Dict[str, Any]:
        """Replies awaited on mail the Desk sent. Reads mail; sends nothing."""
        user = gateway.current_user(request)
        return workflow.follow_ups(request, user, refresh=refresh, limit=limit)

    @router.post("/runs/{run_id}/follow-ups/{follow_id}/close")
    def desk_follow_up_close(request: Request, run_id: int, follow_id: str) -> Dict[str, Any]:
        user = gateway.current_user(request)
        return guarded(lambda: workflow.close_follow_up(request, user, run_id, follow_id))

    @router.post("/runs/{run_id}/task-updates/{task_id}/apply")
    def desk_task_update_apply(request: Request, run_id: int, task_id: str) -> Dict[str, Any]:
        """Mark done the task this run matched. Writes only the person's own records."""
        user = gateway.current_user(request)
        return guarded(lambda: workflow.apply_task_update(request, user, run_id, task_id))

    @router.post("/runs/{run_id}/task-updates/{task_id}/dismiss")
    def desk_task_update_dismiss(request: Request, run_id: int, task_id: str) -> Dict[str, Any]:
        user = gateway.current_user(request)
        return guarded(lambda: workflow.apply_task_update(request, user, run_id, task_id, dismiss=True))

    @router.get("/sandbox")
    def desk_sandbox(request: Request) -> Dict[str, Any]:
        """The caller's isolated provider world and everything done in it."""
        user = gateway.current_user(request)
        world = registry.default_for(user.email)
        if world is None:
            raise HTTPException(status_code=404, detail="This backend has no sandbox world for you.")
        return {"account": user.email, "world": world.snapshot()}

    @router.post("/sandbox/deliver")
    def desk_sandbox_deliver(request: Request, body: DeliverBody) -> Dict[str, Any]:
        """Put a synthetic message in the caller's own sandbox mailbox. It is
        not taken in here: the worker, or a sweep, finds it like any mail."""
        user = gateway.current_user(request)
        world = registry.default_for(user.email)
        if world is None:
            raise HTTPException(status_code=404, detail="This backend has no sandbox world for you.")
        row = world.deliver(provider=body.provider, from_addr=body.from_addr, subject=body.subject,
                            body=body.body, thread_id=body.thread_id)
        return {"delivered": {key: row[key] for key in ("id", "threadId", "provider", "timestamp",
                                                        "provider_account_id")}}

    @router.get("/runs/{run_id}")
    def desk_run(request: Request, run_id: int) -> Dict[str, Any]:
        user = gateway.current_user(request)
        return guarded(lambda: workflow.view(request, user, run_id))

    @router.post("/runs/{run_id}/advance")
    def desk_run_advance(request: Request, run_id: int) -> Dict[str, Any]:
        user = gateway.current_user(request)
        return guarded(lambda: workflow.advance(request, user, run_id))

    @router.get("/briefing")
    def desk_briefing(request: Request, limit: int = Query(default=50, ge=1, le=100)) -> Dict[str, Any]:
        return service.briefing(request, gateway.current_user(request), limit=limit)

    return router
