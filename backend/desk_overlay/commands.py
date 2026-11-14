"""Work the executive asks for directly, in their own words.

"Remind me tomorrow at 9 to call Peter." "Move my 1:1 with Omar to Wednesday
at 14:00, let him know, and remind me to bring the hiring numbers." "Chase
anything I am still waiting on that is overdue."

An instruction is read into OPERATIONS (by rules, or by one structured model
call when a model is configured and asked for). Each operation is then
planned by the same checked code that plans an email:

- a meeting is found on the calendar, by the words the executive used; two
  candidates are a question, not a choice the Desk makes;
- a new time is checked on every connected calendar; unknown is not free;
- nobody is written to unless a RECORD names them: the attendees of the
  meeting being changed (from the calendar), or the person a follow-up is
  waiting on (from the follow-up). An instruction cannot name a new address;
- every mail and calendar change is a card a person approves; what depends on
  another step (telling the attendees, a reminder tied to the new time) is
  proposed only after that step took effect.

The instruction is the signed-in person's own. It is still only DATA to a
model: the model reports operations with quotes, and proposes nothing itself.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import lifecycle, planning, plans, reading, understanding
from .availability import InvalidAvailabilityRequest, parse_instant, resolve_zone
from .sandbox import parse_time

OPERATIONS = ("reminder", "task", "reschedule", "cancel", "notify", "chase_overdue")
MAX_TEXT = 2000
MAX_OPERATIONS = 6

PROMPT = """You read one instruction that an executive typed to their own secretary desk, and report the operations it asks for. You do not act.

Answer with one JSON object: {"operations": [...]}. At most six, in the order they should happen. Each operation:
  "type": one of reminder, task, reschedule, cancel, notify, chase_overdue
  "evidence": one SHORT EXACT QUOTE copied from the instruction that asks for it. Never paraphrase.
  and, by type:
     reminder: "title" (what to be reminded of, without the time), "remind_at" (ISO 8601 with offset; resolve words like tomorrow against "now" and "timezone"; null when no time is given), "before_meeting" (true when the reminder belongs to the meeting this instruction moves or mentions and no time is given)
     task: "title", "due_at" (ISO 8601 with offset, or null)
     reschedule: "target_hint" (the words that identify the existing meeting), "new_start" (ISO 8601 with offset), "new_end" (or null to keep the length)
     cancel: "target_hint"
     notify: tell the people on the meeting this instruction changes. No fields.
     chase_overdue: send reminders for replies the executive is waiting on that are overdue. No fields.
