"""Command line for the office simulator.

Whole days (each starts its own clean sandbox backend and stops it):

    python -m officesim doctor                  what is configured, what is missing
    python -m officesim init                    write the office specification
    python -m officesim profiles                list the day profiles
    python -m officesim run normal              one simulated day, with evidence
    python -m officesim run all                 every profile, plus a combined summary
    python -m officesim demo                    the replayable demonstration
    python -m officesim robustness              replays, restarts, duplicates, bad responses

One step at a time, against a sandbox you keep running:

    python -m officesim serve                   start the sandbox and leave it running
    python -m officesim status                  health, clock, worker, world counts
    python -m officesim clock 2026-11-16T09:00:00+01:00
    python -m officesim inject --from greta --subject "..." --body "..."
    python -m officesim tick                    one pass of the Desk's intake worker
    python -m officesim runs                    the Desk's runs
    python -m officesim show 12                 one run: plan, actions, timeline
    python -m officesim approvals               what is waiting for the executive
    python -m officesim approve 41              the executive approves an action
    python -m officesim reject 41 | retry 41
    python -m officesim state calendar          the sandbox mailbox, calendar or tasks
    python -m officesim briefing                the Desk's briefing

Everything is synthetic and stays on this machine.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import metrics as metrics_module
from . import oracle, report, scenarios
from .adapter import DeskApiError, DeskClient, SandboxServer, load_config, package_root
from .executive import MODES, Executive
from .office import DEFAULT_DAY, DEFAULT_SEED, OfficeClock, build_office, from_header, person
from .runner import Simulation

DEFAULT_PORT = 8914


def work_dir() -> Path:
    path = package_root() / ".work"
    path.mkdir(exist_ok=True)
    return path


def write_spec(day: str, seed: int, path: Optional[Path] = None) -> Path:
    path = path or (work_dir() / "office.json")
    path.write_text(json.dumps(build_office(day, seed), indent=1) + "\n", encoding="utf-8", newline="\n")
    return path


def run_day(profile_id: str, *, seed: int = DEFAULT_SEED, day: str = DEFAULT_DAY, port: int = DEFAULT_PORT,
            out_dir: Optional[Path] = None, executive: str = "attentive", worker: str = "manual",
            quiet: bool = False, observe: Any = None, keep_server: bool = False,
            extra_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One simulated day on a fresh sandbox backend. Returns the result and its summary."""
    profile = scenarios.build(profile_id)
    spec_path = write_spec(day, seed, work_dir() / f"office-{profile_id}.json")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    claims = "memory"
    if profile.get("claims") == "sqlite":
        store = work_dir() / f"claims-{profile_id}.db"
        if store.exists():
            store.unlink()
        claims = f"sqlite:{store}"
    server = SandboxServer(spec_path, port=port, worker=worker, claims=claims,
                           log_path=work_dir() / f"server-{profile_id}.log", extra_env=extra_env)
    narrate = (lambda line: None) if quiet else (lambda line: print(line, flush=True))
    server.start()
    try:
        simulation = Simulation(DeskClient(server.base_url), spec, profile, seed=seed,
                                executive=Executive(executive), narrate=narrate, observe=observe)
        result = simulation.run()
    finally:
        if not keep_server:
            server.stop()
    suffix = "" if executive == "attentive" else f"-{executive}"
    out = Path(out_dir) if out_dir else package_root() / "evidence" / f"{profile_id}{suffix}"
    summary = report.write(result, out)
    return {"result": result, "summary": summary, "out": out, "server": server}


def headline(summary: Dict[str, Any]) -> str:
    m = summary["metrics"]
    r, o, a, f, h = m["requests"], m["outcomes"], m["autonomy"], m["failures"], m["human"]
    return (f"{summary['profile']['name']}: {r['received']} messages, {r['actionable']} actionable; "
            f"{o['completedCorrectly']} done correctly, {o['correctlyHandedToExecutive']} correctly handed "
            f"over, {o['declinedByExecutive']} declined, {o['completedAfterHumanCorrection']} corrected, "
            f"{o['partlyCompleted']} partial, {o['leftForHuman']} left for a human, {o['incorrect']} "
            f"incorrect. Approvals-only: {a['handledWithApprovalsOnly']}/{a['actionableRequests']}. "
            f"Decisions: {h['decisions']}. Checks: {f['checksPassed']} pass, {f['checksFailed']} fail. "
            f"Invariant violations: {f['invariantViolations']}.")


# ── commands ────────────────────────────────────────────────────────────────

