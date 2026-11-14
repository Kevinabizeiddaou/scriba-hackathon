"""Measure the backend scenarios with a REAL model. Run by hand, never by pytest.

    SCRIBA_BACKEND_PATH=<scriba>/Gmail python backend/eval/run_configured_model.py [--preflight] [--only B01,B02]

The key is read from ``backend/.env.model.local`` (ignored by git) and is
never printed. Everything else is the test harness of
``tests/integration/test_scenarios_with_scriba.py``: the real Scriba
application, in-memory chat storage, an isolated provider world per scenario,
tripwires on every provider client. The only thing that leaves this machine
is the model request, which carries the scenario's synthetic email.

Every model call is counted. A scenario whose understanding call failed falls
back to the rules inside the engine; it is reported as ``model_answered:
false`` and is NOT counted as a model result.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PLACEHOLDERS = ("", "PASTE_KEY_HERE", "test-key", "test", "dummy", "sk-test")


def load_key(path: Path) -> None:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip("\"'")
    if values.get("OPENAI_API_KEY", "") in PLACEHOLDERS:
        sys.exit(f"no real key in {path}")
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        if values.get(name):
            os.environ[name] = values[name]


def bootstrap() -> None:
    scriba = os.environ.get("SCRIBA_BACKEND_PATH", "").strip()
    if not (scriba and (Path(scriba) / "app" / "main.py").is_file()):
        sys.exit("SCRIBA_BACKEND_PATH must name the Gmail/ directory of a Scriba checkout")
    try:
        import dotenv

        dotenv.load_dotenv = lambda *args, **kwargs: False
    except ImportError:
        pass
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/scriba_test?sslmode=disable")
    for name, value in (("DB_POOL_MIN", "0"), ("DB_POOL_TIMEOUT", "2"), ("GMAIL_RECONCILE_ENABLED", "false"),
                        ("CHAT_ANSWER_PASS", "off"), ("AGENT_RELEASE_BACKGROUND_REFRESH", "false")):
        os.environ.setdefault(name, value)
    os.environ["DESK_MODEL"] = "on"
    for path in (str(Path(scriba) / "tests"), scriba, str(BACKEND)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    import contract_harness  # noqa: F401  (pins Scriba's session settings before its modules load)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", default=str(BACKEND / ".env.model.local"))
    parser.add_argument("--preflight", action="store_true", help="one small model call, then stop")
    parser.add_argument("--only", default="")
    parser.add_argument("--out", default=str(BACKEND.parent / "docs" / "handoff" /
                                             "eval-backend-scenarios-configured-model.json"))
    args = parser.parse_args()
    load_key(Path(args.key_file))
    bootstrap()

    from desk_overlay.gateway import ScribaGateway

    calls = []
    real_model_json = ScribaGateway.model_json

    def counted(self, messages, **kwargs):
        entry = {"ok": False, "seconds": None, "error": None, "answer": None}
        calls.append(entry)
        started = time.monotonic()
        try:
            answer = real_model_json(self, messages, **kwargs)
            entry.update(ok=True, answer=answer)
            return answer
        except Exception as error:  # the engine falls back to rules; we record that it did
            entry["error"] = f"{type(error).__name__}: {str(error)[:300]}"
            raise
        finally:
            entry["seconds"] = round(time.monotonic() - started, 2)

    ScribaGateway.model_json = counted

    if args.preflight:
        gateway = ScribaGateway()
        print("model configured:", gateway.model_configured())
        with gateway.model_usage() as usage:
            try:
                answer = gateway.model_json([
                    {"role": "system", "content": "Answer with the JSON object {\"ok\": true}."},
                    {"role": "user", "content": "ping"}], max_tokens=50)
                print("answer:", answer)
            except Exception as error:
                print("FAILED:", type(error).__name__, str(error)[:500])
        print("usage:", json.dumps(usage, default=str))
        return

    from tests.integration import test_scenarios_with_scriba as T

    import logging

    logging.disable(logging.INFO)
    # The harness polls for under a second, enough for a scripted answer. A
    # real model takes seconds: poll for up to four minutes per scenario.
    quick_drive = T.drive
    T.drive = lambda desk, body, decision="approve": quick_drive(desk, body, decision=decision, limit=12000)

    wanted = {name.strip() for name in args.only.split(",") if name.strip()}
    results = []
    for scenario in T.SCENARIOS:
        if wanted and scenario["id"] not in wanted:
            continue
        before, problem = len(calls), None
        started = time.monotonic()
        try:
            run, approvals, world = T.run_scenario(scenario, "configured_model")
            T._RESULTS["configured_model"].append(T.measure(scenario, run, approvals, world))
            if world.violations:
                problem = f"isolation violations: {world.violations}"
        except AssertionError as error:
            problem = f"assertion: {str(error)[:400]}"
        except Exception as error:
            problem = f"{type(error).__name__}: {str(error)[:400]}"
        mine = calls[before:]
        measured = T._RESULTS["configured_model"]
        result = dict(measured[-1]) if measured and measured[-1]["id"] == scenario["id"] else {
            "id": scenario["id"], "category": scenario["category"], "title": scenario["title"]}
        result.update(model_calls=len(mine), model_answered=bool(mine) and all(c["ok"] for c in mine),
                      model_errors=[c["error"] for c in mine if c["error"]],
                      model_seconds=round(sum(c["seconds"] or 0 for c in mine), 2),
                      model_answers=[c["answer"] for c in mine if c["ok"]],
                      wall_seconds=round(time.monotonic() - started, 2), harness_problem=problem)
        results.append(result)
        good = all(result.get(key) for key in ("intent_ok", "plan_ok", "outcome_ok", "flags_ok"))
        print(f"{scenario['id']:5} calls={len(mine)} answered={result['model_answered']} "
              f"{'correct' if good else 'NOT correct'} intent={result.get('intent')} outcome={result.get('outcome')}"
              f"{' unsafe=' + str(result['unsafe']) if result.get('unsafe') else ''}"
              f"{' PROBLEM ' + problem if problem else ''}", flush=True)

    answered = [r for r in results if r["model_answered"] and "intent_ok" in r]
    models = sorted({str(entry.get("model") if isinstance(entry, dict) else entry)
                     for r in results for entry in ((r.get("usage") or {}).get("models") or [])})
    priced = [(r.get("usage") or {}).get("estimatedCostUsd") for r in results]
    report = {
        "format": "desk.backend-scenarios.configured-model/1",
        "ranAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "models": models, "scenarios": len(results), "model_answered": len(answered),
        "model_calls": len(calls), "model_call_failures": sum(1 for c in calls if not c["ok"]),
        "total_cost_usd": sum(priced) if priced and all(p is not None for p in priced) else None,
        "median_model_seconds": sorted(r["model_seconds"] for r in results)[len(results) // 2] if results else None,
        "summary_all": T.summarize([r for r in results if "intent_ok" in r]),
        "summary_model_answered_only": T.summarize(answered),
        "harness_problems": [{"id": r["id"], "problem": r["harness_problem"]} for r in results if r["harness_problem"]],
        "results": results,
    }
    if not wanted:
        Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        print("written:", args.out)
    print(json.dumps({key: report[key] for key in report if key != "results"}, indent=1, default=str))


if __name__ == "__main__":
    main()