Rules: never invent a time, a meeting or a person. Never output an email address. If the instruction asks for something that is none of these, leave it out."""

_TIME_WORDS = (r"(?:today|tonight|tomorrow|on\s+\w+day|next\s+\w+|this\s+\w+|"
               r"at\s+\d{1,2}(?:[:.]\d{2})?(?:\s?[ap]\.?m\.?)?|at\s+noon|\w+day)")
_REMIND = re.compile(r"\bremind me\b((?:\s+" + _TIME_WORDS + r")*)\s+(?:to|about|that)\s+(.+?)(?=[.!?]|$)", re.I)
_MOVE = re.compile(r"\b(?:move|reschedule|push|shift|bring)\s+(?:my\s+|the\s+|our\s+)?(.+?)\s+to\s+(.+?)"
                   r"(?=,|\s+and\s+|[.!?]|$)", re.I)
_CANCEL = re.compile(r"\bcancel\s+(?:my\s+|the\s+|our\s+)?(.+?)(?=,|\s+and\s+|[.!?]|$)", re.I)
_NOTIFY = re.compile(r"\b(?:let\s+(?:him|her|them|everyone|[A-Z]\w+)\s+know|tell\s+(?:him|her|them|everyone|[A-Z]\w+)|"
                     r"notify|inform)\b", re.I)
_CHASE = re.compile(r"\b(?:chase|nudge|follow\s+up)\b", re.I)
_WAITING = re.compile(r"\b(?:overdue|waiting|outstanding|late|haven't heard|not heard)\b", re.I)
_BARE_HOUR = re.compile(r"\bat\s+(\d{1,2})(?:[:.](\d{2}))?(?!\s?[ap]\.?m|\d|[:.]\d)", re.I)


# ── reading a time the executive typed ──────────────────────────────────────

def moment_in(text: str, now: dt.datetime) -> Tuple[Optional[dt.datetime], Optional[str]]:
    """(when, assumption). One day (today when none is named) and one time.
    A bare hour is read the way a working day is spoken: 8 to 12 as written,
    1 to 7 as the afternoon, and that reading is reported as an assumption."""
    lowered = " ".join(str(text or "").lower().split())
    days = reading._days(lowered, now.date())
    if len(days) > 1:
        return None, None
    day = days[0] if days else now.date()
    times, _ = reading._times(lowered)
    assumption = None
    if len(times) == 1:
        hour, minute = times[0]
    elif not times:
        bare = _BARE_HOUR.search(lowered)
        if not bare:
            return None, None
        hour, minute = int(bare.group(1)), int(bare.group(2) or 0)
        if 1 <= hour <= 7:
            hour += 12
            assumption = f"\"at {bare.group(1)}\" was read as {hour}:{minute:02d}, in the afternoon."
        elif not 8 <= hour <= 23:
            return None, None
    else:
        return None, None
    when = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=now.tzinfo)
    if not days and when <= now:
        when += dt.timedelta(days=1)
    return when, assumption


def moment_label(value: Any, zone: dt.tzinfo) -> str:
    when = parse_time(value)
    if when is None:
        return str(value or "")
    local = when.astimezone(zone)
    return f"{local.strftime('%A')} {local.day} {local.strftime('%B')} at {local.strftime('%H:%M')}"


# ── operations ──────────────────────────────────────────────────────────────

def parse_rules(text: str, now: dt.datetime) -> List[Dict[str, Any]]:
    operations: List[Dict[str, Any]] = []
    move = _MOVE.search(text)
    if move:
        when, assumption = moment_in(move.group(2), now)
        operations.append({"type": "reschedule", "target_hint": move.group(1).strip(),
                           "new_start": when.isoformat() if when else None, "new_end": None,
                           "evidence": [move.group(0).strip()], "assumption": assumption})
    else:
        cancel = _CANCEL.search(text)
        if cancel:
            operations.append({"type": "cancel", "target_hint": cancel.group(1).strip(),
                               "evidence": [cancel.group(0).strip()]})
    if operations and _NOTIFY.search(text):
        operations.append({"type": "notify", "evidence": [_NOTIFY.search(text).group(0)]})
    for remind in _REMIND.finditer(text):
        when, assumption = moment_in(remind.group(1), now) if remind.group(1).strip() else (None, None)
        title = remind.group(2).strip()
        operations.append({"type": "reminder", "title": title[:1].upper() + title[1:],
                           "remind_at": when.isoformat() if when else None,
                           "before_meeting": when is None and bool(move),
                           "evidence": [remind.group(0).strip()], "assumption": assumption})
    if _CHASE.search(text) and _WAITING.search(text):
        operations.append({"type": "chase_overdue", "evidence": [_CHASE.search(text).group(0)]})
    return operations[:MAX_OPERATIONS]


def validate(answer: Any, text: str) -> List[Dict[str, Any]]:
    """A model's operations, reduced to what the instruction supports."""
    haystack = understanding._norm(text)
    operations: List[Dict[str, Any]] = []
    raw = answer.get("operations") if isinstance(answer, Mapping) else None
    for entry in (raw if isinstance(raw, list) else [])[:MAX_OPERATIONS]:
        if not isinstance(entry, Mapping) or entry.get("type") not in OPERATIONS:
            continue
        evidence = understanding._quoted(entry.get("evidence"), haystack)
        if not evidence:
            continue                      # nothing in the instruction asks for it
        operation: Dict[str, Any] = {"type": entry["type"], "evidence": evidence, "source": "model"}
        for key in ("remind_at", "due_at", "new_start", "new_end"):
            value = entry.get(key)
            moment = parse_time(value) if value and understanding._has_offset(value) else None
            operation[key] = moment.isoformat() if moment else None
        for key in ("title", "target_hint"):
            if isinstance(entry.get(key), str) and entry[key].strip():
                # Words only: an address in a model's field is never used.
                operation[key] = " ".join(entry[key].split())[:160]
        operation["before_meeting"] = bool(entry.get("before_meeting"))
        operations.append(operation)
    return operations


