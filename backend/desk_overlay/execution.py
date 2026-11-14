"""The Desk's execution gate, on Scriba's own approve, retry and cancel.

Scriba's approve route claims a card atomically, re-validates it and hands it
to Scriba's execution engine. This module wraps that path. It does not
replace it: the claim, the validation and the card record stay Scriba's.

What the gate adds, in the server, for every card of a Desk run (and for
every card at all when the Desk chat scope is enforced):

1. **External writes are held** unless ``readiness`` says they are enabled.
   An approve or retry of a mail or calendar card on a real provider comes
   back ``needs_info`` with ``error_code: "external_writes_disabled"`` and
   nothing is claimed or executed. Disabled buttons in a client are not the
   enforcement; this is.
2. **A sandbox world replaces the provider.** When a world is in force for
   the run, Scriba's engine is not called: the approved action is applied to
   the world and logged there. A real provider client reached during that
   call raises ``SandboxIsolationError`` (the tripwire).
3. **Unknown outcomes stay unknown.** A provider call that times out after it
   may have taken effect marks the card ``outcome_unknown``. A retry first
   reads the provider state back; if the effect is there the card is closed
   as executed without a second write, and if no read-back is possible the
   retry is refused until the user confirms they checked.
4. **Evidence.** The human decision, the execution and the verification of
   each action are recorded on the run with their times.

Scriba is imported inside ``install`` only.
"""
from __future__ import annotations

import contextvars
import datetime as dt
import logging
import os
import time
from typing import Any, Callable, Dict, List, Mapping, Optional

from . import lifecycle, readiness
from .gateway import DeskUser
from .sandbox import (OP_CANCEL_EVENT, OP_CREATE_EVENT, OP_CREATE_REMINDER, OP_CREATE_TASK,
                      OP_DRAFT_EMAIL, OP_SEND_EMAIL, OP_UPDATE_EVENT, SandboxFault,
                      SandboxIsolationError, SandboxWorld, WorldRegistry, active_world)

logger = logging.getLogger(__name__)

HELD_CODE = "external_writes_disabled"
UNKNOWN_CODE = "outcome_unknown"
RETRY_CONFIRM_FLAG = "desk_retry_after_unknown_confirmed"
TOOL_OPS = {
    "send_email": OP_SEND_EMAIL, "draft_email_reply": OP_DRAFT_EMAIL,
    "create_calendar_event": OP_CREATE_EVENT, "update_calendar_event": OP_UPDATE_EVENT,
    "cancel_calendar_event": OP_CANCEL_EVENT, "create_task": OP_CREATE_TASK,
    "create_reminder": OP_CREATE_REMINDER,
}
# Real provider entry points. Reaching one while a world is in force is a defect.
_TRIPWIRES = (
    ("app.calendar_client", ("calendar_service",)),
    ("app.gmail_client", ("gmail_service", "send_message_once")),
    ("app.outlook_client", ("get_access_token", "get_access_token_for_scopes", "_calendar_token",
                            "graph_get", "_graph_get", "_graph_post", "_graph_patch", "_graph_delete",
                            "send_email", "fetch_event", "update_calendar_event",
                            "delete_calendar_event")),
)

# Set while a Desk-governed approve or retry is running in this context.
_call: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("desk_call", default=None)


