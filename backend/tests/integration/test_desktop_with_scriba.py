"""The Desk's bridge to Scriba's desktop agent.

Three things are tested, and they are different things:

1. **This backend, as it is.** Scriba's own switch says the desktop subsystem
   is off, so the bridge reports that and queues nothing. That is a real call
   into Scriba.
2. **The adapter**, against stand-ins for Scriba's service functions that keep
   their real names, signatures and return shapes (read from Scriba's source at
   3ae3a2a). This proves the bridge calls them correctly and reads their
   records honestly. It does NOT prove a device executed anything: Scriba's
   desktop tables need Postgres, which this environment does not have.
3. **A fake device** in a sandbox world, through the Desk's routes. Everything
   it returns is marked simulated.

No real desktop was connected or controlled by any of this.
"""
from unittest.mock import patch

import pytest

from desk_overlay import desktop
from desk_overlay.gateway import DeskUser

from .test_execution_with_scriba import ALICE, BOB, sandbox_desk

AGENT = {"id": 7, "device_name": "Office PC", "device_kind": "desktop", "status": "online", "ready": True,
         "state": "ready", "session_state": "unlocked", "agent_version": "0.4.9", "last_seen_at": "2026-03-02T07:59:00+00:00",
         "allowed_folders": ["C:/Reports"], "capabilities": {}, "update": {"required": False}}
RECORDING = {"id": 3, "name": "Export the weekly report", "kind": "desktop", "status": "ready", "step_count": 9,
             "has_password": False, "checks": [{"name": "the export exists"}], "apps": ["Excel"], "unattended": False}


def job(status, **over):
    base = {"id": 41, "desktop_agent_id": 7, "status": status, "job_type": "rpa.replay", "error": None,
            "failure_stage": None, "created_at": "t0", "claimed_at": None, "finished_at": None, "updated_at": "t0",
            "cancel_requested": False, "result": {},
            # A real payload embeds the recorded steps, which may hold what was typed.
            "payload": {"recording_id": 3, "name": "Export the weekly report",
                        "steps": [{"action": "type", "text": "s3cret-typed-text"}], "allow_apps": ["excel.exe"]}}
    return {**base, **over}


# ── 1. this backend as it is ────────────────────────────────────────────────

def test_on_this_backend_scriba_says_the_desktop_agent_is_off_and_nothing_is_queued():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE, world=False)                 # no sandbox world: Scriba's real subsystem is asked
        bridge = desktop.DesktopBridge(desk["routed"])
        status = bridge.status(DeskUser(id=1, email=ALICE))
        assert status["available"] is False and status["reason"] == "desktop_agent_disabled"
        assert status["simulated"] is False and status["devices"] == []
        with pytest.raises(desktop.DesktopUnavailable) as refused:
            bridge.assign(DeskUser(id=1, email=ALICE), 3, confirmed=True)
        assert refused.value.code == "desktop_agent_disabled"


# ── 2. the adapter, against Scriba's function shapes ────────────────────────

class ScribaShaped:
    """Stand-ins with the names and signatures of Scriba's own functions."""

    def __init__(self):
        self.calls, self.jobs = [], {}

    def install(self, stack):
        from app import desktop_repository, desktop_security
        from app.services import desktop_agent_service, desktop_job_service, desktop_recording_service

        stack.enter_context(patch.object(desktop_security, "desktop_enabled", lambda: (True, "")))
        stack.enter_context(patch.object(desktop_agent_service, "list_user_agents",
                                         lambda user_id: [dict(AGENT)] if int(user_id) == 1 else []))
        stack.enter_context(patch.object(desktop_recording_service, "list_all",
                                         lambda *, user_id: [dict(RECORDING)] if int(user_id) == 1 else []))

        def replay(*, user_id, recording_id, agent_id=None, repeat_folder="", repeat_extensions=None):
            self.calls.append(("replay", user_id, recording_id, agent_id))
            self.jobs[41] = job("queued")
            return {"recording_id": recording_id, "job_id": 41, "status": "queued"}

        def get_job(*, user_id, job_id):
            self.calls.append(("get_job", user_id, job_id))
            return dict(self.jobs[int(job_id)])

        def cancel_job(*, user_id, job_id):
            self.calls.append(("cancel_job", user_id, job_id))
            self.jobs[int(job_id)]["cancel_requested"] = True
            return {"job": dict(self.jobs[int(job_id)]), "state": "stopping"}

        stack.enter_context(patch.object(desktop_recording_service, "replay", replay))
        stack.enter_context(patch.object(desktop_job_service, "get_job", get_job))
        stack.enter_context(patch.object(desktop_job_service, "cancel_job", cancel_job))
        stack.enter_context(patch.object(desktop_repository, "list_audit",
                                         lambda *, user_id, desktop_job_id=None, limit=100: []))
        return self


