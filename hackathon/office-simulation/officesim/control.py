"""The simulator's control surface on the sandbox backend: ``/sim/*``.

It exists only in a process started by ``sandbox_server.py``. It lets the
simulator play the OUTSIDE WORLD of the Desk's isolated provider world:

- set the world's clock (time passes);
- put a message in a mailbox (someone writes to the executive);
- make a provider fail, time out or become unreadable (services break);
- run one pass of the Desk's real intake worker (instead of waiting for its
  timer);
- stop the worker's process state, or leave an action in flight (a restart,
  an interruption);
- read the world's whole state back, for verification.

It never opens a run, writes a card, approves anything or records an
outcome. Work is done by the Desk's own workflow, and approvals go through
Scriba's own ``/chat/tool-calls/{id}/approve`` route. Every route here needs
Scriba's session like any other route of the application.

Imported only inside the Scriba process (FastAPI is Scriba's dependency).
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

CONTROL_VERSION = "1"


class ClockBody(BaseModel):
    now: str


class DeliverBody(BaseModel):
    provider: str = Field(default="gmail", pattern="^(gmail|outlook)$")
    message_id: str = Field(min_length=1, max_length=200)
    from_addr: str = Field(min_length=3, max_length=300)
    subject: str = Field(max_length=500)
    body: str = Field(max_length=20000)
    thread_id: Optional[str] = Field(default=None, max_length=200)
    account: Optional[str] = Field(default=None, max_length=200)
    received_at: Optional[str] = None
    labels: Optional[List[str]] = None
    to: Optional[List[str]] = None


class FaultBody(BaseModel):
    tool: str = Field(min_length=3, max_length=60)
    mode: str = Field(default="fail_times", pattern="^(fail_times|fail_always|uncertain)$")
    times: int = Field(default=1, ge=1, le=50)
    error: str = Field(default="provider_error", max_length=80)


class UnreadableBody(BaseModel):
    key: str = Field(min_length=3, max_length=200)      # "outlook", "google:<account>", "gmail_mail", "outlook_mail"
    code: Optional[str] = Field(default=None, max_length=80)   # None: readable again


class InterruptBody(BaseModel):
    toolCallId: int


class RemoveEventBody(BaseModel):
    eventId: str = Field(min_length=1, max_length=200)


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, dt.datetime) else value


def build_world(world_class: Any, spec: Mapping[str, Any]) -> Any:
    """The Desk's sandbox world for the office specification."""
    from desk_overlay.sandbox import parse_time

    executive = spec["executive"]
    world = world_class(
        spec["worldId"], owner_email=spec["scribaUser"], principal_email=executive["gmail"],
        principal_name=executive["name"], timezone=spec["timezone"],
        gmail_accounts=list(spec["accounts"]["gmail"]), outlook_account=spec["accounts"]["outlook"],
        now=parse_time(spec["startsAt"]), preferences=dict(spec["preferences"]),
        label="office-simulation")
    for event in spec["calendar"]:
        world.add_event(provider=event["provider"], title=event["title"], start=event["start"],
                        end=event["end"], event_id=event["id"], account=event["account"],
                        attendees=list(event["attendees"]), organizer=event["organizer"],
                        location=event.get("location"))
    for task in spec["tasks"]:
        world.tasks.append({"description": "", "created_at": spec["startsAt"], **task})
    for reminder in spec["reminders"]:
        world.reminders.append({"created_at": spec["startsAt"], **reminder})
    for follow in spec["followUps"]:
        world.follow_ups.append(dict(follow))
    for row in spec["sent"]:
        world.sent.append(dict(row))
    return world


def dump_world(world: Any) -> Dict[str, Any]:
    """Everything in the world, in plain JSON. No secret exists in a world."""
    with world._lock:
        return {
            "id": world.id, "label": world.label, "now": world.now().isoformat(),
            "timezone": world.timezone, "preferences": dict(world.preferences),
            "accounts": {"gmail": list(world.gmail_accounts), "outlook": world.outlook_account},
            "mail": {provider: [dict(row) for row in rows] for provider, rows in world.mail.items()},
            "sent": [dict(row) for row in world.sent],
            "drafts": [dict(row) for row in world.drafts],
            "events": [{key: _iso(value) for key, value in event.items()}
                       for event in sorted(world.events.values(), key=lambda e: (e["start"], e["id"]))],
            "tasks": [dict(task) for task in world.tasks],
            "reminders": [dict(reminder) for reminder in world.reminders],
            "followUps": [dict(follow) for follow in world.follow_ups],
            "faults": [dict(fault) for fault in world.faults],
            "unreadable": dict(world.unreadable),
            "operations": [dict(entry) for entry in world.oplog],
            "isolationViolations": list(world.violations),
            "simulated": True,
        }


