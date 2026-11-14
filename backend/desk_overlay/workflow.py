"""The Desk workflow for one incoming email.

    incoming email -> classify -> gather thread and calendar context -> plan
        -> propose actions -> wait for approval -> execute -> verify
        -> follow up -> record

The Desk owns everything up to the proposal, and the follow-up. Approval,
execution and the action record are Scriba's: every proposal is a Scriba chat
action card, created through Scriba's own validation gate and approved
through Scriba's existing ``/chat/tool-calls/{id}/approve`` route, which
claims the card atomically and runs it through Scriba's execution engine. A
run is a Scriba chat conversation; its evidence is an append-only list of
events on that conversation (``lifecycle.py``).

Nothing here sends mail or writes a calendar. What is proposed:

- Actionable email: a task card, with the deadline when one is written out.
- New meeting request at a time verified free: a calendar-event card. The
  confirmation reply is proposed only AFTER the event has executed.
- A time that is busy, or that could not be read from the message: a reply
  card offering times verified free on every calendar.
- Reschedule: the original event is found among the SENDER's meetings; a
  card that moves THAT event (never a second event) is proposed when the new
  time is verified free.
- Cancellation: the same search; a cancellation card for that event.
- Anything the Desk cannot verify is held and handed to the person.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import threading
from typing import Any, Dict, List, Optional

from . import lifecycle, planning
from .availability import InvalidAvailabilityRequest, parse_instant, resolve_zone
from .claims import LEASE_SECONDS, MemoryClaims, claim_key
from .service import DeskService, NotFound

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# An action that took full effect; one that took effect only in part.
_DONE = ("executed",)
_PARTIAL = ("partially_executed",)
_EFFECT = _DONE + _PARTIAL
_OPEN = ("pending", "needs_info", "draft", "awaiting_approval", "approved", "executing")
# Messages a sweep opens a run for. Informational and automated mail is left alone.
SWEEP_CATEGORIES = ("meeting_request", "action_item", "needs_reply")
SWEEP_MAX_NEW = 5
TRIGGERS = ("manual", "sweep", "worker", "evaluation")
# How long the Desk waits for an answer before it proposes a reminder.
FOLLOW_UP_DAYS = 2
EVENT_SEARCH_DAYS = 45
REPLY_PURPOSES_AWAITING = ("offer_times", "clarify", "nudge")


class IntakeBusy(RuntimeError):
    """Another worker holds the claim for this message right now."""


def sender_address(from_addr: str) -> Optional[str]:
    """The address in a From header. The only attendee the Desk adds on its own."""
    match = _EMAIL_RE.search(str(from_addr or ""))
    return match.group(0).lower() if match else None


def run_key(user_id: int, provider: str, account: Optional[str], item_id: str,
            namespace: str = "") -> str:
    """Identity of one inbound message for one user: the same message is one run.

    User, provider, receiving account and provider message id: a provider id
    is unique only inside one mailbox. ``namespace`` keeps one evaluation
    case's synthetic messages apart from another's.
    """
    raw = f"{int(user_id)}|{provider}|{(account or '').strip().lower()}|{item_id}"
    if namespace:
        raw = f"{namespace}|{raw}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class DeskWorkflow:
    def __init__(self, service: DeskService, gateway: Any, claims: Any = None,
                 agent: Any = None) -> None:
        self.service = service
        self.gateway = gateway
        self.claims = claims or MemoryClaims()
        # An optional model-driven planner (``agent.DeskAgent``). It may refine
        # a plan; every proposal it makes passes the same checks as below.
        self.agent = agent
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _namespace(self, user: Any) -> str:
        namespace = getattr(self.gateway, "key_namespace", None)
        return namespace(user) if callable(namespace) else ""

    def _world_id(self, user: Any) -> Optional[str]:
        world_for = getattr(self.gateway, "world_for", None)
        world = world_for(user) if callable(world_for) else None
        return world.id if world is not None else None

    def _is_evaluation(self, user: Any) -> bool:
        world_for = getattr(self.gateway, "world_for", None)
        world = world_for(user) if callable(world_for) else None
        return bool(world is not None and world.evaluation)

    def _record(self, user: Any, run: Dict[str, Any], kind: str, data: Dict[str, Any]) -> None:
        lifecycle.record(self.gateway, user, run, kind, data, at=self.service.now(user).isoformat())

    # ── intake ──────────────────────────────────────────────────────────────
    def intake(self, ctx: Any, user: Any, *, provider: str, item_id: str,
               mailbox: Optional[str] = None, trigger: str = "manual") -> Dict[str, Any]:
        detail = self.service.inbox_item(ctx, user, provider=provider, item_id=item_id, mailbox=mailbox)
        item = detail["item"]
        key = run_key(user.id, provider, item.get("provider_account_id"), item_id, self._namespace(user))

        # The process lock keeps two threads of this process apart cheaply. The
        # claim is what holds across processes and restarts.
        with self._lock(key):
            claim = self._claim(user, key)
            if claim.state == "done":
                existing = (self.gateway.get_run(user, claim.run_id) if claim.run_id else None) \
                    or self.gateway.find_run(user, key)
                if existing is not None:
                    return self.view(ctx, user, existing["id"], duplicate=True)
                # The ledger says a run exists and Scriba has none (it was
                # deleted). Take the message again rather than lose it.
                self.claims.release(user.id, claim_key(key), claim.token)
                claim = self._claim(user, key)
            if not claim.claimed:
                raise IntakeBusy("This message is being taken in by another worker.")
            try:
                existing = self.gateway.find_run(user, key)
                if existing is not None:      # opened before claims existed, or by a peer
                    self.claims.settle(user.id, claim_key(key), claim.token, existing["id"])
                    return self.view(ctx, user, existing["id"], duplicate=True)
                run = self._open(ctx, user, provider, item, detail, key, trigger)
            except Exception:
                self.claims.release(user.id, claim_key(key), claim.token)
                raise
            self.claims.settle(user.id, claim_key(key), claim.token, run["id"])
        return self.view(ctx, user, run["id"])

    def _claim(self, user: Any, key: str) -> Any:
        claim = self.claims.claim(user.id, claim_key(key))
        if claim.state == "in_flight" and (claim.age_seconds or 0) > LEASE_SECONDS \
                and self.gateway.find_run(user, key) is None:
            # Its holder died before opening a run. Nothing outside Scriba has
            # happened, so the claim can be taken over.
            self.claims.release(user.id, claim_key(key), claim.token)
            claim = self.claims.claim(user.id, claim_key(key))
        return claim

    def _open(self, ctx: Any, user: Any, provider: str, item: Dict[str, Any],
              detail: Dict[str, Any], key: str, trigger: str) -> Dict[str, Any]:
        triage = item["triage"]
        now = self.service.now(user).isoformat()
        meta: Dict[str, Any] = {
            "key": key,
            "provider": provider,
            "email_id": item.get("id"),
            "thread_id": item.get("threadId"),
            "provider_account_id": item.get("provider_account_id"),
            "from_addr": item.get("from_addr"),
            "subject": item.get("subject"),
            "received_at": item.get("timestamp"),
            "category": triage["category"],
            "outcome": triage["outcome"],
            "created_at": now,
            "trigger": trigger if trigger in TRIGGERS else "manual",
            "sandbox": self._world_id(user),
            "evaluation": self._is_evaluation(user),
            "held": None,
            "draft_request": detail.get("draftRequest"),
        }
        plan = self._plan(ctx, user, item, detail)
        meta["held"] = plan["held"]
        if plan.get("flags"):
            meta["flags"] = plan["flags"]
        run = self.gateway.open_run(
            user, title=f"Desk: {str(item.get('subject') or 'incoming email')[:80]}", meta=meta,
            summary=_summary(meta, plan["proposals"]))

        self._record(user, run, "stage", {
            "stage": "RECEIVED", "trigger": meta["trigger"], "provider": provider,
            "account": meta["provider_account_id"], "messageId": meta["email_id"],
            "threadId": meta["thread_id"], "receivedAt": meta["received_at"]})
        self._record(user, run, "stage", {
            "stage": "CLASSIFIED", "category": triage["category"], "outcome": triage["outcome"],
            "priority": triage.get("priority"), "reasons": triage.get("reasons") or [],
            "meetingIntent": triage.get("meeting_intent"), "flags": plan.get("flags") or []})
        self._record(user, run, "stage", {"stage": "CONTEXT_GATHERING",
                                          "threadMessages": (detail.get("thread") or {}).get("count")})
        for read in plan["reads"]:
            self._record(user, run, "read", read)
        self._record(user, run, "stage", {"stage": "PLANNING", "planner": plan["planner"]})
        for usage in plan.get("usage") or []:
            self._record(user, run, "usage", usage)
        for decision in plan["decisions"]:
            self._record(user, run, "decision", decision)
        for proposal in plan["proposals"]:
            self._propose(user, run, proposal)
        return run

    def _propose(self, user: Any, run: Dict[str, Any], proposal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        meta = run["meta"]
        card = self.gateway.propose_action(
            user, run, tool_name=proposal["tool_name"], tool_input=proposal["tool_input"],
            email_id=meta.get("email_id"), thread_id=meta.get("thread_id"), provider=meta.get("provider"))
        self._record(user, run, "proposal", {
            "toolCallId": (card or {}).get("id"), "tool": proposal["tool_name"],
            "purpose": proposal.get("purpose"), "reason": proposal.get("reason"),
            "proposedSlots": proposal.get("proposedSlots"),
            "status": (card or {}).get("status")})
        return card

    # ── planning ────────────────────────────────────────────────────────────
    def _plan(self, ctx: Any, user: Any, item: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
        """What to propose for this message, and why. Reads only."""
        triage = item["triage"]
        plan: Dict[str, Any] = {"proposals": [], "held": None, "decisions": [], "reads": [],
                                "usage": [], "flags": [], "planner": "rules"}
        text = str(item.get("body") or item.get("snippet") or "")
        calendar = detail.get("calendar")
        if calendar is not None:
            for entry in calendar.get("calendars") or []:
                plan["reads"].append({"tool": "calendar.find_free_slots", "provider": entry.get("provider"),
                                      "account": entry.get("account"), "ok": bool(entry.get("ok")),
                                      "error": entry.get("error")})

        if planning.injection_suspected(item.get("subject"), text):
            # Mail is data. Text that addresses the assistant is not obeyed,
            # and nothing is proposed on the strength of a message carrying it.
            plan["flags"].append("prompt_injection_suspected")
            plan["held"] = {
                "reason": "untrusted_instructions", "slots": [], "calendars": [],
                "message": "This message contains text written as instructions to an assistant. "
                           "Nothing is proposed automatically. Read it yourself before acting."}
            plan["decisions"].append({"decision": "escalate", "reason": "untrusted_instructions",
                                      "explanation": "The message tries to instruct the assistant, "
                                                     "so it was handed to you."})
            return plan

        if triage["category"] == "action_item":
            self._plan_task(ctx, user, item, plan)
        elif triage["category"] == "meeting_request":
            self._plan_meeting(ctx, user, item, calendar, plan)
        elif triage["category"] == "needs_reply":
            plan["decisions"].append({"decision": "escalate", "reason": "reply_needs_author",
                                      "explanation": "This needs a reply in your words. A draft can "
                                                     "be prepared for you to review."})
        else:
            plan["decisions"].append({"decision": "none", "reason": triage["category"],
                                      "explanation": "No action is needed for this message."})

        if self.agent is not None:
            try:
                plan = self.agent.refine(ctx, user, item, detail, plan, workflow=self)
            except Exception as exc:   # the agent failing never loses the rule-based plan
                plan["decisions"].append({"decision": "agent_unavailable", "reason": type(exc).__name__,
                                          "explanation": "The model could not be used; the plan above "
                                                         "is rule-based."})
        return plan

    def _plan_task(self, ctx: Any, user: Any, item: Dict[str, Any], plan: Dict[str, Any]) -> None:
        title = str(item.get("subject") or "Follow up on email").strip()[:160]
        try:
            open_tasks = self.gateway.open_tasks(ctx, user, 100)
            plan["reads"].append({"tool": "task.list", "ok": True, "count": len(open_tasks)})
        except Exception:
            open_tasks = None
            plan["reads"].append({"tool": "task.list", "ok": False, "error": "unavailable"})
        if open_tasks and any(_same_title(task.get("title"), title) for task in open_tasks):
            # A second message about the same thing must not make a second task.
            plan["held"] = {"reason": "task_exists", "slots": [], "calendars": [],
                            "message": "An open task with this title already exists, so no second "
                                       "one is proposed."}
            plan["decisions"].append({"decision": "none", "reason": "task_exists",
                                      "explanation": "You already have this task."})
            return
        task: Dict[str, Any] = {
            "title": title,
            "description": (f"From {item.get('from_addr')}, received {item.get('timestamp')} "
                            f"({item.get('provider')}). {item.get('snippet') or ''}").strip(),
            "priority": item["triage"].get("priority") or "medium",
        }
        due = None
        try:
            zone_name, _, _, _ = self.service.working_context(user, None, None, None)
            due = planning.deadline_from(f"{item.get('subject')}\n{item.get('body') or item.get('snippet') or ''}",
                                         self.service.now(user).astimezone(resolve_zone(zone_name)))
        except InvalidAvailabilityRequest:
            due = None
        if due is not None:
            task["due_at"] = due.isoformat()
        plan["proposals"].append({"tool_name": "create_task", "tool_input": task, "purpose": "record_task",
                                  "reason": "The message names something to do"
                                            + (f", due {due.isoformat()}." if due else
                                               "; no date could be read from it.")})
        plan["decisions"].append({"decision": "propose", "reason": "action_item",
                                  "explanation": "A task is proposed from this message."})

    def _offer(self, user: Any, item: Dict[str, Any], calendar: Optional[Dict[str, Any]],
               reason: str, purpose: str) -> Optional[Dict[str, Any]]:
        """A reply offering times verified free on EVERY calendar, or None
        when there is nothing verified to offer."""
        slots = (calendar or {}).get("slots") or []
        recipient = sender_address(str(item.get("from_addr") or ""))
        if not (calendar or {}).get("complete") or not slots or not recipient:
            return None
        offered = [{"start": slot["start"], "end": slot["end"]} for slot in slots[:3]]
        return {"tool_name": "send_email", "purpose": purpose, "proposedSlots": offered,
                "reason": "Only times verified free on every connected calendar are offered.",
                "tool_input": self._reply_input(item, planning.offer_times_reply(
                    slots=offered, timezone=str(calendar.get("timezone") or ""), reason=reason))}

    @staticmethod
    def _reply_input(item: Dict[str, Any], body: str) -> Dict[str, Any]:
        provider = str(item.get("provider") or "gmail")
        reply: Dict[str, Any] = {
            "provider": provider, "mode": "reply",
            "to": sender_address(str(item.get("from_addr") or "")),
            "subject": planning.reply_subject(str(item.get("subject") or "")),
            "body": body, "thread_id": item.get("threadId") or item.get("thread_id"),
            "provider_account_id": item.get("provider_account_id"),
        }
        # Name the message being answered in the field each provider uses.
        reply["email_id" if provider == "gmail" else "message_id"] = item.get("id") or item.get("email_id")
        return reply

    def _hold(self, plan: Dict[str, Any], user: Any, item: Dict[str, Any],
              calendar: Optional[Dict[str, Any]], reason: str, message: str,
              offer: Optional[str] = None, **extra: Any) -> None:
        plan["held"] = {"reason": reason, "slots": (calendar or {}).get("slots") or [],
                        "calendars": (calendar or {}).get("calendars") or [], "message": message, **extra}
        plan["decisions"].append({"decision": "hold", "reason": reason, "explanation": message})
        if offer:
            reply = self._offer(user, item, calendar, reason if reason != "change_time_busy" else "reschedule",
                                offer)
            if reply:
                plan["proposals"].append(reply)
                plan["decisions"].append({"decision": "propose", "reason": offer,
                                          "explanation": "A reply offering verified free times is proposed."})

    def _plan_meeting(self, ctx: Any, user: Any, item: Dict[str, Any],
                      calendar: Optional[Dict[str, Any]], plan: Dict[str, Any]) -> None:
        intent = (item.get("triage") or {}).get("meeting_intent") or "new"
        try:
            zone_name, _, _, duration = self.service.working_context(user, None, None, None)
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "invalid_preferences",
                       "The time zone in your preferences is not valid.")
            return

        usage_scope = getattr(self.gateway, "model_usage", None)
        if callable(usage_scope):
            with usage_scope() as calls:
                extracted = self.gateway.extract_meeting(user, item, zone_name)
            plan["usage"].extend(calls)
        else:
            extracted = self.gateway.extract_meeting(user, item, zone_name)
        action = str((extracted or {}).get("calendar_action") or "").lower()
        plan["reads"].append({"tool": "model.extract_request", "ok": bool(extracted),
                              "error": None if extracted else "no_usable_answer"})
        # The rule-based intent is the floor. The model may recognise a change
        # the rules missed; it may not turn a change request into a new booking.
        if intent == "new" and action in ("reschedule", "cancel"):
            intent = action
        if intent in ("reschedule", "cancel"):
            self._plan_change(ctx, user, item, calendar, plan, intent, extracted, zone_name)
            return

        start = str((extracted or {}).get("requested_start") or "").strip()
        if not extracted or action not in ("create", "") or not start:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "No specific time could be read from the message, so no event is proposed. "
                       "Offer the free times in a reply.", offer="clarify")
            return
        window = self._window(start, extracted, zone_name, duration)
        if window is None:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "The requested time could not be read.", offer="clarify")
            return
        try:
            check = self.service.slot_check(ctx, user, start=window[0], end=window[1], timezone=zone_name)
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "The requested time could not be read.", offer="clarify")
            return
        for entry in check["calendars"]:
            plan["reads"].append({"tool": "calendar.check_availability", "provider": entry.get("provider"),
                                  "account": entry.get("account"), "ok": bool(entry.get("ok")),
                                  "error": entry.get("error")})
        if check["free"] is not True:
            conflict = check["free"] is False
            self._hold(
                plan, user, item, calendar,
                "calendar_conflict" if conflict else "availability_unknown",
                ("The requested time conflicts with an existing commitment. " if conflict else
                 "A calendar could not be read, so the requested time is not verified. ")
                + "No event is proposed. Offer verified free times in a reply.",
                offer="offer_times" if conflict else None,
                requested=check["slot"], conflicts=check["conflicts"], calendars=check["calendars"])
            return
        # Attendees: the sender, taken from the message's From header. Names or
        # addresses that appear only in the message text are not added.
        sender = sender_address(str(item.get("from_addr") or ""))
        plan["proposals"].append({
            "tool_name": "create_calendar_event", "purpose": "book",
            "reason": "The requested time is free on every connected calendar.",
            "tool_input": {
                "title": str(extracted.get("summary") or item.get("subject") or "Meeting").strip()[:160],
                "start": check["slot"]["start"], "end": check["slot"]["end"], "timezone": zone_name,
                "attendees": [sender] if sender else [],
                "description": f"Requested by {item.get('from_addr')} by email.",
            }})
        plan["decisions"].append({"decision": "propose", "reason": "time_free",
                                  "explanation": "The requested time is free, so the meeting is "
                                                 "proposed for your approval."})

    @staticmethod
    def _window(start: str, extracted: Dict[str, Any], zone_name: str, duration: int) -> Optional[tuple]:
        end = str(extracted.get("requested_end") or "").strip()
        if end:
            return start, end
        try:
            minutes = int(extracted.get("duration_minutes") or duration)
            return start, (parse_instant(start, resolve_zone(zone_name))
                           + dt.timedelta(minutes=max(15, min(minutes, 480)))).isoformat()
        except (InvalidAvailabilityRequest, TypeError, ValueError):
            return None

    def _plan_change(self, ctx: Any, user: Any, item: Dict[str, Any], calendar: Optional[Dict[str, Any]],
                     plan: Dict[str, Any], intent: str, extracted: Optional[Dict[str, Any]],
                     zone_name: str) -> None:
        """Move or cancel the ORIGINAL event. Never a second event."""
        sender = sender_address(str(item.get("from_addr") or ""))
        now = self.service.now(user)
        try:
            events = self.gateway.calendar_events(user, now - dt.timedelta(days=1),
                                                  now + dt.timedelta(days=EVENT_SEARCH_DAYS))
            plan["reads"].append({"tool": "calendar.list_events", "ok": True, "count": len(events)})
        except Exception:
            plan["reads"].append({"tool": "calendar.list_events", "ok": False, "error": "unavailable"})
            self._hold(plan, user, item, calendar, "calendar_lookup_failed",
                       "Your calendar could not be searched for this meeting, so nothing is proposed.")
            return
        found = planning.find_target_events(
            events, sender=sender, subject=str(item.get("subject") or ""),
            hint=str((extracted or {}).get("target_event_hint") or ""))
        candidates = [{key: event.get(key) for key in ("id", "title", "start", "end", "provider")}
                      for event in found["candidates"][:5]]
        if found["status"] == "sender_not_on_any_event":
            self._hold(plan, user, item, calendar, "event_not_found",
                       "No meeting with this sender was found in the next weeks, so there is nothing "
                       "to change. Check which meeting they mean.")
            return
        if found["status"] == "ambiguous":
            self._hold(plan, user, item, calendar, "event_ambiguous",
                       "Several meetings with this sender match. Choose which one they mean.",
                       candidates=candidates)
            return
        event = found["event"]
        target = {key: event.get(key) for key in ("id", "title", "start", "end", "provider",
                                                  "provider_account_id")}
        if not event.get("is_organizer"):
            self._hold(plan, user, item, calendar, "not_organizer",
                       "You are not the organizer of this meeting, so it cannot be changed from "
                       "your calendar. Reply to the organizer instead.", target=target)
            return
        base = {"event_id": event.get("id"), "calendar_provider": event.get("provider"),
                "timezone": zone_name}
        if event.get("provider") == "google" and event.get("provider_account_id"):
            base["provider_account_id"] = event.get("provider_account_id")

        if intent == "cancel":
            plan["proposals"].append({
                "tool_name": "cancel_calendar_event", "purpose": "cancel", "tool_input": base,
                "reason": f"{sender} is on this meeting and asked to cancel it.", "target": target})
            plan["decisions"].append({"decision": "propose", "reason": "cancel_requested",
                                      "explanation": f"Cancelling \"{event.get('title')}\" is proposed "
                                                     "for your approval."})
            return

        start = str((extracted or {}).get("requested_start") or "").strip()
        zone = resolve_zone(zone_name)
        try:
            old_start = parse_instant(str(event.get("start")), zone)
            old_end = parse_instant(str(event.get("end")), zone)
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "calendar_lookup_failed",
                       "The meeting's current time could not be read.", target=target)
            return
        if not start:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "They ask to move this meeting but no new time could be read. Offer free "
                       "times in a reply.", offer="offer_times", target=target)
            return
        try:
            new_start = parse_instant(start, zone)
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "The new time could not be read.", offer="offer_times", target=target)
            return
        requested_end = str((extracted or {}).get("requested_end") or "").strip()
        try:
            new_end = parse_instant(requested_end, zone) if requested_end else new_start + (old_end - old_start)
        except InvalidAvailabilityRequest:
            new_end = new_start + (old_end - old_start)
        try:
            check = self.service.slot_check(ctx, user, start=new_start.isoformat(), end=new_end.isoformat(),
                                            timezone=zone_name, ignore=[(old_start, old_end)])
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "The new time could not be read.", offer="offer_times", target=target)
            return
        for entry in check["calendars"]:
            plan["reads"].append({"tool": "calendar.check_availability", "provider": entry.get("provider"),
                                  "account": entry.get("account"), "ok": bool(entry.get("ok")),
                                  "error": entry.get("error")})
        if check["free"] is not True:
            conflict = check["free"] is False
            self._hold(plan, user, item, calendar,
                       "calendar_conflict" if conflict else "availability_unknown",
                       ("The new time conflicts with an existing commitment. " if conflict else
                        "A calendar could not be read, so the new time is not verified. ")
                       + "The meeting is not moved.",
                       offer="offer_times" if conflict else None, target=target,
                       requested=check["slot"], conflicts=check["conflicts"], calendars=check["calendars"])
            return
        plan["proposals"].append({
            "tool_name": "update_calendar_event", "purpose": "reschedule", "target": target,
            "reason": "The new time is free on every connected calendar. The existing event is moved.",
            "tool_input": {**base, "start": check["slot"]["start"], "end": check["slot"]["end"]}})
        plan["decisions"].append({"decision": "propose", "reason": "new_time_free",
                                  "explanation": f"Moving \"{event.get('title')}\" is proposed for "
                                                 "your approval."})

    # ── sweep ───────────────────────────────────────────────────────────────
    def sweep(self, ctx: Any, user: Any, *, provider: str = "all", limit: int = 25,
              max_new: int = SWEEP_MAX_NEW, mailbox: Optional[str] = None,
              trigger: str = "sweep") -> Dict[str, Any]:
        """Open a run for every recent message that needs one and has none.

        Bounded on purpose: at most ``max_new`` runs are opened per call,
        because each meeting request costs a model call and calendar reads.
        The rest are reported as ``deferred`` and picked up by the next call.
        One message failing does not stop the others. Like ``intake``, this
        proposes actions; it sends no mail and writes no calendar.
        """
        guard = self._lock(f"sweep|{int(user.id)}")
        if not guard.acquire(blocking=False):
            return {"account": user.email, "status": "already_running", "examined": 0,
                    "opened": [], "existing": 0, "skipped": 0, "deferred": [], "failed": [],
                    "sources": [], "complete": False}
        try:
            inbox = self.service.inbox(ctx, user, provider=provider, limit=limit, mailbox=mailbox)
            opened: List[Dict[str, Any]] = []
            deferred: List[Dict[str, Any]] = []
            failed: List[Dict[str, Any]] = []
            existing = skipped = 0
            for item in inbox["items"]:
                ref = {"provider": item.get("provider"), "id": item.get("id"),
                       "subject": item.get("subject"),
                       "category": (item.get("triage") or {}).get("category")}
                if ref["category"] not in SWEEP_CATEGORIES or not ref["id"] or not ref["provider"] \
                        or _not_inbound(item):
                    skipped += 1
                    continue
                key = run_key(user.id, ref["provider"], item.get("provider_account_id"), ref["id"],
                              self._namespace(user))
                if self.gateway.find_run(user, key) is not None:
                    existing += 1
                    continue
                if len(opened) + len(failed) >= max_new:
                    deferred.append(ref)
                    continue
                try:
                    run = self.intake(ctx, user, provider=ref["provider"], item_id=ref["id"],
                                      mailbox=mailbox, trigger=trigger)
                except IntakeBusy:
                    existing += 1             # a peer is opening it right now
                    continue
                except Exception as exc:  # one bad message must not stop the sweep
                    failed.append({**ref, "error": type(exc).__name__})
                    continue
                if run.get("duplicate"):
                    existing += 1
                else:
                    opened.append({**ref, "runId": run.get("runId"), "state": run.get("state")})
            return {"account": user.email, "status": "completed", "examined": len(inbox["items"]),
                    "opened": opened, "existing": existing, "skipped": skipped,
                    "deferred": deferred, "failed": failed,
                    "sources": inbox["sources"],
                    # False when a connected mailbox could not be read: mail may be missing.
                    "complete": bool(inbox["complete"])}
        finally:
            guard.release()

    # ── advancing after approval ────────────────────────────────────────────
    def advance(self, ctx: Any, user: Any, run_id: int) -> Dict[str, Any]:
        """Propose what may only follow an executed step: the confirmation
        reply, once the calendar change exists. Safe to repeat."""
        run = self._run(user, run_id)
        meta = run["meta"]
        with self._lock(meta["key"]):
            cards = self.gateway.run_cards(user, run)
            purposes = self._purposes(user, run)
            has_confirmation = any(c["tool_name"] == "send_email"
                                   and purposes.get(c.get("id")) == "confirm" for c in cards)
            changed = next((c for c in cards if c["tool_name"] in (
                "create_calendar_event", "update_calendar_event", "cancel_calendar_event")
                and c["status"] in _EFFECT), None)
            recipient = sender_address(str(meta.get("from_addr") or ""))
            if changed and not has_confirmation and recipient:
                data, output = changed.get("input") or {}, changed.get("output") or {}
                after = ((output.get("operation") or {}).get("after") or {})
                planned = data.get("planned_change") or {}
                title = str(data.get("title") or data.get("event_title") or after.get("title")
                            or meta.get("subject") or "the meeting")
                if changed["tool_name"] == "cancel_calendar_event":
                    body = planning.cancellation_reply(title=title)
                else:
                    body = planning.confirmation_reply(
                        title=title, timezone=str(data.get("timezone") or ""),
                        start=str(planned.get("start") or data.get("start")),
                        end=str(planned.get("end") or data.get("end")),
                        moved=changed["tool_name"] == "update_calendar_event")
                item = {"provider": meta["provider"], "from_addr": meta.get("from_addr"),
                        "subject": meta.get("subject"), "threadId": meta.get("thread_id"),
                        "provider_account_id": meta.get("provider_account_id"), "id": meta.get("email_id")}
                self._propose(user, run, {
                    "tool_name": "send_email", "purpose": "confirm",
                    "reason": "The calendar change has taken effect, so the sender is told.",
                    "tool_input": self._reply_input(item, body)})
            self._track_follow_ups(ctx, user, run)
        return self.view(ctx, user, run_id)

    def _purposes(self, user: Any, run: Dict[str, Any],
                  events: Optional[List[Dict[str, Any]]] = None) -> Dict[Any, Optional[str]]:
        events = events if events is not None else self.gateway.run_events(user, run)
        return {(e.get("data") or {}).get("toolCallId"): (e.get("data") or {}).get("purpose")
                for e in events if e.get("kind") == "proposal"}

    # ── follow-ups ──────────────────────────────────────────────────────────
    def _track_follow_ups(self, ctx: Any, user: Any, run: Dict[str, Any]) -> None:
        """Open a follow-up for each executed reply that awaits an answer;
        close it when the answer arrives; mark it overdue, and propose a
        reminder for approval, when it does not. Never sends anything."""
        meta = run["meta"]
        events = self.gateway.run_events(user, run)
        cards = self.gateway.run_cards(user, run)
        purposes = self._purposes(user, run, events)
        known = {f["id"]: f for f in lifecycle.follow_ups(events)}
        now = self.service.now(user)

        for card in cards:
            purpose = purposes.get(card.get("id"))
            follow_id = f"fu-{run['id']}-{card.get('id')}"
            if (card["tool_name"] == "send_email" and card["status"] in _DONE
                    and purpose in REPLY_PURPOSES_AWAITING and follow_id not in known):
                data = card.get("input") or {}
                opened = {"id": follow_id, "state": "waiting", "toolCallId": card.get("id"),
                          "threadId": data.get("thread_id") or meta.get("thread_id"),
                          "waitingOn": sender_address(str(data.get("to") or meta.get("from_addr") or "")),
                          "subject": meta.get("subject"), "sentAt": now.isoformat(),
                          "dueAt": (now + dt.timedelta(days=FOLLOW_UP_DAYS)).isoformat()}
                self._record(user, run, "followup", opened)
                known[follow_id] = opened

        waiting = [f for f in known.values() if f.get("state") in ("waiting", "overdue")]
        if not waiting:
            return
        try:
            _, rows = self.service.read_mail(ctx, user, [meta["provider"]], 100, None)
        except Exception:
            return      # unknown is not "no reply": leave the follow-up as it is
        for follow in waiting:
            sent_at = str(follow.get("sentAt") or "")
            answer = next((row for row in rows
                           if str(row.get("threadId") or "") == str(follow.get("threadId") or "")
                           and sender_address(str(row.get("from_addr") or "")) == follow.get("waitingOn")
                           and str(row.get("id")) != str(meta.get("email_id"))
                           and str(row.get("timestamp") or "") > sent_at), None)
            if answer is not None:
                self._record(user, run, "followup", {
                    "id": follow["id"], "state": "satisfied", "satisfiedBy": answer.get("id"),
                    "satisfiedAt": answer.get("timestamp")})
                continue
            due = str(follow.get("dueAt") or "")
            if follow.get("state") == "waiting" and due and now.isoformat() > due:
                self._record(user, run, "followup", {"id": follow["id"], "state": "overdue"})
                item = {"provider": meta["provider"], "from_addr": meta.get("from_addr"),
                        "subject": meta.get("subject"), "threadId": follow.get("threadId"),
                        "provider_account_id": meta.get("provider_account_id"), "id": meta.get("email_id")}
                # A reminder is PROPOSED. Chasing someone is the person's call.
                self._propose(user, run, {
                    "tool_name": "send_email", "purpose": "nudge",
                    "reason": "No answer arrived by the follow-up date.",
                    "tool_input": self._reply_input(item, planning.nudge_reply(
                        subject=str(meta.get("subject") or "")))})

    def close_follow_up(self, ctx: Any, user: Any, run_id: int, follow_id: str) -> Dict[str, Any]:
        run = self._run(user, run_id)
        known = {f["id"]: f for f in lifecycle.follow_ups(self.gateway.run_events(user, run))}
        if follow_id not in known:
            raise NotFound("Follow-up not found.")
        if known[follow_id].get("state") in ("waiting", "overdue"):
            self._record(user, run, "followup", {"id": follow_id, "state": "closed", "by": user.email})
        return self.view(ctx, user, run_id)

    def follow_ups(self, ctx: Any, user: Any, *, refresh: bool = True, limit: int = 50) -> Dict[str, Any]:
        """Every follow-up across the user's runs, newest run first."""
        found: List[Dict[str, Any]] = []
        for run in self.gateway.list_runs(user, limit):
            if refresh:
                try:
                    with self._lock(run["meta"]["key"]):
                        self._track_follow_ups(ctx, user, run)
                except Exception:
                    pass
            for follow in lifecycle.follow_ups(self.gateway.run_events(user, run)):
                found.append({**follow, "runId": run["id"]})
        counts = {state: sum(1 for f in found if f.get("state") == state)
                  for state in ("waiting", "overdue", "satisfied", "closed")}
        return {"account": user.email, "followUps": found, "counts": counts}

    # ── reading a run ───────────────────────────────────────────────────────
    def _run(self, user: Any, run_id: int) -> Dict[str, Any]:
        run = self.gateway.get_run(user, int(run_id))
        if run is None:
            raise NotFound("Run not found.")
        return run

    def view(self, ctx: Any, user: Any, run_id: int, *, duplicate: bool = False,
             detail: bool = True) -> Dict[str, Any]:
        run = self._run(user, run_id)
        meta = run["meta"]
        cards = self.gateway.run_cards(user, run)
        events = self.gateway.run_events(user, run)
        actions = _action_views(cards, events, meta)
        statuses = [action["status"] for action in actions]
        done = [s for s in statuses if s in _DONE]
        partial = [s for s in statuses if s in _PARTIAL]
        failed = [s for s in statuses if s == "failed"]
        waiting = [s for s in statuses if s in _OPEN]

        if not actions:
            state = "no_action_proposed"
        elif waiting:
            state = "awaiting_approval" if any(s in ("awaiting_approval", "needs_info") for s in waiting) \
                else "executing"
        elif partial or (done and failed):
            state = "partial"
        elif failed:
            state = "failed"
        elif done:
            state = "completed"
        else:
            state = "cancelled"

        changed = next((a for a in actions if a["tool_name"] in (
            "create_calendar_event", "update_calendar_event", "cancel_calendar_event")), None)
        has_reply = any(a["tool_name"] == "send_email" for a in actions)
        has_confirmation = any(a["tool_name"] == "send_email" and a["purpose"] == "confirm" for a in actions)
        next_steps: List[str] = []
        if changed and changed["status"] in _EFFECT and not has_confirmation:
            next_steps.append("advance")          # POST /desk/runs/{id}/advance
        if meta.get("draft_request") and not has_reply and not (changed and changed["status"] in _EFFECT):
            next_steps.append("draft_reply")      # POST the draft_request to Scriba
        stage = lifecycle.derive(meta, actions, events, pending_next="advance" in next_steps)
        follow = lifecycle.follow_ups(events)
        counts: Dict[str, int] = {}
        for status in statuses:
            counts[status] = counts.get(status, 0) + 1
        view: Dict[str, Any] = {
            "runId": run["id"],
            "duplicate": duplicate,
            "state": state,
            "lifecycle": stage,
            "trigger": meta.get("trigger") or "manual",
            "simulated": bool(meta.get("sandbox")),
            "email": {key: meta.get(key) for key in (
                "provider", "email_id", "thread_id", "provider_account_id", "from_addr", "subject",
                "received_at")},
            "category": meta.get("category"),
            "outcome": meta.get("outcome"),
            "flags": meta.get("flags") or [],
            "createdAt": meta.get("created_at"),
            "updatedAt": events[-1].get("at") if events else meta.get("created_at"),
            "held": meta.get("held"),
            "draftRequest": meta.get("draft_request"),
            "actionCounts": counts,
            "next": next_steps,
            "followUps": follow,
        }
        if detail:
            view["actions"] = actions
            view["timeline"] = lifecycle.timeline(events)
            view["usage"] = lifecycle.usage_of(events)
        return view

    def list_runs(self, ctx: Any, user: Any, limit: int = 50) -> List[Dict[str, Any]]:
        """The user's runs, newest first, each with where it stands."""
        rows = []
        for run in self.gateway.list_runs(user, limit):
            view = self.view(ctx, user, run["id"], detail=False)
            rows.append({
                "runId": run["id"],
                **{key: run["meta"].get(key) for key in (
                    "provider", "email_id", "subject", "from_addr", "category", "created_at")},
                "state": view["state"], "lifecycle": view["lifecycle"]["stage"],
                "next": view["next"], "trigger": view["trigger"], "simulated": view["simulated"],
                "held": {"reason": (view["held"] or {}).get("reason")} if view["held"] else None,
                "actionCounts": view["actionCounts"], "updatedAt": view["updatedAt"],
                "followUps": [{"id": f.get("id"), "state": f.get("state")} for f in view["followUps"]],
            })
        return rows

    def counts(self, ctx: Any, user: Any, limit: int = 200) -> Dict[str, int]:
        """Runs by lifecycle stage, for the worker status."""
        totals: Dict[str, int] = {}
        for run in self.gateway.list_runs(user, limit):
            stage = self.view(ctx, user, run["id"], detail=False)["lifecycle"]["stage"]
            totals[stage] = totals.get(stage, 0) + 1
        return totals


