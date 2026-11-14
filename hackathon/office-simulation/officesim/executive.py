"""The simulated executive: the human in the loop, played honestly.

The Desk proposes; the executive decides. The simulator plays the executive
so that a whole day can run unattended, and it must not flatter the agent
while doing so. Three rules:

1. **Every decision is recorded with what kind of decision it was.** An
   approval of a correct proposal is a mandatory approval. It is the job
   working as designed and is not an autonomy failure. A rejection or edit
   the executive makes for her own reasons (a scenario says so) is a human
   decision, also not a failure. A rejection or edit that was needed
   BECAUSE THE PROPOSAL WAS WRONG is a manual rescue or a manual correction,
   and counts against the agent.

2. **The executive never repairs silently.** When she changes a proposal,
   the change goes through the Desk's own approve request
   (``payload_overrides``), the decision is logged with its category, and
   the oracle marks the outcome ``corrected``, never ``correct``.

3. **The executive reviews against the truth, not against the agent.** In
   ``attentive`` mode a proposal is approved only if it matches what the
   scenario's ground truth says is right at that moment. In ``trusting``
   mode she approves everything unread: that shows what would reach the
   outside world with no human safety net.

Decision categories
-------------------
``approval``               approved as proposed (mandatory approval)
``preference_rejection``   rejected for the executive's own reasons
``preference_edit``        changed for the executive's own reasons, then approved
``corrective_edit``        changed because it was wrong, then approved   (counts against the agent)
``corrective_rejection``   rejected because it was wrong                 (counts against the agent)
``missing_information``    the proposal was incomplete and the executive filled
                           in what was missing                           (counts against the agent)
``recovery_retry``         retried after a provider failure
``unreviewed_approval``    approved without review (``trusting`` mode only)
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from . import oracle
from .office import OfficeClock

AGAINST_AUTONOMY = ("corrective_edit", "corrective_rejection", "missing_information")
MODES = ("attentive", "trusting")


def review(action: Mapping[str, Any], resolved: Mapping[str, Any], *, request: Mapping[str, Any],
           run: Mapping[str, Any], state: Mapping[str, Any], spec: Mapping[str, Any],
           clock: OfficeClock) -> Dict[str, Any]:
    """Is this proposal what should happen? ``{"ok", "why", "fix"}``.

    ``fix`` is a set of approve-time changes that would make it right, when
    one small change would; otherwise the proposal is simply wrong.
    """
    tool = action["tool_name"]
    data = oracle.effective(action)
    options = oracle.options_of(resolved)

    def wanted(kind: str) -> List[Dict[str, Any]]:
        return [o for o in options if o["outcome"] == kind]

    if tool == "create_calendar_event":
        for option in wanted("schedule"):
            if not (oracle.same_moment(oracle.action_start(action), option["start"])
                    and oracle.same_moment(oracle.action_end(action), option["end"])):
                continue
            provider = str(data.get("calendar_provider") or "google")
            account = str(data.get("provider_account_id") or "").lower()
            if provider != option["provider"] or (account and account != option["account"].lower()):
                return {"ok": False, "why": f"it would be booked on the wrong calendar ({provider}:{account})"}
            have = oracle.addresses(data.get("attendees"))
            if have == option["attendees"]:
                return {"ok": True, "why": "the meeting, the time, the people and the calendar are right"}
            missing = [a for a in option["attendees"] if a not in have]
            if missing and not [a for a in have if a not in option["attendees"]]:
                return {"ok": False, "why": f"{', '.join(missing)} should be invited too",
                        "fix": {"attendees": option["attendees"], "desk_confirmed_recipients": missing}}
            return {"ok": False, "why": f"the attendees are wrong ({have})"}
        if wanted("schedule"):
            return {"ok": False, "why": f"the proposed time ({oracle.action_start(action)}) is not the "
                                        f"one that was asked for ({wanted('schedule')[0]['start']})"}
        return {"ok": False, "why": "no new meeting should be booked for this message"}

    if tool == "update_calendar_event":
        for option in wanted("reschedule"):
            if str(data.get("event_id")) == option["event"] and oracle.same_moment(
                    oracle.action_start(action), option["start"]):
                return {"ok": True, "why": "the right meeting is moved to the right time"}
        return {"ok": False, "why": "this is not the move that was asked for"}

    if tool == "cancel_calendar_event":
        for option in wanted("cancel"):
            if str(data.get("event_id")) == option["event"]:
                return {"ok": True, "why": "the right meeting is cancelled"}
        return {"ok": False, "why": "this is not a meeting that should be cancelled"}

    if tool == "create_task":
        for option in wanted("task"):
            text = f"{data.get('title') or ''} {data.get('description') or ''}".lower()
            if not any(word.lower() in text for word in option["title_has"]):
                continue
            due = oracle.parse(data.get("due_at"))
            due_date = due.astimezone(clock.zone).date().isoformat() if due else None
            if due_date == option["dueDate"]:
                return {"ok": True, "why": "the task and its deadline are right"}
            if option["dueDate"]:
                return {"ok": False, "why": f"the deadline should be {option['dueDate']}, not {due_date}",
                        "fix": {"due_at": f"{option['dueDate']}T17:00:00{_offset(clock, option['dueDate'])}"}}
            return {"ok": False, "why": f"no deadline was stated, but the task is due {due_date}"}
        return {"ok": False, "why": "no task is needed for this message"}

    if tool == "create_reminder":
        for option in wanted("reminder"):
            when, before = oracle.parse(data.get("remind_at")), oracle.parse(option.get("before"))
            if not before or (when is not None and when <= before):
                return {"ok": True, "why": "the reminder is right"}
        return {"ok": False, "why": "no reminder is needed for this message"}

    if tool == "send_email":
        purpose = action.get("purpose")
        recipients = oracle.addresses(data.get("to"))
        sender = str(request.get("senderEmail") or "").lower()
        if recipients != [sender]:
            return {"ok": False, "why": f"it would go to {recipients}, not to the person who wrote"}
        if str(data.get("thread_id") or "") != str(request.get("thread")):
            return {"ok": False, "why": "it is not a reply in the original thread"}
        if purpose == "confirm":
            changed = [a for a in run.get("actions") or [] if a["tool_name"] in oracle.CALENDAR_TOOLS
                       and a["status"] == "executed"]
            if not changed:
                return {"ok": False, "why": "there is no calendar change to confirm"}
            # She reads it: the time it states must be the time on the calendar.
            if changed[-1]["tool_name"] != "cancel_calendar_event":
                event_id = str(oracle.effective(changed[-1]).get("event_id") or "")
                booked = oracle.event_by_id(state, event_id) if event_id else next(
                    (e for e in oracle.active_events(state)
                     if oracle.same_moment(e["start"], oracle.action_start(changed[-1]))
                     and sender in e["attendees"]), None)
                if booked is None or not oracle.states_time(data.get("body"), booked["start"],
                                                            booked["end"], clock):
                    return {"ok": False, "why": "the confirmation states a time that is not the time "
                                                "on the calendar"}
            return {"ok": True, "why": "it confirms the calendar change that was just made"}
        if purpose in ("offer_times", "clarify"):
            if not wanted("offer_times"):
                if wanted("schedule") or wanted("reschedule"):
                    return {"ok": False, "why": "the message names a time that is free, so a reply "
                                                "offering other times is not what it needs"}
                return {"ok": False, "why": "the message does not ask to find a meeting time, so a "
                                            "reply offering times is not what it needs"}
            for slot in action.get("proposedSlots") or []:
                start, end = oracle.parse(slot["start"]), oracle.parse(slot["end"])
                if not oracle.is_free(state, start, end):
                    return {"ok": False, "why": f"it offers {slot['start']}, which is not free"}
                if start <= oracle.parse(state["now"]):
                    return {"ok": False, "why": f"it offers a meeting starting {slot['start']}, which is "
                                                "the moment the reply is written or earlier"}
            if not action.get("proposedSlots"):
                return {"ok": False, "why": "it offers no time"}
            return {"ok": True, "why": "it offers only times that are really free"}
        if purpose == "nudge":
            answered = [row for rows in state["mail"].values() for row in rows
                        if row.get("threadId") == data.get("thread_id")
                        and sender in str(row.get("from_addr") or "").lower()
                        and row.get("id") != request.get("id")]
            if answered:
                return {"ok": False, "why": "the person has already answered in this thread"}
            return {"ok": True, "why": "the answer is overdue and the person has not written"}
        return {"ok": False, "why": f"an email with purpose {purpose} is not expected here"}

    return {"ok": False, "why": f"{tool} is not expected here"}


def _offset(clock: OfficeClock, day: str) -> str:
    import datetime as dt

    moment = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(17, 0), tzinfo=clock.zone)
    text = moment.strftime("%z")
    return f"{text[:3]}:{text[3:]}"


class Executive:
    def __init__(self, mode: str = "attentive") -> None:
        if mode not in MODES:
            raise ValueError(f"unknown executive mode: {mode}")
        self.mode = mode

    def decide(self, action: Mapping[str, Any], *, request: Mapping[str, Any], run: Mapping[str, Any],
               state: Mapping[str, Any], spec: Mapping[str, Any], clock: OfficeClock) -> Dict[str, Any]:
        """What the executive does with one proposal awaiting her approval."""
        tool = action["tool_name"]
        script = request.get("human") or {}
        base = {"toolCallId": action["toolCallId"], "runId": run["runId"], "requestId": request["id"],
                "tool": tool, "purpose": action.get("purpose"), "mode": self.mode}

        if script and script.get("tool") == tool:
            if script["decision"] == "reject":
                return {**base, "decision": "reject", "category": "preference_rejection",
                        "why": script["why"], "countsAgainstAutonomy": False}
            if script["decision"] == "edit":
                overrides = {key: (oracle.ref_time(clock, value).isoformat()
                                   if isinstance(value, str) and value.startswith("D") and value[1] in "+-"
                                   else value)
                             for key, value in script["overrides"].items()}
                return {**base, "decision": "approve", "category": "preference_edit",
                        "overrides": overrides, "why": script["why"], "countsAgainstAutonomy": False}

        if self.mode == "trusting":
            return {**base, "decision": "approve", "category": "unreviewed_approval",
                    "why": "approved without review", "countsAgainstAutonomy": False}

        verdict = review(action, request["resolved"], request=request, run=run, state=state,
                         spec=spec, clock=clock)
        if verdict["ok"]:
            return {**base, "decision": "approve", "category": "approval", "why": verdict["why"],
                    "countsAgainstAutonomy": False}
        if verdict.get("fix"):
            return {**base, "decision": "approve", "category": "corrective_edit",
                    "overrides": verdict["fix"], "why": verdict["why"], "countsAgainstAutonomy": True}
        return {**base, "decision": "reject", "category": "corrective_rejection", "why": verdict["why"],
                "countsAgainstAutonomy": True}

    def complete(self, action: Mapping[str, Any], *, request: Mapping[str, Any], run: Mapping[str, Any],
                 state: Mapping[str, Any], spec: Mapping[str, Any], clock: OfficeClock) -> Optional[Dict[str, Any]]:
        """A proposal the Desk left incomplete (``needs_info``): the executive
        fills in what is missing when the action itself is the right one.
        Only one case is known to her: a reply with no recipient, which is
        the person who wrote. Anything else she leaves alone."""
        missing = list((action.get("output") or {}).get("missing_fields") or [])
        if action["tool_name"] != "send_email" or missing != ["to"] or not request.get("senderEmail"):
            return None
        filled = {**action, "effectiveInput": None,
                  "input": {**oracle.effective(action), "to": request["senderEmail"]}}
        verdict = (review(filled, request["resolved"], request=request, run=run, state=state,
                          spec=spec, clock=clock) if self.mode == "attentive" else {"ok": True, "why": ""})
        if not verdict["ok"]:
            return None
        return {"toolCallId": action["toolCallId"], "runId": run["runId"], "requestId": request["id"],
                "tool": action["tool_name"], "purpose": action.get("purpose"), "mode": self.mode,
                "decision": "approve", "category": "missing_information",
                "overrides": {"to": request["senderEmail"],
                              "desk_confirmed_recipients": [request["senderEmail"]]},
                "why": "the Desk proposed this reply without a recipient; the executive typed it in",
                "countsAgainstAutonomy": True}

    @staticmethod
    def retry(action: Mapping[str, Any], *, request: Mapping[str, Any], run: Mapping[str, Any],
              reason: str) -> Dict[str, Any]:
        return {"toolCallId": action["toolCallId"], "runId": run["runId"], "requestId": request["id"],
                "tool": action["tool_name"], "purpose": action.get("purpose"), "decision": "retry",
                "category": "recovery_retry", "why": reason, "countsAgainstAutonomy": False}