def test_the_adapter_lists_assigns_follows_and_cancels_through_scribas_own_functions():
    from contextlib import ExitStack

    with sandbox_desk() as desk, ExitStack() as stack:
        desk["sign_in"](ALICE, world=False)
        scriba = ScribaShaped().install(stack)
        bridge, alice = desktop.DesktopBridge(desk["routed"]), DeskUser(id=1, email=ALICE)

        status = bridge.status(alice)
        assert status["available"] is True and status["simulated"] is False
        assert status["devices"][0]["name"] == "Office PC" and status["devices"][0]["canRunRecordedTasks"] is True
        assert status["tasks"] == [{"id": 3, "name": "Export the weekly report", "kind": "desktop", "ready": True,
                                    "steps": 9, "hasPassword": False, "checks": 1, "apps": ["Excel"],
                                    "runsWhileLocked": False, "simulated": False}]

        # Not without an explicit go-ahead, and not for a recording that is not theirs.
        with pytest.raises(desktop.DesktopUnavailable) as plain:
            bridge.assign(alice, 3)
        assert plain.value.code == "confirmation_required" and scriba.calls == []
        with pytest.raises(desktop.DesktopUnavailable) as foreign:
            bridge.assign(alice, 99, confirmed=True)
        assert foreign.value.code == "recording_not_found" and scriba.calls == []

        queued = bridge.assign(alice, 3, 7, confirmed=True)
        assert ("replay", 1, 3, 7) in scriba.calls
        assert queued["state"] == "ACCEPTED" and queued["final"] is False and queued["verified"] is False
        assert queued["task"] == "Export the weekly report" and queued["simulated"] is False
        assert "s3cret-typed-text" not in str(queued)                # recorded steps never leave the bridge
        assert queued["resume"]["supported"] is False

        stopped = bridge.cancel(alice, 41)
        assert ("cancel_job", 1, 41) in scriba.calls and stopped["cancelRequested"] is True

        # Another person sees no device and no task, and cannot queue this one.
        bob = DeskUser(id=2, email=BOB)
        assert bridge.status(bob)["reason"] == "no_device_paired"
        with pytest.raises(desktop.DesktopUnavailable):
            bridge.assign(bob, 3, confirmed=True)


@pytest.mark.parametrize("record, state, verified", [
    (job("queued"), "ACCEPTED", False),
    (job("claimed", claimed_at="t1"), "STARTED", False),
    (job("running", claimed_at="t1"), "RUNNING", False),
    (job("awaiting_approval"), "AWAITING_APPROVAL", False),
    (job("cancelled"), "CANCELLED", False),
    (job("succeeded", result={"replayed": 9, "checks": [{"name": "c", "passed": True}]}), "VERIFIED", True),
    # It reported success and the recording has no check: nothing shows the result.
    (job("succeeded", result={"replayed": 9, "checks": []}), "SUCCEEDED_UNVERIFIED", False),
    # A step fell back to a recorded position: finished, and not to be trusted unseen.
    (job("succeeded", result={"replayed": 9, "needs_review": True, "checks": [{"passed": True}]}), "NEEDS_REVIEW", False),
    (job("failed", failure_stage="check_failed", claimed_at="t1"), "FAILED", False),
    (job("failed", failure_stage="blocked", claimed_at="t1", error="A window that was not recorded appeared."), "FAILED", False),
    # Started, then silent: part of it may have run.
    (job("failed", claimed_at="t1", error="Replay didn't report back — it may have been stopped on the device."),
     "OUTCOME_UNKNOWN", False),
    # Never started: nothing happened.
    (job("failed", failure_stage="device_revoked"), "FAILED", False),
    (job("some_new_status"), "FAILED", False),
])
def test_a_job_record_is_read_as_what_it_proves_and_no_more(record, state, verified):
    view = desktop.job_view(record, simulated=False)
    assert view["state"] == state and view["verified"] is verified
    assert view["final"] is (state in desktop.FINAL)
    assert state in desktop.STATES


# ── 3. a fake device, through the routes ────────────────────────────────────

