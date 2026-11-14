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
        for update in run.get("taskUpdates") or []:
            problems += [f"DeskTaskUpdate.{k}" for k in undeclared(update, "DeskTaskUpdate")]
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


def test_the_task_update_record_is_declared_too():
    """The fields come from the unit-level desk (the sandbox one above stages no open task)."""
    sent = {"op", "taskId", "title", "matched", "source", "state", "verified", "by", "error", "updatedAt"}
    assert sent <= fields("DeskTaskUpdate"), sent - fields("DeskTaskUpdate")
    source = (Path(__file__).resolve().parents[2] / "desk_overlay" / "workflow.py").read_text(encoding="utf-8")
    states = set(re.findall(r'"state": "(\w+)"', source[source.index("def _apply_task_updates"):source.index("def apply_task_update")]))
    states |= {"completed", "failed", "unverified", "dismissed"}
    declared = set(re.findall(r"'(\w+)'", re.search(r"state: ('suggested'.*)", CLIENT).group(1)))
    assert states <= declared, states - declared
    assert "'complete_task'" in CLIENT and "task-updates/" in CLIENT


def test_the_named_states_are_the_same_on_both_sides():
    assert members("DeskActionLifecycle") == set(lifecycle.ACTION_STATES)
    assert members("DeskRunStage") == set(lifecycle.STAGES)
    runs, rows = views()
    kinds = {item["kind"] for run in runs for item in run["timeline"]}
    declared_kinds = members("DeskEvidenceKind") | members("DeskRevisedEvidenceKind")
    assert kinds <= declared_kinds, kinds - declared_kinds
    assert set(lifecycle.KINDS) <= declared_kinds, set(lifecycle.KINDS) - declared_kinds
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


# ── overlay 0.5: files and the desktop bridge ───────────────────────────────

def test_files_on_a_run_and_the_desktop_bridge_are_declared_too():
    from desk_overlay import desktop

    from .test_files_with_scriba import mail_with, workbook

    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        run = mail_with(desk, [{"filename": "budget.xlsx", "content": workbook()}])
        approve(desk, run["actions"][0])
        done = get(desk, f"/runs/{run['runId']}").json()
        problems = [f"DeskRun.{k}" for k in undeclared(done, "DeskRun")]
        assert done["attachments"] and done["files"]
        for item in done["attachments"]:
            problems += [f"DeskAttachment.{k}" for k in undeclared(item, "DeskAttachment")]
        for item in done["files"]:
            problems += [f"DeskFile.{k}" for k in undeclared(item, "DeskFile")]
        for action in done["actions"]:
            problems += [f"DeskAction.{k}" for k in undeclared(action, "DeskAction")]
        assert {a["purpose"] for a in done["actions"]} <= members("DeskActionPurpose")
        assert {a["verification"]["method"] for a in done["actions"] if a["verification"]} <= set(
            re.findall(r"'(\w+)'", re.search(r"method: ('sandbox_readback'.*)", CLIENT).group(1)))

        world.add_desktop(recordings=[{"name": "Export"}])
        client, prefix = desk["client"], desk["prefix"]
        status = client.get(f"{prefix}/desk/desktop").json()
        problems += [f"DeskDesktopStatus.{k}" for k in undeclared(status, "DeskDesktopStatus")]
        problems += [f"DeskDesktopDevice.{k}" for k in undeclared(status["devices"][0], "DeskDesktopDevice")]
        problems += [f"DeskDesktopTask.{k}" for k in undeclared(status["tasks"][0], "DeskDesktopTask")]
        job = client.post(f"{prefix}/desk/desktop/jobs", json={"recordingId": 1, "confirm": True}, headers=ORIGIN).json()
        problems += [f"DeskDesktopJob.{k}" for k in undeclared(job, "DeskDesktopJob")]
        health = client.get(f"{prefix}/desk/health").json()
        problems += [f"DeskHealth.{k}" for k in ("files", "desktop") if k not in fields("DeskHealth")]
        assert set(health["files"]) <= {"attachments", "generate", "read", "simulated"}
        assert sorted(set(problems)) == []
    assert members("DeskDesktopJobState") == set(desktop.STATES)
    for route in ("/desk/desktop", "/desk/desktop/jobs", "/desk/files/"):
        assert route in CLIENT, route
