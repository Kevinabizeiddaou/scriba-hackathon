"""``/desk/eval/v1``: the sandbox evaluation routes (contract 1.1.0).

The evaluation harness (``frontend/src/evaluation``) sends one case at a
time; this module runs it through the REAL Desk workflow and reports what
happened in the harness's vocabulary. It is a translation layer and nothing
else: it holds no expected answer and no case id is ever inspected.

What is real: the Desk's triage, context gathering, planning, proposals,
Scriba's own card validation, approve path and claim, the Desk's execution
gate, verification and evidence. What is replaced: the providers. Each case
gets its own ``SandboxWorld`` built from the case's own data (mail, calendar,
tasks, awaited replies, clock, faults). The world is in force for everything
done for that case, so no mailbox or calendar can be reached; the tripwire
in ``execution.py`` counts any attempt, and ``GET /meta`` reports the count.

The approval gate is unchanged: the harness plays the person, through
``GET /approvals`` and ``POST /approvals/{id}/decision``, which call the same
approve and cancel a browser does.

These routes exist only in a process started with ``DESK_EVAL_SANDBOX=on``.
They need a Scriba session like every other route, and a run is visible only
to the user who started it.

Not supported: ``input.kind == "conversation"`` (a chat turn needs Scriba's
model-planned chat agent, which is not driven from here yet). Such a run ends
``failed`` with ``conversation_input_unsupported``; it is never faked.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from . import lifecycle
from .gateway import acting_as
from .sandbox import SandboxWorld, parse_time
from .service import AppContext

logger = logging.getLogger(__name__)
CONTRACT_VERSION = "1.1.0"
CONTRACT_HEADER = "X-Executive-Desk-Contract"
MAX_RUNS = 500
TOOL_OF_CARD = {
    "send_email": "email.send", "create_calendar_event": "calendar.create_event",
    "update_calendar_event": "calendar.update_event", "cancel_calendar_event": "calendar.cancel_event",
    "create_task": "task.create", "create_reminder": "reminder.create",
}
SIDE_EFFECT_TOOLS = ("email.send", "calendar.create_event", "calendar.update_event", "calendar.cancel_event")
TOOL_OF_READ = {
    "email.read_thread": "email.read_thread", "calendar.find_free_slots": "calendar.find_free_slots",
    "calendar.check_availability": "calendar.list_events", "calendar.list_events": "calendar.list_events",
}
PRIORITY = {"urgent": "urgent", "high": "high", "medium": "normal", "normal": "normal", "low": "low"}
ALLOWED_FLAGS = ("prompt_injection_suspected", "duplicate", "timezone_ambiguous", "unverified_sender",
                 "outside_working_hours")


class EvalError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _person(address: Any) -> Dict[str, str]:
    email = str(address or "").strip().lower()
    return {"name": email.split("@")[0].replace(".", " ").title() if email else "", "email": email}


def _stamp(value: Any, fallback: str) -> str:
    """An RFC 3339 instant with an offset. The contract rejects anything else."""
    moment = parse_time(value)
    return moment.isoformat() if moment is not None else fallback


def build_world(body: Mapping[str, Any], owner_email: str) -> SandboxWorld:
    """One case's providers, from the case's own data."""
    context = body.get("context") or {}
    principal = context.get("principal") or {}
    address = str(principal.get("email") or "").strip().lower()
    now = parse_time(context.get("now"))
    if not address or now is None:
        raise EvalError(400, "invalid_request", "context.principal.email and context.now are required.")
    hours = principal.get("workingHours") or {}
    zone = str(principal.get("timezone") or "UTC")
    world = SandboxWorld(
        f"case-{uuid.uuid4().hex[:12]}", owner_email=owner_email, principal_email=address,
        principal_name=str(principal.get("name") or ""), timezone=zone, gmail_accounts=[address],
        now=now, label="evaluation", evaluation=True,
        preferences={
            "workday_start_time": f"{hours.get('start') or '09:00'}:00",
            "workday_end_time": f"{hours.get('end') or '17:00'}:00",
            # The contract counts Monday as 1; Scriba's preferences count it as 0.
            "preferred_weekdays": [int(day) - 1 for day in (hours.get("days") or [1, 2, 3, 4, 5])
                                   if 1 <= int(day) <= 7],
        })
    world.auto_internal_writes = True       # the contract: internal tools need no approval
    for event in context.get("calendar") or []:
        if str(event.get("status") or "confirmed") == "cancelled":
            continue
        attendees = [str((a or {}).get("email") or "").lower() for a in event.get("attendees") or []]
        world.add_event(provider="google", event_id=str(event.get("id")), title=str(event.get("title") or ""),
                        start=event.get("start"), end=event.get("end"),
                        attendees=[a for a in attendees if a and a != address], organizer=address,
                        location=event.get("location"), description=str(event.get("description") or ""))
    for task in context.get("tasks") or []:
        world.tasks.append({"id": str(task.get("id")), "title": str(task.get("title") or ""),
                            "due_at": task.get("dueAt"),
                            "status": "open" if task.get("status") == "open" else "done"})
    for follow in context.get("followUps") or []:
        world.follow_ups.append({
            "id": str(follow.get("id")), "subject": follow.get("subject"), "threadId": follow.get("threadId"),
            "waitingOn": follow.get("waitingOn"), "sentAt": follow.get("sentAt"),
            "expectedBy": follow.get("expectedBy"),
            "status": "waiting" if follow.get("status") == "waiting" else "closed"})
    for fault in context.get("faults") or []:
        error = fault.get("error") or {}
        world.add_fault(str(fault.get("tool")), mode=str(fault.get("mode") or "fail_always"),
                        times=int(fault.get("times") or 1), error=str(error.get("code") or "provider_error"))
    return world


def deliver_case_mail(world: SandboxWorld, body: Mapping[str, Any]) -> str:
    """Put the case's thread and its triggering message in the world's inbox."""
    case_input = body.get("input") or {}
    email = case_input.get("email") or {}
    if not email.get("id"):
        raise EvalError(400, "invalid_request", "input.email.id is required.")
    for message in [*(case_input.get("thread") or []), email]:
        sender = message.get("from") or {}
        from_addr = f"{sender.get('name') or ''} <{sender.get('email') or ''}>".strip()
        own = str(sender.get("email") or "").lower() == world.principal_email
        if own:
            # The principal's own earlier message: it is sent mail, not an arrival.
            world.sent.append({"id": str(message.get("id")), "provider": "gmail",
                               "provider_account_id": world.principal_email,
                               "to": [str((p or {}).get("email") or "") for p in message.get("to") or []],
                               "subject": str(message.get("subject") or ""),
                               "text": str(message.get("bodyText") or ""),
                               "thread_id": str(message.get("threadId") or ""), "mode": "compose",
                               "in_reply_to": None,
                               "sent_at": _stamp(message.get("sentAt"), world.now().isoformat())})
            continue
        world.deliver(provider="gmail", message_id=str(message.get("id")), from_addr=from_addr,
                      subject=str(message.get("subject") or ""), body=str(message.get("bodyText") or ""),
                      thread_id=str(message.get("threadId") or "") or None,
                      received_at=parse_time(message.get("sentAt")) or world.now(),
                      to=[str((p or {}).get("email") or "") for p in message.get("to") or []])
    return str(email["id"])


class EvalRuns:
    """The evaluation runs of this process. In memory: a run is one case."""

    def __init__(self, app: Any, desk: Dict[str, Any]) -> None:
        self.app = app
        self.gateway = desk["gateway"]
        self.registry = desk["registry"]
        self.workflow = desk["workflow"]
        self.runs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="desk-eval")

    # ── starting a case ─────────────────────────────────────────────────────
    def start(self, user: Any, body: Mapping[str, Any]) -> Dict[str, Any]:
        if str(body.get("mode") or "") != "sandbox":
            raise EvalError(400, "invalid_request", "Evaluation runs only in sandbox mode.")
        kind = str((body.get("input") or {}).get("kind") or "")
        if kind not in ("email", "conversation"):
            raise EvalError(400, "invalid_request", "input.kind must be email or conversation.")
        world = build_world(body, user.email)
        record = {
            "id": f"evalrun-{uuid.uuid4().hex[:16]}", "user": user, "world": world,
            "caseId": str(body.get("caseId") or ""), "kind": kind, "deskRunId": None,
            "state": "queued", "error": None, "started": time.monotonic(), "finished": None,
            "startedAt": world.now().isoformat(), "decisions": {},
        }
        with self._lock:
            if len(self.runs) >= MAX_RUNS:
                oldest = sorted(self.runs.values(), key=lambda r: r["started"])[0]
                self.registry.remove(oldest["world"].id)
                del self.runs[oldest["id"]]
            self.runs[record["id"]] = record
        self.registry.add(world)
        if kind == "conversation":
            self._fail(record, "conversation_input_unsupported",
                       "This backend runs evaluation cases that start from an email. A chat turn "
                       "needs Scriba's model-planned chat agent, which is not driven from here yet.")
        else:
            self._pool.submit(self._intake, record, dict(body))
        return self.view(user, record["id"])

    def _fail(self, record: Dict[str, Any], code: str, message: str, source: str = "backend") -> None:
        record.update(state="failed", finished=time.monotonic(),
                      error={"code": code, "message": message, "source": source, "retryable": False})

    def _intake(self, record: Dict[str, Any], body: Dict[str, Any]) -> None:
        world, user = record["world"], record["user"]
        record["state"] = "running"
        try:
            with self.registry.using(world), acting_as(user):
                message_id = deliver_case_mail(world, body)
                run = self.workflow.intake(AppContext(self.app), user, provider="gmail",
                                           item_id=message_id, trigger="evaluation")
            record["deskRunId"] = run["runId"]
            record["state"] = "open"
        except EvalError as exc:
            self._fail(record, exc.code, exc.message)
        except Exception as exc:
            logger.exception("desk evaluation run could not be started")
            self._fail(record, "run_failed", f"The run could not be started: {type(exc).__name__}.")

    # ── reading ─────────────────────────────────────────────────────────────
    def _own(self, user: Any, run_id: str) -> Dict[str, Any]:
        record = self.runs.get(str(run_id))
        if record is None or record["user"].id != user.id:
            raise EvalError(404, "not_found", "Run not found.")
        return record

    def _desk_view(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if record["deskRunId"] is None:
            return None
        with self.registry.using(record["world"]), acting_as(record["user"]):
            return self.workflow.view(AppContext(self.app), record["user"], record["deskRunId"])

    def view(self, user: Any, run_id: str) -> Dict[str, Any]:
        record = self._own(user, run_id)
        return agent_run(record, self._desk_view(record))

    def approvals(self, user: Any, run_id: Optional[str], statuses: Optional[List[str]]) -> List[Dict[str, Any]]:
        records = [self._own(user, run_id)] if run_id else [
            r for r in self.runs.values() if r["user"].id == user.id]
        found: List[Dict[str, Any]] = []
        for record in records:
            view = self._desk_view(record)
            if view is not None:
                found.extend(approvals_of(record, view))
        if statuses:
            found = [a for a in found if a["status"] in statuses]
        return sorted(found, key=lambda a: a["createdAt"], reverse=True)

    # ── a decision by the harness, which plays the person ───────────────────
    def decide(self, user: Any, approval_id: str, body: Mapping[str, Any]) -> Dict[str, Any]:
        decision = str(body.get("decision") or "")
        if decision not in ("approve", "reject"):
            raise EvalError(400, "invalid_request", "decision must be approve or reject.")
        for record in [r for r in self.runs.values() if r["user"].id == user.id]:
            view = self._desk_view(record)
            if view is None:
                continue
            current = next((a for a in approvals_of(record, view) if a["id"] == approval_id), None)
            if current is None:
                continue
            wanted = "approved" if decision == "approve" else "rejected"
            if current["status"] == wanted:
                return current                      # repeating a decision changes nothing
            if current["status"] != "pending":
                raise EvalError(409, "already_decided", f"This approval was already {current['status']}.")
            card_id = int(approval_id.rsplit("-", 1)[1])
            record["decisions"][approval_id] = {
                "decision": decision, "by": str(body.get("decidedBy") or user.email),
                "note": body.get("note"), "at": record["world"].now().isoformat()}
            with self.registry.using(record["world"]), acting_as(user):
                try:
                    if decision == "approve":
                        self.gateway.approve_card(user, card_id, idempotency_key=f"eval:{approval_id}")
                    else:
                        self.gateway.cancel_card(user, card_id)
                except ValueError as exc:
                    raise EvalError(409, "already_decided", str(exc))
            fresh = self._desk_view(record)
            return next(a for a in approvals_of(record, fresh) if a["id"] == approval_id)
        raise EvalError(404, "not_found", "Approval not found.")


# ── translation: a Desk run in the contract's vocabulary ────────────────────

def _classification(view: Mapping[str, Any]) -> str:
    category = view.get("category")
    intent = next((i["data"].get("meetingIntent") for i in view.get("timeline") or []
                   if i.get("kind") == "stage" and i["data"].get("stage") == "CLASSIFIED"), None)
    if any(f.get("external") and f.get("state") == "satisfied" for f in view.get("followUps") or []):
        return "follow_up"
    if category == "meeting_request":
        return {"reschedule": "reschedule", "cancel": "cancellation"}.get(str(intent), "new_meeting")
    return {"needs_reply": "reply_needed", "action_item": "action_required", "informational": "fyi",
            "automated": "not_meeting_related"}.get(str(category), "unclear")


def _card_input(action: Mapping[str, Any], world: SandboxWorld) -> Dict[str, Any]:
    """The contract's canonical input for a card."""
    data = action.get("input") or {}
    tool = TOOL_OF_CARD[action["tool_name"]]
    zone = str(data.get("timezone") or world.timezone)
    fallback = world.now().isoformat()
    if tool == "email.send":
        from .safeguards import addresses_in

        return {"to": addresses_in(data.get("to")), "cc": addresses_in(data.get("cc")),
                "subject": str(data.get("subject") or ""),
                "bodyText": str(data.get("body") or data.get("text") or ""),
                "threadId": data.get("thread_id"),
                "proposedSlots": [{"start": _stamp(s.get("start"), fallback), "end": _stamp(s.get("end"), fallback)}
                                  for s in (action.get("proposedSlots") or [])]}
    if tool == "calendar.create_event":
        from .safeguards import addresses_in

        return {"title": str(data.get("title") or data.get("summary") or ""),
                "start": _stamp(data.get("start"), fallback), "end": _stamp(data.get("end"), fallback),
                "timezone": zone, "attendees": addresses_in(data.get("attendees")),
                "location": data.get("location"), "description": data.get("description")}
    if tool in ("calendar.update_event", "calendar.cancel_event"):
        event_id = str(data.get("event_id") or "")
        if tool == "calendar.cancel_event":
            return {"eventId": event_id, "notifyAttendees": True}
        planned = data.get("planned_change") if isinstance(data.get("planned_change"), Mapping) else {}
        current = world.events.get(event_id) or {}
        return {"eventId": event_id,
                "title": planned.get("summary") or current.get("title") or data.get("event_title") or "",
                "start": _stamp(planned.get("start") or data.get("start"), fallback),
                "end": _stamp(planned.get("end") or data.get("end"), fallback),
                "timezone": zone, "attendees": list(current.get("attendees") or []),
                "location": current.get("location")}
    if tool == "task.create":
        return {"title": str(data.get("title") or ""),
                "dueAt": _stamp(data.get("due_at"), fallback) if data.get("due_at") else None,
                "sourceEmailId": None}
    return {"text": str(data.get("title") or ""),
            "remindAt": _stamp(data.get("remind_at"), fallback) if data.get("remind_at") else None}


