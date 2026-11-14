"""The replayable demonstration: one command, one simulated working day.

    python -m officesim demo
    python -m officesim demo --step                      (Enter between steps)
    python -m officesim demo --browser --frontend http://localhost:5183

It starts a clean sandbox backend, builds the fictional office, lets the day
arrive message by message, runs the Desk's real workflow, plays the
executive's decisions, and prints what happened as it happens. At the end it
prints the outcomes the oracle confirmed in the sandbox world and writes:

    evidence/demo/report.md         the end-of-day report
    evidence/demo/transitions.md    every run's stages, proposals, approvals,
                                    executions and verifications, in order
    evidence/demo/summary.json, replay.jsonl, runs.json, world-*.json
    evidence/demo/screenshots/      with --browser, labelled SIMULATED

Run it twice and the replay fingerprint is the same. A sandbox left behind by
an interrupted earlier run is stopped first.

Nothing here is a recording of a real mailbox or calendar, and nothing is
sent anywhere.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping

from . import oracle, report, scenarios
from .adapter import package_root
from .jobmodel import JOB, JOB_STATEMENT
from .office import OfficeClock

# Where the browser capture is taken, when --browser is given:
# (step number, stage) -> (label, screens). Only screens that read the
# sandbox world are captured: on this backend the Desk's Tasks, Calendar and
# Activity screens read Scriba's own seeded stores, not the simulated office.
CAPTURES = {
    (1, "proposed"): ("01-morning-proposals", ["overview", "inbox", "approvals", "run"]),
    (1, "done"): ("02-morning-executed", ["work-queue", "run"]),
    (2, "proposed"): ("03-conflict-offer-proposed", ["approvals", "run"]),
    (4, "done"): ("04-client-picked-a-slot-booked", ["run", "find-a-time"]),
    (5, "done"): ("05-meeting-moved", ["run"]),
    ("briefing", "done"): ("06-end-of-day", ["overview", "work-queue"]),
}


def transitions(result: Mapping[str, Any]) -> str:
    """Every run's evidence timeline, as the Desk recorded it."""
    spec = result["spec"]
    clock = OfficeClock(spec["day"], spec["timezone"])
    by_message = {rid: request for rid, request in result["requests"].items()}
    lines = ["# Action transitions", "",
             "> **SIMULATED.** The Desk's own evidence for each run of the demonstration day: every stage, "
             "read, plan, proposal, human decision, execution and verification, in the order it was "
             "recorded. Times are the sandbox world's clock.", ""]
    for run_id in sorted(result["runs"], key=int):
        view = result["runs"][run_id]
        message = (view.get("email") or {}).get("email_id")
        request = by_message.get(message) or {}
        verdict = (result["verdicts"].get(message) or {}).get("verdict", "?")
        lines += [f"## Run {view['runId']}: {request.get('senderName', '?')}, \"{request.get('subject', '?')}\"", "",
                  f"- Trigger: `{view.get('trigger')}`; category: `{view.get('category')}`; planner: "
                  f"`{(view.get('plan') or {}).get('planner')}`; final stage: "
                  f"`{(view.get('lifecycle') or {}).get('stage')}`; oracle verdict: **{verdict}**"]
        plan = view.get("plan") or {}
        for step in plan.get("steps") or []:
            lines.append(f"- Plan step {step['id']}: `{step['tool']}` ({step['purpose']}), needs approval: "
                         f"{step['requiresApproval']}, depends on {step['dependsOn'] or 'nothing'}")
        if view.get("held"):
            lines.append(f"- Held: `{view['held'].get('reason')}`: {view['held'].get('message')}")
        lines += ["", "| Time | Kind | What |", "| --- | --- | --- |"]
        for item in view.get("timeline") or []:
            at = oracle.parse(item["at"]).astimezone(clock.zone).strftime("%a %H:%M:%S")
            lines.append(f"| {at} | {item['kind']} | {str(item['summary']).replace('|', '/')} |")
        lines.append("")
    return "\n".join(lines)


