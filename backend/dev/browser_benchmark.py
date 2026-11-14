"""Benchmark of the Desk's browser tool on the synthetic supplier portal.

    python backend/dev/browser_benchmark.py <scriba backend path> [--reps 20] [--write]

Everything is local and synthetic: a headless Chromium with no profile, the
portal of ``supplier_portal.py`` on 127.0.0.1, a made-up account. No model is
called anywhere, so "model calls" is 0 by construction, not by measurement.

Three ways of doing the same work are timed:

``desk``           the Desk's tool as it runs: page kept between tasks, waits
                   on the page, locators kept from earlier runs where they fit.
``desk, looking``  the same with nothing kept: every control looked up again.
``extension policy``  the comparison. The same steps as a Scriba recording
                   (fixed locators), applied by Scriba's own page player, and
                   driven the way the extension's service worker drives a tab:
                   a new tab per task, wait for the full page load, a fixed
                   500 ms pause after every click. This is that policy
                   re-created over the DevTools protocol. It is NOT the
                   extension in a person's Chrome, whose 30-second job poll
                   and server round trips are not in these numbers.

``--write`` puts the result in docs/handoff/BROWSER_BENCHMARK.md and .json.
"""
from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
from typing import Any, Callable, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import supplier_portal as sp  # noqa: E402

PHONE = "+961 1 555 0199"
FORBIDDEN = ("/subscribe", "/verify-password", "/profile/delete")


def site_of(portal: Any) -> Dict[str, Any]:
    return {"id": "bench", "name": "Northwind supplier portal", "origin": portal.origin, "synthetic": True,
            "start": "/home", "signIn": {"path": "/login", "synthetic": True, "submit": "Sign in",
                                         "fields": {"Email": sp.ACCOUNT, "Password": sp.ACCOUNT_PASSWORD}}}


READ = {"goal": "Read the latest report's figures", "ops": [
    {"op": "open", "path": "/home"}, {"op": "follow", "name": "Reports"},
    {"op": "follow", "name": "quarterly report", "pick": "latest"},
    {"op": "read", "label": "Period", "name": "period"}, {"op": "read", "label": "Total", "name": "total"}]}
FETCH = {"goal": "Download the latest report", "ops": READ["ops"][:4] + [
    {"op": "download", "name": "Download", "kind": "xlsx", "checksum": "SHA-256"}]}
UPDATE = {"goal": "Update the phone number", "ops": [
    {"op": "open", "path": "/profile"}, {"op": "fill", "fields": {"Phone": PHONE}},
    {"op": "submit", "name": "Save changes", "expect": {"check": "text_present", "text": "Saved"},
     "readback": {"path": "/profile", "fields": {"Phone": PHONE}}}]}
FORM = {"goal": "Open a service request", "ops": [
    {"op": "open", "path": "/requests/new"},
    {"op": "fill", "fields": {"Category": "billing", "Subject": "Duplicate invoice"}},
    {"op": "submit", "name": "Continue", "expect": {"check": "text_present", "text": "step 2 of 3"}},
    {"op": "fill", "fields": {"Details": "Issued twice.", "Needed by": "2026-11-30"}},
    {"op": "submit", "name": "Continue", "expect": {"check": "text_present", "text": "review"}},
    {"op": "submit", "name": "Submit request", "expect": {"check": "text_present", "text": "Request received"},
     "readback": {"path": "/requests", "text": "Duplicate invoice"}}]}
FIND = {"goal": "Find an invoice", "ops": [
    {"op": "open", "path": "/invoices"},
    {"op": "find_row", "table": "Invoices", "match": "INV-2026-0142", "name": "invoice"}]}


def good_fetch(result: Dict[str, Any], portal: Any) -> bool:
    return bool(result["downloads"]) and result["downloads"][0]["sha256"] == portal.sha256("q3-2026")


def good_read(result: Dict[str, Any], portal: Any) -> bool:
    return result["values"] == {"period": "Q3 2026", "total": "1930"}


def good_update(result: Dict[str, Any], portal: Any) -> bool:
    return portal.profile["phone"] == PHONE and len(portal.requests_for("/profile", "POST")) == 1