def test_a_sandbox_world_without_a_desktop_can_run_nothing():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        client, prefix = desk["client"], desk["prefix"]
        status = client.get(f"{prefix}/desk/desktop").json()
        assert status["available"] is False and status["reason"] == "no_desktop_in_sandbox"
        refused = client.post(f"{prefix}/desk/desktop/jobs", json={"recordingId": 1, "confirm": True},
                              headers={"Origin": "http://localhost:5173"})
        assert refused.status_code == 409 and refused.headers["x-desk-error-code"] == "no_desktop_in_sandbox"
        assert "no desktop" in str(refused.json()).lower()
        assert client.get(f"{prefix}/desk/health").json()["desktop"] == {
            "available": False, "reason": "no_desktop_in_sandbox", "simulated": True}


def test_a_fake_device_runs_a_recorded_task_to_a_verified_result_and_says_it_is_simulated():
    origin = {"Origin": "http://localhost:5173"}
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        world.add_desktop(recordings=[{"name": "Export the weekly report"}, {"name": "No check", "script": "no_check", "checks": 0},
                                      {"name": "Dialog", "script": "dialog"}, {"name": "Silent", "script": "silent"}])
        client, prefix = desk["client"], desk["prefix"]
        fake = desktop.SandboxDesktop(world)
        status = client.get(f"{prefix}/desk/desktop").json()
        assert status["available"] is True and status["simulated"] is True and len(status["tasks"]) == 4

        assert client.post(f"{prefix}/desk/desktop/jobs", json={"recordingId": 1}, headers=origin).status_code == 400

        def run(recording):
            queued = client.post(f"{prefix}/desk/desktop/jobs", json={"recordingId": recording, "confirm": True},
                                 headers=origin)
            assert queued.status_code == 200, queued.text
            seen = [queued.json()["state"]]
            for _ in range(3):
                fake.step(queued.json()["id"])
                seen.append(client.get(f"{prefix}/desk/desktop/jobs/{queued.json()['id']}").json()["state"])
            return seen, client.get(f"{prefix}/desk/desktop/jobs/{queued.json()['id']}").json()

        seen, done = run(1)
        assert seen == ["ACCEPTED", "STARTED", "RUNNING", "VERIFIED"]
        assert done["verified"] is True and done["simulated"] is True and done["verification"]["passed"] == 1
        assert [e["action"] for e in done["events"]] == ["claim", "replay", "replay"]

        assert run(2)[1]["state"] == "SUCCEEDED_UNVERIFIED"          # finished is not verified
        blocked = run(3)[1]
        assert blocked["state"] == "FAILED" and blocked["failureStage"] == "blocked"   # an unexpected window: it stops
        assert blocked["resume"]["supported"] is False
        assert run(4)[1]["state"] == "OUTCOME_UNKNOWN"               # it went silent: not "failed, try again"

        # Cancelling a running job asks the device to stop; it stops at its next step.
        queued = client.post(f"{prefix}/desk/desktop/jobs", json={"recordingId": 1, "confirm": True}, headers=origin).json()
        fake.step(queued["id"]); fake.step(queued["id"])
        assert client.post(f"{prefix}/desk/desktop/jobs/{queued['id']}/cancel", headers=origin).json()["cancelRequested"] is True
        fake.step(queued["id"])
        assert client.get(f"{prefix}/desk/desktop/jobs/{queued['id']}").json()["state"] == "CANCELLED"

        # Someone else has no access to this world's device or its jobs.
        desk["sign_in"](BOB)
        assert client.get(f"{prefix}/desk/desktop").json()["available"] is False
        assert client.get(f"{prefix}/desk/desktop/jobs/{queued['id']}").status_code == 404


def test_a_locked_or_offline_fake_device_takes_nothing():
    origin = {"Origin": "http://localhost:5173"}
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        world.add_desktop(online=False, recordings=[{"name": "Export"}])
        client, prefix = desk["client"], desk["prefix"]
        assert client.get(f"{prefix}/desk/desktop").json()["reason"] == "no_device_ready"
        refused = client.post(f"{prefix}/desk/desktop/jobs", json={"recordingId": 1, "confirm": True}, headers=origin)
        assert refused.status_code == 409 and world.desktop["jobs"] == {}
        world.add_desktop(locked=True, recordings=[{"name": "Export"}])
        locked = client.post(f"{prefix}/desk/desktop/jobs", json={"recordingId": 1, "confirm": True}, headers=origin)
        assert locked.status_code == 409 and locked.headers["x-desk-error-code"] == "device_locked"
        assert world.desktop["jobs"] == {}