def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_config()
    server = SandboxServer(work_dir() / "office.json")
    problems = server.problems()
    print("Configuration (environment, then .officesim.local.json):")
    for key in ("SCRIBA_BACKEND_PATH", "DESK_BACKEND_PATH", "SCRIBA_PYTHON"):
        print(f"  {key} = {config.get(key) or '(not set)'}")
    if problems:
        print("\nThe sandbox backend cannot be started here:")
        for problem in problems:
            print(f"  - {problem}")
        print("\nEverything that needs no backend still works: init, profiles, and the unit tests.")
        return 1
    print("\nThe sandbox backend can be started.")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = write_spec(args.day, args.seed, Path(args.out) if args.out else None)
    spec = json.loads(path.read_text(encoding="utf-8"))
    print(f"Office specification written to {path}")
    print(f"  {spec['executive']['name']}, {spec['executive']['title']}, {spec['organization']['name']}")
    print(f"  week of {spec['day']} ({spec['timezone']}), seed {spec['seed']}, fingerprint {spec['fingerprint']}")
    print(f"  mailboxes: {', '.join(spec['accounts']['gmail'])} (Gmail); {spec['accounts']['outlook']} (Outlook)")
    print(f"  {len(spec['people'])} people, {len(spec['calendar'])} meetings, {len(spec['tasks'])} tasks, "
          f"{len(spec['reminders'])} reminder, {len(spec['followUps'])} replies awaited")
    return 0


