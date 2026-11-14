"""The machine-readable baseline.

Brings together, without mixing them, everything that has been measured on
one backend commit, sorted by the kind of evidence it is:

    rules_only      the Desk with no model
    scripted_model  the understanding step handed a careful reader's answer
                    (an in-process stub in the backend's own tests)
    real_model      a configured model in the loop
    isolated_provider_sandbox / live_provider   what stood in for the providers

Numbers reported by the other agents are RE-MEASURED here, not copied: the
inputs to this module are the report files their own runners wrote when the
lab re-ran them on the pinned commit. A class nobody measured says so.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Optional

from . import RUNNER_VERSION
from .backend import DeskBackend


def _agent2(path: str) -> Dict[str, Any]:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    results = report["results"]
    verdicts: Dict[str, int] = {}
    for result in results:
        verdicts[result["verdict"]] = verdicts.get(result["verdict"], 0) + 1
    return {
        "caseSet": report["caseSet"]["id"], "cases": len(results), "asExpected": verdicts.get("pass", 0),
        "notAsExpected": verdicts.get("fail", 0), "errors": verdicts.get("error", 0), "skipped": verdicts.get("skipped", 0),
        "targetDataSource": report["target"]["dataSource"], "sandbox": report["target"].get("sandbox"),
        "failing": sorted(r["caseId"] for r in results if r["verdict"] == "fail"),
        "erroring": sorted(r["caseId"] for r in results if r["verdict"] == "error"),
        "errorCodes": sorted({e.get("code") for r in results for e in r.get("errors") or [] if e.get("code")}),
        "harnessVersion": report.get("harnessVersion"), "ranAt": report.get("finishedAt"),
    }


def _agent1(path: str) -> Dict[str, Any]:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"format": report.get("format"), "scenarios": report.get("scenarios"), "modes": report.get("modes") or {},
            "configuredModelNote": report.get("configured_model_note"),
            "notFullyCorrect": {mode: sorted(row["id"] for row in rows if not (row.get("intent_ok") and row.get("outcome_ok")
                                                                             and row.get("plan_ok") and row.get("flags_ok", True)))
                                for mode, rows in (report.get("results") or {}).items() if isinstance(rows, list)}}


def build_baseline(backend: DeskBackend, *, agent2_desk: str, agent2_holdout: str, agent1_scenarios: str,
                   lab_report: Optional[str] = None) -> Dict[str, Any]:
    identity = backend.identity()
    desk, holdout, scenarios = _agent2(agent2_desk), _agent2(agent2_holdout), _agent1(agent1_scenarios)
    lab = json.loads(Path(lab_report).read_text(encoding="utf-8")) if lab_report else None
    summary_as_written = scenarios.get("modes") or {}

    def scen(mode: str, key: str) -> Any:
        return (summary_as_written.get(mode) or {}).get(key) if isinstance(summary_as_written.get(mode), dict) else None

    baseline = {
        "format": "autonomy-quality-lab.baseline/1", "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runnerVersion": RUNNER_VERSION,
        "target": {"backendCommit": identity["backendCommit"], "branch": "agent1/autonomous-engine",
                   "scribaCommit": identity["scribaCommit"], "overlayVersion": identity["overlayVersion"],
                   "contractVersion": identity["contractVersion"], "agentReported": identity["agentReported"],
                   "modelConfigured": identity["executionMode"]["planner"] == "real_model"},
        "evidenceClasses": {
            "rules_only": {
                "measured": True,
                "official_desk_v1": {**desk, "runner": "Agent 2: frontend/scripts/eval.ts, re-run by the lab on this commit",
                                     "reported": "10 as expected, 7 not, 3 errors", "reproduced": (desk["asExpected"], desk["notAsExpected"], desk["errors"]) == (10, 7, 3)},
                "official_holdout_v1": {**holdout, "runner": "Agent 2: frontend/scripts/eval.ts --suite holdout, re-run by the lab",
                                        "reported": "5 as expected", "reproduced": holdout["asExpected"] == 5},
                "backend_scenarios": {"runner": "Agent 1: backend/tests/integration/test_scenarios_with_scriba.py, re-run by the lab",
                                      "everythingCorrect": scen("rules", "all_correct"), "scenarios": scen("rules", "scenarios"),
                                      "reported": "20 of 24 everything correct"},
                "lab_campaign": None if lab is None else {
                    "label": lab["label"], "cases": lab["summary"]["cases"], "byVerdict": lab["summary"]["byVerdict"],
                    "completeJobSuccessRate": lab["summary"]["completeJobSuccessRate"],
                    "safetyViolations": lab["summary"]["safetyViolations"], "falseSuccesses": lab["summary"]["falseSuccesses"],
                    "hardGates": {g["id"]: g["status"] for g in lab["gates"]["hard"]}},
            },
            "scripted_model": {
                "measured": True, "measuredBy": "Agent 1's in-process scenarios only (the model is a stub inside the test process)",
                "backend_scenarios": {"everythingCorrect": scen("scripted_model", "all_correct"), "scenarios": scen("scripted_model", "scenarios"),
                                      "reported": "23 of 24 everything correct"},
                "lab_campaign": "NOT MEASURED: a scripted model cannot be reached over HTTP; the lab will not write the answers itself",
                "warning": "This is an upper bound for the pipeline behind the model. It is not a model's score and must not be described as AI performance.",
            },
            "real_model": {"measured": False, "status": "NOT MEASURED",
                           "why": "The backend reports no configured model (meta.agent = scripted). No model credential is "
                                  "available in this environment; none was requested or created."},
            "isolated_provider_sandbox": {"measured": True, "note": "Every result above ran against a per-case SandboxWorld. "
                                                                    "All effects are simulated."},
            "live_provider": {"measured": False, "status": "NOT MEASURED",
                              "why": "By rule: no live provider write API is called, and the backend's external writes are disabled in code."},
        },
        "notes": {
            "agent1Scenarios": scenarios,
            "chat": "3 of the official 20 cases start from a chat turn; /desk/eval/v1 answers conversation_input_unsupported. "
                    "They are errors in Agent 2's runner and 'unsupported' in the lab.",
        },
    }
    baseline["summary"] = {
        "commit": identity["backendCommit"],
        "rules_only": {"official_desk_v1": f"{desk['asExpected']}/{desk['cases']} as expected, {desk['notAsExpected']} not, {desk['errors']} errors",
                       "official_holdout_v1": f"{holdout['asExpected']}/{holdout['cases']} as expected, {holdout['notAsExpected']} not, {holdout['errors']} errors",
                       "backend_scenarios": f"{scen('rules', 'all_correct')}/{scen('rules', 'scenarios')} everything correct"},
        "scripted_model": {"backend_scenarios": f"{scen('scripted_model', 'all_correct')}/{scen('scripted_model', 'scenarios')} everything correct (pipeline upper bound, not a model)"},
        "real_model": "NOT MEASURED", "isolated_provider_sandbox": "all of the above", "live_provider": "NOT MEASURED",
        "reportedNumbersReproduced": bool(baseline["evidenceClasses"]["rules_only"]["official_desk_v1"]["reproduced"]
                                          and baseline["evidenceClasses"]["rules_only"]["official_holdout_v1"]["reproduced"]),
    }
    return baseline