def _same_title(left: Any, right: Any) -> bool:
    clean = lambda value: re.sub(r"^(?:re|fwd?):\s*", "", " ".join(str(value or "").lower().split()))  # noqa: E731
    return bool(clean(left)) and clean(left) == clean(right)


def _not_inbound(item: Dict[str, Any]) -> bool:
    """Drafts, sent mail, spam and trash are not arrivals. Uses the labels or
    folder a row carries; a row with neither is taken as inbound, because the
    list it came from is already the inbox."""
    if item.get("is_sent") or item.get("is_draft"):
        return True
    labels = {str(label).upper() for label in (item.get("labels") or [])}
    if labels & {"DRAFT", "SPAM", "TRASH", "SENT"}:
        return True
    folder = str(item.get("mail_folder") or "").strip().lower().replace(" ", "")
    return folder in ("sent", "sentitems", "drafts", "junkemail", "deleteditems")


def _summary(meta: Dict[str, Any], proposals: List[Dict[str, Any]]) -> str:
    parts = [f"Incoming {meta['provider']} message from {meta.get('from_addr')}: "
             f"\"{meta.get('subject')}\". Classified as {meta['category']}."]
    if proposals:
        parts.append("Proposed for your approval: "
                     + ", ".join(p["tool_name"] for p in proposals) + ".")
    if meta.get("held"):
        parts.append(str(meta["held"].get("message") or ""))
    elif not proposals:
        parts.append("No action is proposed.")
    return " ".join(part for part in parts if part)


