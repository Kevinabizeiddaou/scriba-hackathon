"""Which of the lab's witnesses are fixed, on which commit?

    $PY tools/witness_matrix.py --baseline reports/A/report.json --against reports/B/report.json [reports/C/report.json ...] --out FILE.md

Takes the root causes of a baseline report and shows, for every affected
case, its verdict in each later report. A root cause is "fixed" on a commit
only when every one of its cases is completed there; a result measured on one
commit is never shown as a result for another. Also lists what got worse.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

RANK = {"completed": 0, "unverified": 1, "safe_handoff": 2, "failed": 3, "unsupported": 4, "error": 4, "unsafe": 5}
SHORT = {"completed": "done", "safe_handoff": "handed over", "failed": "FAILED", "unsafe": "UNSAFE", "unsupported": "unsupported",
         "error": "lab error", None: "not run"}


def load(path: str) -> Dict[str, Any]:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    report["_by_id"] = {r["id"]: r for r in report["results"]}
    return report


def name(report: Dict[str, Any]) -> str:
    return f"`{report['label'].replace('-rules-only', '')}`"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--against", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    base, later = load(args.baseline), [load(p) for p in args.against]
    out: List[str] = ["# Witness matrix: what is fixed, on which commit", "",
                      "Rules-only engine, isolated sandbox, one pass per commit, same runner and seed. No model, no live provider. "
                      "A result is shown under the commit it was measured on and nowhere else.", "",
                      "| Tree | Backend commit | Items | Completed | Handed over | Failed | Unsafe | Unsupported | False successes | Hard gates failing |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for report in [base, *later]:
        s, v = report["summary"], report["summary"]["byVerdict"]
        failing = [g["id"] for g in report["gates"]["hard"] if g["status"] == "fail"]
        out.append(f"| {name(report)} | `{str(report['traceability']['backendCommit'])[:8]}` | {s['cases']} | {v.get('completed', 0)} "
                   f"({(s['completeJobSuccessRate'] or 0) * 100:.1f}%) | {v.get('safe_handoff', 0)} | {v.get('failed', 0)} | "
                   f"**{v.get('unsafe', 0)}** | {v.get('unsupported', 0)} | {s['falseSuccesses']} | {', '.join(failing) or 'none'} |")
    out += ["", "## By root cause found on the baseline", "",
            "| Root cause (baseline) | Severity | Cases | " + " | ".join(name(r) for r in later) + " |",
            "| --- | --- | --- | " + " | ".join("---" for _ in later) + " |"]
    detail: List[str] = []
    for cause in base["rootCauses"]:
        cells = []
        for report in later:
            verdicts = [(report["_by_id"].get(case_id) or {}).get("verdict") for case_id in cause["caseIds"]]
            done = sum(1 for v in verdicts if v == "completed")
            unsafe = sum(1 for v in verdicts if v == "unsafe")
            better = sum(1 for case_id, v in zip(cause["caseIds"], verdicts) if v not in ("completed", None)
                         and RANK[v] < RANK[base["_by_id"][case_id]["verdict"]])
            if done == len(verdicts):
                cells.append("**fixed**")
            else:
                cells.append(f"{done} of {len(verdicts)} fixed" + (f", {better} now handed over" if better else "")
                             + (f", {unsafe} unsafe" if unsafe else ""))
        out.append(f"| {cause['title']} (`{cause['rootCause']}`) | {cause['severity'].replace('_', ' ')} | {cause['affectedCases']} | "
                   + " | ".join(cells) + " |")
        detail += ["", f"### {cause['title']}", "", "| Case | " + name(base) + " | " + " | ".join(name(r) for r in later) + " |",
                   "| --- | --- | " + " | ".join("---" for _ in later) + " |"]
        for case_id in cause["caseIds"]:
            row = [SHORT[(base["_by_id"].get(case_id) or {}).get("verdict")]]
            for report in later:
                result = report["_by_id"].get(case_id) or {}
                cause_now = f" ({result.get('rootCause')})" if result.get("verdict") not in ("completed", None) and \
                    result.get("rootCause") != cause["rootCause"] else ""
                row.append(SHORT[result.get("verdict")] + cause_now)
            detail.append(f"| `{case_id}` | " + " | ".join(row) + " |")
    out += ["", "## What got worse than the baseline", ""]
    any_worse = False
    for report in later:
        worse = [(case_id, base["_by_id"][case_id]["verdict"], r["verdict"], r.get("rootCause"),
                  "; ".join(c["actual"] for c in r["checks"] if c["passed"] is False and c["id"] != "intent_understood")[:200])
                 for case_id, r in report["_by_id"].items()
                 if case_id in base["_by_id"] and RANK[r["verdict"]] > RANK[base["_by_id"][case_id]["verdict"]]]
        new_unsafe = [(case_id, r) for case_id, r in report["_by_id"].items() if r["verdict"] == "unsafe"
                      and (base["_by_id"].get(case_id) or {}).get("verdict") != "unsafe"]
        out.append(f"**{name(report)}**: {len(worse)} cases worse, {len(new_unsafe)} newly unsafe.")
        out.append("")
        if worse:
            any_worse = True
            out += ["| Case | Before | Now | Root cause now | What the office shows |", "| --- | --- | --- | --- | --- |"]
            out += [f"| `{c}` | {SHORT[a]} | {SHORT[b]} | `{rc}` | {why} |" for c, a, b, rc, why in sorted(worse)]
            out.append("")
    if not any_worse:
        out.append("Nothing got worse on any tree.")
    out += ["", "## Still unsafe", ""]
    for report in later:
        unsafe = [r for r in report["results"] if r["verdict"] == "unsafe"]
        out.append(f"**{name(report)}**: {len(unsafe)}." + ("" if unsafe else " None."))
        out += [f"- `{r['id']}` ({', '.join(r['safetyFailures'])}): "
                + "; ".join(c["actual"] for c in r["checks"] if c["passed"] is False and c["safety"])[:220] for r in unsafe]
        out.append("")
    out += ["## Case by case", *detail, ""]
    Path(args.out).write_text("\n".join(out), encoding="utf-8")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
