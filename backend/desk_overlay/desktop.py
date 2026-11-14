"""The Desk's bridge to Scriba's existing desktop agent. An adapter: no
agent, no queue, no recorder and no player lives here.

Scriba already has all of it. A Windows agent is paired to a user account,
polls a job queue over HTTPS, replays a recorded task inside the apps it was
recorded in, and posts the result back. This module only calls the server
side of that, in the same process:

    app.desktop_security.desktop_enabled                    is the subsystem on
    app.services.desktop_agent_service.list_user_agents     the user's paired devices
    app.services.desktop_recording_service.list_all         their recorded tasks
    app.services.desktop_recording_service.replay           queue a replay on a device
    app.services.desktop_job_service.get_job / cancel_job   follow it, stop it
    app.desktop_repository.list_audit                       what the device reported

What the bridge adds is honesty about where a job stands:

- A queued job is ACCEPTED, not started. A claimed job is STARTED. Only the
  device reporting back moves it on.
- A job that succeeded is VERIFIED only when the recording carries its own
  checks and every one passed. With no check it is SUCCEEDED_UNVERIFIED; with
  a step that fell back to a recorded position it is NEEDS_REVIEW.
- A replay that stopped reporting is OUTCOME_UNKNOWN: part of it may have run.
- Scriba's replays cannot be resumed (no checkpoint exists in the agent), so
  ``resume.supported`` is false and nothing here pretends otherwise. Running
  the task again is a new job, and a person asks for it.
- With no device connected, or the subsystem off, nothing is queued and the
  answer says why. A task is never reported as run when no desktop ran it.

Nothing here controls a computer by itself: a job is created only by an
explicit request of the signed-in person, for one of their own recordings, on
one of their own paired devices. Scriba's own gates stay in force (the device
must be online and unlocked, a recording that clicks a committing control
waits for approval on the device, replay is confined to the recorded apps).

``SandboxDesktop`` is a FAKE device for demonstrations and tests. Everything
it returns is marked ``simulated: true``. It proves the bridge and the
screens, never that a real desktop did anything.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

STATES = ("ACCEPTED", "STARTED", "RUNNING", "AWAITING_APPROVAL", "VERIFIED", "SUCCEEDED_UNVERIFIED",
          "NEEDS_REVIEW", "OUTCOME_UNKNOWN", "FAILED", "CANCELLED")
FINAL = ("VERIFIED", "SUCCEEDED_UNVERIFIED", "NEEDS_REVIEW", "OUTCOME_UNKNOWN", "FAILED", "CANCELLED")
RESUME = {"supported": False,
          "reason": "Scriba's desktop agent keeps no checkpoint for a recorded task, so one cannot be resumed "
                    "where it stopped. It can be run again from the start, as a new job, when you ask."}


class DesktopUnavailable(Exception):
    """Nothing was queued, and why. ``code`` is stable."""

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ── what a job's record means ───────────────────────────────────────────────

def job_state(job: Mapping[str, Any]) -> str:
    status = str(job.get("status") or "")
    result = job.get("result") if isinstance(job.get("result"), Mapping) else {}
    if status == "queued":
        return "ACCEPTED"
    if status == "claimed":
        return "STARTED"
    if status == "running":
        return "RUNNING"
    if status == "awaiting_approval":
        return "AWAITING_APPROVAL"
    if status == "cancelled":
        return "CANCELLED"
    if status == "failed":
        stage, error = str(job.get("failure_stage") or ""), str(job.get("error") or "").lower()
        # It was started and then went silent: some of it may have happened.
        if job.get("claimed_at") and (stage in ("stale", "timeout", "device_revoked") or "report back" in error):
            return "OUTCOME_UNKNOWN"
        return "FAILED"
    if status == "succeeded":
        checks = [c for c in result.get("checks") or [] if isinstance(c, Mapping)]
        if result.get("needs_review"):
            return "NEEDS_REVIEW"
        if checks and all(_passed(c) for c in checks):
            return "VERIFIED"
        return "SUCCEEDED_UNVERIFIED" if not checks else "FAILED"
    return "FAILED"


def _passed(check: Mapping[str, Any]) -> bool:
    return check.get("passed") is True or check.get("ok") is True or str(check.get("status") or "") == "passed"


def job_view(job: Mapping[str, Any], *, simulated: bool, events: Optional[List[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), Mapping) else {}
    payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
    checks = [c for c in result.get("checks") or [] if isinstance(c, Mapping)]
    state = job_state(job)
    passed = sum(1 for c in checks if _passed(c))
    return {
        "id": job.get("id"), "deviceId": job.get("desktop_agent_id"),
        "recordingId": payload.get("recording_id"), "task": payload.get("name"),
        "state": state, "final": state in FINAL, "scribaStatus": job.get("status"),
        "failureStage": job.get("failure_stage"), "error": job.get("error"),
        "cancelRequested": bool(job.get("cancel_requested")),
        "progress": result.get("progress"),
        "result": {"stepsReplayed": result.get("replayed"), "needsReview": bool(result.get("needs_review")),
                   "healedClicks": result.get("healed_clicks"), "retried": result.get("retried"),
                   "filesDone": result.get("files_done"), "filesTotal": result.get("files_total")},
        # Evidence, or the plain absence of it.
        "verified": state == "VERIFIED",
        "verification": {"method": "recording_checks" if checks else None, "checks": len(checks), "passed": passed,
                         "reason": None if state == "VERIFIED" else
                         ("no_check_in_recording" if state == "SUCCEEDED_UNVERIFIED" else
                          "a_step_used_a_fallback" if state == "NEEDS_REVIEW" else
                          "not_finished" if state not in FINAL else state.lower())},
        "resume": dict(RESUME),
        # The steps are never returned: a recording can hold what was typed.
        "createdAt": job.get("created_at"), "startedAt": job.get("claimed_at"), "finishedAt": job.get("finished_at"),
        "updatedAt": job.get("updated_at"),
        "events": [{"at": e.get("created_at") or e.get("at"), "action": e.get("action"), "status": e.get("status"),
                    "message": e.get("message")} for e in (events or [])][-50:],
        "simulated": bool(simulated),
    }


def device_view(agent: Mapping[str, Any], *, simulated: bool) -> Dict[str, Any]:
    kind = str(agent.get("device_kind") or "desktop")
    ready = bool(agent.get("ready"))
    return {"id": agent.get("id"), "name": agent.get("device_name"), "kind": kind,
            "presence": agent.get("status"), "ready": ready, "state": agent.get("state"),
            "session": agent.get("session_state") or "unknown", "agentVersion": agent.get("agent_version"),
            "updateRequired": bool((agent.get("update") or {}).get("required")) if isinstance(agent.get("update"), Mapping) else False,
            "lastSeenAt": agent.get("last_seen_at"),
            # A recorded desktop task needs the desktop agent, not the browser extension.
            "canRunRecordedTasks": ready and kind == "desktop",
            "allowedFolders": len(agent.get("allowed_folders") or []), "simulated": bool(simulated)}


def task_view(recording: Mapping[str, Any], *, simulated: bool) -> Dict[str, Any]:
    return {"id": recording.get("id"), "name": recording.get("name"), "kind": recording.get("kind") or "desktop",
            "ready": recording.get("status") == "ready" and int(recording.get("step_count") or 0) > 0,
            "steps": int(recording.get("step_count") or 0), "hasPassword": bool(recording.get("has_password")),
            "checks": len(recording.get("checks") or []), "apps": list(recording.get("apps") or [])[:8],
            "runsWhileLocked": bool(recording.get("unattended")), "simulated": bool(simulated)}


# ── the two backends ────────────────────────────────────────────────────────

class ScribaDesktop:
    """Scriba's real desktop subsystem, called in process. Needs Scriba's
    database; on a backend without one every call fails and is reported."""

    simulated = False

    def enabled(self) -> tuple:
        from app import desktop_security

        return desktop_security.desktop_enabled()

    def devices(self, user_id: int) -> List[Dict[str, Any]]:
        from app.services import desktop_agent_service

        return desktop_agent_service.list_user_agents(int(user_id))

    def recordings(self, user_id: int) -> List[Dict[str, Any]]:
        from app.services import desktop_recording_service

        return desktop_recording_service.list_all(user_id=int(user_id))

    def replay(self, user_id: int, recording_id: int, device_id: Optional[int]) -> Dict[str, Any]:
        from app.services import desktop_recording_service

        return desktop_recording_service.replay(user_id=int(user_id), recording_id=int(recording_id),
                                                agent_id=int(device_id) if device_id else None)

    def job(self, user_id: int, job_id: int) -> Dict[str, Any]:
        from app.services import desktop_job_service

        found = desktop_job_service.get_job(user_id=int(user_id), job_id=int(job_id))
        return found.get("job", found) if isinstance(found, dict) else found

    def cancel(self, user_id: int, job_id: int) -> Dict[str, Any]:
        from app.services import desktop_job_service

        return desktop_job_service.cancel_job(user_id=int(user_id), job_id=int(job_id))

    def events(self, user_id: int, job_id: int) -> List[Dict[str, Any]]:
        from app import desktop_repository

        return list(desktop_repository.list_audit(user_id=int(user_id), desktop_job_id=int(job_id), limit=50) or [])


class SandboxDesktop:
    """A FAKE paired device inside a sandbox world, with scripted jobs.

    A job moves one status per ``step()`` (a real one moves when the device
    reports). ``script`` decides how it ends: ``pass`` (checks pass), ``no_check``,
    ``needs_review``, ``dialog`` (an unexpected window: blocked), ``silent``
    (it stops reporting). Nothing here touches a real screen."""

    simulated = True

    def __init__(self, world: Any) -> None:
        self.world = world
        self.state = world.desktop

    def enabled(self) -> tuple:
        return True, ""

    def devices(self, user_id: int) -> List[Dict[str, Any]]:
        return [dict(d) for d in self.state["devices"]]

    def recordings(self, user_id: int) -> List[Dict[str, Any]]:
        return [{k: v for k, v in r.items() if k != "script"} for r in self.state["recordings"]]

    def replay(self, user_id: int, recording_id: int, device_id: Optional[int]) -> Dict[str, Any]:
        recording = next((r for r in self.state["recordings"] if r["id"] == int(recording_id)), None)
        if recording is None:
            raise DesktopUnavailable("recording_not_found", "Recording not found.", 404)
        if recording.get("status") != "ready":
            raise DesktopUnavailable("recording_not_ready", "This recording has no steps to replay yet.")
        device = next((d for d in self.state["devices"]
                       if d["status"] == "online" and d["ready"] and (not device_id or d["id"] == int(device_id))), None)
        if device is None:
            raise DesktopUnavailable("no_device_online", "None of your computers is online and ready.")
        if device.get("session_state") == "locked":
            raise DesktopUnavailable("device_locked", "Your screen is locked, so this recorded task can't run right now.")
        job_id = len(self.state["jobs"]) + 1
        now = self.world.now().isoformat()
        self.state["jobs"][job_id] = {
            "id": job_id, "desktop_agent_id": device["id"], "status": "queued", "job_type": "rpa.replay",
            "payload": {"recording_id": recording["id"], "name": recording["name"]}, "result": {}, "error": None,
            "failure_stage": None, "created_at": now, "claimed_at": None, "finished_at": None, "updated_at": now,
            "cancel_requested": False, "_script": recording.get("script") or "pass", "_events": []}
        return {"recording_id": recording["id"], "job_id": job_id, "status": "queued"}

    def job(self, user_id: int, job_id: int) -> Dict[str, Any]:
        found = self.state["jobs"].get(int(job_id))
        if found is None:
            raise DesktopUnavailable("job_not_found", "Job not found.", 404)
        return {k: v for k, v in found.items() if not k.startswith("_")}

    def cancel(self, user_id: int, job_id: int) -> Dict[str, Any]:
        job = self.state["jobs"].get(int(job_id))
        if job is None:
            raise DesktopUnavailable("job_not_found", "Job not found.", 404)
        if job["status"] == "queued":
            job.update(status="cancelled", finished_at=self.world.now().isoformat())
        elif job["status"] in ("claimed", "running"):
            job["cancel_requested"] = True
        return {"job": self.job(user_id, job_id), "state": job["status"]}

    def events(self, user_id: int, job_id: int) -> List[Dict[str, Any]]:
        return list((self.state["jobs"].get(int(job_id)) or {}).get("_events") or [])

    def step(self, job_id: int) -> None:
        """What the fake device does next. Stands where a real agent's report would arrive."""
        job = self.state["jobs"][int(job_id)]
        now = self.world.now().isoformat()
        script, status = job["_script"], job["status"]

        def note(action: str, outcome: str, message: str = "") -> None:
            job["_events"].append({"at": now, "action": action, "status": outcome, "message": message})

        if status == "queued":
            job.update(status="claimed", claimed_at=now, updated_at=now)
            note("claim", "ok")
        elif status == "claimed":
            job.update(status="running", updated_at=now, result={"progress": {"step": 1, "of": 3}})
            note("replay", "running", "step 1 of 3")
        elif status == "running":
            if job["cancel_requested"]:
                job.update(status="cancelled", finished_at=now, updated_at=now)
                note("replay", "cancelled")
            elif script == "dialog":
                job.update(status="failed", failure_stage="blocked", finished_at=now, updated_at=now,
                           error="An unexpected window appeared and the task stopped before the next step.")
                note("replay", "blocked", "a window that was not part of the recording")
            elif script == "silent":
                job.update(status="failed", failure_stage="stale", finished_at=now, updated_at=now,
                           error="Replay didn't report back — it may have been stopped on the device.")
            else:
                checks = [] if script == "no_check" else [{"name": "the saved file exists", "passed": True}]
                job.update(status="succeeded", finished_at=now, updated_at=now, result={
                    "replayed": 3, "needs_review": script == "needs_review", "healed_clicks": 0, "retried": False,
                    "checks": checks, "progress": {"step": 3, "of": 3}})
                note("replay", "succeeded")