class ExecutionGate:
    def __init__(self, gateway: Any, registry: WorldRegistry, *,
                 scope_enforced: Callable[[], bool], env: Optional[Mapping[str, str]] = None,
                 clock: Optional[Callable[[], dt.datetime]] = None) -> None:
        self.gateway = gateway
        self.registry = registry
        self.scope_enforced = scope_enforced
        self.env = env if env is not None else os.environ
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._saved: Dict[str, Any] = {}
        self._wires: List[Any] = []
        # Called with (user, run) once an approved action has taken effect.
        self.on_settled: Optional[Callable[[DeskUser, Dict[str, Any]], Any]] = None
        self.stats = {"held": 0, "sandboxExecutions": 0, "isolationViolations": 0}

    @property
    def installed(self) -> bool:
        return bool(self._saved)

    # ── policy ──────────────────────────────────────────────────────────────
    def writes_enabled(self) -> bool:
        return readiness.is_enabled(self.env, guards_installed=bool(self.scope_enforced()),
                                    scriba_commit=self.gateway.scriba_commit())

    def world_for_run(self, user: DeskUser, run: Optional[Dict[str, Any]]) -> Optional[SandboxWorld]:
        """The world a run was opened in. A run never changes worlds."""
        world_id = ((run or {}).get("meta") or {}).get("sandbox")
        if world_id:
            world = self.registry.get(str(world_id))
            if world is None:
                # Its world is gone (the process restarted). It must not fall
                # through to a real provider: it can no longer be executed.
                raise LookupError("sandbox_world_gone")
            return world
        return active_world() or self.registry.default_for(user.email)

    def _now(self, world: Optional[SandboxWorld]) -> str:
        return (world.now() if world is not None else self.clock()).isoformat()

    def _record(self, user: DeskUser, run: Optional[Dict[str, Any]], kind: str,
                data: Dict[str, Any], world: Optional[SandboxWorld]) -> None:
        if run is None:
            return
        try:
            lifecycle.record(self.gateway, user, run, kind, {**data, "simulated": world is not None},
                             at=self._now(world))
        except Exception:
            logger.exception("desk execution evidence could not be recorded kind=%s", kind)

    # ── install on Scriba ───────────────────────────────────────────────────
    def install(self) -> "ExecutionGate":
        if self._saved:
            return self
        import importlib

        from app import chat_calendar_edit, chat_service, llm_client

        repo = chat_service.repo
        gate = self
        saved = self._saved = {
            "approve": chat_service.approve_tool_call, "retry": chat_service.retry_tool_call,
            "cancel": chat_service.cancel_tool_call, "execute": chat_service.execute_action,
            "retry_action": chat_service.retry_action,
            "status": chat_service._safe_provider_status,
            "account_state": chat_service._google_calendar_account_state,
            "temporal": getattr(llm_client, "build_temporal_context", None),
            "edit": {name: getattr(chat_calendar_edit, name) for name in (
                "_fetch_google_event", "_fetch_outlook_event", "_calendar_meetings",
                "_mirrored_provider", "_google_account_for", "_own_outlook_addresses",
                "_user_timezone")},
        }

        def context_for(account_email: str, tool_call_id: Any) -> Optional[Dict[str, Any]]:
            """None when this card is not the Desk's to govern."""
            user_id = chat_service._user_id_for(account_email)
            row = repo.get_tool_call(tool_call_id, user_id=user_id)
            if not row:
                return None
            user = DeskUser(id=int(user_id), email=str(account_email).strip().lower())
            run = gate.gateway.get_run(user, int(row.get("conversation_id") or 0)) \
                if row.get("conversation_id") else None
            if run is None and not gate.scope_enforced():
                return None
            return {"user": user, "run": run, "row": row, "repo": repo, "notes": {}}

        def hold(ctx: Dict[str, Any], tool_call_id: Any, code: str, message: str,
                 **extra: Any) -> Dict[str, Any]:
            row = ctx["row"]
            if str(row.get("status") or "") not in ("awaiting_approval", "needs_info", "failed"):
                return {"tool_call": repo.serialize_tool_call(row)}
            updated = repo.update_tool_call(
                tool_call_id, user_id=ctx["user"].id, status="needs_info", error=code,
                output_payload_patch={"needs_info": True, "blocked": True, "error_code": code,
                                      "message": message, **extra})
            gate.stats["held"] += 1
            return {"tool_call": repo.serialize_tool_call(updated or row)}

        def governed(kind: str, kwargs: Dict[str, Any]) -> Any:
            ctx = context_for(str(kwargs.get("account_email") or ""), kwargs.get("tool_call_id"))
            if ctx is None:
                return saved[kind](**kwargs)
            user, run, row = ctx["user"], ctx["run"], ctx["row"]
            tool = str(row.get("tool_name") or "")
            tool_call_id = kwargs.get("tool_call_id")
            try:
                world = gate.world_for_run(user, run)
            except LookupError:
                return hold(ctx, tool_call_id, "sandbox_world_gone",
                            "This action was prepared in a sandbox that no longer exists, so it "
                            "cannot be executed. Nothing was sent or changed.")
            ctx["world"] = world
            overrides = dict(kwargs.get("payload_overrides") or {})

            if tool in readiness.EXTERNAL_WRITE_TOOLS and world is None and not gate.writes_enabled():
                gate._record(user, run, "approval", {
                    "toolCallId": row.get("id"), "tool": tool, "decision": "approve",
                    "by": user.email, "result": "held", "code": HELD_CODE}, world)
                return hold(
                    ctx, tool_call_id, HELD_CODE,
                    "Sending mail and changing calendars is switched off on this Desk, so this "
                    "action was not executed. Nothing was sent or changed.")

            output = row.get("output_payload") if isinstance(row.get("output_payload"), dict) else {}
            if str(row.get("status") or "") == "failed" and output.get(UNKNOWN_CODE):
                settled = gate._reconcile(ctx, tool, overrides, hold)
                if settled is not None:
                    return settled

            if kind == "approve":
                gate._record(user, run, "approval", {
                    "toolCallId": row.get("id"), "tool": tool, "decision": "approve",
                    "by": user.email, "edited": sorted(overrides)}, world)
            else:
                gate._record(user, run, "human", {
                    "toolCallId": row.get("id"), "tool": tool, "action": "retry", "by": user.email}, world)

            started = time.monotonic()
            token = _call.set(ctx)
            try:
                with gate.registry.using(world):
                    result = saved[kind](**kwargs)
            except Exception as exc:
                gate._record(user, run, "execution", {
                    "toolCallId": row.get("id"), "tool": tool, "status": "failed",
                    "error": type(exc).__name__,
                    "durationMs": int((time.monotonic() - started) * 1000)}, world)
                raise
            finally:
                _call.reset(token)
            return gate._after(ctx, tool, result, int((time.monotonic() - started) * 1000))

        def approve_tool_call(**kwargs: Any) -> Any:
            return governed("approve", kwargs)

        def retry_tool_call(**kwargs: Any) -> Any:
            if _call.get() is not None:      # already inside a governed call
                return saved["retry"](**kwargs)
            return governed("retry", kwargs)

        def cancel_tool_call(**kwargs: Any) -> Any:
            ctx = context_for(str(kwargs.get("account_email") or ""), kwargs.get("tool_call_id"))
            result = saved["cancel"](**kwargs)
            if ctx is not None:
                card = (result or {}).get("tool_call") or {}
                if card.get("status") == "cancelled" and ctx["row"].get("status") != "cancelled":
                    try:
                        world = gate.world_for_run(ctx["user"], ctx["run"])
                    except LookupError:
                        world = None
                    gate._record(ctx["user"], ctx["run"], "approval", {
                        "toolCallId": ctx["row"].get("id"), "tool": ctx["row"].get("tool_name"),
                        "decision": "reject", "by": ctx["user"].email}, world)
            return result

        def execute_action(**kwargs: Any) -> Dict[str, Any]:
            ctx = _call.get()
            world = (ctx or {}).get("world") if ctx else active_world()
            action = kwargs.get("action") or {}
            if world is not None:
                gate.stats["sandboxExecutions"] += 1
                try:
                    return world.execute(action)
                except SandboxFault as fault:
                    if ctx is not None:
                        ctx["notes"]["outcome"] = "unknown"
                    return {"status": "failed", "error": "The provider did not confirm the request.",
                            "error_code": "provider_timeout", "result": {}, "action": {}}
            kind = str(action.get("action_type") or "")
            if ctx is not None and kind in readiness.EXTERNAL_WRITE_TOOLS and not gate.writes_enabled():
                # Defence in depth: the approve wrapper already held this.
                gate.stats["held"] += 1
                return {"status": "failed", "error": "External writes are disabled on this Desk.",
                        "error_code": HELD_CODE, "result": {}, "action": {}}
            return saved["execute"](**kwargs)

        def retry_action(**kwargs: Any) -> Dict[str, Any]:
            ctx = _call.get()
            if (ctx or {}).get("world") is not None or active_world() is not None:
                return {"status": "failed", "error": "A sandbox action is retried from its card.",
                        "error_code": "sandbox_retry_unsupported", "result": {}, "action": {}}
            if ctx is not None and str(ctx["row"].get("tool_name")) in readiness.EXTERNAL_WRITE_TOOLS \
                    and not gate.writes_enabled():
                return {"status": "failed", "error": "External writes are disabled on this Desk.",
                        "error_code": HELD_CODE, "result": {}, "action": {}}
            return saved["retry_action"](**kwargs)

        # Reads Scriba's chat layer makes on its own, answered from the world.
        def in_force(account_email: Optional[str] = None) -> Optional[SandboxWorld]:
            ctx = _call.get()
            if ctx is not None and ctx.get("world") is not None:
                return ctx["world"]
            return gate.registry.current(account_email)

        def safe_provider_status(account_email: str) -> Dict[str, Any]:
            world = in_force(account_email)
            if world is not None:
                return world.provider_status()
            acting = gate.gateway.acting_status()
            return acting if acting is not None else saved["status"](account_email)

        def google_calendar_account_state(account_email: str, provider_account_id: Optional[str]) -> str:
            world = in_force(account_email)
            if world is None:
                return saved["account_state"](account_email, provider_account_id)
            chosen = str(provider_account_id or "").strip().lower()
            return "ok" if not chosen or chosen in world.gmail_accounts else "missing_scope"

        def edit_seam(name: str, sandboxed: Callable[..., Any]) -> Callable[..., Any]:
            original = saved["edit"][name]

            def routed(account_email: str, *args: Any, **kwargs: Any) -> Any:
                world = in_force(account_email)
                if world is None:
                    return original(account_email, *args, **kwargs)
                return sandboxed(world, *args, **kwargs)
            return routed

        def fetch_google(world: SandboxWorld, event_id: str, provider_account_id: Any = None) -> Any:
            try:
                return world.google_event(event_id)
            except LookupError:
                raise chat_calendar_edit.EventLookupError("calendar_event_not_found")

        def fetch_outlook(world: SandboxWorld, event_id: str) -> Any:
            try:
                return world.outlook_event(event_id)
            except LookupError:
                raise chat_calendar_edit.EventLookupError("calendar_event_not_found")

        def meetings(world: SandboxWorld, *, range_start: Any = None, range_end: Any = None) -> Any:
            from .sandbox import parse_time

            return world.meetings(parse_time(range_start), parse_time(range_end))

        def temporal_context(timezone: str, now: Optional[dt.datetime] = None) -> Any:
            world = in_force()
            return saved["temporal"](timezone, now=now or (world.now() if world is not None else None))

        chat_service.approve_tool_call = approve_tool_call
        chat_service.retry_tool_call = retry_tool_call
        chat_service.cancel_tool_call = cancel_tool_call
        chat_service.execute_action = execute_action
        chat_service.retry_action = retry_action
        chat_service._safe_provider_status = safe_provider_status
        chat_service._google_calendar_account_state = google_calendar_account_state
        if saved["temporal"] is not None:
            llm_client.build_temporal_context = temporal_context
        for name, sandboxed in (
            ("_fetch_google_event", fetch_google), ("_fetch_outlook_event", fetch_outlook),
            ("_calendar_meetings", meetings),
            ("_mirrored_provider", lambda world, event_id: world.provider_of_event(event_id)),
            ("_google_account_for", lambda world, event_id, chosen=None: (
                (world.events.get(str(event_id)) or {}).get("account") or (chosen or None))),
            ("_own_outlook_addresses", lambda world: world.own_addresses()),
            ("_user_timezone", lambda world: world.timezone),
        ):
            setattr(chat_calendar_edit, name, edit_seam(name, sandboxed))

        # The tripwire: no real provider client while a world is in force.
        for module_name, names in _TRIPWIRES:
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
            for name in names:
                original = getattr(module, name, None)
                if not callable(original):
                    continue
                setattr(module, name, gate._wire(f"{module_name}.{name}", original, in_force))
                self._wires.append((module, name, original))
        logger.warning("desk_execution_gate_installed external_writes_enabled=%s", gate.writes_enabled())
        return self

    def _wire(self, label: str, original: Callable[..., Any],
              in_force: Callable[..., Optional[SandboxWorld]]) -> Callable[..., Any]:
        gate = self

        def guarded(*args: Any, **kwargs: Any) -> Any:
            ctx = _call.get()
            world = (ctx or {}).get("world") if ctx else active_world()
            if world is not None:
                world.violations.append(label)
                gate.stats["isolationViolations"] += 1
                raise SandboxIsolationError(f"{label} was called while sandbox world {world.id} was in force")
            return original(*args, **kwargs)
        guarded.__wrapped__ = original  # type: ignore[attr-defined]
        return guarded

    def uninstall(self) -> None:
        """Undo ``install``. For tests."""
        if not self._saved:
            return
        from app import chat_calendar_edit, chat_service, llm_client

        saved = self._saved
        chat_service.approve_tool_call = saved["approve"]
        chat_service.retry_tool_call = saved["retry"]
        chat_service.cancel_tool_call = saved["cancel"]
        chat_service.execute_action = saved["execute"]
        chat_service.retry_action = saved["retry_action"]
        chat_service._safe_provider_status = saved["status"]
        chat_service._google_calendar_account_state = saved["account_state"]
        if saved["temporal"] is not None:
            llm_client.build_temporal_context = saved["temporal"]
        for name, original in saved["edit"].items():
            setattr(chat_calendar_edit, name, original)
        for module, name, original in self._wires:
            setattr(module, name, original)
        self._wires, self._saved = [], {}

    # ── after Scriba's approve or retry returned ────────────────────────────
    def _after(self, ctx: Dict[str, Any], tool: str, result: Any, duration_ms: int) -> Any:
        user, run, world, repo = ctx["user"], ctx["run"], ctx.get("world"), ctx["repo"]
        card = dict((result or {}).get("tool_call") or {})
        status = str(card.get("status") or "")
        outcome_unknown = ctx["notes"].get("outcome") == "unknown" and status == "failed"
        if outcome_unknown:
            # Honest state: it may have happened. Never "failed, try again".
            updated = repo.update_tool_call(
                card.get("id"), user_id=user.id, error=UNKNOWN_CODE,
                output_payload_patch={
                    UNKNOWN_CODE: True, "error_code": UNKNOWN_CODE,
                    "message": "The provider did not confirm this action, so it may or may not "
                               "have happened. Check before trying again."})
            if updated:
                card = repo.serialize_tool_call(updated)
                result = {**result, "tool_call": card}
        if status in ("executed", "partially_executed", "failed"):
            self._record(user, run, "execution", {
                "toolCallId": card.get("id"), "tool": tool,
                "status": "unknown" if outcome_unknown else status,
                "error": None if status != "failed" else str(card.get("error") or "") or None,
                "assistantActionId": card.get("assistant_action_id"), "durationMs": duration_ms}, world)
        elif status == "needs_info":
            self._record(user, run, "execution", {
                "toolCallId": card.get("id"), "tool": tool, "status": "held",
                "code": (card.get("output") or {}).get("error_code") or card.get("error")}, world)
        if status in ("executed", "partially_executed"):
            self._verify(ctx, tool, card, result)
            if run is not None and callable(self.on_settled):
                try:
                    with self.registry.using(world):
                        self.on_settled(user, run)
                except Exception:
                    logger.exception("desk follow-on step could not be proposed")
        return result

    def _object_id(self, tool: str, card: Mapping[str, Any], result: Mapping[str, Any]) -> Optional[str]:
        sandbox = ((result.get("assistant_action") or {}) if isinstance(result, Mapping) else {}).get("sandbox")
        if isinstance(sandbox, Mapping) and sandbox.get("object_id"):
            return str(sandbox["object_id"])
        output = card.get("output") or {}
        payload = output.get("result") if isinstance(output.get("result"), Mapping) else {}
        event = payload.get("event") if isinstance(payload.get("event"), Mapping) else {}
        for value in (event.get("id"), output.get("calendar_event_id"), payload.get("message_id"),
                      (payload.get("task") or {}).get("id") if isinstance(payload.get("task"), Mapping) else None,
                      (payload.get("reminder") or {}).get("id")
                      if isinstance(payload.get("reminder"), Mapping) else None):
            if value:
                return str(value)
        return None

    def _verify(self, ctx: Dict[str, Any], tool: str, card: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        user, run, world = ctx["user"], ctx["run"], ctx.get("world")
        op = TOOL_OPS.get(tool)
        data = card.get("input") or {}
        expected = _expected(tool, data)
        readback = None
        try:
            with self.registry.using(world):
                readback = self.gateway.verify_effect(user, op, self._object_id(tool, card, result), expected)
        except Exception:
            logger.exception("desk verification read failed tool=%s", tool)
        if readback is not None:
            verified, method, reason = bool(readback.get("ok")), readback.get("method"), readback.get("reason")
        else:
            # A real provider: the evidence is Scriba's own action record.
            verified = bool(card.get("assistant_action_id")) and card.get("status") == "executed"
            method, reason = "scriba_action_record", None if verified else "no_action_record"
        self._record(user, run, "verification", {
            "toolCallId": card.get("id"), "tool": tool, "verified": verified, "method": method,
            "reason": reason}, world)

    def _reconcile(self, ctx: Dict[str, Any], tool: str, overrides: Dict[str, Any],
                   hold: Callable[..., Any]) -> Optional[Dict[str, Any]]:
        """Before re-running a card whose outcome is unknown: did it happen?"""
        user, run, world, row, repo = ctx["user"], ctx["run"], ctx.get("world"), ctx["row"], ctx["repo"]
        data = row.get("input_payload") or {}
        found = None
        if world is not None:
            found = _find_effect(world, tool, data)
        if found:
            updated = repo.update_tool_call(
                row.get("id"), user_id=user.id, status="executed", error=None,
                output_payload_patch={UNKNOWN_CODE: False, "error_code": None, "reconciled": True,
                                      "calendar_event_id": found if "calendar" in tool else None,
                                      "message": "This action had already taken effect. It was not "
                                                 "run a second time."})
            self._record(user, run, "verification", {
                "toolCallId": row.get("id"), "tool": tool, "verified": True,
                "method": "sandbox_readback", "reconciled": True, "objectId": found}, world)
            return {"tool_call": repo.serialize_tool_call(updated or row), "reconciled": True}
        if world is None and overrides.get(RETRY_CONFIRM_FLAG) is not True:
            return hold(ctx, row.get("id"), UNKNOWN_CODE,
                        "It is not known whether this action happened. Check your mailbox or "
                        "calendar first; then confirm to run it again.", **{UNKNOWN_CODE: True})
        self._record(user, run, "verification", {
            "toolCallId": row.get("id"), "tool": tool, "verified": False,
            "method": "sandbox_readback" if world is not None else "user_confirmed",
            "reason": "effect_not_found"}, world)
        return None


def _expected(tool: str, data: Mapping[str, Any]) -> Dict[str, Any]:
    planned = data.get("planned_change") if isinstance(data.get("planned_change"), Mapping) else {}
    return {"start": planned.get("start") or data.get("start") or data.get("start_time"),
            "timezone": data.get("timezone"), "thread_id": data.get("thread_id")}


def _find_effect(world: SandboxWorld, tool: str, data: Mapping[str, Any]) -> Optional[str]:
    """The id of the effect a card would have had, found by its content."""
    from .sandbox import _zone, parse_time

    zone = _zone(str(data.get("timezone") or world.timezone))
    if tool == "create_calendar_event":
        start = parse_time(data.get("start") or data.get("start_time"), zone)
        title = str(data.get("title") or data.get("summary") or "")
        for event in world.find_events():
            if start and event["start"] == start and (not title or event["title"] == title):
                return str(event["id"])
        return None
    if tool == "send_email":
        thread, body = data.get("thread_id"), str(data.get("body") or data.get("text") or "")
        for row in world.sent:
            if row.get("thread_id") == thread and row.get("text") == body:
                return str(row["id"])
        return None
    if tool == "cancel_calendar_event":
        event = world.events.get(str(data.get("event_id") or ""))
        return str(event["id"]) if event and event["status"] == "cancelled" else None
    if tool == "update_calendar_event":
        planned = data.get("planned_change") if isinstance(data.get("planned_change"), Mapping) else {}
        event = world.events.get(str(data.get("event_id") or ""))
        wanted = parse_time(planned.get("start"), zone)
        return str(event["id"]) if event and wanted and event["start"] == wanted else None
    if tool == "create_task":
        title = str(data.get("title") or "")
        return next((str(t["id"]) for t in world.tasks if t["title"] == title), None)
    return None