def parse_model(gateway: Any, text: str, now: dt.datetime, timezone: str) -> Optional[List[Dict[str, Any]]]:
    try:
        answer = gateway.model_json([
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": json.dumps({
                "now": now.isoformat(), "timezone": timezone, "weekday": now.strftime("%A"),
                "instruction": text}, ensure_ascii=False)}])
    except Exception:
        return None
    operations = validate(answer, text)
    return operations or None


# ── finding the meeting the executive means ─────────────────────────────────

_EVENT_STOP = frozenset("the a an my our your with and of for on at to meeting call session catch up sync".split())


def _event_words(text: Any) -> set:
    lowered = re.sub(r"\b(?:1[:\-\s]?1|1\s?on\s?1|one[\s-]on[\s-]one)\b", " oneonone ", str(text or "").lower())
    return {word for word in re.findall(r"[a-z0-9]+", lowered) if word not in _EVENT_STOP and len(word) > 1}


def find_event(events: List[Mapping[str, Any]], hint: str) -> Dict[str, Any]:
    """The one upcoming meeting the words point at. A word in the title
    counts twice as much as a word in an attendee's address."""
    wanted = _event_words(hint)
    scored = []
    for event in events:
        if str(event.get("status") or "") == "cancelled":
            continue
        title = _event_words(event.get("title"))
        people = set()
        for address in event.get("attendees") or []:
            people |= _event_words(str(address).split("@")[0].replace(".", " "))
        score = 2 * len(wanted & title) + len(wanted & (people - title))
        if score:
            scored.append((score, event))
    if not scored:
        return {"status": "none", "event": None, "candidates": []}
    scored.sort(key=lambda entry: entry[0], reverse=True)
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return {"status": "several", "event": None, "candidates": [e for _, e in scored[:5]]}
    return {"status": "one", "event": scored[0][1], "candidates": [scored[0][1]]}


def change_notice(*, title: str, start: str, end: str, timezone: str, cancelled: bool = False) -> str:
    if cancelled:
        return f"A quick note: \"{title}\" has been cancelled. You should receive a calendar update separately."
    when = planning.slot_label({"start": start, "end": end})
    return (f"A quick note: \"{title}\" has moved to {when} ({timezone}). "
            "You should receive a calendar update separately.")


# ── the planner ─────────────────────────────────────────────────────────────

