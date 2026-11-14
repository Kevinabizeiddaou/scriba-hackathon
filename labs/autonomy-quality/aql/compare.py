"""Before and after: two campaign reports compared case by case.

The comparison is keyed by commit and model configuration, taken from each
report's ``traceability``. It refuses to call two runs comparable when they
were not run on the same cases (different seed or corpus hash): it still
shows the numbers, with a warning in the first line.
"""
from __future__ import annotations

from typing import Any, Dict, List

RANK = {"completed": 0, "unverified": 1, "safe_handoff": 2, "failed": 3, "unsupported": 4, "error": 4, "unsafe": 5}
MEASURES = ("completeJobSuccessRate", "completedOrSafelyHandedOver", "correctIntentRate", "correctFinalStateRate",
            "safetyViolations", "falseSuccesses", "humanRescues", "mandatoryApprovals")


def compare_reports(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    old = {r["id"]: r for r in before["results"]}
    new = {r["id"]: r for r in after["results"]}
    shared = sorted(set(old) & set(new))
    improved, regressed, newly_unsafe, fixed_unsafe = [], [], [], []
    for case_id in shared:
        a, b = old[case_id]["verdict"], new[case_id]["verdict"]
        if a == b:
            continue
        row = {"id": case_id, "before": a, "after": b, "rootCauseBefore": old[case_id].get("rootCause"),
               "rootCauseAfter": new[case_id].get("rootCause")}
        (improved if RANK[b] < RANK[a] else regressed).append(row)
        if b == "unsafe":
            newly_unsafe.append(case_id)
        if a == "unsafe":
            fixed_unsafe.append(case_id)
    causes_before = {c["rootCause"]: c["affectedCases"] for c in before.get("rootCauses") or []}
    causes_after = {c["rootCause"]: c["affectedCases"] for c in after.get("rootCauses") or []}
    gates_before = {g["id"]: g["status"] for g in before["gates"]["hard"]}
    gates_after = {g["id"]: g["status"] for g in after["gates"]["hard"]}
    same_cases = (before["traceability"]["seed"] == after["traceability"]["seed"]
                  and set(old) == set(new))
    return {
        "before": before["traceability"], "after": after["traceability"],
        "beforeLabel": before["label"], "afterLabel": after["label"],
        "comparable": same_cases,
        "note": None if same_cases else "The two runs did not cover the same cases; only the shared ones are compared case by case.",
        "sharedCases": len(shared), "onlyBefore": sorted(set(old) - set(new)), "onlyAfter": sorted(set(new) - set(old)),
        "measures": {m: {"before": before["summary"].get(m), "after": after["summary"].get(m)} for m in MEASURES},
        "latencyMedianMs": {"before": before["summary"]["latencyMs"]["median"], "after": after["summary"]["latencyMs"]["median"]},
        "improved": improved, "regressed": regressed, "newlyUnsafe": newly_unsafe, "noLongerUnsafe": fixed_unsafe,
        "gates": {g: {"before": gates_before.get(g), "after": gates_after.get(g)} for g in sorted(set(gates_before) | set(gates_after))},
        "rootCauses": {c: {"before": causes_before.get(c, 0), "after": causes_after.get(c, 0)}
                       for c in sorted(set(causes_before) | set(causes_after))},
    }


def render_comparison(c: Dict[str, Any]) -> str:
    def ident(key: Dict[str, Any]) -> str:
        return f"`{str(key['backendCommit'])[:12]}` · model `{key['model'] or 'none'}` · `{key['executionMode']}` · runner `{key['runnerVersion']}` · seed `{key['seed']}`"

    out: List[str] = ["# Before and after", "",
                      f"- Before: {ident(c['before'])} ({c['beforeLabel']})",
                      f"- After: {ident(c['after'])} ({c['afterLabel']})", ""]
    if c["note"]:
        out += [f"**{c['note']}**", ""]
    out += [f"{c['sharedCases']} cases in both runs: {len(c['improved'])} improved, {len(c['regressed'])} regressed, "
            f"{len(c['newlyUnsafe'])} newly unsafe, {len(c['noLongerUnsafe'])} no longer unsafe.", "",
            "| Measure | Before | After |", "| --- | --- | --- |"]
    for name, row in c["measures"].items():
        out.append(f"| {name} | {row['before']} | {row['after']} |")
    out.append(f"| latency median (ms) | {c['latencyMedianMs']['before']} | {c['latencyMedianMs']['after']} |")
    out += ["", "| Hard gate | Before | After |", "| --- | --- | --- |"]
    for name, row in c["gates"].items():
        out.append(f"| {name} | {row['before']} | {row['after']} |")
    out += ["", "| Root cause | Cases before | Cases after |", "| --- | --- | --- |"]
    for name, row in c["rootCauses"].items():
        if row["before"] != row["after"]:
            out.append(f"| `{name}` | {row['before']} | {row['after']} |")
    for title, rows in (("Regressed", c["regressed"]), ("Improved", c["improved"])):
        if rows:
            out += ["", f"## {title}", "", "| Case | Before | After | Root cause after |", "| --- | --- | --- | --- |"]
            out += [f"| `{r['id']}` | {r['before']} | {r['after']} | {r['rootCauseAfter'] or ''} |" for r in rows]
    return "\n".join(out) + "\n"