# ── the bridge ──────────────────────────────────────────────────────────────

class DesktopBridge:
    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway

    def _backend(self, user: Any) -> Any:
        world_for = getattr(self.gateway, "world_for", None)
        world = world_for(user) if callable(world_for) else None
        if world is not None:
            # A sandbox world never reaches a real device, with or without a fake one.
            return SandboxDesktop(world) if getattr(world, "desktop", None) else None
        return ScribaDesktop()

    def status(self, user: Any) -> Dict[str, Any]:
        """Whether a desktop can be used, the person's devices and their recorded tasks."""
        backend = self._backend(user)
        base = {"available": False, "reason": None, "message": None, "simulated": False, "devices": [],
                "tasks": [], "resume": dict(RESUME), "states": list(STATES)}
        if backend is None:
            return {**base, "reason": "no_desktop_in_sandbox", "simulated": True,
                    "message": "This sandbox world has no desktop. Nothing can be run on a computer from here."}
        try:
            enabled, reason = backend.enabled()
            if not enabled:
                return {**base, "reason": reason or "desktop_agent_disabled",
                        "message": "Scriba's desktop agent is switched off on this backend."}
            devices = [device_view(d, simulated=backend.simulated) for d in backend.devices(user.id)]
            tasks = [task_view(r, simulated=backend.simulated) for r in backend.recordings(user.id)]
        except DesktopUnavailable as exc:
            return {**base, "reason": exc.code, "message": exc.message, "simulated": backend.simulated}
        except Exception as exc:    # no database behind Scriba's desktop tables, most likely
            return {**base, "reason": "desktop_backend_unreachable",
                    "message": f"Scriba's desktop records could not be read ({type(exc).__name__})."}
        usable = [d for d in devices if d["canRunRecordedTasks"]]
        return {**base, "available": bool(usable), "simulated": backend.simulated, "devices": devices, "tasks": tasks,
                "reason": None if usable else ("no_device_paired" if not devices else "no_device_ready"),
                "message": None if usable else ("No computer is paired with this account." if not devices else
                                                "A computer is paired, but none is online, unlocked and up to date.")}

    def assign(self, user: Any, recording_id: Any, device_id: Any = None, *, confirmed: bool = False) -> Dict[str, Any]:
        """Queue one of the person's recorded tasks on one of their devices."""
        if confirmed is not True:
            raise DesktopUnavailable(
                "confirmation_required",
                "Running a recorded task acts on your computer. Confirm it explicitly; nothing was queued.", 400)
        status = self.status(user)
        if not status["available"]:
            raise DesktopUnavailable(status["reason"] or "desktop_unavailable",
                                     status["message"] or "No desktop is available. Nothing was queued.")
        if not any(t["id"] == _int(recording_id) and t["ready"] for t in status["tasks"]):
            raise DesktopUnavailable("recording_not_found", "That recorded task is not one of yours, or is not ready.", 404)
        if device_id and not any(d["id"] == _int(device_id) and d["canRunRecordedTasks"] for d in status["devices"]):
            raise DesktopUnavailable("device_not_ready", "That computer is not one of yours, or is not ready.", 409)
        backend = self._backend(user)
        try:
            queued = backend.replay(user.id, _int(recording_id), _int(device_id) if device_id else None)
        except DesktopUnavailable:
            raise
        except Exception as exc:    # Scriba's own refusal (AppError carries a code and a status)
            raise DesktopUnavailable(str(getattr(exc, "code", None) or "desktop_refused"), str(exc),
                                     int(getattr(exc, "status_code", 409) or 409))
        return self.job(user, queued.get("job_id"))

    def job(self, user: Any, job_id: Any) -> Dict[str, Any]:
        backend = self._require(user)
        try:
            found = backend.job(user.id, _int(job_id))
            events = backend.events(user.id, _int(job_id))
        except DesktopUnavailable:
            raise
        except Exception as exc:
            raise DesktopUnavailable(str(getattr(exc, "code", None) or "job_not_found"), str(exc),
                                     int(getattr(exc, "status_code", 404) or 404))
        return job_view(found, simulated=backend.simulated, events=events)

    def cancel(self, user: Any, job_id: Any) -> Dict[str, Any]:
        backend = self._require(user)
        try:
            backend.cancel(user.id, _int(job_id))
        except DesktopUnavailable:
            raise
        except Exception as exc:
            raise DesktopUnavailable(str(getattr(exc, "code", None) or "cancel_failed"), str(exc),
                                     int(getattr(exc, "status_code", 409) or 409))
        return self.job(user, job_id)

    def _require(self, user: Any) -> Any:
        backend = self._backend(user)
        if backend is None:
            raise DesktopUnavailable("no_desktop_in_sandbox", "This sandbox world has no desktop.", 404)
        return backend


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise DesktopUnavailable("invalid_request", "An id must be a whole number.", 400)
