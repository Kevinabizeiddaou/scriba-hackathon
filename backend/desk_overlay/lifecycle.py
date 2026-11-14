"""The life of a Desk run, and the evidence for it. Pure apart from ``record``.

A run moves through these stages:

    RECEIVED -> UNDERSTANDING -> INVESTIGATING -> PLANNING
        -> AWAITING_APPROVAL -> EXECUTING -> VERIFYING -> COMPLETED

and can end, or rest, in one of:

    WAITING_FOR_RESPONSE        a reply went out and an answer is awaited
    NEEDS_CLARIFICATION   the request cannot be acted on as written
    ESCALATED             handed to the person; the Desk proposes nothing
    PARTIALLY_COMPLETED   some actions took effect and some did not
    FAILED, CANCELLED

Nothing here is inferred from a wish. The first four stages are events the
workflow records when it does the work. Everything after is derived from the
state of the run's action cards in Scriba and from recorded events: a human
decision, an execution, a verification, a follow-up. Each event carries its
own time and keeps its kind, so an agent decision is never confused with a
tool read, a proposed write, an approval, an execution or a verification.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

STAGES = ("RECEIVED", "UNDERSTANDING", "INVESTIGATING", "PLANNING", "AWAITING_APPROVAL",
          "EXECUTING", "VERIFYING", "COMPLETED", "WAITING_FOR_RESPONSE", "NEEDS_CLARIFICATION",
          "HELD", "ESCALATED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED")
FINAL_STAGES = ("COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED")

# Kinds of evidence. One event is exactly one of these.
KINDS = ("stage", "plan", "decision", "read", "proposal", "approval", "execution", "verification",
         "human", "followup", "usage", "error", "task", "file", "browser")

EXECUTED = ("executed",)
PARTIAL = ("partially_executed",)
OPEN = ("pending", "needs_info", "draft", "awaiting_approval")
RUNNING = ("approved", "executing")
ALREADY_DONE_REASONS = ("already_scheduled", "task_exists", "already_in_progress", "already_handled")
CLARIFY_REASONS = ("time_not_understood", "event_ambiguous", "event_not_found", "intent_unclear",
                   "details_missing")

_SUMMARIES = {
    "RECEIVED": "Request received.",
    "UNDERSTANDING": "Request classified.",
    "INVESTIGATING": "Context gathered.",
    "PLANNING": "Plan made.",
}


def event(kind: str, data: Mapping[str, Any], at: str) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"unknown evidence kind: {kind}")
    return {"v": 1, "kind": kind, "at": at, "data": dict(data)}


def summary_of(item: Mapping[str, Any]) -> str:
    """One line a person can read. Never contains message text."""
    kind, data = item.get("kind"), item.get("data") or {}
    if kind == "stage":
        return _SUMMARIES.get(str(data.get("stage")), f"Stage: {data.get('stage')}.")
    if kind == "plan":
        steps = len(data.get("steps") or [])
        return f"Plan written: {steps} step{'s' if steps != 1 else ''}, {data.get('approvals', 0)} to approve."
    if kind == "decision":
        return str(data.get("explanation") or f"Decided: {data.get('decision')}.")
    if kind == "read":
        state = "read" if data.get("ok", True) else f"could not be read ({data.get('error')})"
        return f"{data.get('tool')}: {state}."
    if kind == "proposal":
        return f"Proposed {data.get('tool')} for approval."
    if kind == "approval":
        verb = "approved" if data.get("decision") == "approve" else "rejected"
        held = " It was held." if data.get("result") == "held" else ""
        return f"{data.get('by')} {verb} {data.get('tool')}.{held}"
    if kind == "execution":
        return f"{data.get('tool')}: {data.get('status')}."
    if kind == "verification":
        return (f"{data.get('tool')}: verified ({data.get('method')})." if data.get("verified")
                else f"{data.get('tool')}: not verified ({data.get('reason')}).")
    if kind == "human":
        return f"{data.get('by')} chose to {data.get('action')} {data.get('tool') or ''}".strip() + "."
    if kind == "followup":
        return f"Follow-up {data.get('state')}."
    if kind == "task":
        return {"completed": "Task marked done", "suggested": "Marking a task done is suggested",
                "dismissed": "The suggestion to mark a task done was dismissed",
                "failed": "The task could not be marked done"}.get(str(data.get("state")), "Task update") \
            + f": {data.get('title') or data.get('taskId')}."
    if kind == "file":
        return {"suggested": "A change to a workbook is suggested", "applied": "A changed copy of the workbook was made",
                "unverified": "A changed copy was made and could not be verified",
                "failed": "The workbook could not be changed", "dismissed": "The suggested change was dismissed",
                }.get(str(data.get("state")), "Workbook change") + f": {data.get('filename') or data.get('changeId')}."
    if kind == "browser":
        phase = data.get("phase")
        if phase == "planned":
            return f"A website errand is planned on {data.get('siteName')}: {data.get('goal')}."
        if phase == "started":
            return f"The browser opened {data.get('site')}."
        if phase == "step":
            what = f"{data.get('op')} {data.get('name') or ''}".strip()
            return f"Browser: {what}: {'done' if data.get('state') == 'done' else data.get('message') or data.get('state')}."
        return {"VERIFIED": "The website errand is done and what it brought back was verified.",
                "COMPLETED": "The website was read."}.get(
            str(data.get("state")), f"The website errand stopped ({data.get('error')}): {data.get('message')}")
    if kind == "usage":
        return f"Model call: {data.get('model')}."
    return str(data.get("message") or "An error was recorded.")


def record(gateway: Any, user: Any, run: Mapping[str, Any], kind: str, data: Mapping[str, Any],
           *, at: str) -> Dict[str, Any]:
    """Append one piece of evidence to the run. Append-only."""
    item = event(kind, data, at)
    gateway.record_event(user, run, item, summary_of(item))
    return item


def file_changes(events: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Each change this run suggested to a workbook, in its latest state."""
    latest: Dict[str, Dict[str, Any]] = {}
    for item in events:
        if item.get("kind") != "file":
            continue
        data = dict(item.get("data") or {})
        key = str(data.get("changeId") or "")
        latest[key] = {**latest.get(key, {}), **{k: v for k, v in data.items() if v is not None},
                       "updatedAt": item.get("at")}
    return list(latest.values())