def cmd_profiles(args: argparse.Namespace) -> int:
    for profile_id in scenarios.PROFILES:
        profile = scenarios.build(profile_id)
        messages = sum(len(step["emails"]) for step in profile["steps"])
        print(f"{profile_id:15} {profile['name']}: {len(profile['steps'])} steps, {messages} scripted "
              f"messages. {profile['description']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    names = list(scenarios.PROFILES) if args.profile == "all" else [args.profile]
    summaries: Dict[str, Dict[str, Any]] = {}
    for name in names:
        print(f"\n===== {name} (seed {args.seed}, executive {args.executive}) =====", flush=True)
        done = run_day(name, seed=args.seed, day=args.day, port=args.port, executive=args.executive,
                       out_dir=Path(args.out) / name if args.out else None, quiet=args.quiet)
        summaries[name] = done["summary"]
        print(f"\n{headline(done['summary'])}\nEvidence: {done['out']}", flush=True)
    if len(names) > 1:
        combined = metrics_module.combine({name: s["metrics"] for name, s in summaries.items()})
        suffix = "" if args.executive == "attentive" else f"-{args.executive}"
        target = (Path(args.out) if args.out else package_root() / "evidence") / f"all-profiles{suffix}.json"
        target.write_text(json.dumps({
            "simulated": True, "seed": args.seed, "day": args.day, "executive": args.executive,
            "combined": combined,
            "perProfile": {name: {"replayFingerprint": s["replayFingerprint"], "engine": s["engine"],
                                  "headline": headline(s), "metrics": s["metrics"]}
                           for name, s in summaries.items()}}, indent=1) + "\n", encoding="utf-8", newline="\n")
        print("\n===== all profiles =====")
        print(json.dumps(combined, indent=1))
        print(f"Combined summary: {target}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    spec_path = write_spec(args.day, args.seed)
    server = SandboxServer(spec_path, port=args.port, worker=args.worker)
    server.start()
    print(f"Sandbox backend running at {server.base_url} (synthetic office; nothing real behind it).")
    print("Sign in as Scriba's seeded test user alice@example.com (password in Scriba's e2e/seeded_server.py).")
    print("Point the Desk frontend at it with VITE_API_BASE_URL. Ctrl+C to stop.")
    try:
        while server.process is not None and server.process.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def _client(args: argparse.Namespace) -> DeskClient:
    client = DeskClient(args.base)
    client.sign_in("alice@example.com")
    return client


def _print(value: Any) -> None:
    print(json.dumps(value, indent=1, ensure_ascii=False, default=str))


def cmd_status(args: argparse.Namespace) -> int:
    client = _client(args)
    health, meta, state = client.health(), client.sim_meta(), client.sim_state()["world"]
    _print({"simulated": True, "overlay": health.get("version"), "deskBackend": meta.get("deskBackend"),
            "executionMode": health.get("executionMode"),
            "externalWritesEnabled": (health.get("externalWrites") or {}).get("enabled"),
            "modelConfigured": (health.get("model") or {}).get("configured"),
            "clock": state["now"], "timezone": state["timezone"], "worker": client.worker()["worker"],
            "world": {"inbox": sum(len(v) for v in state["mail"].values()), "sent": len(state["sent"]),
                      "events": len(oracle.active_events(state)), "tasks": len(state["tasks"]),
                      "operations": len(state["operations"]),
                      "isolationViolations": state["isolationViolations"]}})
    return 0


def cmd_clock(args: argparse.Namespace) -> int:
    _print(_client(args).sim_clock(args.now))
    return 0


def cmd_inject(args: argparse.Namespace) -> int:
    client = _client(args)
    state = client.sim_state()["world"]
    sender = from_header(args.sender) if "@" not in args.sender else args.sender
    provider = "outlook" if args.to == "outlook" else "gmail"
    account = (state["accounts"]["outlook"] if args.to == "outlook"
               else state["accounts"]["gmail"][1 if args.to == "advisory" else 0])
    message_id = args.id or f"cli-{int(time.time() * 1000)}"
    _print(client.sim_deliver({"provider": provider, "account": account, "message_id": message_id,
                               "from_addr": sender, "subject": args.subject, "body": args.body,
                               "thread_id": args.thread or f"thread-{message_id}"}))
    return 0


def cmd_tick(args: argparse.Namespace) -> int:
    _print(_client(args).sim_worker_tick()["tick"])
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    for row in sorted(_client(args).runs(), key=lambda r: r["runId"]):
        print(f"run {row['runId']:>4}  {row['lifecycle']:<22} {row['category']:<16} "
              f"{json.dumps(row['actionCounts'])}  {row['from_addr']}: {row['subject']}"
              + (f"  [held: {row['held']['reason']}]" if row.get("held") else ""))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    view = _client(args).run(args.run)
    if args.json:
        _print(view)
        return 0
    print(f"Run {view['runId']} (simulated: {view['simulated']}, trigger: {view['trigger']})")
    print(f"  {view['email']['from_addr']}: {view['email']['subject']}")
    print(f"  stage {view['lifecycle']['stage']} ({view['lifecycle']['reason']}); category {view['category']}; "
          f"flags {view['flags']}; held {(view.get('held') or {}).get('reason')}")
    plan = view.get("plan") or {}
    print(f"  plan by {plan.get('planner')}: intents {[i['type'] for i in plan.get('intents') or []]}")
    for fact in plan.get("facts") or []:
        print(f"    fact: {fact}")
    for assumption in plan.get("assumptions") or []:
        print(f"    assumption: {assumption}")
    for step in plan.get("steps") or []:
        print(f"    step {step['id']}: {step['tool']} ({step['purpose']}) depends on {step['dependsOn']}: {step['state']}")
    for action in view.get("actions") or []:
        print(f"  action {action['toolCallId']}: {action['tool_name']} [{action.get('purpose')}] {action['status']}"
              f" verified={action['verified']} attempts={action['attempts']}"
              + (f" error={action['errorCode']}" if action.get("errorCode") else ""))
    for item in view.get("timeline") or []:
        print(f"    {item['at']}  {item['kind']:<12} {item['summary']}")
    return 0


def cmd_approvals(args: argparse.Namespace) -> int:
    client = _client(args)
    found = 0
    for row in sorted(client.runs(), key=lambda r: r["runId"]):
        if not (row.get("actionCounts") or {}).get("awaiting_approval"):
            continue
        for action in client.run(row["runId"])["actions"]:
            if action["status"] == "awaiting_approval":
                found += 1
                data = action["input"]
                detail = {k: data.get(k) for k in ("title", "start", "end", "attendees", "to", "subject",
                                                   "event_id", "due_at", "calendar_provider") if data.get(k)}
                print(f"action {action['toolCallId']} (run {row['runId']}): {action['tool_name']} "
                      f"[{action.get('purpose')}] {json.dumps(detail, ensure_ascii=False)}\n    why: {action.get('reason')}")
    if not found:
        print("Nothing is waiting for the executive.")
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        if args.command == "approve":
            overrides = json.loads(args.overrides) if args.overrides else None
            answer = client.approve(args.action, idempotency_key=f"cli:{args.action}:{int(time.time())}",
                                    payload_overrides=overrides)
        elif args.command == "reject":
            answer = client.reject(args.action)
        else:
            answer = client.retry(args.action)
    except DeskApiError as exc:
        print(f"Refused: {exc}")
        return 1
    card = answer.get("tool_call") or {}
    print(f"action {card.get('id')}: {card.get('tool_name')} is now {card.get('status')}"
          + (f" ({(card.get('output') or {}).get('error_code')})" if (card.get("output") or {}).get("error_code") else ""))
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    state = _client(args).sim_state()["world"]
    zone = OfficeClock(DEFAULT_DAY, state["timezone"]).zone
    if args.section == "calendar":
        for event in state["events"]:
            start = oracle.parse(event["start"]).astimezone(zone)
            print(f"{start.strftime('%a %d %b %H:%M')}-{oracle.parse(event['end']).astimezone(zone).strftime('%H:%M')}"
                  f"  {event['status']:<10} {event['provider']}:{event['account']}  {event['title']}  "
                  f"[{', '.join(event['attendees'])}]  ({event['id']})")
    elif args.section == "inbox":
        for provider, rows in state["mail"].items():
            for row in sorted(rows, key=lambda r: r["timestamp"]):
                print(f"{row['timestamp']}  {provider}:{row['provider_account_id']}  {row['from_addr']}: "
                      f"{row['subject']}  ({row['id']})")
    elif args.section == "sent":
        for row in state["sent"]:
            print(f"{row['sent_at']}  from {row.get('provider_account_id')} to {row['to']}: {row['subject']}\n"
                  f"    {row['text'][:200]}")
    elif args.section == "tasks":
        for task in state["tasks"]:
            print(f"{task['status']:<6} due {task.get('due_at') or '-':<26} {task['title']}  ({task['id']})")
    elif args.section == "operations":
        for op in state["operations"]:
            print(f"{op['seq']:>3} {op['at']}  {op['op']:<24} {op['status']:<9} {op.get('object_id')} "
                  f"{op.get('error') or ''}")
    else:
        _print(state)
    return 0


def cmd_briefing(args: argparse.Namespace) -> int:
    _print(_client(args).briefing())
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from . import demo

    return demo.main(args)


def cmd_robustness(args: argparse.Namespace) -> int:
    from . import robustness

    return robustness.main(args)


def cmd_results(args: argparse.Namespace) -> int:
    from . import results

    return results.main(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="officesim", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def day_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--seed", type=int, default=DEFAULT_SEED)
        p.add_argument("--day", default=DEFAULT_DAY, help="the simulated Monday (YYYY-MM-DD)")
        p.add_argument("--port", type=int, default=DEFAULT_PORT)

    def live(p: argparse.ArgumentParser) -> None:
        p.add_argument("--base", default=f"http://127.0.0.1:{DEFAULT_PORT}")

    sub.add_parser("doctor").set_defaults(run=cmd_doctor)
    sub.add_parser("results").set_defaults(run=cmd_results)
    p = sub.add_parser("init"); day_options(p); p.add_argument("--out"); p.set_defaults(run=cmd_init)
    sub.add_parser("profiles").set_defaults(run=cmd_profiles)
    p = sub.add_parser("run"); day_options(p)
    p.add_argument("profile", choices=[*scenarios.PROFILES, "all"])
    p.add_argument("--executive", choices=MODES, default="attentive")
    p.add_argument("--out"); p.add_argument("--quiet", action="store_true"); p.set_defaults(run=cmd_run)
    p = sub.add_parser("serve"); day_options(p)
    p.add_argument("--worker", choices=("manual", "thread"), default="thread"); p.set_defaults(run=cmd_serve)
    p = sub.add_parser("demo"); day_options(p)
    p.add_argument("--browser", action="store_true", help="also capture screenshots of the Desk frontend")
    p.add_argument("--frontend", help="URL of a running Desk frontend pointed at this sandbox (for --browser)")
    p.add_argument("--step", action="store_true", help="wait for Enter between steps")
    p.add_argument("--out"); p.set_defaults(run=cmd_demo)
    p = sub.add_parser("robustness"); day_options(p); p.add_argument("--out"); p.set_defaults(run=cmd_robustness)

    p = sub.add_parser("status"); live(p); p.set_defaults(run=cmd_status)
    p = sub.add_parser("clock"); live(p); p.add_argument("now"); p.set_defaults(run=cmd_clock)
    p = sub.add_parser("inject"); live(p)
    p.add_argument("--from", dest="sender", required=True, help="a person id from the office, or 'Name <address>'")
    p.add_argument("--subject", required=True); p.add_argument("--body", required=True)
    p.add_argument("--to", choices=("work", "advisory", "outlook"), default="work")
    p.add_argument("--thread"); p.add_argument("--id"); p.set_defaults(run=cmd_inject)
    p = sub.add_parser("tick"); live(p); p.set_defaults(run=cmd_tick)
    p = sub.add_parser("runs"); live(p); p.set_defaults(run=cmd_runs)
    p = sub.add_parser("show"); live(p); p.add_argument("run", type=int)
    p.add_argument("--json", action="store_true"); p.set_defaults(run=cmd_show)
    p = sub.add_parser("approvals"); live(p); p.set_defaults(run=cmd_approvals)
    for name in ("approve", "reject", "retry"):
        p = sub.add_parser(name); live(p); p.add_argument("action", type=int)
        if name == "approve":
            p.add_argument("--overrides", help="JSON of fields the executive changes at approval")
        p.set_defaults(run=cmd_decide)
    p = sub.add_parser("state"); live(p)
    p.add_argument("section", nargs="?", default="all",
                   choices=("all", "calendar", "inbox", "sent", "tasks", "operations")); p.set_defaults(run=cmd_state)
    p = sub.add_parser("briefing"); live(p); p.set_defaults(run=cmd_briefing)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return int(args.run(args) or 0)
    except DeskApiError as exc:
        print(f"The backend refused or did not answer: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
