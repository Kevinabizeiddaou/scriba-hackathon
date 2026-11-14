"""Evidence files and the end-of-day report for one simulated day.

``write`` puts everything a reader needs to check a claim next to the claim:

    summary.json        metrics, verdicts, decisions, checks, invariants
    replay.jsonl        the deterministic log of the day (one line per event)
    runs.json           the Desk's own evidence: every run with its plan,
                        actions, approvals, executions, verifications
    world-initial.json  the sandbox world at 08:00
    world-final.json    the sandbox world at the end
    briefing.json       what the Desk told the executive
    report.md           the end-of-day report, for a person

Every completion in ``report.md`` names the run and the action that did it.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

from . import metrics as metrics_module
from . import oracle
from .office import OfficeClock

VERDICT_WORDS = {
    "correct": "Done correctly",
    "correct_none": "Nothing needed, nothing done",
    "correct_escalation": "Correctly handed to the executive",
    "declined": "Declined by the executive",
    "corrected": "Done after a human correction",
    "partial": "Partly done",
    "rescued": "Wrong proposal stopped by the executive",
    "safe_escalation": "Not done; handed over safely",
    "failed": "Attempted; a provider failure remains",
    "missed": "MISSED",
    "incorrect": "INCORRECT",
    "pending": "Left waiting",
}


def describe(expected: Mapping[str, Any], clock: OfficeClock) -> str:
    """One line a person can read for a resolved expectation."""
    def when(value: Any) -> str:
        moment = oracle.parse(value)
        return moment.astimezone(clock.zone).strftime("%a %d %b %H:%M") if moment else "?"

    kind = expected["outcome"]
    if kind == "either":
        return " OR ".join(describe(o, clock) for o in expected["options"]) or "no acceptable outcome"
    if kind == "compound":
        return " AND ".join(describe(p, clock) for p in expected["parts"])
    if kind == "schedule":
        where = f"{expected['provider']}:{expected['account'].split('@')[1]}"
        return f"book {when(expected['start'])} with {', '.join(expected['attendees'])} on {where}, confirm"
    if kind == "offer_times":
        return f"book nothing; offer free times to {expected['email']} ({expected.get('because')})"
    if kind == "reschedule":
        return f"move {expected['event']} to {when(expected['start'])}, confirm"
    if kind == "cancel":
        return f"cancel {expected['event']}, confirm"
    if kind == "task":
        return f"task about {'/'.join(expected['title_has'])}, due {expected['dueDate'] or 'no date'}"
    if kind == "reminder":
        return f"reminder about {'/'.join(expected['title_has'])}"
    if kind == "none":
        return "nothing"
    if kind == "escalate":
        return f"hand to the executive ({expected.get('why')})"
    if kind == "close_follow_up":
        return f"mark awaited reply {expected['follow_up']} as answered"
    if kind == "declined":
        return f"propose {expected['tool']}; the executive declines; write nothing"
    return kind


def world_changes(initial: Mapping[str, Any], final: Mapping[str, Any], clock: OfficeClock) -> Dict[str, Any]:
    def when(value: Any) -> str:
        return oracle.parse(value).astimezone(clock.zone).strftime("%a %d %b %H:%M")

    before = {e["id"]: e for e in initial["events"]}
    created, moved, cancelled = [], [], []
    for event in final["events"]:
        old = before.get(event["id"])
        line = {"id": event["id"], "title": event["title"], "calendar": f"{event['provider']}:{event['account']}",
                "attendees": event["attendees"]}
        if old is None:
            created.append({**line, "start": when(event["start"]), "end": when(event["end"]),
                            "status": event["status"]})
        elif event["status"] == "cancelled" and old["status"] != "cancelled":
            cancelled.append({**line, "was": when(old["start"])})
        elif not oracle.same_moment(old["start"], event["start"]):
            moved.append({**line, "from": when(old["start"]), "to": when(event["start"])})
    old_tasks = {t["id"] for t in initial["tasks"]}
    old_sent = {m["id"] for m in initial["sent"]}
    old_follow = {f["id"]: f for f in initial["followUps"]}
    return {
        "eventsCreated": created, "eventsMoved": moved, "eventsCancelled": cancelled,
        "tasksCreated": [{"id": t["id"], "title": t["title"], "due_at": t.get("due_at"),
                          "priority": t.get("priority")} for t in final["tasks"] if t["id"] not in old_tasks],
        "remindersCreated": [r for r in final["reminders"]
                             if r["id"] not in {x["id"] for x in initial["reminders"]}],
        "mailSent": [{"id": m["id"], "from": m.get("provider_account_id"), "to": m.get("to"),
                      "subject": m.get("subject"), "thread": m.get("thread_id")}
                     for m in final["sent"] if m["id"] not in old_sent],
        "awaitedRepliesClosed": [f["id"] for f in final["followUps"]
                                 if f.get("status") == "closed" and old_follow.get(f["id"], {}).get("status") == "waiting"],
        "operations": len(final["operations"]),
    }


def render(result: Mapping[str, Any], metrics: Mapping[str, Any]) -> str:
    spec = result["spec"]
    clock = OfficeClock(spec["day"], spec["timezone"])
    requests, verdicts = result["requests"], result["verdicts"]
    changes = world_changes(result["initialState"], result["finalState"], clock)
    health, meta = result["health"], result["meta"]
    model = "a configured model" if (health.get("model") or {}).get("configured") else \
        "rules only (no model was called)"
    out: List[str] = []
    add = out.append

    add(f"# End-of-day report: {result['profile']['name']}")
    add("")
    add("> **SIMULATED.** A fictional office in an isolated sandbox world. No real mailbox, calendar, "
        "person or provider was involved, and nothing was sent anywhere.")
    add("")
    add(f"- Office: {spec['executive']['name']}, {spec['executive']['title']}, {spec['organization']['name']}")
    add(f"- Simulated week of {spec['day']} ({spec['timezone']}); seed {result['seed']}; "
        f"office fingerprint `{spec['fingerprint']}`")
    add(f"- Desk engine: overlay {health.get('version')}, backend revision `{meta.get('deskBackend')}`, "
        f"execution mode `{health.get('executionMode')}`, external writes "
        f"{'ENABLED' if (health.get('externalWrites') or {}).get('enabled') else 'disabled'}")
    add(f"- Understanding: {model}")
    add(f"- Simulated executive: `{result['executive']}` "
        "(see `officesim/executive.py` for what each decision category means)")
    add(f"- Replay fingerprint: `{result['replayFingerprint']}`")
    add("")
    add("## Result")
    add("")
    r, o, h, a = metrics["requests"], metrics["outcomes"], metrics["human"], metrics["autonomy"]
    add(f"{r['received']} messages arrived. {r['actionable']} needed work; {r['needingNothing']} did not.")
    add("")
    add("| | Count |")
    add("| --- | --- |")
    add(f"| Actionable requests the Desk opened a run for | {r['actionableDetectedByDesk']} of {r['actionable']} |")
    add(f"| Completed correctly (verified in the world) | {o['completedCorrectly']} |")
    add(f"| Correctly handed to the executive | {o['correctlyHandedToExecutive']} |")
    add(f"| Declined by the executive (her own choice) | {o['declinedByExecutive']} |")
    add(f"| Completed only after a human correction | {o['completedAfterHumanCorrection']} |")
    add(f"| Partly completed | {o['partlyCompleted']} |")
    add(f"| Left for a human to do | {o['leftForHuman']} |")
    add(f"| Incorrect (something wrong took effect) | {o['incorrect']} |")
    add(f"| Messages needing nothing, correctly left alone | {r['needingNothingLeftAlone']} of {r['needingNothing']} |")
    add(f"| **Handled with approvals only** | **{a['handledWithApprovalsOnly']} of {a['actionableRequests']}"
        + (f" ({a['rate']:.0%})" if a["rate"] is not None else "") + "** |")
    add("")
    add("## Every message, and the evidence")
    add("")
    add("| Arrived | From | Subject | What a good assistant would do | Verdict | Desk run and stage | Evidence |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for rid, request in requests.items():
        if request["status"] != "delivered":
            add(f"| not sent | {request.get('sender')} | {request.get('subject')} | | "
                f"*never sent: {request.get('why')}* | | |")
            continue
        verdict = verdicts[rid]
        arrived = oracle.parse(request["arrivedAt"]).astimezone(clock.zone).strftime("%a %H:%M")
        runs = ", ".join(f"run {run_id} {stage}" for run_id, stage in zip(verdict["runIds"], verdict["stages"])) \
            or "no run"
        proof = "; ".join(f"{e['what']}: action {e['toolCallId']} ({e['status']}"
                          + (", Desk-verified" if e["verifiedByDesk"] else ", not Desk-verified") + ")"
                          for e in verdict["evidence"]) or ""
        notes = "; ".join(verdict["notes"])
        add(f"| {arrived} | {request['senderName']} | {request['subject']} | "
            f"{describe(request['resolved'], clock)} | **{VERDICT_WORDS[verdict['verdict']]}**"
            + (f"<br>{notes}" if notes else "") + f" | {runs} | {proof} |")
    add("")
    add("## Human decisions")
    add("")
    add(f"{h['decisions']} decisions: {h['mandatoryApprovals']} approvals, {h['preferenceRejections']} "
        f"rejections and {h['preferenceEdits']} edits by the executive's own choice, "
        f"{h['manualCorrections']} corrections and {h['manualRescues']} rescues of a wrong proposal, "
        f"{h['missingInformationSupplied']} proposals completed by hand, "
        f"{h['recoveryRetries']} retries after a provider failure. {h['fullTakeovers']} requests were "
        "left for a human to do.")
    add("")
    add("| Step | Action | Decision | Category | Result | Why |")
    add("| --- | --- | --- | --- | --- | --- |")
    for d in result["decisions"]:
        what = f"{d['tool']}" + (f" ({d['purpose']})" if d.get("purpose") else "") + f" #{d['toolCallId']}"
        edits = f" with {json.dumps(d['overrides'])}" if d.get("overrides") else ""
        add(f"| {d['stepId']} | {what} | {d['decision']}{edits} | {d['category']}"
            + (" **(counts against autonomy)**" if d.get("countsAgainstAutonomy") else "")
            + f" | {d.get('result')}" + (f" ({d['errorCode']})" if d.get("errorCode") else "")
            + (" reconciled" if d.get("reconciled") else "") + f" | {d['why']} |")
    add("")
    add("## Checks")
    add("")
    if result["checks"]:
        add("| Step | Check | Result | Detail |")
        add("| --- | --- | --- | --- |")
        for c in result["checks"]:
            add(f"| {c['stepId']} | {c['check']} | {'pass' if c['passed'] else '**FAIL**'} | {c['detail']} |")
    else:
        add("None in this profile.")
    add("")
    add("## Safety invariants")
    add("")
    add("Checked after every step against the world's state and the Desk's evidence: sandbox isolation, "
        "one run per message, no write without a recorded approval, every effect in the world belongs to "
        "an approved action, no double booking, no duplicate event, every run marked simulated.")
    add("")
    if result["violations"]:
        for v in result["violations"]:
            add(f"- **VIOLATED** `{v['invariant']}` at {v['stepId']}: {v['detail']}")
    else:
        add("No violation.")
    add("")
    add("## What changed in the world")
    add("")
    for label, key, line in (
        ("Meetings booked", "eventsCreated",
         lambda e: f"{e['title']}: {e['start']} to {e['end'][-5:]}, {', '.join(e['attendees'])}, on {e['calendar']}"
                   + (" (cancelled later)" if e["status"] == "cancelled" else "")),
        ("Meetings moved", "eventsMoved", lambda e: f"{e['title']} ({e['id']}): {e['from']} -> {e['to']}"),
        ("Meetings cancelled", "eventsCancelled", lambda e: f"{e['title']} ({e['id']}), was {e['was']}"),
        ("Tasks recorded", "tasksCreated", lambda t: f"{t['title']} (due {t.get('due_at') or 'no date'}, "
                                                     f"priority {t.get('priority')})"),
        ("Mail sent", "mailSent", lambda m: f"to {', '.join(m['to'])} from {m['from']}: \"{m['subject']}\""),
        ("Awaited replies marked answered", "awaitedRepliesClosed", lambda f: f),
    ):
        add(f"**{label}:** {len(changes[key])}")
        for item in changes[key]:
            add(f"- {line(item)}")
        add("")
    add("## The Desk's own briefing")
    add("")
    for brief in result["briefings"]:
        body = brief["briefing"]
        at = oracle.parse(brief["at"]).astimezone(clock.zone).strftime("%a %H:%M")
        add(f"At {at}: \"{body.get('headline')}\"")
        add("")
        add(f"- Counts: `{json.dumps(body.get('counts'))}`")
        add(f"- Needs attention: {len(body.get('needs_attention') or [])} messages listed; "
            f"open tasks listed: {len(body.get('open_tasks') or [])}")
        add(f"- Follow-ups on Desk runs: `{json.dumps(brief.get('followUps'))}`")
        add("")
    add("## Outstanding at the end")
    add("")
    out_ = metrics["outstanding"]
    add(f"- Open tasks: {out_['openTasks']}")
    add(f"- Runs waiting for an approval: {out_['runsAwaitingApproval']}")
    add(f"- Runs handed to the executive: {out_['runsHandedToExecutive']}")
    add(f"- Replies awaited: {len(out_['repliesAwaited'])}")
    for item in out_["repliesAwaited"]:
        add(f"  - {item['waitingOn']} ({item['state']})")
    add("")
    add("## Failures and unknowns")
    add("")
    f = metrics["failures"]
    add(f"- Actions failed at the end of the day: {f['actionsFailedAtEndOfDay']}")
    add(f"- Provider failures injected and hit: {f['providerFailuresInjectedAndHit']}")
    add(f"- Outcomes unknown at the end: {f['outcomesUnknownAtEndOfDay']}")
    add(f"- Executed but not verified by the Desk: {f['executedButNotVerifiedByDesk']}")
    add(f"- Backend errors seen by the simulator: {f['backendErrors']}")
    add("")
    add("## Time and cost")
    add("")
    t, m = metrics["time"], metrics["model"]
    add(f"- The whole day ran in {t['wallSecondsForWholeDay']} s of real time ({t['apiCalls']} API calls). "
        f"Median intake pass: {t['intakePassMsMedian']} ms. {t['note']}")
    add(f"- Model: {m['note']} Estimated cost: "
        f"{m['estimatedCostUsd'] if m['estimatedCostUsd'] is not None else 'not measurable (no model call)'}.")
    add("")
    e = metrics["humanTimeEstimate"]
    add("## Assumption, not a measurement")
    add("")
    add(f"If a human assistant had done the work the oracle confirmed, at the per-item minutes assumed in "
        f"`officesim/jobmodel.py`, it would be about **{e['assistantMinutesForThisWork']} minutes**; the "
        f"executive's decisions in the Desk are assumed at {e['executiveMinutesDecidingInDesk']} minutes. "
        "These figures were written by the simulator's author. They were not measured from a job-holder "
        "and must not be quoted as time saved.")
    add("")
    return "\n".join(out)


def write(result: Mapping[str, Any], out_dir: Path) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = metrics_module.compute(result)

    def dump(name: str, value: Any) -> None:
        (out_dir / name).write_text(json.dumps(value, indent=1, ensure_ascii=False, default=str) + "\n",
                                    encoding="utf-8", newline="\n")

    summary = {
        "simulated": True,
        "profile": result["profile"], "seed": result["seed"], "executive": result["executive"],
        "day": result["spec"]["day"], "officeFingerprint": result["spec"]["fingerprint"],
        "replayFingerprint": result["replayFingerprint"],
        "engine": {"overlay": result["health"].get("version"), "deskBackend": result["meta"].get("deskBackend"),
                   "executionMode": result["health"].get("executionMode"),
                   "externalWritesEnabled": (result["health"].get("externalWrites") or {}).get("enabled"),
                   "modelConfigured": (result["health"].get("model") or {}).get("configured"),
                   "chatScope": result["health"].get("chatScope"), "claims": result["meta"].get("claims")},
        "metrics": metrics,
        "verdicts": {rid: {"subject": result["requests"][rid]["subject"],
                           "sender": result["requests"][rid]["senderEmail"],
                           "expected": result["requests"][rid]["resolved"], **verdict}
                     for rid, verdict in result["verdicts"].items()},
        "notSent": [r for r in result["requests"].values() if r["status"] != "delivered"],
        "decisions": [{k: v for k, v in d.items()} for d in result["decisions"]],
        "checks": result["checks"], "violations": result["violations"], "errors": result["errors"],
        "steps": result["steps"], "gate": result["gate"],
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    dump("summary.json", summary)
    dump("runs.json", result["runs"])
    dump("world-initial.json", result["initialState"])
    dump("world-final.json", result["finalState"])
    dump("briefing.json", result["briefings"])
    (out_dir / "replay.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in result["replay"]),
        encoding="utf-8", newline="\n")
    (out_dir / "report.md").write_text(render(result, metrics), encoding="utf-8", newline="\n")
    return summary
