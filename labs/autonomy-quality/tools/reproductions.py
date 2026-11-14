"""Exact reproductions of the most damaging root causes of one report.

    $PY tools/reproductions.py --report reports/<label> --top 5 --api http://127.0.0.1:8811 --out docs/REPRODUCTIONS.md

For each of the ``--top`` root causes (ranked by the acceptance class of
their worst case, then by how many cases they affect) it writes

* ``docs/repro/<n>-<root cause>.json``: the exact request body the lab sent
  (POST /desk/eval/v1/evaluation/runs), which is all ``tools/replay.py`` needs;
* a section in the Markdown file: the message, the command, what must happen,
  and what did happen. With ``--api`` the "replayed just now" block is the
  output of replaying the request against that backend, not text copied from
  the campaign.
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

from acceptance_report import CLASSES, DAMAGE, acceptance_class, engine_said, what_happened   # noqa: E402
from aql.rootcauses import KNOWLEDGE   # noqa: E402


def truth_in_words(truth: Dict[str, Any]) -> str:
    def job(j: Dict[str, Any]) -> str:
        kind = j["kind"]
        if kind == "book":
            return f"a meeting booked {j.get('start')} to {j.get('end')} with the requester invited"
        if kind == "reschedule":
            return f"the existing meeting `{j.get('eventId') or j.get('event')}` moved to {j.get('start')}, and no second event"
        if kind == "cancel":
            return f"the existing meeting `{j.get('eventId') or j.get('event')}` cancelled"
        if kind == "task":
            words = " / ".join("+".join(group) for group in j.get("keywords") or [])
            return f"a task recorded ({words})" + (f" due {j['dueDate']}" if j.get("dueDate") else "")
        if kind == "escalate":
            return "the run put in front of the person (not filed as done)"
        if kind == "reply":
            return "a reply drafted for approval that says what it must"
        if kind == "none":
            return "nothing done, and nothing asked of anyone"
        rest = {k: v for k, v in j.items() if k != "kind"}
        return kind + (": " + json.dumps(rest, ensure_ascii=False) if rest else "")
    options = truth.get("anyOf") or [truth.get("jobs") or [{"kind": "none"}]]
    return " **or** ".join(" **and** ".join(job(j) for j in jobs) for jobs in options)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--report", required=True, help="a report directory (report.json and traces.jsonl.gz)")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--api", help="replay each request against this backend and include the output")
    parser.add_argument("--heldout", help="heldout.json of tools/holdout_probe.py on the same commit: its cases are ranked with the rest")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    folder = Path(args.report)
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    with gzip.open(folder / "traces.jsonl.gz", "rt", encoding="utf-8") as archive:
        traces = {p["id"]: p for p in map(json.loads, archive)}

    if args.heldout:
        held = json.loads(Path(args.heldout).read_text(encoding="utf-8"))
        if str(held["target"]["backendCommit"]) != str(report["traceability"]["backendCommit"]):
            print("the held-out probe was run on another commit", file=sys.stderr)
            return 2
        cases = {c["id"]: c for c in held["cases"]}
        for result in held["results"]:
            report["results"].append(result)
            traces[result["id"]] = {"case": cases[result["id"]], "trace": None}

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for result in report["results"]:
        if result["verdict"] != "completed" and result.get("rootCause"):
            groups.setdefault(result["rootCause"], []).append(result)
    ranked = sorted(groups.items(), key=lambda kv: (min(DAMAGE[acceptance_class(r)] for r in kv[1]),
                                                    -sum(1 for r in kv[1] if DAMAGE[acceptance_class(r)] < 2), -len(kv[1]), kv[0]))
    commit = str(report["traceability"]["backendCommit"])
    out_path = Path(args.out)
    repro_dir = out_path.parent / "repro"
    repro_dir.mkdir(parents=True, exist_ok=True)
    for stale in repro_dir.glob("*.json"):
        stale.unlink()
    top = ranked[:args.top]
    lines = [f"# Exact reproductions: the {len(top)} most damaging root causes on `{commit[:12]}`", "",
             f"From Agent 3 for Agent 1. Backend commit `{commit}`, `{report['traceability']['executionMode']}`, model "
             f"`{report['traceability']['model'] or 'none'}`, lab seed {report['traceability']['seed']}. "
             f"Source: `{folder.as_posix()}`.", "",
             "Ranked by the worst class a root cause reaches (unsafe action, then false completion, then wrong outcome, and so on), "
             "then by the number of cases it affects. Every request below is synthetic; nothing leaves the machine.", "",
             "To run any of them (a seeded sandbox backend is enough; the lab server also shows the office afterwards):", "",
             "```bash", "# the backend under test, unmodified, in the sandbox",
             "SCRIBA_BACKEND_PATH=<Scriba at 3ae3a2aa>/Gmail  $PY labs/autonomy-quality/server/lab_server.py --backend <checkout>/backend --port 8811",
             "# one reproduction: standard library only, approves whatever is put in front of it",
             "$PY labs/autonomy-quality/tools/replay.py --api http://127.0.0.1:8811 --request labs/autonomy-quality/docs/repro/<file>.json",
             "# the same case through the lab's oracle, with its verdict and full trace",
             "cd labs/autonomy-quality && $PY -m aql run --api http://127.0.0.1:8811 --only <case id>", "```", "",
             "| # | Root cause | Worst class | Cases | Witness |", "| --- | --- | --- | --- | --- |"]
    sections: List[str] = []
    for number, (cause, members) in enumerate(top, 1):
        info = KNOWLEDGE.get(cause) or {}
        worst_class = acceptance_class(min(members, key=lambda r: DAMAGE[acceptance_class(r)]))
        candidates = [r for r in members if acceptance_class(r) == worst_class]

        def size(r: Dict[str, Any]) -> int:
            # The witness: the shortest message of the worst class that needs no mid-run script.
            case = traces[r["id"]]["case"]
            email = case["input"].get("email") or {}
            return (len(str(email.get("bodyText") or "")) + 400 * len(case["input"].get("thread") or [])
                    + 5000 * len(case.get("script") or []) + (5000 if case["input"]["kind"] != "email" else 0))
        witness = min(candidates, key=size)
        payload = traces[witness["id"]]
        case = payload["case"]
        name = f"{number}-{cause}.json"
        request = {"caseId": case["id"], "input": case["input"], "context": case["context"], "mode": "sandbox",
                   "_note": f"Exact body the lab sent for {case['id']} (seed {case.get('seed')}), without this key."}
        (repro_dir / name).write_text(json.dumps(request, indent=1, ensure_ascii=False), encoding="utf-8")
        email = case["input"].get("email") or {}
        counts = {c: sum(1 for r in members if acceptance_class(r) == c) for c in CLASSES}
        lines.append(f"| {number} | {info.get('title') or cause} (`{cause}`) | {worst_class} | {len(members)} | `{witness['id']}` |")
        context = case["context"]
        sec = [f"## {number}. {cause}", "", f"**{info.get('title') or cause}**", "",
               f"- Affected on this commit: {len(members)} cases ("
               + ", ".join(f"{n} {c.lower()}" for c, n in counts.items() if n) + "): "
               + ", ".join(f"`{r['id']}`" for r in sorted(members, key=lambda r: r["id"])) + ".",
               f"- Witness: `{witness['id']}` ({case.get('title')}). Request: [`repro/{name}`](repro/{name}).",
               f"- In the case: the clock is {context.get('now')}; the principal is {context['principal']['email']} "
               f"({context['principal'].get('timezone')}); {len(context.get('calendar') or [])} events on the calendar, "
               f"{len(context.get('tasks') or [])} tasks, {len(context.get('followUps') or [])} open follow-ups, "
               f"{len(case['input'].get('thread') or [])} earlier messages in the thread.", ""]
        if case["input"]["kind"] == "email":
            sec += ["The message:", "", "```text", f"From: {(email.get('from') or {}).get('name')} <{(email.get('from') or {}).get('email')}>",
                    f"Subject: {email.get('subject')}", "", str(email.get("bodyText")), "```", ""]
        else:
            sec += ["The chat turn:", "", "```text", json.dumps(case["input"], ensure_ascii=False, indent=1)[:1500], "```", ""]
        if case.get("script"):
            sec += [f"This case also has a script the lab plays during the run (`{json.dumps(case['script'], ensure_ascii=False)[:300]}`); "
                    "`replay.py` does not play it: use the `aql run --only` form.", ""]
        sec += ["**Must happen** (from the meaning of the request; any one alternative is accepted): " + truth_in_words(case["truth"]) + ".", ""]
        if info.get("expected"):
            sec += [info["expected"], ""]
        sec += [f"**Happened on `{commit[:7]}`** (campaign): the engine said `{engine_said(witness)}`; the office shows: "
                f"{what_happened(witness) or 'nothing changed'}.", ""]
        if args.api:
            run = subprocess.run([sys.executable, str(HERE / "tools" / "replay.py"), "--api", args.api, "--request", str(repro_dir / name)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=180)
            sec += ["Replayed just now:", "", "```console", f"$ python tools/replay.py --api {args.api} --request docs/repro/{name}",
                    (run.stdout or run.stderr).rstrip(), "```", ""]
        desk = (payload.get("trace") or {}).get("deskRun") or {}
        steps = [f"{t.get('kind')}: {t.get('summary')}" for t in desk.get("timeline") or [] if t.get("kind") in ("stage", "plan", "decision", "held")]
        if steps:
            sec += ["The Desk's own timeline for it: " + " → ".join(steps[-6:]) + ".", ""]
        if info.get("suggestion"):
            sec += ["**Where the lab thinks it lives** (a proposal; the backend is Agent 1's): " + info["suggestion"]
                    + (f" (`{info['where']}`)" if info.get("where") else ""), ""]
        accept = info.get("acceptance") or [f"The cases {', '.join(sorted(r['id'] for r in members)[:6])} reach `completed` with no safety check failing."]
        sec += ["**Accepted when:**", ""] + [f"- {item}" for item in accept] + [""]
        sections += sec
    lines += [""] + sections
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {out_path} and {len(top)} requests in {repro_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
