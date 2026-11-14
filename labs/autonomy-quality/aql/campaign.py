"""Run a campaign and assemble its report.

A campaign is: the semantic corpus, the metamorphic relations, the
adversarial cases and the product-route scenarios, each run ``repeat`` times
against one backend, then judged, classified, clustered and gated.

Every result is traceable to: backend commit + runner version + scenario
seed + model + execution mode. Those five are in ``report["traceability"]``
and are repeated on every result.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import platform
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import REPORT_FORMAT, RUNNER_VERSION, adversarial, corpus, metamorphic, scenarios
from .backend import DeskBackend
from .classify import classify, cluster
from .gates import evaluate as evaluate_gates
from .metrics import breakdown, consistency, summarize
from .oracle import judge
from .rootcauses import KNOWLEDGE
from .runner import CaseRunner

FAMILIES = ("semantic", "metamorphic", "adversarial", "scenario")


def build_items(seed: int, families: List[str]) -> Dict[str, Any]:
    items: Dict[str, Any] = {"cases": [], "relations": []}
    if "semantic" in families:
        items["cases"] += corpus.build(seed)
    if "metamorphic" in families:
        items["relations"] = metamorphic.build(seed)
        items["cases"] += metamorphic.members(items["relations"])
    if "adversarial" in families:
        items["cases"] += adversarial.build(seed)
    return items


def run_campaign(backend: DeskBackend, *, seed: int, families: List[str], repeat: int = 1, label: str = "",
                 only: Optional[List[str]] = None, progress: Optional[Callable[[str], None]] = None,
                 timeout: float = 25.0) -> Dict[str, Any]:
    say = progress or (lambda line: None)
    started = dt.datetime.now(dt.timezone.utc)
    items = build_items(seed, families)
    cases = [c for c in items["cases"] if not only or any(c["id"].startswith(prefix) for prefix in only)]
    by_id = {c["id"]: c for c in cases}
    runner = CaseRunner(backend, timeout=timeout)
    identity = backend.identity()
    trace_key = {"backendCommit": identity["backendCommit"], "runnerVersion": RUNNER_VERSION, "seed": seed,
                 "model": identity["executionMode"]["model"], "executionMode": identity["executionMode"]["label"]}

    rounds: List[List[Dict[str, Any]]] = []
    for attempt in range(1, repeat + 1):
        results: List[Dict[str, Any]] = []
        for index, case in enumerate(cases, 1):
            if case["input"]["kind"] == "conversation" and not backend.caps.get("chat"):
                # Still sent: the backend's own refusal is the evidence, not the lab's assumption.
                pass
            result = judge(case, runner.run(case))
            result["_case"] = case
            classify(result, case)
            result["attempt"], result["traceability"] = attempt, trace_key
            results.append(result)
            say(f"[{attempt}/{repeat}] {index:>3}/{len(cases)} {result['id']:<42} {result['verdict']:<12} "
                f"{(result.get('rootCause') or '')}")
        if "scenario" in families:
            for result in scenarios.run_all(backend, only):
                result["attempt"], result["traceability"] = attempt, trace_key
                results.append(result)
                say(f"[{attempt}/{repeat}] scenario {result['id']:<38} {result['verdict']:<12} {(result.get('rootCause') or '')}")
        rounds.append(results)

    first = rounds[0]
    indexed = {r["id"]: r for r in first}
    relations = [metamorphic.evaluate(rel, indexed) for rel in items["relations"]
                 if rel["base"]["id"] in indexed and all(c["id"] in indexed for c in rel["followUps"])]
    stable = consistency(rounds)
    summary = summarize(first)
    gates = evaluate_gates([r for results in rounds for r in results], summary, stable)
    reproduce = "python -m aql run --api {api} --seed {seed} --only {{id}}".format(api=backend.api_root, seed=seed)
    clusters = cluster(first, by_id, KNOWLEDGE, reproduce)
    finished = dt.datetime.now(dt.timezone.utc)

    report = {
        "format": REPORT_FORMAT, "label": label or f"campaign-{started.strftime('%Y%m%dT%H%M%SZ')}",
        "startedAt": started.isoformat(), "finishedAt": finished.isoformat(),
        "traceability": trace_key,
        "target": identity,
        "runner": {"version": RUNNER_VERSION, "python": platform.python_version(), "platform": platform.platform(),
                   "repeat": repeat, "families": families, "only": only,
                   "corpus": corpus.manifest([c for c in cases if c["family"] == "semantic"], seed) if "semantic" in families else None},
        "evidence": evidence_statement(identity),
        "summary": summary,
        "byFamily": {family: summarize([r for r in first if r.get("family") == family])
                     for family in FAMILIES if any(r.get("family") == family for r in first)},
        "byCategory": breakdown([r for r in first if r.get("family") == "semantic"], "category"),
        "byLanguage": breakdown([r for r in first if r.get("family") == "semantic"], "lang"),
        "adversarialByCategory": breakdown([r for r in first if r.get("family") in ("adversarial", "scenario")], "category"),
        "metamorphic": {
            "relations": len(relations), "hold": sum(1 for r in relations if r["holds"]),
            "broken": sum(1 for r in relations if r["holds"] is False),
            "byRelation": _by_relation(relations), "results": relations},
        "consistency": stable, "gates": gates, "rootCauses": clusters,
        "missingEndpoints": identity["missing"],
        "results": [strip(r) for r in first],
        "repeats": [[{"id": r["id"], "verdict": r["verdict"], "rootCause": r.get("rootCause")} for r in results]
                    for results in rounds[1:]],
    }
    report["_full"] = first        # with traces; written per case, not into the report
    return report


def _by_relation(relations: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    table: Dict[str, Dict[str, int]] = {}
    for relation in relations:
        row = table.setdefault(relation["relation"], {"relations": 0, "hold": 0, "broken": 0, "followUps": 0, "followUpsBroken": 0})
        row["relations"] += 1
        row["hold"] += 1 if relation["holds"] else 0
        row["broken"] += 1 if relation["holds"] is False else 0
        row["followUps"] += len(relation["followUps"])
        row["followUpsBroken"] += sum(1 for f in relation["followUps"] if f["holds"] is False)
    return table


def strip(result: Dict[str, Any]) -> Dict[str, Any]:
    """A result without its trace and its case: what goes in the report."""
    return {key: value for key, value in result.items() if key not in ("trace", "_case")}


def evidence_statement(identity: Dict[str, Any]) -> Dict[str, Any]:
    """Which of the five evidence classes this campaign's numbers belong to.
    A class that was not exercised says NOT MEASURED. Nothing is inferred."""
    mode = identity["executionMode"]
    real = mode["planner"] == "real_model"
    return {
        "rules_only": {"measured": not real, "note": "The Desk with no model: rule-based reading only." if not real else "not this run"},
        "scripted_model": {"measured": False, "note": "NOT MEASURED by this lab. A scripted model exists only inside the "
                                                       "backend's own tests (an in-process stub); it cannot be reached over HTTP. "
                                                       "See the baseline report for Agent 1's figure, re-run and verified."},
        "real_model": {"measured": real, "model": mode["model"] if real else None,
                       "note": "A configured model took part in planning." if real else
                               "NOT MEASURED: the backend reports no configured model (meta.agent = scripted, "
                               "desk.model.configured = false)."},
        "isolated_provider_sandbox": {"measured": identity["capabilities"].get("eval", False),
                                      "note": "Every mail and calendar effect was applied to a per-case SandboxWorld. "
                                              "All results are simulated: none is a provider success."},
        "live_provider": {"measured": False, "note": "NOT MEASURED, by design: the lab never calls a live provider and the "
                                                    "backend's external writes are disabled in code."},
        "statement": ("These are results of the RULES-ONLY engine in an isolated sandbox. They say nothing about a model."
                      if not real else "A configured model took part; providers were an isolated sandbox."),
    }


def write_report(report: Dict[str, Any], out_dir: Path) -> Dict[str, Path]:
    from .report import render_html, render_markdown, render_root_causes

    out_dir.mkdir(parents=True, exist_ok=True)
    traces = out_dir / "traces"
    traces.mkdir(exist_ok=True)
    full = report.pop("_full", [])
    for result in full:
        payload = {key: value for key, value in result.items() if key != "_case"}
        payload["case"] = result.get("_case")
        name = result["id"].replace("/", "__") + ".json"
        (traces / name).write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    paths = {"json": out_dir / "report.json", "markdown": out_dir / "REPORT.md", "html": out_dir / "dashboard.html",
             "rootCauses": out_dir / "ROOT_CAUSES.md", "gates": out_dir / "gates.json"}
    paths["json"].write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    paths["gates"].write_text(json.dumps({"traceability": report["traceability"], **report["gates"]}, indent=1), encoding="utf-8")
    paths["markdown"].write_text(render_markdown(report), encoding="utf-8")
    paths["rootCauses"].write_text(render_root_causes(report), encoding="utf-8")
    paths["html"].write_text(render_html(report), encoding="utf-8")
    return paths


_ = os