# name, task, what is switched on before the timed run, what "correct" means, does it recover from something
SCENARIOS: List[Dict[str, Any]] = [
    {"id": "retrieve_document", "title": "Navigate and read a document's figures", "task": READ, "good": good_read},
    {"id": "download_verify", "title": "Download a file and verify it", "task": FETCH, "good": good_fetch},
    {"id": "multi_page_form", "title": "Complete a form over three pages", "task": FORM, "write": True,
     "good": lambda r, p: len(p.requests) == 1 and p.requests[0]["subject"] == "Duplicate invoice"
     and len(p.requests_for("/requests/submit", "POST")) == 1},
    {"id": "find_across_pages", "title": "Find a value across the pages of a table", "task": FIND,
     "good": lambda r, p: (r["values"].get("invoice") or {}).get("Amount") == str(sp.INVOICES[12]["amount"])},
    {"id": "update_portal", "title": "Update information on the portal", "task": UPDATE, "write": True,
     "good": good_update},
    {"id": "recover_timeout", "title": "Recover from one slow answer", "task": READ, "good": good_read,
     "recovers": True, "navigation_seconds": 1.0,
     "setup": lambda p: p.fault("/reports", "hang", seconds=1.6, times=1)},
    {"id": "changed_layout", "title": "The page layout changed since last time", "task": FETCH, "good": good_fetch,
     "recovers": True, "learn_first": True, "setup": lambda p: p.set(layout="b", delay_ms=150)},
    {"id": "popup_modal", "title": "A dialog is in the way", "task": FETCH, "good": good_fetch, "recovers": True,
     "setup": lambda p: p.set(modal=True)},
    {"id": "misleading_site", "title": "A decoy download and a password prompt", "task": FETCH, "good": good_fetch,
     "setup": lambda p: p.set(lure=p.lure_origin)},
    {"id": "prompt_injection", "title": "Pages carry text written to an assistant", "task": FETCH,
     "good": lambda r, p: good_fetch(r, p) and len(r["untrustedFindings"]) >= 2,
     "setup": lambda p: p.set(injection=True)},
    {"id": "uncertain_write", "title": "A submission that gets no answer", "task": UPDATE, "write": True,
     "good": good_update, "recovers": True, "setup": lambda p: p.fault("/profile", "drop_after_write")},
    {"id": "resume_interrupted", "title": "The browser dies mid-task; the task is taken up again", "task": FETCH,
     "good": good_fetch, "recovers": True, "kill_after": 2},
]


def unsafe(portal: Any) -> int:
    """Things that must never happen, counted from the portal's own log."""
    posts = [entry for entry in portal.log if entry["method"] == "POST"]
    count = len(portal.lure_hits) + sum(1 for e in posts if e["path"].startswith(FORBIDDEN))
    count += max(0, len([e for e in posts if e["path"] == "/profile"]) - 1)             # a write made twice
    count += max(0, len([e for e in posts if e["path"] == "/requests/submit"]) - 1)
    return count


def summary(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"median": None, "p95": None, "n": 0}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, max(0, int(round(0.95 * len(ordered) + 0.5)) - 1))]
    return {"median": round(statistics.median(ordered), 1), "p95": round(p95, 1), "n": len(ordered)}


def run_desk(browser: Any, sessions: Any, scenario: Dict[str, Any], rep: int, *, use_learned: bool) -> Dict[str, Any]:
    portal, stop = sp.start(with_lure=True)
    owner = f"{scenario['id']}-{rep}-{use_learned}"
    try:
        session = sessions.session(owner, site_of(portal))
        task = scenario["task"]
        # Signed in and warm, as the second task of a day would find it. Not timed.
        warm = browser.run_task(session, task if scenario.get("learn_first") else {"ops": [{"op": "open", "path": "/home"}]},
                                use_learned=use_learned)
        assert warm["state"] in ("VERIFIED", "COMPLETED"), warm
        portal.log.clear()
        if scenario.get("setup"):
            scenario["setup"](portal)
        options: Dict[str, Any] = {"use_learned": use_learned}
        if scenario.get("write"):
            options["approval"] = browser.binding(session.site, browser.validate(task)[0])
        if scenario.get("navigation_seconds"):
            browser.NAVIGATION_SECONDS = scenario["navigation_seconds"]
        began = time.perf_counter()
        if scenario.get("kill_after"):
            def record(step: Dict[str, Any]) -> None:
                if step.get("index") == scenario["kill_after"] and step.get("state") == "done":
                    sessions.browser.kill()
            first = browser.run_task(session, task, record=record, **options)
            assert first["state"] == "INTERRUPTED", first["state"]
            result = browser.run_task(session, task, **options)
            result["actions"] += first["actions"]
        else:
            result = browser.run_task(session, task, **options)
        elapsed = (time.perf_counter() - began) * 1000
        done = result["state"] in ("VERIFIED", "COMPLETED")
        correct = done and bool(scenario["good"](result, portal))
        return {"ms": elapsed, "completed": done, "correct": correct, "falseSuccess": done and not correct,
                "unsafe": unsafe(portal), "actions": result["actions"], "state": result["state"],
                "recovered": sorted({r.split(":")[0] for s in result["steps"] for r in s.get("recovered") or []}),
                "steps": [(s["op"], s.get("ms")) for s in result["steps"]]}
    finally:
        browser.NAVIGATION_SECONDS = 15.0
        sessions.forget(owner)
        stop()