def closing(result: Mapping[str, Any], summary: Mapping[str, Any]) -> List[str]:
    spec = result["spec"]
    clock = OfficeClock(spec["day"], spec["timezone"])
    changes = report.world_changes(result["initialState"], result["finalState"], clock)
    m = summary["metrics"]
    out = ["", "=" * 78, "END OF DAY (SIMULATED: fictional office, sandbox world, nothing was sent)", "=" * 78, ""]
    out.append("Verified in the sandbox world by the oracle:")
    for rid, verdict in result["verdicts"].items():
        if verdict["verdict"] not in ("correct", "corrected"):
            continue
        request = result["requests"][rid]
        proof = ", ".join(f"{e['what']} (run {e['runId']}, action {e['toolCallId']})" for e in verdict["evidence"])
        out.append(f"  + {request['senderName']}: \"{request['subject']}\" -> {proof}")
    out.append("")
    out.append("Not completed by the Desk:")
    for rid, verdict in result["verdicts"].items():
        if verdict["verdict"] in ("correct", "corrected", "correct_none"):
            continue
        request = result["requests"][rid]
        out.append(f"  - {request['senderName']}: \"{request['subject']}\" -> "
                   f"{report.VERDICT_WORDS[verdict['verdict']]}. {'; '.join(verdict['notes'])}")
    out.append("")
    out.append("Final provider state, compared with 08:00:")
    out.append(f"  meetings booked {len(changes['eventsCreated'])}, moved {len(changes['eventsMoved'])}, "
               f"cancelled {len(changes['eventsCancelled'])}; tasks recorded {len(changes['tasksCreated'])}; "
               f"mail sent {len(changes['mailSent'])}; awaited replies marked answered "
               f"{len(changes['awaitedRepliesClosed'])}")
    for event in changes["eventsCreated"]:
        out.append(f"    booked: {event['title']}, {event['start']}, {', '.join(event['attendees'])} "
                   f"[{event['calendar']}]")
    for event in changes["eventsMoved"]:
        out.append(f"    moved:  {event['title']}, {event['from']} -> {event['to']}")
    for event in changes["eventsCancelled"]:
        out.append(f"    cancelled: {event['title']} (was {event['was']})")
    h, a, f = m["human"], m["autonomy"], m["failures"]
    out += ["",
            f"Requests: {m['requests']['received']} received, {m['requests']['actionable']} actionable. "
            f"Handled with approvals only: {a['handledWithApprovalsOnly']} of {a['actionableRequests']}.",
            f"Human: {h['mandatoryApprovals']} approvals; {h['manualRescues']} wrong proposals stopped; "
            f"{h['manualCorrections']} corrected; {h['missingInformationSupplied']} completed by hand; "
            f"{h['fullTakeovers']} requests left for a human.",
            f"Safety: {f['invariantViolations']} invariant violations; {f['checksFailed']} of "
            f"{f['checksFailed'] + f['checksPassed']} checks failed (see the report).",
            f"Model: {m['model']['note']}",
            f"Replay fingerprint: {summary['replayFingerprint']} (run it again: it does not change)."]
    return out


def main(args: argparse.Namespace) -> int:
    from .cli import run_day

    out = Path(args.out) if args.out else package_root() / "evidence" / "demo"
    shots = out / "screenshots"
    frontend = getattr(args, "frontend", None)
    capture_script = package_root() / "browser" / "capture.mjs"
    captured: List[str] = []
    notes: List[str] = []
    base = f"http://localhost:{args.port}"

    print("=" * 78)
    print("SCRIBA EXECUTIVE DESK: OFFICE SIMULATION (SIMULATED DATA, SANDBOX EXECUTION)")
    print("=" * 78)
    print(f"The job: {JOB}. {JOB_STATEMENT}")
    print("The outside world and the executive are played by the simulator. The work is done by the "
          "Desk's own intake worker, plans, approval cards, execution gate and verification.\n")

    def observe(stage: str, record: Mapping[str, Any]) -> None:
        number = int(str(record["id"]).rsplit("-", 1)[1])
        key = "briefing" if record["kind"] == "briefing" else number
        label, screens = CAPTURES.get((key, stage), (None, []))
        if args.browser and label:
            if not frontend:
                notes.append("--browser needs --frontend <url of a running Desk frontend>")
            elif not capture_script.is_file():
                notes.append("browser/capture.mjs is not present")
            else:
                screens = list(screens)
                command = ["node", str(capture_script), "--frontend", frontend, "--api", base,
                           "--out", str(shots), "--name", label]
                if record.get("runsOpened"):
                    command += ["--run", str(record["runsOpened"][0])]
                else:
                    screens = [screen for screen in screens if screen != "run"]
                command += ["--screens", ",".join(screens)]
                done = subprocess.run(command, capture_output=True, text=True, timeout=300)
                if done.returncode == 0:
                    captured.append(label)
                    print(f"   [screenshot {label}]")
                else:
                    notes.append(f"capture {label} failed: {(done.stderr or done.stdout).strip()[:200]}")
        if args.step and stage == "done":
            try:
                input("   (Enter for the next step) ")
            except EOFError:
                pass

    extra_env: Dict[str, str] = {}
    if frontend:
        extra_env["ALLOWED_ORIGINS"] = frontend.rstrip("/")
    done = run_day(scenarios.DEMO_PROFILE, seed=args.seed, day=args.day, port=args.port, out_dir=out,
                   observe=observe, extra_env=extra_env)
    result, summary = done["result"], done["summary"]
    (out / "transitions.md").write_text(transitions(result), encoding="utf-8", newline="\n")
    for line in closing(result, summary):
        print(line)
    print(f"\nEvidence: {out}")
    if args.browser:
        print(f"Screenshots: {', '.join(captured) or 'none'}"
              + (f" in {shots}" if captured else ""))
        for note in dict.fromkeys(notes):
            print(f"  note: {note}")
    return 0
