"""Job-replacement measurement: completed work, not activity.

Every number here is counted from a simulation result: the oracle's verdict
per message (read from the sandbox world's state), the simulated executive's
logged decisions, and the Desk's own run evidence. Nothing is estimated
except the block named ``humanTimeEstimate``, which is an explicit
assumption and is labelled as one wherever it is shown.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from . import oracle
from .jobmodel import ASSUMED_APPROVAL_MINUTES, ASSUMED_HUMAN_MINUTES

# The executive did nothing but approve (or decline for her own reasons).
AUTONOMOUS = ("correct", "correct_escalation", "declined")
# The executive, or someone, still has to do the work or repair it.
TAKEOVER = ("safe_escalation", "missed", "rescued", "failed", "pending")


def _count(items: List[Any]) -> Dict[str, int]:
    found: Dict[str, int] = {}
    for item in items:
        found[str(item)] = found.get(str(item), 0) + 1
    return dict(sorted(found.items()))


def compute(result: Mapping[str, Any]) -> Dict[str, Any]:
    requests = {rid: r for rid, r in result["requests"].items() if r["status"] == "delivered"}
    verdicts: Mapping[str, Mapping[str, Any]] = result["verdicts"]
    decisions: List[Mapping[str, Any]] = result["decisions"]
    runs: List[Mapping[str, Any]] = list(result["runs"].values())
    actions = oracle.actions_of(runs)
    final = result["finalState"]

    actionable = [rid for rid, r in requests.items() if r["needsWork"]]
    quiet = [rid for rid in requests if rid not in actionable]
    by_verdict = _count([verdicts[rid]["verdict"] for rid in requests])
    actionable_verdicts = [verdicts[rid]["verdict"] for rid in actionable]
    detected = [rid for rid in actionable if verdicts[rid]["runIds"]]

    autonomous = [rid for rid in actionable if verdicts[rid]["verdict"] in AUTONOMOUS]
    completed = [rid for rid in actionable if verdicts[rid]["verdict"] == "correct"]
    escalated_right = [rid for rid in actionable if verdicts[rid]["verdict"] == "correct_escalation"]
    declined = [rid for rid in actionable if verdicts[rid]["verdict"] == "declined"]
    corrected = [rid for rid in actionable if verdicts[rid]["verdict"] == "corrected"]
    partial = [rid for rid in actionable if verdicts[rid]["verdict"] == "partial"]
    takeover = [rid for rid in actionable if verdicts[rid]["verdict"] in TAKEOVER]
    incorrect = [rid for rid in requests if verdicts[rid]["verdict"] == "incorrect"]

    # Effects the oracle confirmed in the world, by kind.
    evidence = [item for rid in requests if verdicts[rid]["verdict"] in ("correct", "corrected", "partial")
                for item in verdicts[rid]["evidence"]]
    confirmed = _count([item["what"] for item in evidence])
    calendar_changes = sum(n for what, n in confirmed.items() if what.startswith("calendar event"))
    replies = sum(n for what, n in confirmed.items() if what.startswith(("confirmation", "reply")))
    tasks = confirmed.get("task created", 0) + confirmed.get("reminder created", 0)

    by_category = _count([d["category"] for d in decisions])
    executed = [a for a in actions if a["status"] == "executed"]
    failed_now = [a for a in actions if a["status"] == "failed"]
    unknown_now = [a for a in actions if a.get("outcomeUnknown")]
    unverified = [a for a in executed if not a.get("verified")]
    provider_failures = [op for op in final["operations"] if op["status"] in ("failed", "unknown")]

    follow = (result.get("followUps") or {}).get("followUps") or []
    seeded = final["followUps"]
    initial_seeded = {f["id"]: f for f in result["initialState"]["followUps"]}
    satisfied = [f for f in follow if f.get("state") == "satisfied"] + [
        f for f in seeded if f.get("status") == "closed" and initial_seeded.get(f["id"], {}).get("status") == "waiting"]
    outstanding = {
        "repliesAwaited": [{"waitingOn": f.get("waitingOn"), "state": f.get("state"), "thread": f.get("threadId")}
                           for f in follow if f.get("state") in ("waiting", "overdue")]
        + [{"waitingOn": (f.get("waitingOn") or {}).get("email"), "state": "waiting (from before the day)",
            "thread": f.get("threadId")} for f in seeded if f.get("status") == "waiting"],
        "openTasks": len([t for t in final["tasks"] if t.get("status") == "open"]),
        "runsAwaitingApproval": len([r for r in runs if (r.get("lifecycle") or {}).get("stage") == "AWAITING_APPROVAL"]),
        "runsHandedToExecutive": len([r for r in runs if (r.get("lifecycle") or {}).get("stage")
                                      in ("ESCALATED", "NEEDS_CLARIFICATION", "HELD")]),
    }

    usage = [run.get("usage") for run in runs if run.get("usage")]
    durations = [int((a.get("execution") or {}).get("durationMs") or 0) for a in actions if a.get("execution")]
    ticks = result.get("tickMs") or []

    # ── an explicit assumption, never a measurement ─────────────────────────
    human_minutes = len(requests) * ASSUMED_HUMAN_MINUTES["triage_message"]
    kind_minutes = {"calendar event created": "schedule", "calendar event moved": "reschedule",
                    "calendar event cancelled": "cancel", "reply offering times": "offer_times",
                    "task created": "task", "reminder created": "reminder"}
    for what, count in confirmed.items():
        if what in kind_minutes:
            human_minutes += count * ASSUMED_HUMAN_MINUTES[kind_minutes[what]]
    executive_minutes = len([d for d in decisions]) * ASSUMED_APPROVAL_MINUTES

    def rate(part: int, whole: int) -> Optional[float]:
        return round(part / whole, 3) if whole else None

    return {
        "requests": {
            "received": len(requests),
            "notSent": len([r for r in result["requests"].values() if r["status"] != "delivered"]),
            "actionable": len(actionable),
            "needingNothing": len(quiet),
            "actionableDetectedByDesk": len(detected),
            "needingNothingLeftAlone": len([rid for rid in quiet if verdicts[rid]["verdict"] == "correct_none"]),
        },
        "outcomes": {
            "byVerdict": by_verdict,
            "completedCorrectly": len(completed),
            "correctlyHandedToExecutive": len(escalated_right),
            "declinedByExecutive": len(declined),
            "completedAfterHumanCorrection": len(corrected),
            "partlyCompleted": len(partial),
            "leftForHuman": len(takeover),
            "incorrect": len(incorrect),
            "incorrectRequests": incorrect,
        },
        "verifiedWork": {
            "calendarChanges": calendar_changes,
            "emailReplies": replies,
            "tasksAndReminders": tasks,
            "byKind": confirmed,
            "followUpsSatisfied": len(satisfied),
            "duplicatesPrevented": len(result.get("duplicatesPrevented") or []),
            "duplicatesPreventedDetail": result.get("duplicatesPrevented") or [],
        },
        "failures": {
            "actionsFailedAtEndOfDay": len(failed_now),
            "providerFailuresInjectedAndHit": len(provider_failures),
            "outcomesUnknownAtEndOfDay": len(unknown_now),
            "executedButNotVerifiedByDesk": len(unverified),
            "invariantViolations": len(result["violations"]),
            "backendErrors": len(result["errors"]),
            "checksFailed": len([c for c in result["checks"] if not c["passed"]]),
            "checksPassed": len([c for c in result["checks"] if c["passed"]]),
        },
        "human": {
            "decisions": len(decisions),
            "byCategory": by_category,
            "mandatoryApprovals": by_category.get("approval", 0) + by_category.get("unreviewed_approval", 0),
            "preferenceRejections": by_category.get("preference_rejection", 0),
            "preferenceEdits": by_category.get("preference_edit", 0),
            "manualCorrections": by_category.get("corrective_edit", 0),
            "manualRescues": by_category.get("corrective_rejection", 0),
            "missingInformationSupplied": by_category.get("missing_information", 0),
            "recoveryRetries": by_category.get("recovery_retry", 0),
            "fullTakeovers": len(takeover),
            "takeoverRequests": takeover,
        },
        "autonomy": {
            "actionableRequests": len(actionable),
            "handledWithApprovalsOnly": len(autonomous),
            "rate": rate(len(autonomous), len(actionable)),
            "definition": "Actionable requests that ended in the right outcome with no human action "
                          "other than approving (or declining) what the Desk proposed.",
        },
        "outstanding": outstanding,
        "time": {
            "wallSecondsForWholeDay": result["wallSeconds"],
            "apiCalls": result["apiCalls"],
            "intakePassMsMedian": sorted(ticks)[len(ticks) // 2] if ticks else None,
            "intakePassMsMax": max(ticks) if ticks else None,
            "executionMsTotal": sum(durations),
            "note": "Real time on this machine against the sandbox, with no model call and no "
                    "provider network. It is not a latency figure for a live deployment.",
        },
        "model": {
            "configured": bool((result["health"].get("model") or {}).get("configured")),
            "runsWithUsage": len(usage),
            "estimatedCostUsd": (round(sum(u.get("estimatedCostUsd") or 0 for u in usage), 6)
                                 if usage and all(u.get("estimatedCostUsd") is not None for u in usage) else None),
            "note": "No model call was recorded: the Desk ran on its rules." if not usage else
                    "From the Desk's own per-run usage records.",
        },
        "humanTimeEstimate": {
            "IS_AN_ASSUMPTION": True,
            "assistantMinutesForThisWork": round(human_minutes, 1),
            "executiveMinutesDecidingInDesk": round(executive_minutes, 1),
            "basis": "Per-item minutes in officesim/jobmodel.py, written by the simulator's author. "
                     "Not measured from a job-holder. Only work the oracle confirmed is counted.",
        },
    }


def combine(all_metrics: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Totals across several simulated days."""
    def total(*path: str) -> int:
        value = 0
        for metrics in all_metrics.values():
            node: Any = metrics
            for key in path:
                node = node.get(key, 0) if isinstance(node, Mapping) else 0
            value += int(node or 0)
        return value

    actionable, autonomous = total("autonomy", "actionableRequests"), total("autonomy", "handledWithApprovalsOnly")
    return {
        "days": len(all_metrics),
        "requestsReceived": total("requests", "received"),
        "actionable": actionable,
        "actionableDetectedByDesk": total("requests", "actionableDetectedByDesk"),
        "completedCorrectly": total("outcomes", "completedCorrectly"),
        "correctlyHandedToExecutive": total("outcomes", "correctlyHandedToExecutive"),
        "declinedByExecutive": total("outcomes", "declinedByExecutive"),
        "completedAfterHumanCorrection": total("outcomes", "completedAfterHumanCorrection"),
        "partlyCompleted": total("outcomes", "partlyCompleted"),
        "leftForHuman": total("outcomes", "leftForHuman"),
        "incorrect": total("outcomes", "incorrect"),
        "handledWithApprovalsOnly": autonomous,
        "autonomyRate": round(autonomous / actionable, 3) if actionable else None,
        "calendarChangesVerified": total("verifiedWork", "calendarChanges"),
        "emailRepliesVerified": total("verifiedWork", "emailReplies"),
        "tasksAndRemindersVerified": total("verifiedWork", "tasksAndReminders"),
        "followUpsSatisfied": total("verifiedWork", "followUpsSatisfied"),
        "duplicatesPrevented": total("verifiedWork", "duplicatesPrevented"),
        "mandatoryApprovals": total("human", "mandatoryApprovals"),
        "preferenceRejections": total("human", "preferenceRejections"),
        "preferenceEdits": total("human", "preferenceEdits"),
        "manualCorrections": total("human", "manualCorrections"),
        "manualRescues": total("human", "manualRescues"),
        "missingInformationSupplied": total("human", "missingInformationSupplied"),
        "recoveryRetries": total("human", "recoveryRetries"),
        "invariantViolations": total("failures", "invariantViolations"),
        "checksPassed": total("failures", "checksPassed"),
        "checksFailed": total("failures", "checksFailed"),
        "executedButNotVerifiedByDesk": total("failures", "executedButNotVerifiedByDesk"),
        "backendErrors": total("failures", "backendErrors"),
    }