# ── the comparison: Scriba's recording, the extension's waiting policy ───────
def recording(portal: Any, which: str) -> List[Dict[str, Any]]:
    link = lambda text, **more: {"action": "click", "locator": {"tag": "a", "text": text, **more}}   # noqa: E731
    if which == "read":
        return [{"action": "goto", "url": portal.origin + "/home"}, link("Reports", href="/reports"),
                {"action": "click", "locator": {"id": "open-q3-2026", "tag": "a", "text": "Q3 2026 quarterly report"}},
                {"action": "extract", "name": "period", "locator": {"id": "period"}},
                {"action": "extract", "name": "total", "locator": {"id": "total"}}]
    return [{"action": "goto", "url": portal.origin + "/profile"},
            {"action": "fill", "locator": {"name": "phone"}, "text": PHONE},
            {"action": "click", "locator": {"tag": "button", "text": "Save changes"}},
            {"action": "verify", "check": "text_present", "text": "Saved"}]


def run_extension_policy(cdp: Any, sessions: Any, scenario: Dict[str, Any], rep: int, which: str) -> Dict[str, Any]:
    """Scriba's player and steps, driven as ``browser_extension/sw.js`` drives a tab."""
    from app.services import web_steps

    portal, stop = sp.start(with_lure=True)
    owner = f"ext-{scenario['id']}-{rep}"
    allow = lambda url: url.startswith(portal.origin + "/") or url == portal.origin     # noqa: E731
    page = None
    try:
        # The person is signed in already (their own profile, in the extension's case). Not timed.
        first = sessions.browser.page(owner, allow, sessions.bundle)
        first.goto(portal.origin + "/login")
        for step in ({"action": "fill", "locator": {"name": "email"}, "text": sp.ACCOUNT},
                     {"action": "fill", "locator": {"name": "password"}, "text": sp.ACCOUNT_PASSWORD}):
            first.call_function("__scriba.applyStep", step, [portal.origin])
        marks = first.marks()
        first.call_function("__scriba.applyStep", {"action": "click", "locator": {"tag": "button", "text": "Sign in"}},
                            [portal.origin])
        first.settle(marks)
        first.close()
        portal.log.clear()
        if scenario.get("setup"):
            scenario["setup"](portal)
        steps = web_steps.sanitize_web_steps(recording(portal, which))
        origins = web_steps.web_allow_origins(steps)
        began = time.perf_counter()
        page = sessions.browser.page(owner, allow, sessions.bundle)            # sw.js: a new tab for every replay
        extracted: Dict[str, Any] = {}
        failed, actions, checks_failed = None, 0, 0
        for step in steps:
            if step["action"] == "goto":
                loads = page._full_loads
                page.goto(step["url"])
                page._wait(lambda: page._full_loads > loads, 15.0, "The page load")      # waitForTabComplete
                continue
            try:
                out = page.call_function("__scriba.applyStep", step, origins, timeout=20.0)
            except cdp.BrowserError as error:
                failed = str(error)[:120]
                break
            if not out or out.get("error"):
                failed = (out or {}).get("error") or "The page could not be driven."
                break
            actions += 1
            if out.get("extracted"):
                extracted[out["extracted"]["name"]] = out["extracted"]["value"]
            if out.get("needsReview"):
                checks_failed += 1
            if step["action"] in ("click", "key"):                                      # sw.js settle()
                loads = page._full_loads
                time.sleep(0.5)
                if page.marks()[1] > 0 and page._full_loads == loads and page._world is None:
                    page._wait(lambda: page._full_loads > loads, 15.0, "The page load")
                page.wait_ready(15.0)
        elapsed = (time.perf_counter() - began) * 1000
        done = failed is None and checks_failed == 0
        correct = done and (extracted == {"period": "Q3 2026", "total": "1930"} if which == "read"
                            else good_update({}, portal))
        return {"ms": elapsed, "completed": done, "correct": correct, "falseSuccess": done and not correct,
                "unsafe": unsafe(portal), "actions": actions, "state": "done" if done else "failed",
                "error": failed, "recovered": [], "steps": []}
    finally:
        if page is not None:
            page.close()
        sessions.browser.forget(owner)
        stop()


