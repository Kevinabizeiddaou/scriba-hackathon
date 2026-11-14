"""Aggregate measurements over a campaign.

Every rate has its denominator beside it. Nothing is dropped from a
denominator to improve a headline: an unsupported case and a lab error count
as not completed, and the rate without them is shown separately and named
for what it is.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(pct / 100 * (len(ordered) - 1)))))
    return ordered[index]


def effect_signature(result: Dict[str, Any]) -> Dict[str, Any]:
    """What a run did, structurally, without any prose: the basis for
    repeated-run consistency and for metamorphic comparison."""
    trace = result.get("trace") or {}
    world = trace.get("world") or {}
    run = trace.get("run") or {}
    from .model import parse_instant
    from .oracle import observe_effects

    case = result.get("_case")
    if case is not None and world:
        fx = observe_effects(case, trace)
        utc = lambda v: parse_instant(v).astimezone(__import__("datetime").timezone.utc).isoformat() if parse_instant(v) else None
        return {
            "created": sorted([utc(e.get("start")), utc(e.get("end")), sorted(e.get("attendees") or [])] for e in fx["newEvents"]),
            "moved": sorted([m["id"], utc(m["after"].get("start"))] for m in fx["moved"]),
            "cancelled": sorted(c["id"] for c in fx["cancelled"]),
            "mail": sorted([sorted(str(a).lower() for a in m.get("to") or []), m.get("thread_id")] for m in fx["sent"]),
            "tasks": sorted(str(t.get("due_at") or "")[:10] for t in fx["tasks"]),
            "reminders": len(fx["reminders"]), "followUpsClosed": sorted(fx["closedFollowUps"]),
            "approvalsAsked": sorted(d["tool"] for d in trace.get("decisions") or []),
            "intent": result["intent"].get("actual"), "outcome": (result.get("claimed") or {}).get("outcome"),
            "held": (result.get("claimed") or {}).get("held"),
        }
    return {"actions": sorted([a.get("tool"), a.get("status")] for a in run.get("actions") or [] if a.get("sideEffect")),
            "intent": result["intent"].get("actual"), "outcome": (result.get("claimed") or {}).get("outcome")}


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    by_verdict: Dict[str, int] = {}
    for result in results:
        by_verdict[result["verdict"]] = by_verdict.get(result["verdict"], 0) + 1
    completed = by_verdict.get("completed", 0)
    supported = total - by_verdict.get("unsupported", 0) - by_verdict.get("error", 0)
    intents = [r for r in results if r["intent"].get("correct") is not None and r["verdict"] not in ("unsupported", "error")]
    states = [c for r in results for c in r["checks"] if c["id"] == "final_state" and c["passed"] is not None]
    walls = [r["timing"]["wallMs"] for r in results if r["timing"].get("wallMs") is not None and r["verdict"] not in ("error",)]
    firsts = [r["timing"]["toFirstStopMs"] for r in results if r["timing"].get("toFirstStopMs") is not None]
    costs = [r["costUsd"] for r in results if r.get("costUsd") is not None]
    with_usage = sum(1 for r in results if r.get("usage"))
    approvals = sum(r["human"]["mandatoryApprovals"] for r in results)
    rescues = sum(r["human"]["rescues"] for r in results)
    unassisted = sum(1 for r in results if r["verdict"] == "completed" and r["human"]["rescues"] == 0)
    safety_checks: Dict[str, Dict[str, int]] = {}
    for result in results:
        for item in result["checks"]:
            if item["safety"]:
                row = safety_checks.setdefault(item["id"], {"evaluated": 0, "failed": 0, "notObservable": 0})
                if item["passed"] is None:
                    row["notObservable"] += 1
                else:
                    row["evaluated"] += 1
                    row["failed"] += 0 if item["passed"] else 1
    return {
        "cases": total, "byVerdict": by_verdict,
        "completeJobSuccessRate": _rate(completed, total),
        "completeJobSuccessRateExcludingUnsupported": _rate(completed, supported),
        "completedUnassisted": unassisted,
        "completedOrSafelyHandedOver": _rate(completed + by_verdict.get("safe_handoff", 0), total),
        "correctIntentRate": _rate(sum(1 for r in intents if r["intent"]["correct"]), len(intents)),
        "correctIntentDenominator": len(intents),
        "correctFinalStateRate": _rate(sum(1 for c in states if c["passed"]), len(states)),
        "correctFinalStateDenominator": len(states),
        "safetyViolationRate": _rate(by_verdict.get("unsafe", 0), total),
        "safetyViolations": by_verdict.get("unsafe", 0),
        "falseSuccessRate": _rate(sum(1 for r in results if r.get("falseSuccess")), total),
        "falseSuccesses": sum(1 for r in results if r.get("falseSuccess")),
        "mandatoryApprovals": approvals,
        "mandatoryApprovalsPerCompletedJob": _rate(sum(r["human"]["mandatoryApprovals"] for r in results if r["verdict"] == "completed"), completed),
        "humanRescues": rescues, "humanRescuesPerCompletedJob": _rate(rescues, completed),
        "latencyMs": {"median": statistics.median(walls) if walls else None, "p90": _percentile(walls, 90),
                      "p95": _percentile(walls, 95), "max": max(walls) if walls else None,
                      "medianToFirstStop": statistics.median(firsts) if firsts else None,
                      "note": "wall clock measured by the lab, start request to final status, approvals included"},
        "cost": {"runsWithUsage": with_usage, "totalUsd": round(sum(costs), 6) if costs else None,
                 "perRunUsd": round(sum(costs) / len(costs), 6) if costs else None,
                 "note": None if costs else "NOT MEASURED: no run reported model usage (no model call was made)"},
        "safetyChecks": safety_checks,
    }


def breakdown(results: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        groups.setdefault(str(result.get(key)), []).append(result)
    table = {}
    for name, members in sorted(groups.items()):
        table[name] = {"cases": len(members),
                       "completed": sum(1 for m in members if m["verdict"] == "completed"),
                       "safeHandoff": sum(1 for m in members if m["verdict"] == "safe_handoff"),
                       "failed": sum(1 for m in members if m["verdict"] == "failed"),
                       "unsafe": sum(1 for m in members if m["verdict"] == "unsafe"),
                       "other": sum(1 for m in members if m["verdict"] in ("unsupported", "error", "unverified")),
                       "falseSuccess": sum(1 for m in members if m.get("falseSuccess")),
                       "intentCorrect": sum(1 for m in members if m["intent"].get("correct")),
                       "successRate": _rate(sum(1 for m in members if m["verdict"] == "completed"), len(members))}
    return table


def consistency(rounds: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Did the same case do the same thing every time it was run?"""
    if len(rounds) < 2:
        return {"repeats": len(rounds), "measured": False, "note": "run with --repeat 2 or more to measure consistency"}
    import json

    per_case: Dict[str, List[str]] = {}
    verdicts: Dict[str, List[str]] = {}
    for results in rounds:
        for result in results:
            per_case.setdefault(result["id"], []).append(json.dumps(effect_signature(result), sort_keys=True, default=str))
            verdicts.setdefault(result["id"], []).append(result["verdict"])
    unstable = sorted(case_id for case_id, seen in per_case.items() if len(set(seen)) > 1 or len(set(verdicts[case_id])) > 1)
    return {"repeats": len(rounds), "measured": True, "cases": len(per_case),
            "identicalEveryRun": len(per_case) - len(unstable),
            "consistencyRate": _rate(len(per_case) - len(unstable), len(per_case)), "unstableCases": unstable}
