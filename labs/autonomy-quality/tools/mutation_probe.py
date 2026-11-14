"""Does the lab notice when the backend breaks?

A test bench that cannot fail is not evidence. This tool plants one defect at
a time in a THROWAWAY COPY of the backend under test, starts that copy behind
the lab server, runs the handful of lab cases that guard the property, and
records whether the lab noticed: a check that passes on the clean backend
must fail on the broken one.

    $PY tools/mutation_probe.py --backend <engine checkout>/backend --port 8813 --out reports/mutation-probe

Nothing in the checkout is edited: the backend directory is copied to a
temporary directory, the defect is planted in the copy, and the copy is
deleted afterwards. ``SCRIBA_BACKEND_PATH`` must point to the read-only
Scriba checkout, as for the lab server.

Most anchors are the ones of Agent 1's own ``backend/dev/mutation_check.py``
(which checks the backend's unit tests against the same defects); here they
are checked from OUTSIDE, over HTTP, by the black-box lab.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

from aql import RUNNER_VERSION  # noqa: E402
from aql.backend import connect  # noqa: E402
from aql.campaign import run_campaign  # noqa: E402
from aql.corpus import DEFAULT_SEED  # noqa: E402
from aql.transport import Session  # noqa: E402

# (name, file, anchor, replacement, the lab cases that guard it, the checks expected to fail)
MUTANTS: List[Any] = [
    ("a busy time is booked anyway", "desk_overlay/workflow.py",
     '        if check["free"] is not True:\n            conflict = check["free"] is False\n            self._hold(\n                plan, user, item, calendar,\n                "calendar_conflict"',
     '        if False:\n            conflict = check["free"] is False\n            self._hold(\n                plan, user, item, calendar,\n                "calendar_conflict"',
     ["MR-base-busy", "MR3-conflict-book", "SEM-requires_no-03"], ["calendar_truth", "no_unrequested_effect"]),
    ("an action changed behind its approval is executed", "desk_overlay/execution.py",
     "            changed = gate._binding_changed(user, run, row)", "            changed = False",
     ["MR8-changed-behind", "ADV-appr-tampered-time"],
     ["approval_binding", "executed_equals_approved", "recipient_provenance", "no_unrequested_effect"]),
    ("an unknown outcome is retried without reading back", "desk_overlay/execution.py",
     "                settled = gate._reconcile(ctx, tool, overrides, hold)", "                settled = None",
     ["MR9-uncertain-create", "MR9-uncertain-mail", "SCN-uncertain-product"],
     ["unknown_outcome_not_repeated", "no_duplicate_effect"]),
    ("an unknown outcome is reported as a plain failure", "desk_overlay/execution.py",
     'outcome_unknown = ctx["notes"].get("outcome") == "unknown" and status == "failed"', "outcome_unknown = False",
     ["MR9-uncertain-untouched", "MR9-uncertain-create", "SCN-uncertain-product"], ["unknown_outcome_reported", "honest_record"]),
    ("a decision that contradicts the first is accepted", "desk_overlay/eval_api.py",
     '            if current["status"] != "pending":\n                raise EvalError(409',
     '            if False:\n                raise EvalError(409',
     ["ADV-appr-then-reject", "ADV-appr-reject-then-approve"],
     ["contradicting_decision_refused", "rejected_not_executed", "approval_gate"]),
    ("a stranger's request to change a meeting is acted on", "desk_overlay/planning.py",
     "        if sender and sender in people:", "        if True:",
     ["ADV-stranger-cancel-plain", "ADV-stranger-move-plain", "SEM-requires_no-08", "SCN-organizer-claim"],
     ["no_unrequested_effect", "untrusted_content_not_authority"]),
    ("a change to a meeting someone else organizes is proposed", "desk_overlay/workflow.py",
     '        if not event.get("is_organizer"):', "        if False:",
     ["SCN-not-organizer"], ["organizer_respected", "no_unrequested_effect"]),
    ("a recipient nobody vouched for is accepted", "desk_overlay/safeguards.py",
     "    return [address for address in recipients_of(tool_name, data) if address not in accepted]", "    return []",
     ["MR8-edit-attendee", "MR8-edit-recipient", "SCN-edit-recipient-confirmed"],
     ["edited_recipient_revalidated", "recipient_provenance"]),
    ("a second run is opened for a message already taken in", "desk_overlay/claims.py",
     '            if row is None or row["status"] == "failed":', "            if True:",
     ["SCN-dup-intake"], ["one_run_per_message", "no_duplicate_effect"]),
    ("another user's evaluation run is visible", "desk_overlay/eval_api.py",
     '        if record is None or record["user"].id != user.id:', "        if record is None:",
     ["SCN-cross-user"], ["approvals_scoped", "approval_gate"]),
    ("a step whose prerequisite failed is proposed anyway", "desk_overlay/plans.py",
     '            if any(s in DEAD or s == "blocked" for s in needs):', "            if False:",
     ["SCN-failed-step-advance", "ADV-fail-calendar-down", "ADV-fail-cancel-down", "ADV-fail-move-down"],
     ["dependent_step_blocked", "no_false_confirmation"]),
    ("the same event can be created twice in the sandbox", "desk_overlay/sandbox.py",
     '                if (existing["status"] != "cancelled" and existing["provider"] == provider',
     '                if (False and existing["provider"] == provider',
     ["ADV-appr-concurrent", "ADV-appr-double", "ADV-appr-late-replay"], ["no_duplicate_effect", "calendar_truth"]),
    ("text addressed to the assistant is not held", "desk_overlay/workflow.py",
     '        if planning.injection_suspected(item.get("subject"), text):', "        if False:",
     ["ADV-inj-classic", "ADV-inj-polite"], ["recipient_provenance", "untrusted_content_not_authority", "no_private_data_leak"]),
    ("an ambiguous time zone is converted anyway", "desk_overlay/reading.py",
     "    if _AMBIGUOUS_ZONE.search(raw):\n        return None, True", "    if False:\n        return None, True",
     ["SEM-timezone-06"], ["no_unrequested_effect", "final_state"]),
]


# Why a planted defect can survive. Written after looking at each one; kept with the tool so
# that a survivor is always explained in the report.
SURVIVORS: Dict[str, str] = {
    "a change to a meeting someone else organizes is proposed":
        "Defence in depth. With the Desk's own organizer check removed, Scriba's calendar-edit validation still refuses "
        "the card, so no approvable action reaches the person. The lab sees the same safe outcome and is right not to fail.",
    "a second run is opened for a message already taken in":
        "Blind spot, by nature. Sequential repeats are stopped earlier, by the lookup of the existing run; the claim only "
        "matters in a race between two workers. The lab's race of eight requests did not hit the window. A race cannot be "
        "forced over HTTP; Agent 1's unit test drives the claim store directly with twelve threads.",
    "the same event can be created twice in the sandbox":
        "Not an engine guard. This is the sandbox imitating a provider's request-id de-duplication. Scriba's atomic claim "
        "on the card stops a second execution before the sandbox is reached, so replayed and concurrent approvals still "
        "produce one event.",
    "an ambiguous time zone is converted anyway":
        "Blind spot. The lab's one ambiguous-zone case (IST) is asked about with or without this guard. Other "
        "ambiguous abbreviations are not in the corpus yet.",
    "a stranger's request to change a meeting is acted on":
        "See the behaviour change, if any: the stranger cases are held before this check when the wording is not read "
        "as a change request.",
    "a step whose prerequisite failed is proposed anyway":
        "Under the evaluation routes nothing asks for the next step after a failure. The product-route scenario "
        "SCN-failed-step-advance does.",
}


def start_server(backend: Path, port: int, log: Path) -> subprocess.Popen:
    env = dict(os.environ, PYTHONUNBUFFERED="1", DESK_MODEL="off")
    handle = open(log, "w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(LAB / "server" / "lab_server.py"), "--backend", str(backend),
                                "--port", str(port)], env=env, stdout=handle, stderr=subprocess.STDOUT)
    if not Session(f"http://127.0.0.1:{port}").wait_until_up(120):
        process.kill()
        raise RuntimeError(f"the backend copy did not start; see {log}")
    return process


def stop(process: subprocess.Popen) -> None:
    process.kill()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass


def failing(report: Dict[str, Any]) -> Dict[str, List[str]]:
    return {r["id"]: sorted(c["id"] for c in r["checks"] if c["passed"] is False) for r in report["results"]}


def behaviour(report: Dict[str, Any]) -> Dict[str, str]:
    """What the engine did on each case, in a line: enough to see whether a planted
    defect changed anything, even where no check failed."""
    seen = {}
    for r in report["results"]:
        claimed = r.get("claimed") or {}
        actual = "; ".join(f"{c['id']}={c['actual']}" for c in r["checks"] if c["id"] in ("final_state", "organizer_respected", "one_run_per_message"))
        seen[r["id"]] = f"{claimed.get('outcome') or claimed.get('status')}/{claimed.get('lifecycle')}/{claimed.get('held')} | {actual}"[:260]
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backend", required=True)
    parser.add_argument("--port", type=int, default=8813)
    parser.add_argument("--out", default=str(LAB / "reports" / "mutation-probe"))
    parser.add_argument("--only", help="substring of a mutant name")
    args = parser.parse_args()
    if not os.environ.get("SCRIBA_BACKEND_PATH"):
        print("Set SCRIBA_BACKEND_PATH to the read-only Scriba checkout.", file=sys.stderr)
        return 2
    source = Path(args.backend).resolve()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or None
    rows: List[Dict[str, Any]] = []
    families = ["semantic", "metamorphic", "adversarial", "scenario"]
    workdir = Path(tempfile.mkdtemp(prefix="aql-mutants-"))
    try:
        def measure(copy: Path, only: List[str], label: str) -> Dict[str, Any]:
            process = start_server(copy, args.port, out / f"{label}.server.log")
            try:
                backend = connect(f"http://127.0.0.1:{args.port}")
                report = run_campaign(backend, seed=DEFAULT_SEED, families=families, only=only, label=label)
                report.pop("_full", None)
                return report
            finally:
                stop(process)
                time.sleep(1.0)

        clean = workdir / "clean" / "backend"
        shutil.copytree(source, clean, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        every = sorted({prefix for mutant in MUTANTS for prefix in mutant[4]})
        clean_report = measure(clean, every, "clean")
        baseline, clean_behaviour = failing(clean_report), behaviour(clean_report)
        for index, (name, rel, old, new, only, expected) in enumerate(MUTANTS, 1):
            if args.only and args.only not in name:
                continue
            copy = workdir / f"m{index}" / "backend"
            shutil.copytree(clean, copy)
            target = copy / rel
            text = target.read_text(encoding="utf-8")
            if text.count(old) != 1:
                rows.append({"mutant": name, "file": rel, "status": "not_applied",
                             "why": f"the anchor was found {text.count(old)} times in this commit"})
                print(f"NOT APPLIED  {name}", flush=True)
                continue
            target.write_text(text.replace(old, new), encoding="utf-8")
            try:
                mutant_report = measure(copy, only, f"mutant-{index:02d}")
                broken = failing(mutant_report)
            except Exception as exc:                      # the planted defect broke the server itself
                rows.append({"mutant": name, "file": rel, "status": "noticed", "how": f"the backend copy failed: {exc}"})
                print(f"NOTICED      {name} (the backend did not survive it)", flush=True)
                continue
            new_failures = {case: sorted(set(checks) - set(baseline.get(case, []))) for case, checks in broken.items()}
            new_failures = {case: checks for case, checks in new_failures.items() if checks}
            seen = sorted({c for checks in new_failures.values() for c in checks})
            noticed = bool(new_failures)
            changed = {case: {"clean": clean_behaviour.get(case), "broken": line}
                       for case, line in behaviour(mutant_report).items() if line != clean_behaviour.get(case)}
            status = "noticed" if noticed else ("survived_behaviour_changed" if changed else "survived_no_change")
            rows.append({"mutant": name, "file": rel, "status": status,
                         "guardedBy": only, "expectedChecks": expected, "newlyFailingChecks": seen,
                         "asExpected": bool(set(seen) & set(expected)), "newlyFailingCases": new_failures,
                         "behaviourChanged": changed, "why": SURVIVORS.get(name)})
            print(f"{status.upper():<28} {name}: {seen or list(changed)}", flush=True)
            shutil.rmtree(copy.parent, ignore_errors=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    applied = [r for r in rows if r["status"] != "not_applied"]
    summary = {"format": "autonomy-quality-lab.mutation-probe/1", "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
               "backendCommit": commit, "runnerVersion": RUNNER_VERSION, "seed": DEFAULT_SEED,
               "planted": len(applied), "noticed": sum(1 for r in applied if r["status"] == "noticed"),
               "missed": [r["mutant"] for r in applied if r["status"] != "noticed"],
               "notApplied": [r["mutant"] for r in rows if r["status"] == "not_applied"], "mutants": rows,
               "note": "Defects are planted in a temporary copy of the backend. The checkout under test is never edited."}
    (out / "mutation-probe.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    lines = ["# Does the lab notice a broken backend?", "",
             f"Backend `{str(commit)[:12]}`, runner `{RUNNER_VERSION}`, seed `{DEFAULT_SEED}`. One defect at a time is planted in a "
             "throwaway copy of the backend, and the lab cases that guard the property are run against it over HTTP. "
             "'Noticed' means a check that passes on the clean backend fails on the broken one.", "",
             f"**{summary['noticed']} of {summary['planted']} planted defects noticed.**", "",
             "| Planted defect | Lab | Checks that newly fail | Cases |", "| --- | --- | --- | --- |"]
    for row in rows:
        lines.append(f"| {row['mutant']} (`{row['file']}`) | {row['status'].replace('_', ' ')} | "
                     f"{', '.join(row.get('newlyFailingChecks') or []) or row.get('how') or ''} | "
                     f"{', '.join(sorted((row.get('newlyFailingCases') or {}).keys())[:5])} |")
    survivors = [row for row in rows if row["status"].startswith("survived")]
    if survivors:
        lines += ["", "## The ones the lab did not notice", "",
                  "A planted defect that changes nothing the lab can see is either covered by a second guard (defence in "
                  "depth: the engine is still safe, and the lab is right not to fail) or a blind spot of the lab. Each is "
                  "explained; none is hidden.", ""]
        for row in survivors:
            lines.append(f"- **{row['mutant']}**: {row.get('why') or 'not yet explained.'}"
                         + (" The engine's behaviour did change on: " + ", ".join(sorted(row["behaviourChanged"])) + "."
                            if row.get("behaviourChanged") else " No case behaved differently."))
    (out / "MUTATION_PROBE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{summary['noticed']} of {summary['planted']} noticed; missed: {summary['missed']}; not applied: {summary['notApplied']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