def _action_status(action: Mapping[str, Any]) -> str:
    status = str(action.get("status") or "")
    if status == "awaiting_approval":
        return "awaiting_approval"
    if status in ("approved", "executing"):
        return "running"
    if status in ("executed", "partially_executed"):
        return "succeeded"
    if status == "failed":
        return "failed"
    if status == "cancelled":
        return "rejected"
    return "skipped"                # held (needs_info) or unsupported: it will not run as it is


def _error(action: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if action.get("status") != "failed":
        return None
    code = str(action.get("errorCode") or action.get("error") or "tool_failed")
    return {"code": code, "message": str(action.get("message") or "The action did not complete."),
            "source": "tool", "retryable": code not in ("outcome_unknown",)}


def _event_draft(event: Mapping[str, Any], zone: str, fallback: str) -> Dict[str, Any]:
    return {"id": str(event.get("id") or ""), "title": str(event.get("title") or ""),
            "start": _stamp(event.get("start"), fallback), "end": _stamp(event.get("end"), fallback),
            "timezone": zone, "attendees": [_person(a) for a in event.get("attendees") or []],
            "location": event.get("location"), "description": event.get("description") or None,
            "status": "cancelled" if event.get("status") == "cancelled" else "confirmed"}


def approvals_of(record: Mapping[str, Any], view: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One approval per mail or calendar card. Held cards are not offered:
    they cannot be approved as they stand."""
    world, found = record["world"], []
    fallback = world.now().isoformat()
    for action in view.get("actions") or []:
        tool = TOOL_OF_CARD.get(action["tool_name"])
        if tool not in SIDE_EFFECT_TOOLS or action["status"] in ("needs_info", "unsupported", "pending", "draft"):
            continue
        approval_id = f"apr-{action['toolCallId']}"
        canonical = _card_input(action, world)
        zone = str(canonical.get("timezone") or world.timezone)
        if tool == "email.send":
            change: Dict[str, Any] = {"type": "email", "tool": tool, **canonical}
            title = f"Send \"{canonical['subject']}\" to {', '.join(canonical['to'])}"
        elif tool == "calendar.create_event":
            draft = {**canonical, "attendees": [_person(a) for a in canonical["attendees"]]}
            change = {"type": "calendar_create", "tool": tool, "event": draft}
            title = f"Book \"{canonical['title']}\""
        else:
            event = world.events.get(canonical["eventId"]) or {}
            operation = (action.get("output") or {}).get("operation") or {}
            before = operation.get("before") or {}
            original = _event_draft({**event, "title": before.get("title") or event.get("title"),
                                     "start": before.get("start") or event.get("start"),
                                     "end": before.get("end") or event.get("end"),
                                     "status": "confirmed"}, zone, fallback)
            if tool == "calendar.update_event":
                after = {key: original[key] for key in ("title", "timezone", "attendees", "location", "description")}
                after.update(title=canonical["title"] or original["title"], start=canonical["start"],
                             end=canonical["end"])
                change = {"type": "calendar_update", "tool": tool, "eventId": canonical["eventId"],
                          "before": original, "after": after}
                title = f"Move \"{original['title']}\""
            else:
                change = {"type": "calendar_cancel", "tool": tool, "eventId": canonical["eventId"],
                          "event": original, "notifyAttendees": True}
                title = f"Cancel \"{original['title']}\""
        status = {"awaiting_approval": "pending", "cancelled": "rejected"}.get(action["status"], "approved")
        decision = (record.get("decisions") or {}).get(approval_id) or {}
        execution = action.get("execution") or {}
        exec_status = {"executed": "executed", "partially_executed": "executed", "failed": "failed",
                       "approved": "executing", "executing": "executing"}.get(action["status"], "not_started")
        found.append({
            "id": approval_id, "runId": record["id"], "requestId": None, "conversationId": None,
            "title": title, "explanation": str(action.get("reason") or "Proposed by the Desk."),
            "riskNotes": [], "changes": [change], "status": status,
            "createdAt": _stamp(action.get("proposedAt"), fallback), "expiresAt": None,
            "decidedAt": _stamp(decision.get("at"), fallback) if status != "pending" else None,
            "decidedBy": decision.get("by") if status != "pending" else None,
            "decisionNote": decision.get("note") if status != "pending" else None,
            "execution": {"status": exec_status,
                          "finishedAt": _stamp(execution.get("at"), fallback)
                          if exec_status in ("executed", "failed") else None,
                          "error": _error(action), "simulated": True},
        })
    return found


def _outcome(view: Mapping[str, Any]) -> str:
    """What the run achieved, from what actually executed."""
    done = [a for a in view.get("actions") or [] if a.get("status") in ("executed", "partially_executed")]
    names = {a["tool_name"] for a in done}
    if "create_calendar_event" in names:
        return "scheduled"
    if "update_calendar_event" in names:
        return "rescheduled"
    if "cancel_calendar_event" in names:
        return "cancelled_meeting"
    sent = [a for a in done if a["tool_name"] == "send_email"]
    if sent:
        purpose = sent[-1].get("purpose")
        return {"offer_times": "alternatives_proposed", "clarify": "clarification_requested",
                "nudge": "follow_up_sent"}.get(str(purpose), "replied")
    if names & {"create_task", "create_reminder"}:
        return "task_recorded"
    actions = view.get("actions") or []
    if actions and all(a.get("status") == "cancelled" for a in actions):
        return "declined"
    stage = (view.get("lifecycle") or {}).get("stage")
    if actions or stage in ("ESCALATED", "NEEDS_CLARIFICATION", "VERIFYING", "FAILED"):
        return "escalated"
    return "no_action"


def agent_run(record: Mapping[str, Any], view: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    world = record["world"]
    fallback = world.now().isoformat()
    base: Dict[str, Any] = {
        "id": record["id"], "trigger": "evaluation", "requestId": None, "conversationId": None,
        "status": "queued" if record["state"] == "queued" else "running", "outcome": None, "triage": None,
        "summary": None, "assistantMessage": None, "actions": [], "approvalIds": [],
        "startedAt": record["startedAt"], "finishedAt": None, "durationMs": None, "usage": None,
        "error": None, "humanInterventions": [],
        # Not part of the contract; clients ignore fields they do not know.
        "sandbox": {"world": world.id, "isolationViolations": len(world.violations),
                    "operations": len(world.oplog)},
    }
    if record["state"] == "failed":
        base.update(status="failed", error=record["error"], finishedAt=fallback,
                    durationMs=int(((record["finished"] or time.monotonic()) - record["started"]) * 1000),
                    summary=record["error"]["message"])
        return base
    if view is None:
        return base

    timeline = view.get("timeline") or []
    order = {id(item): index for index, item in enumerate(timeline)}
    actions: List[Dict[str, Any]] = []
    for item in timeline:
        data = item.get("data") or {}
        if item.get("kind") == "read" and data.get("tool") in TOOL_OF_READ:
            tool = TOOL_OF_READ[data["tool"]]
            entry_input = {key: data[key] for key in ("threadId", "timeMin", "timeMax", "durationMinutes")
                           if data.get(key) is not None}
            actions.append({
                "_order": order[id(item)], "tool": tool, "sideEffect": False,
                "status": "succeeded" if data.get("ok", True) else "failed",
                "summary": lifecycle.summary_of(item), "input": entry_input,
                "output": {key: data[key] for key in ("count", "provider", "account") if data.get(key) is not None},
                "startedAt": _stamp(item.get("at"), fallback), "finishedAt": _stamp(item.get("at"), fallback),
                "durationMs": None, "approvalId": None, "idempotencyKey": None,
                "error": None if data.get("ok", True) else {
                    "code": str(data.get("error") or "read_failed"), "message": "The read did not complete.",
                    "source": "tool", "retryable": True},
            })
        elif item.get("kind") == "followup" and data.get("external") and data.get("state") == "satisfied":
            actions.append({
                "_order": order[id(item)], "tool": "followup.close", "sideEffect": False,
                "status": "succeeded", "summary": "Closed the follow-up: the awaited answer arrived.",
                "input": {"followUpId": data.get("id")}, "output": {"satisfiedBy": data.get("satisfiedBy")},
                "startedAt": _stamp(item.get("at"), fallback), "finishedAt": _stamp(item.get("at"), fallback),
                "durationMs": None, "approvalId": None, "idempotencyKey": f"followup:{data.get('id')}",
                "error": None,
            })
    position = {(i.get("data") or {}).get("toolCallId"): order[id(i)] for i in timeline
                if i.get("kind") == "execution"}
    waiting_base = len(timeline) + 1
    for index, action in enumerate(view.get("actions") or []):
        tool = TOOL_OF_CARD.get(action["tool_name"])
        if tool is None:
            continue
        status = _action_status(action)
        execution = action.get("execution") or {}
        ran = status in ("succeeded", "failed")
        output = None
        if ran:
            verification = action.get("verification") or {}
            output = {"verified": bool(action.get("verified")), "verification": verification.get("method"),
                      "outcomeUnknown": bool(action.get("outcomeUnknown"))}
            event_id = ((action.get("output") or {}).get("calendar_event_id")
                        or (((action.get("output") or {}).get("result") or {}).get("event") or {}).get("id"))
            if event_id:
                output["eventId"] = str(event_id)
        actions.append({
            "_order": position.get(action["toolCallId"], waiting_base + index) if ran else waiting_base + index,
            "tool": tool, "sideEffect": tool in SIDE_EFFECT_TOOLS, "status": status,
            "summary": str(action.get("reason") or f"{tool}"), "input": _card_input(action, world),
            "output": output,
            "startedAt": _stamp(execution.get("at"), fallback) if ran else None,
            "finishedAt": _stamp(execution.get("at"), fallback) if ran else None,
            "durationMs": execution.get("durationMs") if ran else None,
            "approvalId": f"apr-{action['toolCallId']}" if tool in SIDE_EFFECT_TOOLS else None,
            "idempotencyKey": action.get("idempotencyKey"), "error": _error(action),
        })
    actions.sort(key=lambda entry: entry.pop("_order"))
    for sequence, entry in enumerate(actions, start=1):
        entry.update(id=f"{record['id']}-a{sequence}", runId=record["id"], sequence=sequence, simulated=True)

    stage = (view.get("lifecycle") or {}).get("stage")
    status = {"AWAITING_APPROVAL": "awaiting_approval", "EXECUTING": "running", "FAILED": "failed"}.get(
        str(stage), "completed")
    if stage == "VERIFYING" and not (view.get("lifecycle") or {}).get("outcomeUnknown"):
        status = "running"
    # A card that is held cannot be decided by the harness: the run rests there.
    pending = approvals_of(record, view)
    if status == "awaiting_approval" and not any(a["status"] == "pending" for a in pending):
        status = "completed"
    final = status in ("completed", "failed", "cancelled")
    held = view.get("held") or {}
    flags = [flag for flag in view.get("flags") or [] if flag in ALLOWED_FLAGS]
    target = held.get("target") or next((a.get("input", {}).get("event_id") and
                                         {"id": a["input"]["event_id"]} for a in view.get("actions") or []
                                         if a["tool_name"] in ("update_calendar_event", "cancel_calendar_event")), None)
    requested = held.get("requested") or next((
        {"start": a["input"].get("start"), "end": a["input"].get("end")} for a in view.get("actions") or []
        if a["tool_name"] in ("create_calendar_event", "update_calendar_event")), None)
    windows = [{"start": _stamp(requested.get("start"), fallback), "end": _stamp(requested.get("end"), fallback)}] \
        if requested and requested.get("start") and requested.get("end") else []
    failed = next((entry["error"] for entry in actions if entry["error"]), None)
    interventions = [{"at": _stamp(d.get("at"), fallback), "kind": "approval", "by": str(d.get("by") or ""),
                      "note": d.get("note")} for d in (record.get("decisions") or {}).values()]
    usage = view.get("usage")
    base.update(
        status=status, outcome=_outcome(view) if final else None,
        triage={"classification": _classification(view),
                "priority": PRIORITY.get(str(next((i["data"].get("priority") for i in timeline
                                                   if i.get("kind") == "stage"
                                                   and i["data"].get("stage") == "CLASSIFIED"), "low")), "normal"),
                "flags": flags,
                "extracted": {"title": None, "attendees": [_person(view["email"].get("from_addr") and
                                                                   _sender(view["email"]["from_addr"]))],
                              "durationMinutes": None, "requestedWindows": windows,
                              "requesterTimezone": None, "location": None, "modality": None,
                              "referencedEventId": str(target.get("id")) if target and target.get("id") else None,
                              "missingFields": ["time"] if held.get("reason") == "time_not_understood" else [],
                              "notes": held.get("message")}},
        summary=next((lifecycle.summary_of(i) for i in reversed(timeline) if i.get("kind") == "decision"), None),
        actions=actions, approvalIds=[a["id"] for a in pending],
        startedAt=_stamp(view.get("createdAt"), record["startedAt"]),
        finishedAt=_stamp(view.get("updatedAt"), fallback) if final else None,
        durationMs=int((time.monotonic() - record["started"]) * 1000) if final else None,
        usage={"models": usage["models"], "estimatedCostUsd": usage["estimatedCostUsd"]} if usage else None,
        error=(failed if status == "failed" else None) or (
            {"code": "run_failed", "message": "The run failed.", "source": "backend", "retryable": False}
            if status == "failed" else None),
        humanInterventions=interventions,
    )
    base["lifecycle"] = view.get("lifecycle")       # the Desk's own stage, for debugging a result
    return base


def _sender(from_addr: Any) -> str:
    from .workflow import sender_address

    return sender_address(str(from_addr or "")) or ""


def build_eval_router(app: Any, desk: Dict[str, Any]) -> APIRouter:
    router = APIRouter(prefix="/desk/eval/v1", tags=["desk-eval"])
    gateway = desk["gateway"]
    runs = EvalRuns(app, desk)
    desk["eval"] = runs
    headers = {CONTRACT_HEADER: CONTRACT_VERSION}

    def answer(call: Any, status: int = 200) -> JSONResponse:
        try:
            return JSONResponse(call(), status_code=status, headers=headers)
        except EvalError as exc:
            return JSONResponse({"error": {"code": exc.code, "message": exc.message}},
                                status_code=exc.status, headers=headers)

    @router.get("/meta")
    def meta(request: Request) -> JSONResponse:
        user = gateway.current_user(request)
        gate = desk.get("gate")
        model = bool(gateway.model_configured())
        return answer(lambda: {
            "contractVersion": CONTRACT_VERSION, "service": "scriba-desk-overlay",
            # "real" only when a model takes part in planning. Without one the
            # Desk still runs, on rules alone, and its results are not the product's.
            "agent": "real" if model else "scripted",
            "sandbox": True,
            "principal": {"name": user.email.split("@")[0], "email": user.email, "timezone": "UTC"},
            "simulatedNow": None,
            "capabilities": {"evaluation": True, "faultInjection": True, "chat": False,
                             "tokenUsage": True, "idempotentPosts": False},
            # Beyond the contract: how this sandbox is built and what it has seen.
            "desk": {
                "planner": "rules+model" if model else "rules",
                "model": {"configured": model},
                "internalWrites": "automatic",
                "conversationInput": "unsupported",
                "isolation": {"tripwire": bool(gate is not None and gate.installed),
                              "violations": int((gate.stats if gate else {}).get("isolationViolations", 0)),
                              "sandboxExecutions": int((gate.stats if gate else {}).get("sandboxExecutions", 0))},
            },
        })

    @router.post("/evaluation/runs")
    async def start(request: Request) -> JSONResponse:
        user = gateway.current_user(request)
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"error": {"code": "invalid_request", "message": "The body must be a JSON object."}},
                                status_code=400, headers=headers)
        return answer(lambda: runs.start(user, body), status=202)

    @router.get("/runs/{run_id}")
    def run(request: Request, run_id: str) -> JSONResponse:
        user = gateway.current_user(request)
        return answer(lambda: runs.view(user, run_id))

    @router.get("/approvals")
    def approvals(request: Request, runId: Optional[str] = None,
                  status: Optional[str] = Query(default=None)) -> JSONResponse:
        user = gateway.current_user(request)
        wanted = [part for part in str(status or "").split(",") if part] or None
        return answer(lambda: runs.approvals(user, runId, wanted))

    @router.post("/approvals/{approval_id}/decision")
    async def decide(request: Request, approval_id: str) -> JSONResponse:
        user = gateway.current_user(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        return answer(lambda: runs.decide(user, approval_id, body if isinstance(body, dict) else {}))

    return router