def build_control_router(app: Any, spec: Mapping[str, Any], world: Any, options: Mapping[str, Any]) -> APIRouter:
    router = APIRouter(prefix="/sim", tags=["office-simulation"])

    def desk() -> Dict[str, Any]:
        return app.state.desk

    def session_user(request: Request) -> Any:
        user = desk()["gateway"].current_user(request)
        if str(user.email).lower() != str(spec["scribaUser"]).lower():
            raise HTTPException(status_code=403, detail="This sandbox belongs to another user.")
        return user

    @router.get("/meta")
    def meta(request: Request) -> Dict[str, Any]:
        session_user(request)
        return {"control": CONTROL_VERSION, "worldId": world.id, "specFingerprint": spec.get("fingerprint"),
                "day": spec["day"], "seed": spec["seed"], "timezone": spec["timezone"],
                # The kind of claim store only: a file path says where this runs.
                "workerMode": options.get("worker"),
                "claims": str(options.get("claims") or "").split(":", 1)[0],
                "deskBackend": options.get("deskBackendCommit"), "model": options.get("model"),
                "simulated": True}

    @router.get("/state")
    def state(request: Request) -> Dict[str, Any]:
        session_user(request)
        gate = desk().get("gate")
        return {"world": dump_world(world), "gate": dict(getattr(gate, "stats", {}) or {})}

    @router.post("/clock")
    def clock(request: Request, body: ClockBody) -> Dict[str, Any]:
        from desk_overlay.sandbox import parse_time

        session_user(request)
        moment = parse_time(body.now)
        if moment is None:
            raise HTTPException(status_code=400, detail="now must be an ISO 8601 time.")
        before = world.now()
        if moment < before:
            # Time only moves forward: a clock that runs backwards would let a
            # later event be judged against an earlier state.
            raise HTTPException(status_code=409, detail="The clock cannot move backwards.")
        world.set_now(moment)
        return {"before": before.isoformat(), "now": world.now().isoformat()}

    @router.post("/deliver")
    def deliver(request: Request, body: DeliverBody) -> Dict[str, Any]:
        from desk_overlay.sandbox import parse_time

        session_user(request)
        existing = next((row for row in world.mail.get(body.provider, []) if row["id"] == body.message_id), None)
        if existing is not None:
            # A provider notifying twice about one message does not make two messages.
            return {"delivered": False, "duplicateNotification": True, "id": existing["id"],
                    "threadId": existing["threadId"]}
        row = world.deliver(provider=body.provider, message_id=body.message_id, from_addr=body.from_addr,
                            subject=body.subject, body=body.body, thread_id=body.thread_id,
                            account=body.account, received_at=parse_time(body.received_at),
                            labels=body.labels, to=body.to)
        return {"delivered": True, "duplicateNotification": False,
                **{key: row[key] for key in ("id", "threadId", "provider", "timestamp", "provider_account_id")}}

    @router.post("/fault")
    def fault(request: Request, body: FaultBody) -> Dict[str, Any]:
        session_user(request)
        world.add_fault(body.tool, mode=body.mode, times=body.times, error=body.error)
        return {"faults": [dict(entry) for entry in world.faults]}

    @router.post("/faults/clear")
    def faults_clear(request: Request) -> Dict[str, Any]:
        session_user(request)
        world.faults.clear()
        return {"faults": []}

    @router.post("/unreadable")
    def unreadable(request: Request, body: UnreadableBody) -> Dict[str, Any]:
        session_user(request)
        if body.code:
            world.unreadable[body.key] = body.code
        else:
            world.unreadable.pop(body.key, None)
        return {"unreadable": dict(world.unreadable)}

    @router.post("/world/remove-event")
    def remove_event(request: Request, body: RemoveEventBody) -> Dict[str, Any]:
        """Someone else deletes a meeting from the calendar behind the Desk's
        back (an organizer, the executive on her phone)."""
        session_user(request)
        with world._lock:
            gone = world.events.pop(body.eventId, None)
        return {"removed": bool(gone), "eventId": body.eventId}

    @router.post("/worker/tick")
    def worker_tick(request: Request) -> Dict[str, Any]:
        """One pass of the Desk's own intake worker, now instead of on its timer."""
        user = session_user(request)
        worker = desk()["worker"]
        # A backing-off user is skipped on the worker's real (monotonic) clock.
        # Simulated time has moved on, so the back-off is over: clear it the
        # way the passing of real time would.
        slot = worker._users.get(user.email)
        if slot is not None:
            slot["notBefore"] = 0.0
        summary = worker.tick()
        return {"tick": summary, "worker": worker.status(user)}

    @router.post("/worker/restart")
    def worker_restart(request: Request) -> Dict[str, Any]:
        """Simulate the worker's process restarting: its in-memory state is
        thrown away and it is built again. With file-backed claims, the claim
        store is reopened from the file, as a new process would."""
        user = session_user(request)
        from desk_overlay.worker import IntakeWorker

        state = desk()
        old = state["worker"]
        old.stop(timeout=1.0)
        workflow = state["workflow"]
        claims_note = getattr(workflow.claims, "kind", "unknown")
        if str(options.get("claims") or "").startswith("sqlite:"):
            from desk_overlay.claims import SqliteClaims

            workflow.claims = SqliteClaims(str(options["claims"]).split(":", 1)[1])
            claims_note = "sqlite (reopened from file)"
        fresh = IntakeWorker(app, state["gateway"], workflow, env=state["env"], registry=state["registry"])
        fresh.recover = state["gate"].recover_stale
        state["worker"] = fresh
        if options.get("worker") == "thread":
            fresh.start()
        return {"restarted": True, "claims": claims_note, "worker": fresh.status(user)}

    @router.post("/interrupt")
    def interrupt(request: Request, body: InterruptBody) -> Dict[str, Any]:
        """Leave one approved action in flight, as a process that stopped
        between claiming the card and running it would. The action's effect is
        NOT applied. The Desk's own recovery has to settle it."""
        user = session_user(request)
        import app.chat_repository as chat_repo

        card = chat_repo.get_tool_call(body.toolCallId, user_id=user.id)
        if card is None:
            raise HTTPException(status_code=404, detail="No such action.")
        if card.get("status") != "awaiting_approval":
            raise HTTPException(status_code=409, detail="Only an action awaiting approval can be interrupted.")
        chat_repo.update_tool_call(body.toolCallId, user_id=user.id, status="executing",
                                   updated_at="2000-01-01T00:00:00+00:00")
        after = chat_repo.get_tool_call(body.toolCallId, user_id=user.id) or {}
        return {"toolCallId": body.toolCallId, "status": after.get("status"), "effectApplied": False}

    return router