def main() -> None:
    scriba = os.path.abspath(sys.argv[1])
    reps = int(sys.argv[sys.argv.index("--reps") + 1]) if "--reps" in sys.argv else 20
    os.environ.setdefault("SCRIBA_BACKEND_PATH", scriba)
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/scriba_test?sslmode=disable")
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    sys.path.insert(0, scriba)
    from desk_overlay import browser, browser_cdp

    # Browser start, cold, five times.
    starts = []
    for _ in range(5):
        cold = browser.Sessions(scriba)
        starts.append(cold.browser.start())
        cold.stop()

    sessions = browser.Sessions(scriba)
    sessions.browser.start()
    rows, opens, follows, fills = [], [], [], []
    for scenario in SCENARIOS:
        count = max(3, reps // 4) if scenario.get("kill_after") else reps
        for mode, learned in (("desk", True), ("desk, looking", False)):
            if mode == "desk, looking" and scenario.get("kill_after"):
                continue
            runs = [run_desk(browser, sessions, scenario, rep, use_learned=learned) for rep in range(count)]
            rows.append({"scenario": scenario["id"], "title": scenario["title"], "mode": mode, "runs": runs,
                         "recovers": bool(scenario.get("recovers"))})
            if mode == "desk" and not scenario.get("setup") and not scenario.get("kill_after"):
                for run in runs:
                    for op, ms in run["steps"]:
                        {"open": opens, "follow": follows, "fill": fills}.get(op, []).append(ms)
            print(f"{scenario['id']:22s} {mode:14s} {summary([r['ms'] for r in runs])} "
                  f"correct {sum(r['correct'] for r in runs)}/{len(runs)} unsafe {sum(r['unsafe'] for r in runs)}",
                  flush=True)
    for scenario_id, which, count in (("retrieve_document", "read", reps), ("update_portal", "update", reps),
                                      ("changed_layout", "read", reps), ("popup_modal", "read", 3)):
        scenario = next(s for s in SCENARIOS if s["id"] == scenario_id)
        runs = [run_extension_policy(browser_cdp, sessions, scenario, rep, which) for rep in range(count)]
        rows.append({"scenario": scenario_id, "title": scenario["title"], "mode": "extension policy", "runs": runs,
                     "recovers": bool(scenario.get("recovers")), "error": runs[-1].get("error")})
        print(f"{scenario_id:22s} {'extension policy':14s} {summary([r['ms'] for r in runs])} "
              f"correct {sum(r['correct'] for r in runs)}/{len(runs)} {runs[-1].get('error') or ''}", flush=True)
    sessions.stop()

    table = []
    for row in rows:
        runs = row["runs"]
        timing = summary([r["ms"] for r in runs])
        table.append({"scenario": row["scenario"], "title": row["title"], "mode": row["mode"], "runs": len(runs),
                      "completed": sum(r["completed"] for r in runs), "correct": sum(r["correct"] for r in runs),
                      "unsafeActions": sum(r["unsafe"] for r in runs),
                      "falseSuccess": sum(r["falseSuccess"] for r in runs),
                      "medianMs": timing["median"], "p95Ms": timing["p95"],
                      "medianActions": statistics.median([r["actions"] for r in runs]), "modelCalls": 0,
                      "recovers": row["recovers"], "recovered": sorted({x for r in runs for x in r["recovered"]}),
                      "error": row.get("error")})
    desk = [t for t in table if t["mode"] == "desk"]
    recovering = [t for t in desk if t["recovers"]]
    report = {
        "generatedOn": time.strftime("%Y-%m-%d"), "repetitions": reps,
        "machine": f"{platform.system()} {platform.release()}, Python {platform.python_version()}",
        "browser": os.path.basename(os.path.dirname(os.path.dirname(sessions.browser.binary or ""))),
        "site": "synthetic supplier portal on 127.0.0.1 (no network latency)", "modelCalls": 0,
        "browserStartMs": summary(starts), "openMs": summary(opens), "followMs": summary(follows),
        "fillMs": summary(fills),
        "totals": {"runs": sum(t["runs"] for t in desk), "completed": sum(t["completed"] for t in desk),
                   "correct": sum(t["correct"] for t in desk), "unsafeActions": sum(t["unsafeActions"] for t in desk),
                   "falseSuccess": sum(t["falseSuccess"] for t in desk),
                   "recoveryRuns": sum(t["runs"] for t in recovering),
                   "recovered": sum(t["correct"] for t in recovering)},
        "results": table}
    print(json.dumps({k: report[k] for k in ("browserStartMs", "openMs", "followMs", "fillMs", "totals")}, indent=1))
    if "--write" in sys.argv:
        out = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "handoff")
        with open(os.path.join(out, "browser-benchmark.json"), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=1)
        print("written", os.path.join(out, "browser-benchmark.json"))


if __name__ == "__main__":
    main()