class Commands:
    def __init__(self, workflow: Any) -> None:
        self.workflow = workflow

    @property
    def gateway(self) -> Any:
        return self.workflow.gateway

    @property
    def service(self) -> Any:
        return self.workflow.service

    def run(self, ctx: Any, user: Any, text: str, *, request_id: Optional[str] = None,
            trigger: str = "chat") -> Dict[str, Any]:
        from .workflow import IntakeBusy, claim_key, run_key

        text = " ".join(str(text or "").split())[:MAX_TEXT]
        if not text:
            raise InvalidAvailabilityRequest("An instruction is required.")
        workflow = self.workflow
        identity = str(request_id or uuid.uuid4().hex)[:120]
        key = run_key(user.id, "command", None, identity, workflow._namespace(user))
        with workflow._lock(key):
            claim = workflow._claim(user, key)
            if claim.state == "done":
                existing = (self.gateway.get_run(user, claim.run_id) if claim.run_id else None) \
                    or self.gateway.find_run(user, key)
                if existing is not None:      # the same request sent again is the same run
                    return workflow.view(ctx, user, existing["id"], duplicate=True)
                workflow.claims.reopen(user.id, claim_key(key), claim.token)
                claim = workflow._claim(user, key)
            if not claim.claimed:
                raise IntakeBusy("This instruction is being taken in by another worker.")
            try:
                run = self._open(ctx, user, text, key, trigger)
            except Exception:
                workflow.claims.release(user.id, claim_key(key), claim.token)
                raise
            workflow.claims.settle(user.id, claim_key(key), claim.token, run["id"])
        return workflow.view(ctx, user, run["id"])

    # ── reading and planning ────────────────────────────────────────────────
    def _read(self, user: Any, text: str, now: dt.datetime, zone_name: str,
              plan: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
        workflow = self.workflow
        configured = getattr(self.gateway, "model_configured", None)
        if workflow.model_understanding and callable(configured) and configured():
            with self.gateway.model_usage() as calls:
                operations = parse_model(self.gateway, text, now, zone_name)
            plan["usage"].extend(calls)
            plan["reads"].append({"tool": "model.understand", "ok": bool(operations),
                                  "error": None if operations else "no_supported_operation"})
            if operations:
                return operations, "model"
        return parse_rules(text, now), "rules"

    def _open(self, ctx: Any, user: Any, text: str, key: str, trigger: str) -> Dict[str, Any]:
        workflow = self.workflow
        now = self.service.now(user)
        plan: Dict[str, Any] = {"proposals": [], "deferred": [], "held": None, "decisions": [], "reads": [],
                                "usage": [], "flags": [], "planner": "rules", "confirm_sender": False,
                                "vouched": [], "facts": [], "assumptions": [], "missing": []}
        try:
            zone_name, _, _, _ = self.service.working_context(user, None, None, None)
        except InvalidAvailabilityRequest:
            zone_name = "UTC"
        local_now = now.astimezone(resolve_zone(zone_name))
        operations, source = self._read(user, text, local_now, zone_name, plan)
        plan["planner"] = "model+rules" if source == "model" else "rules"
        if not operations:
            plan["held"] = {"reason": "intent_unclear", "slots": [], "calendars": [], "missing": [],
                            "message": "I could not tell what to do from that. I can set a reminder, move "
                                       "or cancel a meeting and tell its attendees, record a task, or "
                                       "chase replies that are overdue."}
            plan["decisions"].append({"decision": "hold", "reason": "intent_unclear",
                                      "explanation": "The instruction was not understood; nothing is proposed."})
        else:
            self._plan(ctx, user, operations, plan, zone_name, local_now)

        kinds = [operation["type"] for operation in operations]
        meta: Dict[str, Any] = {
            "key": key, "kind": "command", "command": text, "command_kinds": kinds,
            "provider": "gmail", "email_id": None, "thread_id": None, "provider_account_id": None,
            "from_addr": None, "subject": text[:120], "received_at": now.isoformat(),
            "category": "command", "outcome": "command", "created_at": now.isoformat(),
            "trigger": trigger if trigger in ("chat", "evaluation") else "chat",
            "sandbox": workflow._world_id(user), "evaluation": workflow._is_evaluation(user),
            "held": plan["held"], "draft_request": None,
            # Who the Desk may write to on this run: taken from calendar and
            # follow-up RECORDS while planning, never from the instruction.
            "vouched": sorted(set(plan["vouched"])), "timezone": zone_name,
        }
        read = {"source": source, "dropped": [], "intents": [
            {"type": operation["type"], "confidence": None, "evidence": operation.get("evidence") or [],
             "missing": [], "source": source} for operation in operations]}
        typed = plans.build(meta=meta, understanding=read, plan=plan)
        run = self.gateway.open_run(user, title=f"Desk: {text[:80]}", meta=meta,
                                    summary=f"You asked: \"{text[:300]}\".")
        record = workflow._record
        record(user, run, "stage", {"stage": "RECEIVED", "trigger": meta["trigger"], "kind": "command"})
        record(user, run, "stage", {"stage": "UNDERSTANDING", "category": "command", "source": source,
                                    "priority": "normal", "flags": [],
                                    "intents": [{"type": kind, "confidence": None} for kind in kinds]})
        record(user, run, "stage", {"stage": "INVESTIGATING"})
        for item in plan["reads"]:
            record(user, run, "read", item)
        record(user, run, "stage", {"stage": "PLANNING", "planner": plan["planner"]})
        record(user, run, "plan", typed)
        for usage in plan["usage"]:
            record(user, run, "usage", usage)
        for decision in plan["decisions"]:
            record(user, run, "decision", decision)
        for proposal in plan["proposals"]:
            workflow._propose(user, run, proposal)
        return run

    def _plan(self, ctx: Any, user: Any, operations: List[Dict[str, Any]], plan: Dict[str, Any],
              zone_name: str, now: dt.datetime) -> None:
        changed: Optional[Dict[str, Any]] = None        # the calendar change of this instruction
        for operation in operations:
            if operation.get("assumption"):
                plan["assumptions"].append(operation["assumption"])
            kind = operation["type"]
            if kind in ("reschedule", "cancel"):
                if changed is not None:
                    plan["decisions"].append({"decision": "none", "reason": "second_calendar_change",
                                              "explanation": "A second meeting change in the same "
                                                             "instruction was left for you."})
                    continue
                changed = self._plan_change(ctx, user, operation, plan, zone_name, now)
            elif kind == "notify":
                self._plan_notify(user, plan, changed)
            elif kind == "reminder":
                self._plan_reminder(operation, plan, changed, now)
            elif kind == "task":
                self._plan_task(operation, plan)
            elif kind == "chase_overdue":
                self._plan_chase(ctx, user, plan)

    def _hold(self, plan: Dict[str, Any], reason: str, message: str, **extra: Any) -> None:
        if plan["held"] is None:
            plan["held"] = {"reason": reason, "slots": [], "calendars": [], "message": message, **extra}
        plan["decisions"].append({"decision": "hold", "reason": reason, "explanation": message})

    def _plan_change(self, ctx: Any, user: Any, operation: Mapping[str, Any], plan: Dict[str, Any],
                     zone_name: str, now: dt.datetime) -> Optional[Dict[str, Any]]:
        from .workflow import EVENT_SEARCH_DAYS

        try:
            events = self.gateway.calendar_events(user, now - dt.timedelta(hours=1),
                                                  now + dt.timedelta(days=EVENT_SEARCH_DAYS))
            plan["reads"].append({"tool": "calendar.list_events", "ok": True, "count": len(events),
                                  "timeMin": (now - dt.timedelta(hours=1)).isoformat(),
                                  "timeMax": (now + dt.timedelta(days=EVENT_SEARCH_DAYS)).isoformat()})
        except Exception:
            plan["reads"].append({"tool": "calendar.list_events", "ok": False, "error": "unavailable"})
            self._hold(plan, "calendar_lookup_failed",
                       "Your calendar could not be searched for that meeting, so nothing is proposed.")
            return None
        found = find_event(events, str(operation.get("target_hint") or ""))
        candidates = [{key: event.get(key) for key in ("id", "title", "start", "end", "provider")}
                      for event in found["candidates"]]
        if found["status"] == "none":
            self._hold(plan, "event_not_found", "I found no upcoming meeting that matches "
                       f"\"{operation.get('target_hint')}\". Which meeting do you mean?")
            return None
        if found["status"] == "several":
            self._hold(plan, "event_ambiguous", "More than one meeting matches "
                       f"\"{operation.get('target_hint')}\". Which one do you mean?", candidates=candidates)
            return None
        event = found["event"]
        target = {key: event.get(key) for key in ("id", "title", "start", "end", "provider",
                                                  "provider_account_id")}
        plan["facts"].append(f"\"{event.get('title')}\" is the only upcoming meeting those words match.")
        if not event.get("is_organizer"):
            self._hold(plan, "not_organizer", f"You are not the organizer of \"{event.get('title')}\", so it "
                       "cannot be changed from your calendar.", target=target)
            return None
        base = {"event_id": event.get("id"), "calendar_provider": event.get("provider"), "timezone": zone_name}
        if event.get("provider") == "google" and event.get("provider_account_id"):
            base["provider_account_id"] = event.get("provider_account_id")
        if operation["type"] == "cancel":
            plan["proposals"].append({"tool_name": "cancel_calendar_event", "purpose": "cancel",
                                      "tool_input": base, "target": target,
                                      "reason": f"You asked to cancel \"{event.get('title')}\"."})
            plan["decisions"].append({"decision": "propose", "reason": "cancel_requested",
                                      "explanation": f"Cancelling \"{event.get('title')}\" is proposed."})
            return {"event": event, "index": len(plan["proposals"]) - 1, "cancelled": True}

        zone = resolve_zone(zone_name)
        start = str(operation.get("new_start") or "")
        try:
            old_start = parse_instant(str(event.get("start")), zone)
            old_end = parse_instant(str(event.get("end")), zone)
            new_start = parse_instant(start, zone) if start else None
        except InvalidAvailabilityRequest:
            new_start = None
            old_start = old_end = None
        if new_start is None or old_start is None:
            plan["missing"].append("new time")
            self._hold(plan, "time_not_understood", f"I could not read the new time for "
                       f"\"{event.get('title')}\". When should it move to?", target=target)
            return None
        end = str(operation.get("new_end") or "")
        try:
            new_end = parse_instant(end, zone) if end else new_start + (old_end - old_start)
        except InvalidAvailabilityRequest:
            new_end = new_start + (old_end - old_start)
        if not end:
            plan["assumptions"].append("The meeting keeps its length.")
        try:
            check = self.service.slot_check(ctx, user, start=new_start.isoformat(), end=new_end.isoformat(),
                                            timezone=zone_name, ignore=[(old_start, old_end)])
        except InvalidAvailabilityRequest:
            self._hold(plan, "time_not_understood", "The new time could not be read.", target=target)
            return None
        for entry in check["calendars"]:
            plan["reads"].append({"tool": "calendar.check_availability", "provider": entry.get("provider"),
                                  "account": entry.get("account"), "ok": bool(entry.get("ok")),
                                  "error": entry.get("error"), "timeMin": check["slot"]["start"],
                                  "timeMax": check["slot"]["end"]})
        if check["free"] is not True:
            conflict = check["free"] is False
            self._hold(plan, "calendar_conflict" if conflict else "availability_unknown",
                       (f"You are not free then, so \"{event.get('title')}\" was not moved."
                        if conflict else
                        "A calendar could not be read, so the new time is not verified and the "
                        "meeting was not moved."),
                       target=target, requested=check["slot"], conflicts=check["conflicts"],
                       calendars=check["calendars"])
            return None
        plan["facts"].append(f"The new time is free on every connected calendar ({len(check['calendars'])} read).")
        plan["proposals"].append({
            "tool_name": "update_calendar_event", "purpose": "reschedule", "target": target,
            "reason": "The new time is free on every connected calendar. The existing event is moved.",
            "tool_input": {**base, "start": check["slot"]["start"], "end": check["slot"]["end"]}})
        plan["decisions"].append({"decision": "propose", "reason": "new_time_free",
                                  "explanation": f"Moving \"{event.get('title')}\" is proposed for your approval."})
        return {"event": event, "index": len(plan["proposals"]) - 1, "cancelled": False,
                "start": check["slot"]["start"], "end": check["slot"]["end"]}

    def _own_addresses(self, user: Any) -> set:
        own = {str(user.email).lower()}
        try:
            status = self.gateway.provider_status_for(user) or {}
        except Exception:
            status = {}
        for account in (status.get("emailAccounts") or []) + (status.get("gmailAccounts") or []):
            if isinstance(account, Mapping):
                own.add(str(account.get("email") or "").lower())
        own.add(str(status.get("outlookEmail") or "").lower())
        return own

    def _plan_notify(self, user: Any, plan: Dict[str, Any], changed: Optional[Dict[str, Any]]) -> None:
        if changed is None:
            plan["decisions"].append({"decision": "none", "reason": "nothing_to_tell",
                                      "explanation": "Nobody is told, because no meeting was changed."})
            return
        from .safeguards import addresses_in

        event = changed["event"]
        own = self._own_addresses(user)
        people = [address for address in addresses_in(event.get("attendees")) if address not in own]
        if not people:
            plan["decisions"].append({"decision": "none", "reason": "nobody_to_tell",
                                      "explanation": "That meeting has no other attendee to tell."})
            return
        # The attendees come from the calendar event. That is the provenance
        # the recipient check accepts; the instruction's own words are not.
        plan["vouched"].extend(people)
        plan["facts"].append("The people to tell are the attendees on the calendar event: " + ", ".join(people) + ".")
        plan["deferred"].append({
            "tool": "send_email", "purpose": "notify", "depends_on_index": changed["index"],
            "pending": {"to": people, "title": event.get("title"), "cancelled": bool(changed.get("cancelled")),
                        "provider": "outlook" if event.get("provider") == "outlook" else "gmail",
                        "provider_account_id": event.get("provider_account_id")
                        if event.get("provider") == "google" else None}})

    def _plan_reminder(self, operation: Mapping[str, Any], plan: Dict[str, Any],
                       changed: Optional[Dict[str, Any]], now: dt.datetime) -> None:
        title = str(operation.get("title") or "").strip()
        when = parse_time(operation.get("remind_at"))
        if not title:
            self._hold(plan, "details_missing", "What should the reminder say?")
            return
        if when is not None:
            if when <= now:
                self._hold(plan, "details_missing", "That time has already passed. When should I remind you?")
                return
            plan["proposals"].append({"tool_name": "create_reminder", "purpose": "record_task",
                                      "reason": "You asked to be reminded.",
                                      "tool_input": {"title": title[:160], "remind_at": when.isoformat()}})
            plan["decisions"].append({"decision": "propose", "reason": "reminder_requested",
                                      "explanation": "A reminder is set as you asked."})
            return
        if changed is not None and not changed.get("cancelled") and changed.get("start"):
            start = parse_time(changed["start"])
            remind_at = start - dt.timedelta(hours=1)
            if remind_at <= now:
                remind_at = start - dt.timedelta(minutes=15)
            plan["assumptions"].append("No time was given for the reminder; it is set one hour before the meeting.")
            # It belongs to the moved meeting: it is set only once the move took effect.
            plan["deferred"].append({"tool": "create_reminder", "purpose": "record_task",
                                     "depends_on_index": changed["index"],
                                     "pending": {"tool_name": "create_reminder", "purpose": "record_task",
                                                 "reason": "You asked to be reminded before this meeting.",
                                                 "tool_input": {"title": title[:160],
                                                                "remind_at": remind_at.isoformat()}}})
            return
        plan["missing"].append("reminder time")
        self._hold(plan, "details_missing", f"When should I remind you to \"{title}\"?")

    def _plan_task(self, operation: Mapping[str, Any], plan: Dict[str, Any]) -> None:
        title = str(operation.get("title") or "").strip()
        if not title:
            return
        task: Dict[str, Any] = {"title": title[:160], "priority": "medium", "description": "You asked for this in chat."}
        if parse_time(operation.get("due_at")):
            task["due_at"] = parse_time(operation["due_at"]).isoformat()
        plan["proposals"].append({"tool_name": "create_task", "purpose": "record_task", "tool_input": task,
                                  "reason": "You asked for this task."})
        plan["decisions"].append({"decision": "propose", "reason": "task_requested",
                                  "explanation": "The task is recorded as you asked."})

    def _plan_chase(self, ctx: Any, user: Any, plan: Dict[str, Any]) -> None:
        listing = self.workflow.follow_ups(ctx, user, refresh=True)
        plan["reads"].append({"tool": "followup.list", "ok": True, "count": len(listing["followUps"])})
        overdue = [f for f in listing["followUps"] if f.get("state") == "overdue"]
        if not overdue:
            waiting = sum(1 for f in listing["followUps"] if f.get("state") == "waiting")
            plan["decisions"].append({
                "decision": "none", "reason": "nothing_overdue",
                "explanation": "Nothing you are waiting on is overdue"
                               + (f" ({waiting} still within their time)." if waiting else ".")})
            return
        for follow in overdue:
            person = str(follow.get("waitingOn") or "").lower()
            if follow.get("nudges") or follow.get("nudgePending") or not person:
                plan["decisions"].append({
                    "decision": "none", "reason": "already_chased", "followUpId": follow.get("id"),
                    "explanation": f"A reminder about \"{follow.get('subject')}\" was already "
                                   "sent or is waiting for you; no second one is proposed."})
                continue
            plan["vouched"].append(person)          # the person the follow-up RECORD is waiting on
            subject = str(follow.get("subject") or "my earlier message")
            plan["proposals"].append({
                "tool_name": "send_email", "purpose": "nudge", "followUpId": follow.get("id"),
                "reason": f"No answer arrived by {follow.get('dueAt')}.",
                "tool_input": {"provider": "gmail", "mode": "compose", "to": person,
                               "subject": planning.reply_subject(subject),
                               "body": planning.nudge_reply(subject=subject),
                               "thread_id": follow.get("threadId")}})
            plan["decisions"].append({"decision": "propose", "reason": "follow_up_overdue",
                                      "followUpId": follow.get("id"),
                                      "explanation": f"A reminder to {person} is proposed for your approval."})

    # ── a deferred step whose prerequisite took effect ──────────────────────
    def propose_notification(self, user: Any, run: Dict[str, Any], changed_card: Mapping[str, Any],
                             step: Mapping[str, Any]) -> None:
        pending = step.get("pending") or {}
        data = changed_card.get("input") or {}
        planned = data.get("planned_change") or {}
        title = str(pending.get("title") or data.get("event_title") or "the meeting")
        body = change_notice(title=title, timezone=str(data.get("timezone") or run["meta"].get("timezone") or ""),
                             start=str(planned.get("start") or data.get("start")),
                             end=str(planned.get("end") or data.get("end")),
                             cancelled=bool(pending.get("cancelled")))
        message: Dict[str, Any] = {"provider": pending.get("provider") or "gmail", "mode": "compose",
                                   "to": ", ".join(pending.get("to") or []),
                                   "subject": f"Update: {title}", "body": body}
        if pending.get("provider_account_id"):
            message["provider_account_id"] = pending["provider_account_id"]
        self.workflow._propose(user, run, {
            "tool_name": "send_email", "purpose": "notify", "stepId": step["id"],
            "reason": "The meeting has changed, so its attendees are told.", "tool_input": message})


# ── what to say back ────────────────────────────────────────────────────────

def reply_text(view: Mapping[str, Any], zone_name: str) -> str:
    """One short paragraph, in the Desk's voice, from what the run shows.
    It states only what executed, what waits for approval and what did not
    happen."""
    zone = resolve_zone(zone_name or "UTC")
    said: List[str] = []
    for action in view.get("actions") or []:
        tool, status, data = action.get("tool_name"), action.get("status"), action.get("input") or {}
        done = status in ("executed", "partially_executed")
        waits = status in ("awaiting_approval", "needs_info", "approved", "executing")
        if tool == "create_reminder":
            when = moment_label(data.get("remind_at"), zone)
            said.append(f"I set a reminder for {when}: {data.get('title')}." if done else
                        f"A reminder for {when} is ready for you to confirm: {data.get('title')}." if waits else
                        f"The reminder \"{data.get('title')}\" was not set.")
        elif tool == "create_task":
            said.append(f"I recorded the task \"{data.get('title')}\"." if done else
                        f"The task \"{data.get('title')}\" is ready for you to confirm." if waits else
                        f"The task \"{data.get('title')}\" was not recorded.")
        elif tool == "update_calendar_event":
            planned = data.get("planned_change") or {}
            title = (action.get("target") or {}).get("title") or data.get("event_title") or "the meeting"
            when = moment_label(planned.get("start") or data.get("start"), zone)
            said.append(f"I moved \"{title}\" to {when}." if done else
                        f"Moving \"{title}\" to {when} is waiting for your approval." if waits else
                        f"\"{title}\" was not moved.")
        elif tool == "cancel_calendar_event":
            title = (action.get("target") or {}).get("title") or data.get("event_title") or "the meeting"
            said.append(f"I cancelled \"{title}\"." if done else
                        f"Cancelling \"{title}\" is waiting for your approval." if waits else
                        f"\"{title}\" was not cancelled.")
        elif tool == "send_email":
            to = str(data.get("to") or "")
            if action.get("purpose") == "nudge":
                said.append(f"I sent a polite reminder to {to}." if done else
                            f"A polite reminder to {to} is waiting for your approval." if waits else
                            f"No reminder went to {to}.")
            else:
                said.append(f"I told {to} about the change." if done else
                            f"A note to {to} about the change is waiting for your approval." if waits else
                            f"No note went to {to}.")
    for step in (view.get("plan") or {}).get("steps") or []:
        if step.get("deferred") and step.get("toolCallId") is None:
            what = "tell the attendees" if step.get("purpose") == "notify" else "set the reminder"
            said.append(f"Once the meeting change has gone through I will {what}." if step.get("state") in ("waiting", "ready")
                        else f"I did not {what}, because the meeting was not changed.")
    held = view.get("held") or {}
    if held.get("message"):
        said.append(str(held["message"]))
    if not said:
        last = next((item["data"].get("explanation") for item in reversed(view.get("timeline") or [])
                     if item.get("kind") == "decision"), None)
        said.append(str(last or "There was nothing to do."))
    return " ".join(said)


__all__ = ["Commands", "reply_text", "parse_rules", "validate", "find_event", "moment_in", "lifecycle"]
