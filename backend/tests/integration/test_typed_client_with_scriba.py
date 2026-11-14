"""One representation: what the backend sends is what ``frontend/src/api/desk.ts``
declares. A field or a state added on one side and not the other fails here.

The responses are real ones, produced through Scriba's routes in a sandbox
world; the declarations are read from the TypeScript source.
"""
import re
from pathlib import Path

from desk_overlay import lifecycle

from .test_execution_with_scriba import (ALICE, OP_CREATE_EVENT, ORIGIN, approve, get, meeting, sandbox_desk)

CLIENT = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "api" / "desk.ts").read_text(encoding="utf-8")


def fields(interface):
    """The top-level fields of ``export interface <name> { ... }``."""
    block = re.search(r"export interface " + interface + r" \{\r?\n(.*?)\r?\n\}", CLIENT, re.S)
    assert block, f"{interface} is not declared in desk.ts"
    return set(re.findall(r"^  (\w+)\??:", block.group(1), re.M))


def members(union):
    """The string literals of ``export type <name> = | 'A' | 'B'``."""
    block = re.search(r"export type " + union + r" =(.*?)(?:\r?\n\r?\n|\Z)", CLIENT, re.S)
    assert block, f"{union} is not declared in desk.ts"
    return set(re.findall(r"'([^']+)'", re.sub(r"/\*\*.*?\*/", "", block.group(1), flags=re.S)))


def undeclared(sent, interface):
    return sorted(set(sent) - fields(interface))


def views():
    """Runs that between them carry every kind of record: a plan with two
    steps, an approved and verified action, an edit, a failure with a retry,
    an unknown outcome, a rejection."""
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        first = meeting(desk)
        approve(desk, first["actions"][0], payload_overrides={"title": "Intro call with Sofia"})
        done = get(desk, f"/runs/{first['runId']}").json()
        approve(desk, done["actions"][1])
        done = get(desk, f"/runs/{first['runId']}").json()

        world.add_fault(OP_CREATE_EVENT, mode="uncertain", times=1, error="timeout")
        second = meeting(desk, message_id="m2", start="2026-03-06T10:00:00+00:00", end="2026-03-06T10:30:00+00:00",
                         body="Could we meet on Friday at 10:00 for 30 minutes?")
        approve(desk, second["actions"][0])
        unknown = get(desk, f"/runs/{second['runId']}").json()

        third = meeting(desk, message_id="m3", start="2026-03-09T10:00:00+00:00", end="2026-03-09T10:30:00+00:00",
                        body="Could we meet on Monday at 10:00 for 30 minutes?")
        desk["client"].post(f"/chat/tool-calls/{third['actions'][0]['toolCallId']}/cancel", headers=ORIGIN)
        rejected = get(desk, f"/runs/{third['runId']}").json()
        rows = get(desk, "/runs").json()["runs"]
        return [done, unknown, rejected], rows


def test_every_field_the_backend_sends_is_declared_in_the_typed_client():
    runs, rows = views()
    problems = []
    for run in runs:
        problems += [f"DeskRun.{k}" for k in undeclared(run, "DeskRun")]
        problems += [f"DeskLifecycle.{k}" for k in undeclared(run["lifecycle"], "DeskLifecycle")]
        problems += [f"DeskPlan.{k}" for k in undeclared(run["plan"], "DeskPlan")]
        for step in run["plan"]["steps"]:
            problems += [f"DeskPlanStep.{k}" for k in undeclared(step, "DeskPlanStep")]
        for intent in run["plan"]["intents"]:
            problems += [f"DeskPlanIntent.{k}" for k in undeclared(intent, "DeskPlanIntent")]
        for follow in run["followUps"]:
            problems += [f"DeskFollowUp.{k}" for k in undeclared(follow, "DeskFollowUp")]
        for item in run["timeline"]:
            problems += [f"DeskTimelineItem.{k}" for k in undeclared(item, "DeskTimelineItem")]
        for action in run["actions"]:
            problems += [f"DeskAction.{k}" for k in undeclared(action, "DeskAction")]
            for decision in action["decisions"]:
                problems += [f"DeskActionDecision.{k}" for k in undeclared(decision, "DeskActionDecision")]
            if action["execution"]:
                problems += [f"DeskActionExecution.{k}" for k in undeclared(action["execution"], "DeskActionExecution")]
            if action["verification"]:
                problems += [f"DeskActionVerification.{k}" for k in undeclared(action["verification"], "DeskActionVerification")]
            if action["retry"]:
                problems += [f"DeskActionRetry.{k}" for k in undeclared(action["retry"], "DeskActionRetry")]
    for row in rows:
        problems += [f"DeskRunRow.{k}" for k in undeclared(row, "DeskRunRow")]
    assert sorted(set(problems)) == []


def test_the_records_under_test_really_cover_the_states():
    runs, _ = views()
    states = {a["lifecycle"] for run in runs for a in run["actions"]}
    assert {"VERIFIED", "OUTCOME_UNKNOWN", "REJECTED"} <= states
    assert any(a["edited"] for run in runs for a in run["actions"])
    assert any(a["retry"] for run in runs for a in run["actions"])
    assert any(len(run["plan"]["steps"]) == 2 for run in runs)


def test_the_named_states_are_the_same_on_both_sides():
    assert members("DeskActionLifecycle") == set(lifecycle.ACTION_STATES)
    assert members("DeskRunStage") == set(lifecycle.STAGES)
    runs, rows = views()
    kinds = {item["kind"] for run in runs for item in run["timeline"]}
    assert kinds <= members("DeskEvidenceKind"), kinds - members("DeskEvidenceKind")
    assert {run["lifecycle"]["stage"] for run in runs} <= members("DeskRunStage")
    assert {row["lifecycle"] for row in rows} <= members("DeskRunStage")
    modes = {"rerun", "readback_first", "confirm_first"}
    assert modes <= set(re.findall(r"'(\w+)'", re.search(r"export interface DeskActionRetry \{.*?\}", CLIENT, re.S).group(0)))


def test_every_reason_and_code_the_backend_can_emit_is_named_in_the_typed_client():
    backend = Path(__file__).resolve().parents[2] / "desk_overlay"
    source = "\n".join((backend / name).read_text(encoding="utf-8") for name in ("workflow.py", "execution.py"))
    reasons = set(re.findall(r'_hold\(plan, user, item, calendar,\s*"(\w+)"', source))
    reasons |= set(re.findall(r'plan\["held"\] = \{\s*"reason": "(\w+)"', source))
    reasons |= {"calendar_conflict", "availability_unknown"}           # chosen by an expression in two places
    declared = members("DeskHeldReasonV2") | members("DeskHeldReasonV3") | members("DeskHeldReasonRevised")
    assert reasons - declared == set(), reasons - declared
    assert len(reasons) >= 12
    codes = {"external_writes_disabled", "proposal_changed", "outcome_unknown", "sandbox_world_gone", "interrupted"}
    for code in codes:
        assert f'"{code}"' in source, code
    assert codes <= members("DeskGateHoldCode") | members("DeskRevisedCardCode")