def _action_views(cards: List[Dict[str, Any]], events: List[Dict[str, Any]],
                  meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_card: Dict[Any, Dict[str, Any]] = {}
    for item in events:
        data = item.get("data") or {}
        card_id = data.get("toolCallId")
        if card_id is None:
            continue
        slot = by_card.setdefault(card_id, {})
        if item.get("kind") == "proposal":
            slot["proposal"] = {**data, "at": item.get("at")}
        elif item.get("kind") == "approval":
            slot.setdefault("decisions", []).append({**data, "at": item.get("at")})
        elif item.get("kind") == "execution":
            slot["execution"] = {**data, "at": item.get("at")}
        elif item.get("kind") == "verification":
            slot["verification"] = {**data, "at": item.get("at")}
    return [_action_view(card, by_card.get(card.get("id"), {}), meta) for card in cards]


def _action_view(card: Dict[str, Any], evidence: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """One proposed action. ``verified`` is true only on evidence: a read-back
    of the provider state where one exists, otherwise Scriba's record of the
    executed action. It is never inferred from the status alone."""
    status = str(card.get("status") or "")
    output = card.get("output") or {}
    proposal = evidence.get("proposal") or {}
    verification = evidence.get("verification")
    if verification is not None:
        verified = bool(verification.get("verified")) and status in _DONE
    else:
        verified = bool(status in _DONE and card.get("assistant_action_id"))
    unknown = bool(output.get("outcome_unknown")) and status == "failed"
    return {
        "toolCallId": card.get("id"),
        "tool_name": card.get("tool_name"),
        "status": status,
        "requiresApproval": True,
        "purpose": proposal.get("purpose"),
        "reason": proposal.get("reason"),
        "proposedSlots": proposal.get("proposedSlots"),
        "input": card.get("input") or {},
        "output": output,
        "message": output.get("message"),
        "error": card.get("error"),
        "errorCode": output.get("error_code") or (card.get("error") if status in ("needs_info", "failed") else None),
        "availability": output.get("availability"),
        # One identity per real-world effect: a retry of this card reuses it.
        "idempotencyKey": f"desk:{meta.get('key')}:{card.get('id')}",
        # Scriba links an executed card to the action row its engine recorded.
        "assistantActionId": card.get("assistant_action_id"),
        "verified": verified,
        "verification": verification,
        "outcomeUnknown": unknown,
        "simulated": bool(meta.get("sandbox")),
        "proposedAt": proposal.get("at"),
        "decisions": evidence.get("decisions") or [],
        "execution": evidence.get("execution"),
        "approve": {"method": "POST", "path": f"/chat/tool-calls/{card.get('id')}/approve"}
        if status in ("awaiting_approval", "needs_info") else None,
    }