def task_updates(events: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Each existing task this run touched, in its latest state."""
    latest: Dict[str, Dict[str, Any]] = {}
    for item in events:
        if item.get("kind") != "task":
            continue
        data = dict(item.get("data") or {})
        key = str(data.get("taskId") or "")
        latest[key] = {**latest.get(key, {}), **{k: v for k, v in data.items() if v is not None},
                       "updatedAt": item.get("at")}
    return list(latest.values())


def follow_ups(events: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Each follow-up of the run in its latest state."""
    latest: Dict[str, Dict[str, Any]] = {}
    for item in events:
        if item.get("kind") != "followup":
            continue
        data = dict(item.get("data") or {})
        key = str(data.get("id") or "")
        if not key:
            continue
        merged = {**latest.get(key, {}), **{k: v for k, v in data.items() if v is not None}}
        merged["updatedAt"] = item.get("at")
        latest[key] = merged
    return list(latest.values())


def usage_of(events: List[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Model usage recorded on the run, summed per model. None when no model
    call was recorded: that is "unknown", not zero."""
    calls = [item.get("data") or {} for item in events if item.get("kind") == "usage"]
    if not calls:
        return None
    models: Dict[str, Dict[str, Any]] = {}
    cost: Optional[float] = 0.0
    for call in calls:
        name = str(call.get("model") or "unknown")
        entry = models.setdefault(name, {"model": name, "calls": 0, "inputTokens": 0,
                                         "outputTokens": 0, "cachedInputTokens": None})
        entry["calls"] += 1
        for key, source in (("inputTokens", "inputTokens"), ("outputTokens", "outputTokens")):
            if call.get(source) is None:
                entry[key] = None
            elif entry[key] is not None:
                entry[key] += int(call[source])
        if call.get("cachedInputTokens") is not None:
            entry["cachedInputTokens"] = (entry["cachedInputTokens"] or 0) + int(call["cachedInputTokens"])
        if call.get("costUsd") is None:
            cost = None            # one unpriced call: the run has no total
        elif cost is not None:
            cost += float(call["costUsd"])
    return {"models": list(models.values()),
            "estimatedCostUsd": round(cost, 6) if cost is not None else None,
            "priceSource": next((c.get("priceSource") for c in calls if c.get("priceSource")), None)}


def derive(meta: Mapping[str, Any], actions: List[Mapping[str, Any]],
           events: List[Mapping[str, Any]], *, pending_next: bool = False) -> Dict[str, Any]:
    """Where the run stands now.

    ``actions`` are the run's action views (``status``, ``outcomeUnknown``,
    ``verified``). ``pending_next`` is true when a step may still be proposed
    (the confirmation reply after a booking).
    """
    statuses = [str(action.get("status") or "") for action in actions]
    waiting_on = [f for f in follow_ups(events) if f.get("state") in ("waiting", "overdue", "escalated")]
    held = meta.get("held") if isinstance(meta.get("held"), Mapping) else None
    unknown = any(action.get("outcomeUnknown") for action in actions)
    reason: Optional[str] = None

    updates = task_updates(events)
    if not actions and updates and not held:
        states = {str(update.get("state")) for update in updates}
        if "failed" in states:
            stage, reason = "ESCALATED", "task_completion_failed"
        elif "suggested" in states:
            # Marking the person's task done is theirs to confirm here.
            stage, reason = "ESCALATED", "task_completion_suggested"
        elif "unverified" in states:
            # The change was sent and could not be read back: not done yet.
            stage, reason = "VERIFYING", "task_not_verified"
        elif "completed" in states:
            stage, reason = "COMPLETED", "task_completed"
        else:
            stage, reason = "COMPLETED", "no_action_needed"
    elif not actions:
        if held:
            reason = str(held.get("reason") or "")
            if reason in ALREADY_DONE_REASONS:
                # A request that repeats something already in place: nothing
                # is left to do, and nobody needs to be asked.
                stage = "COMPLETED"
            else:
                stage = "NEEDS_CLARIFICATION" if reason in CLARIFY_REASONS else "ESCALATED"
        elif meta.get("draft_request"):
            stage, reason = "ESCALATED", "reply_needs_author"
        else:
            stage, reason = "COMPLETED", "no_action_needed"
    elif any(status in OPEN for status in statuses):
        open_actions = [a for a in actions if a.get("status") in OPEN]
        if all(a.get("held") for a in open_actions):
            # Every open action is held by a guard: nothing can be approved as it stands.
            stage, reason = "HELD", str(open_actions[0].get("errorCode") or "held")
        else:
            stage = "AWAITING_APPROVAL"
    elif any(status in RUNNING for status in statuses):
        stage = "EXECUTING"
    else:
        done = [a for a in actions if a.get("status") in EXECUTED]
        partial = [a for a in actions if a.get("status") in PARTIAL]
        failed = [a for a in actions if a.get("status") == "failed"]
        if unknown:
            stage, reason = "VERIFYING", "outcome_unknown"
        elif partial or (done and failed):
            stage = "PARTIALLY_COMPLETED"
        elif failed:
            stage = "FAILED"
        elif not done:
            stage = "CANCELLED"
        elif pending_next:
            stage, reason = "EXECUTING", "next_step_pending"
        elif any((a.get("verification") or {}).get("verified") is False for a in done):
            # It executed and the provider state does not show it. That is not
            # "done": it is handed to the person.
            stage, reason = "ESCALATED", "verification_failed"
        elif any(not a.get("verified") for a in done):
            stage, reason = "VERIFYING", "not_yet_verified"
        elif waiting_on:
            stage = "WAITING_FOR_RESPONSE"
        else:
            stage = "COMPLETED"

    # A change to a workbook that is suggested, failed or unverified is work
    # that is not finished, whatever else the run did.
    changes = {str(change.get("state")) for change in file_changes(events)}
    if stage == "COMPLETED" and changes & {"suggested", "failed", "unverified"}:
        if "failed" in changes:
            stage, reason = "ESCALATED", "file_change_failed"
        elif "unverified" in changes:
            stage, reason = "VERIFYING", "file_change_not_verified"
        else:
            stage, reason = "ESCALATED", "file_change_suggested"

    # A website errand that has not brought back what it went for is work that is not finished.
    planned = next((e.get("data") or {} for e in events if e.get("kind") == "browser"
                    and (e.get("data") or {}).get("phase") == "planned"), None)
    if planned is not None and stage == "COMPLETED":
        last = next((e.get("data") or {} for e in reversed(events) if e.get("kind") == "browser"
                     and (e.get("data") or {}).get("phase") == "result"), None)
        decided = {(e.get("data") or {}).get("reason") for e in events if e.get("kind") == "decision"}
        if last is None:
            stage, reason = "EXECUTING", "browser_running"
        elif last.get("state") == "OUTCOME_UNKNOWN":
            stage, reason = "VERIFYING", "browser_outcome_unknown"
        elif last.get("state") == "INTERRUPTED":
            stage, reason = "ESCALATED", "browser_interrupted"
        elif last.get("state") not in ("VERIFIED", "COMPLETED"):
            stage, reason = "ESCALATED", "browser_failed"
        elif "workbook_not_mapped" in decided:
            stage, reason = "ESCALATED", "workbook_not_mapped"

    compensation = None
    if stage == "PARTIALLY_COMPLETED":
        # The Desk never undoes an executed action on its own.
        compensation = {
            "policy": "escalate",
            "message": "Some of this work took effect and some did not. Nothing is undone "
                       "automatically: retry the step that failed, or finish it yourself.",
        }
    return {"stage": stage, "reason": reason, "final": stage in FINAL_STAGES,
            "outcomeUnknown": unknown, "compensation": compensation}


# ── the lifecycle of ONE action ─────────────────────────────────────────────
#
# A run's stage says where the whole request stands. Each action has its own
# state, and it is explicit: a client never has to work it out from a status,
# a flag and an error code. "The provider accepted the request" is EXECUTED_
# UNVERIFIED; only evidence makes it VERIFIED.
ACTION_STATES = (
    "PROPOSED",              # waits for the person; can be approved as it stands
    "HELD",                  # a guard or a missing detail holds it; cannot be approved as it stands
    "APPROVED",              # approved, claimed, not started
    "EXECUTING",             # being carried out
    "EXECUTED_UNVERIFIED",   # the call returned; there is no evidence yet that it took effect
    "VERIFIED",              # it took effect, on evidence
    "VERIFICATION_FAILED",   # the call returned and the state read back does not show it
    "PARTIALLY_EXECUTED",    # part of it took effect; nothing is undone
    "OUTCOME_UNKNOWN",       # the provider did not confirm; it may or may not have happened
    "INTERRUPTED",           # the process stopped; read back, the effect is not there
    "FAILED",                # it did not take effect
    "REJECTED",              # the person rejected it; it never ran
)
ACTION_FINAL = ("VERIFIED", "REJECTED")


def action_state(status: str, *, held: bool = False, verified: bool = False,
                 verification: Optional[Mapping[str, Any]] = None, outcome_unknown: bool = False,
                 error_code: Optional[str] = None) -> str:
    """The explicit state of one action, from its card and the evidence."""
    status = str(status or "")
    if status in ("needs_info",) or (status in OPEN and held):
        return "HELD"
    if status in OPEN:
        return "PROPOSED"
    if status == "approved":
        return "APPROVED"
    if status == "executing":
        return "EXECUTING"
    if status in EXECUTED:
        if verified:
            return "VERIFIED"
        if verification is not None and verification.get("verified") is False:
            return "VERIFICATION_FAILED"
        return "EXECUTED_UNVERIFIED"
    if status in PARTIAL:
        return "PARTIALLY_EXECUTED"
    if status == "failed":
        if outcome_unknown:
            return "OUTCOME_UNKNOWN"
        return "INTERRUPTED" if error_code == "interrupted" else "FAILED"
    if status == "cancelled":
        return "REJECTED"
    return "FAILED" if status == "unsupported" else "PROPOSED"


def retry_of(state: str, *, simulated: bool, attempts: int) -> Optional[Dict[str, Any]]:
    """Whether a retry is possible and what it does first. None: no retry.

    - ``rerun``: nothing happened, so the action is simply run.
    - ``readback_first``: the outcome is unknown and the state can be read
      (a sandbox): the retry looks for the effect and does not repeat it.
    - ``confirm_first``: the outcome is unknown and cannot be read (a real
      provider): the retry is refused until the person says they checked
      (``payload_overrides.desk_retry_after_unknown_confirmed``).
    """
    if state in ("FAILED", "INTERRUPTED"):
        mode = "rerun"
    elif state == "OUTCOME_UNKNOWN":
        mode = "readback_first" if simulated else "confirm_first"
    else:
        return None
    return {"mode": mode, "attempts": int(attempts),
            # One identity per effect: a retry is the same effect, never a second one.
            "sameEffect": True}


def timeline(events: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [{"at": item.get("at"), "kind": item.get("kind"), "summary": summary_of(item),
             "data": item.get("data") or {}} for item in events]
