"""Robustness and repeatability: the same things again, things twice, things
going wrong.

    python -m officesim robustness

Runs on fresh sandbox backends and writes ``evidence/robustness/``:

    robustness.json     every case with what was observed
    robustness.md       the same, for a person
    replay-a.jsonl, replay-b.jsonl   two replays of the same day, line by line

A case passes or fails on what the world and the Desk's evidence show. A
case that cannot be run here is reported as NOT RUN with the reason; it is
never counted as passed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import oracle, scenarios
from .adapter import DeskApiError, DeskClient, SandboxServer, package_root
from .executive import Executive
from .fakes import FakeDesk
from .office import DEFAULT_DAY, DEFAULT_SEED, OfficeClock, build_office, fingerprint, from_header
from .runner import Simulation

MEI = ("Hi Layla, would you be free on Wednesday at 14:00 for a 30 minute call to walk through the new "
       "cold-chain lanes?")


class Cases:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def add(self, name: str, passed: Optional[bool], detail: str, **data: Any) -> None:
        status = "NOT RUN" if passed is None else ("pass" if passed else "FAIL")
        self.rows.append({"case": name, "status": status, "detail": detail, **data})
        print(f"  [{status}] {name}: {detail}", flush=True)


def _mail(client: DeskClient, spec: Dict[str, Any], message_id: str, sender: str, subject: str, body: str,
          thread: Optional[str] = None) -> Dict[str, Any]:
    return client.sim_deliver({"provider": "gmail", "account": spec["accounts"]["gmail"][0],
                               "message_id": message_id, "from_addr": from_header(sender), "subject": subject,
                               "body": body, "thread_id": thread or f"thread-{message_id}"})


def _opened(tick: Dict[str, Any]) -> int:
    return int((((tick.get("tick") or {}).get("users") or [{}])[0]).get("opened") or 0)


def live_cases(cases: Cases, *, port: int, day: str, seed: int, work: Path) -> None:
    """Cases that need one fresh sandbox, played in order on the same world."""
    from .cli import write_spec

    spec_path = write_spec(day, seed, work / "office-robustness.json")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    clock = OfficeClock(day, spec["timezone"])
    with SandboxServer(spec_path, port=port, log_path=work / "server-robustness.log") as server:
        client = DeskClient(server.base_url)
        client.sign_in(spec["scribaUser"])
        client.sim_clock(clock.iso(0, "08:30"))

        # ── an empty inbox ──────────────────────────────────────────────────
        tick = client.sim_worker_tick()
        brief = client.briefing()
        cases.add("empty inbox", _opened(tick) == 0 and client.runs() == [] and not brief.get("unavailable"),
                  f"a worker pass over no mail opened {_opened(tick)} runs; runs listed: {len(client.runs())}; "
                  f"the briefing answered \"{brief.get('headline')}\" with unavailable={brief.get('unavailable')}")

        # ── the same event repeated ─────────────────────────────────────────
        _mail(client, spec, "rb-mei", "mei", "Cold-chain lanes: intro call", MEI)
        first = _opened(client.sim_worker_tick())
        run_id = client.runs()[0]["runId"]
        again = client.intake("gmail", "rb-mei")
        second_tick = _opened(client.sim_worker_tick())
        sweep = client.sweep()
        notify = client.sim_deliver({"provider": "gmail", "message_id": "rb-mei",
                                     "from_addr": from_header("mei"), "subject": "x", "body": "x"})
        cases.add("the same message taken in again",
                  first == 1 and again.get("duplicate") is True and again.get("runId") == run_id
                  and second_tick == 0 and not sweep["opened"] and len(client.runs()) == 1
                  and notify.get("duplicateNotification") is True,
                  f"first pass opened {first} run ({run_id}); POST /desk/intake again returned run "
                  f"{again.get('runId')} with duplicate={again.get('duplicate')}; a second worker pass opened "
                  f"{second_tick}; a manual sweep opened {len(sweep['opened'])}; the mailbox ignored a second "
                  f"notification: {notify.get('duplicateNotification')}; runs in total: {len(client.runs())}")

        # ── the model step when no model is configured ──────────────────────
        view = client.run(run_id)
        reads = [(e["data"].get("tool"), e["data"].get("ok"), e["data"].get("error"))
                 for e in view["timeline"] if e["kind"] == "read"]
        model_read = next((r for r in reads if r[0] == "model.extract_request"), None)
        configured = bool((client.health().get("model") or {}).get("configured"))
        if configured:
            cases.add("incomplete model results", None,
                      "a model is configured in this process; this case covers the no-model fallback only")
        else:
            cases.add("no model answer: the rules take over, and the run says so",
                      model_read == ("model.extract_request", False, "model_not_configured")
                      and (view["plan"] or {}).get("planner") == "rules" and view["usage"] is None,
                      f"the run records {model_read}; planner={((view['plan'] or {}).get('planner'))}; "
                      f"usage={view['usage']} (null, not zero)")
            cases.add("incomplete model results (a model that answers nothing, or half an answer)", None,
                      "NOT RUN: no model is configured in this environment, so a real partial model answer "
                      "cannot be produced. The engine's own tests script that case.")

        # ── a duplicate email: the same request as a new message ───────────
        _mail(client, spec, "rb-mei-copy", "mei", "Cold-chain lanes: intro call", MEI, thread="thread-rb-mei")
        client.sim_worker_tick()
        cards = {}
        for row in client.runs():
            for action in client.run(row["runId"])["actions"]:
                if action["tool_name"] == "create_calendar_event":
                    cards[row["email_id"]] = action["toolCallId"]
        one = client.approve(cards["rb-mei"], idempotency_key="rb:1")["tool_call"]
        two = client.approve(cards["rb-mei-copy"], idempotency_key="rb:2")["tool_call"] \
            if "rb-mei-copy" in cards else {}
        state = client.sim_state()["world"]
        events = [e for e in oracle.active_events(state) if "mei.tanaka@brightwavefoods.example" in e["attendees"]]
        cases.add("a duplicate email, both proposals approved",
                  one.get("status") == "executed" and len(events) == 1
                  and (not two or two.get("status") != "executed"),
                  f"first approval: {one.get('status')}; second approval: {two.get('status')} "
                  f"({(two.get('output') or {}).get('error_code')}); meetings with the sender on the "
                  f"calendar: {len(events)}")
        _mail(client, spec, "rb-mei-third", "mei", "Cold-chain lanes: intro call", MEI, thread="thread-rb-mei")
        client.sim_worker_tick()
        third = next(client.run(r["runId"]) for r in client.runs() if r["email_id"] == "rb-mei-third")
        cases.add("the request again after it was booked",
                  (third.get("held") or {}).get("reason") == "already_scheduled" and not third["actions"],
                  f"held: {(third.get('held') or {}).get('reason')}; actions proposed: {len(third['actions'])}; "
                  f"flags: {third.get('flags')}")

        # ── a missing calendar ──────────────────────────────────────────────
        advisory = spec["accounts"]["gmail"][1]
        client.sim_unreadable(f"google:{advisory}", "not_found")
        _mail(client, spec, "rb-jonas", "jonas", "Pipeline numbers",
              "Layla, could we meet on Thursday at 15:00 for 30 minutes to go through the pipeline numbers?")
        client.sim_worker_tick()
        held = next(client.run(r["runId"]) for r in client.runs() if r["email_id"] == "rb-jonas")
        before = len(client.sim_state()["world"]["operations"])
        cases.add("a calendar that is missing",
                  (held.get("held") or {}).get("reason") == "availability_unknown" and not held["actions"],
                  f"with one Google calendar answering not_found the run is held as "
                  f"{(held.get('held') or {}).get('reason')}, proposes {len(held['actions'])} actions, and "
                  f"the world has {before} operations (unchanged by this request)")
        client.sim_unreadable(f"google:{advisory}", None)

        # ── a meeting deleted behind the Desk's back ────────────────────────
        _mail(client, spec, "rb-priya", "priya", "Our 1:1 today",
              "Layla, could we move our 1:1 to today at 16:30? My terminal walk-through is running over.")
        client.sim_worker_tick()
        move = next(client.run(r["runId"]) for r in client.runs() if r["email_id"] == "rb-priya")
        card = next((a["toolCallId"] for a in move["actions"] if a["tool_name"] == "update_calendar_event"), None)
        if card is None:
            cases.add("a meeting deleted before the approval", False,
                      f"no move was proposed (held: {(move.get('held') or {}).get('reason')})")
        else:
            client.sim_remove_event("evt-priya-1on1")
            try:
                answer = client.approve(card, idempotency_key="rb:3")["tool_call"]
                outcome = f"{answer.get('status')} ({(answer.get('output') or {}).get('error_code') or answer.get('error')})"
                executed = answer.get("status") == "executed"
            except DeskApiError as exc:
                outcome, executed = f"HTTP {exc.status}", False
            after = client.run(move["runId"])
            cases.add("a meeting deleted before the approval",
                      not executed and after["lifecycle"]["stage"] != "COMPLETED"
                      and not any(a["tool_name"] == "send_email" for a in after["actions"]),
                      f"approving the move of a meeting that no longer exists: {outcome}; the run rests in "
                      f"{after['lifecycle']['stage']}; confirmations proposed: "
                      f"{sum(1 for a in after['actions'] if a['tool_name'] == 'send_email')}")

        # ── a restart ───────────────────────────────────────────────────────
        runs_before = sorted(r["runId"] for r in client.runs())
        client.sim_worker_restart()
        opened = _opened(client.sim_worker_tick())
        runs_after = sorted(r["runId"] for r in client.runs())
        cases.add("a worker restart (in-memory claims)", opened == 0 and runs_before == runs_after,
                  f"{len(runs_before)} runs before, {len(runs_after)} after; the first pass after the "
                  f"restart opened {opened}. (The unreliable day repeats this with claims on a file.)")

        state = client.sim_state()["world"]
        cases.add("sandbox isolation held throughout", not state["isolationViolations"],
                  f"real provider clients reached: {state['isolationViolations'] or 'none'}")


def replay_cases(cases: Cases, *, port: int, day: str, seed: int, out: Path) -> None:
    """The same day twice, then with another seed."""
    from .cli import run_day

    a = run_day("normal", seed=seed, day=day, port=port, quiet=True, out_dir=out / "replay-a")["result"]
    b = run_day("normal", seed=seed, day=day, port=port, quiet=True, out_dir=out / "replay-b")["result"]
    same_world = a["replay"][0]["worldFingerprint"] == b["replay"][0]["worldFingerprint"]
    cases.add("the same seed gives the same initial office",
              same_world and a["spec"]["fingerprint"] == b["spec"]["fingerprint"],
              f"office specification {a['spec']['fingerprint']} twice; the sandbox world as built from it: "
              f"{a['replay'][0]['worldFingerprint']} and {b['replay'][0]['worldFingerprint']}")
    differences = [(x, y) for x, y in zip(a["replay"], b["replay"]) if x != y]
    identical = a["replayFingerprint"] == b["replayFingerprint"]
    detail = (f"{len(a['replay'])} log entries each; fingerprints {a['replayFingerprint']} and "
              f"{b['replayFingerprint']}")
    if not identical:
        first = differences[0] if differences else ({"len": len(a["replay"])}, {"len": len(b["replay"])})
        detail += f"; {len(differences)} entries differ; the first: {json.dumps(first[0])[:300]} vs " \
                  f"{json.dumps(first[1])[:300]}"
    cases.add("replaying a complete day reproduces it", identical, detail,
              variance={"entriesCompared": min(len(a["replay"]), len(b["replay"])),
                        "entriesDiffering": len(differences)})
    verdict_a = {k: v["verdict"] for k, v in a["verdicts"].items()}
    verdict_b = {k: v["verdict"] for k, v in b["verdicts"].items()}
    cases.add("the verdicts are the same on replay", verdict_a == verdict_b,
              f"{len(verdict_a)} verdicts; differing: "
              f"{[k for k in verdict_a if verdict_a[k] != verdict_b.get(k)] or 'none'}")
    c = run_day("normal", seed=seed + 1, day=day, port=port, quiet=True, out_dir=out / "replay-other-seed")["result"]
    verdict_c = {k: v["verdict"] for k, v in c["verdicts"].items()}
    cases.add("another seed: the same office, other arrival seconds and counterpart choices",
              c["replay"][0]["worldFingerprint"] == a["replay"][0]["worldFingerprint"],
              f"world {c['replay'][0]['worldFingerprint']} (same); replay {c['replayFingerprint']} "
              f"({'same' if c['replayFingerprint'] == a['replayFingerprint'] else 'different, as expected'}); "
              f"verdicts that changed with the seed: "
              f"{[k for k in verdict_a if verdict_a[k] != verdict_c.get(k)] or 'none'}",
              variance={"verdictsChangedWithSeed": [k for k in verdict_a if verdict_a[k] != verdict_c.get(k)]})
    import shutil

    for name in ("replay-a", "replay-b", "replay-other-seed"):
        if name != "replay-other-seed":
            (out / f"{name}.jsonl").write_text((out / name / "replay.jsonl").read_text(encoding="utf-8"),
                                               encoding="utf-8", newline="\n")
        shutil.rmtree(out / name, ignore_errors=True)      # the two replay logs are what is kept


def profile_cases(cases: Cases, *, port: int, day: str, seed: int) -> None:
    """Cases the day profiles already exercise: run them and read their checks."""
    from .cli import run_day

    wanted = {
        "unreliable": {
            "duplicate_notification_one_run": "a duplicate notification",
            "restart_opens_no_duplicate_runs": "a worker restart (claims reopened from a file)",
            "interrupted_action_is_settled_then_takes_effect_once": "an interruption in the middle of an approved action",
            "partial_success_reported_as_partial": "a partial provider failure",
            "unknown_outcome_is_read_back_not_repeated": "an uncertain outcome",
        },
        "human_in_loop": {"invalid_approvals_change_nothing": "invalid approvals"},
        "follow_up": {"overdue_follow_up_is_chased": "an unanswered follow-up",
                      "reminder_is_not_repeated": "an unanswered follow-up: no second reminder"},
    }
    for profile, checks in wanted.items():
        result = run_day(profile, seed=seed, day=day, port=port, quiet=True)["result"]
        for check, label in checks.items():
            found = [c for c in result["checks"] if c["check"] == check]
            if not found:
                cases.add(label, None, f"NOT RUN: the {profile} day never reached this check")
                continue
            cases.add(label, all(c["passed"] for c in found),
                      " | ".join(c["detail"] for c in found), profile=profile, steps=[c["stepId"] for c in found])
        cases.add(f"safety invariants during the {profile} day", not result["violations"],
                  f"violations: {result['violations'] or 'none'}")


def simulator_cases(cases: Cases, *, seed: int) -> None:
    """The simulator itself, against a backend that misbehaves or does nothing."""
    spec = build_office()
    profile = scenarios.build("normal")
    profile = {**profile, "steps": profile["steps"][:4]}

    with FakeDesk(spec) as fake:
        result = Simulation(DeskClient(fake.base_url), spec, profile, seed=seed, executive=Executive()).run()
    verdicts = {v["verdict"] for rid, v in result["verdicts"].items() if result["requests"][rid]["needsWork"]}
    cases.add("a backend that does nothing earns nothing", verdicts == {"missed"},
              f"against a stand-in that never opens a run, the actionable requests are judged: {sorted(verdicts)}")

    def fail_second(count: int) -> Any:
        return (500, {"detail": "boom"}) if count == 2 else None

    def garbage(count: int) -> Any:
        return (200, b"<html>not json</html>") if count == 3 else None

    broken = {("POST", "/sim/worker/tick"): fail_second, ("GET", "/desk/runs"): garbage}
    with FakeDesk(spec, broken=broken) as fake:
        result = Simulation(DeskClient(fake.base_url), spec, profile, seed=seed, executive=Executive()).run()
    cases.add("an unexpected backend response",
              len(result["errors"]) >= 1 and len(result["steps"]) == len(profile["steps"])
              and len(result["verdicts"]) >= 1,
              f"a 500 and a non-JSON answer were injected; the runner recorded {len(result['errors'])} "
              f"backend error(s) ({'; '.join(e['error'][:80] for e in result['errors'])}), played all "
              f"{len(result['steps'])} steps and still produced {len(result['verdicts'])} verdicts")


def main(args: argparse.Namespace) -> int:
    from .cli import work_dir

    out = Path(args.out) if args.out else package_root() / "evidence" / "robustness"
    out.mkdir(parents=True, exist_ok=True)
    cases = Cases()
    groups: List[tuple] = [
        ("Repeatability", lambda: replay_cases(cases, port=args.port, day=args.day, seed=args.seed, out=out)),
        ("Repeats, duplicates, missing things", lambda: live_cases(
            cases, port=args.port, day=args.day, seed=args.seed, work=work_dir())),
        ("Failures the day profiles exercise", lambda: profile_cases(
            cases, port=args.port, day=args.day, seed=args.seed)),
        ("The simulator against a broken backend", lambda: simulator_cases(cases, seed=args.seed)),
    ]
    sections: Dict[str, List[Dict[str, Any]]] = {}
    for title, run in groups:
        print(f"\n== {title}", flush=True)
        start = len(cases.rows)
        try:
            run()
        except Exception as exc:              # a group that cannot run is a failed case, not a crash
            cases.add(f"{title} (group aborted)", False, f"{type(exc).__name__}: {exc}")
        sections[title] = cases.rows[start:]

    counts = {status: sum(1 for r in cases.rows if r["status"] == status) for status in ("pass", "FAIL", "NOT RUN")}
    payload = {"simulated": True, "seed": args.seed, "day": args.day, "counts": counts, "sections": sections}
    (out / "robustness.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")
    lines = ["# Robustness and repeatability", "",
             "> **SIMULATED.** Fresh sandbox backends, a fictional office, no provider.", "",
             f"Seed {args.seed}, week of {args.day}. **{counts['pass']} passed, {counts['FAIL']} failed, "
             f"{counts['NOT RUN']} not run.** A case that could not be run is not a pass.", ""]
    for title, rows in sections.items():
        lines += [f"## {title}", "", "| Case | Result | What was observed |", "| --- | --- | --- |"]
        lines += [f"| {r['case']} | {'**FAIL**' if r['status'] == 'FAIL' else r['status']} | "
                  f"{r['detail'].replace('|', '/')} |" for r in rows]
        lines.append("")
    (out / "robustness.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"\n{counts['pass']} passed, {counts['FAIL']} failed, {counts['NOT RUN']} not run. Written to {out}")
    return 0 if counts["FAIL"] == 0 else 1
