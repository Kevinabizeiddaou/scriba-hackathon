"""Lab harness server: the Desk backend, UNMODIFIED, plus lab probe routes.

    set SCRIBA_BACKEND_PATH=<Scriba checkout>\\Gmail          (read-only checkout)
    <python> labs/autonomy-quality/server/lab_server.py --backend <hackathon checkout>/backend --port 8811

It runs ``<backend>/dev/seeded_desk_server.py`` exactly as that file runs
itself. No file of the backend is edited or copied. The only thing added is
a set of routes under ``/lab/v1`` that are mounted on the application AFTER
the backend's own ``install`` returned:

* **Observation** (read-only): the full state of a sandbox world. The
  evaluation contract (``/desk/eval/v1``) reports what the engine SAYS it
  did; it has no route that shows the synthetic office afterwards. The lab's
  outcome oracle refuses to trust a claim, so it reads the world itself.
* **Environment control**: an office the lab builds for a seeded user (two
  mailboxes, two calendars, a clock), mail arriving in it, and the outside
  world changing while a run is open (someone else books the slot, a
  calendar stops answering, a provider starts failing). These touch the
  SandboxWorld only: the provider stand-in, never the Desk's decisions.
* **Fault simulation on stored state** (clearly instrumented, used only by
  the adversarial campaign): a stored action changed behind an approval, and
  a process that stopped mid-action. They exist because no public route can
  produce those conditions; each result that used one says so.

Everything here is test instrumentation. It is never mounted in a product
process: this file is the only place that mounts it. The interface the lab
would like the backend to offer natively instead is in
``docs/INTEGRATION_INTERFACE.md``.
"""

import argparse
import datetime as dt
import os
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

LAB_SERVER_VERSION = "1.0.0"


def _git(path: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (dt.datetime, dt.date)) else value


def dump_world(world: Any) -> Dict[str, Any]:
    """Everything in a SandboxWorld, as plain JSON. Reads only."""
    with world._lock:
        events = [{key: _iso(val) for key, val in event.items()} for event in world.events.values()]
        return {
            "id": world.id, "label": world.label, "evaluation": bool(world.evaluation),
            "now": world.now().isoformat(), "timezone": world.timezone,
            "ownerEmail": world.owner_email, "principalEmail": world.principal_email,
            "accounts": {"gmail": list(world.gmail_accounts), "outlook": world.outlook_account},
            "ownAddresses": world.own_addresses(),
            "preferences": dict(world.preferences),
            "autoInternalWrites": bool(world.auto_internal_writes),
            "events": sorted(events, key=lambda e: str(e.get("start"))),
            "mail": {provider: [dict(row) for row in rows] for provider, rows in world.mail.items()},
            "sent": [dict(row) for row in world.sent],
            "drafts": [dict(row) for row in world.drafts],
            "tasks": [dict(row) for row in world.tasks],
            "reminders": [dict(row) for row in world.reminders],
            "followUps": [dict(row) for row in world.follow_ups],
            "faults": [dict(row) for row in world.faults],
            "unreadable": dict(world.unreadable),
            "operations": [dict(row) for row in world.oplog],
            "isolationViolations": list(world.violations),
        }


def _apply_changes(world: Any, body: Mapping[str, Any]) -> Dict[str, Any]:
    """The outside world changes. Provider stand-in only."""
    from desk_overlay.sandbox import parse_time

    applied: Dict[str, Any] = {}
    if body.get("now"):
        world.set_now(parse_time(body["now"]))
        applied["now"] = world.now().isoformat()
    for event in body.get("addEvents") or []:
        row = world.add_event(
            provider=str(event.get("provider") or "google"), event_id=event.get("id"),
            title=str(event.get("title") or "Busy"), start=event.get("start"), end=event.get("end"),
            account=event.get("account"), attendees=list(event.get("attendees") or []),
            organizer=event.get("organizer"), location=event.get("location"),
            description=str(event.get("description") or ""))
        applied.setdefault("addedEvents", []).append(row["id"])
    for event_id in body.get("removeEvents") or []:
        with world._lock:
            if world.events.pop(str(event_id), None) is not None:
                applied.setdefault("removedEvents", []).append(str(event_id))
    for key, code in (body.get("unreadable") or {}).items():
        if code:
            world.unreadable[str(key)] = str(code)
        else:
            world.unreadable.pop(str(key), None)
        applied["unreadable"] = dict(world.unreadable)
    for fault in body.get("faults") or []:
        world.add_fault(str(fault.get("tool")), mode=str(fault.get("mode") or "fail_always"),
                        times=int(fault.get("times") or 1), error=str(fault.get("error") or "provider_error"))
        applied.setdefault("faults", []).append(fault.get("tool"))
    if body.get("clearFaults"):
        world.faults.clear()
        applied["clearFaults"] = True
    for message in body.get("deliver") or []:
        row = world.deliver(
            provider=str(message.get("provider") or "gmail"), message_id=message.get("id"),
            from_addr=str(message.get("from") or ""), subject=str(message.get("subject") or ""),
            body=str(message.get("body") or ""), thread_id=message.get("threadId"),
            received_at=parse_time(message.get("receivedAt")), account=message.get("account"),
            to=message.get("to"), labels=message.get("labels"))
        applied.setdefault("delivered", []).append(
            {"id": row["id"], "threadId": row["threadId"], "provider": row["provider"],
             "provider_account_id": row["provider_account_id"]})
    for sent in body.get("sent") or []:
        world.sent.append({
            "id": str(sent.get("id")), "provider": str(sent.get("provider") or "gmail"),
            "provider_account_id": (sent.get("account") or world.principal_email),
            "to": list(sent.get("to") or []), "subject": str(sent.get("subject") or ""),
            "text": str(sent.get("body") or ""), "thread_id": sent.get("threadId"), "mode": "compose",
            "in_reply_to": None, "sent_at": sent.get("sentAt") or world.now().isoformat()})
        applied.setdefault("sentSeeded", []).append(str(sent.get("id")))
    return applied


def mount_lab_routes(app: Any, info: Dict[str, Any]) -> None:
    from fastapi import APIRouter, HTTPException, Request

    desk = getattr(app.state, "desk", None) or {}
    router = APIRouter(prefix="/lab/v1", tags=["lab"])
    gateway = desk.get("gateway")
    registry = desk.get("registry")

    def user_of(request: Request) -> Any:
        if gateway is None:
            raise HTTPException(status_code=501, detail="This backend has no Desk gateway.")
        return gateway.current_user(request)

    def eval_record(request: Request, run_id: str) -> Dict[str, Any]:
        user = user_of(request)
        runs = desk.get("eval")
        record = runs.runs.get(run_id) if runs is not None else None
        if record is None or record["user"].id != user.id:
            raise HTTPException(status_code=404, detail="Evaluation run not found.")
        return record

    def office_of(request: Request) -> Any:
        user = user_of(request)
        world = registry.default_for(user.email) if registry is not None else None
        if world is None:
            raise HTTPException(status_code=404, detail="No lab office for this user. POST /lab/v1/office first.")
        return world

    @router.get("/info")
    def lab_info(request: Request) -> Dict[str, Any]:
        user_of(request)
        gate = desk.get("gate")
        return {**info, "labServerVersion": LAB_SERVER_VERSION,
                "features": {
                    "evalWorldProbe": desk.get("eval") is not None,
                    "office": registry is not None,
                    "storedStateFaults": gate is not None,
                },
                "env": {key: os.environ.get(key) for key in (
                    "DESK_MODEL", "DESK_UNDERSTANDING", "DESK_AGENT", "DESK_CHAT_SCOPE", "DESK_CLAIMS",
                    "DESK_EVAL_SANDBOX", "DESK_INTAKE_WORKER")},
                "gateStats": dict(getattr(gate, "stats", {}) or {})}

    # ── observation ─────────────────────────────────────────────────────────
    @router.get("/eval-runs/{run_id}/world")
    def eval_world(request: Request, run_id: str) -> Dict[str, Any]:
        record = eval_record(request, run_id)
        return {"evalRunId": run_id, "deskRunId": record.get("deskRunId"), "world": dump_world(record["world"])}

    @router.get("/office/world")
    def office_world(request: Request) -> Dict[str, Any]:
        return {"world": dump_world(office_of(request))}

    # ── environment control ─────────────────────────────────────────────────
    @router.post("/eval-runs/{run_id}/world/changes")
    async def eval_world_changes(request: Request, run_id: str) -> Dict[str, Any]:
        record = eval_record(request, run_id)
        return {"applied": _apply_changes(record["world"], await request.json())}

    @router.post("/office")
    async def office_create(request: Request) -> Dict[str, Any]:
        """A fresh office for the caller: its own accounts, clock and calendars."""
        from desk_overlay.sandbox import SandboxWorld, parse_time

        user = user_of(request)
        if registry is None:
            raise HTTPException(status_code=501, detail="This backend has no sandbox worlds.")
        body = await request.json()
        import uuid

        hours = body.get("workingHours") or {}
        gmail = [str(a).lower() for a in (body.get("gmailAccounts") or [])]
        world = SandboxWorld(
            f"lab-{uuid.uuid4().hex[:12]}", owner_email=user.email,
            principal_email=str(body.get("principalEmail") or (gmail[0] if gmail else user.email)),
            principal_name=str(body.get("principalName") or ""), timezone=str(body.get("timezone") or "UTC"),
            gmail_accounts=gmail, outlook_account=body.get("outlookAccount"),
            now=parse_time(body.get("now")), label="lab-office",
            preferences={
                "workday_start_time": f"{hours.get('start') or '09:00'}:00",
                "workday_end_time": f"{hours.get('end') or '18:00'}:00",
                "preferred_weekdays": [int(d) - 1 for d in (hours.get("days") or [1, 2, 3, 4, 5])],
            })
        world.auto_internal_writes = bool(body.get("autoInternalWrites"))
        registry.add(world, default=True)
        applied = _apply_changes(world, {key: body.get(key) for key in (
            "addEvents", "unreadable", "faults", "deliver", "sent")})
        for task in body.get("tasks") or []:
            world.tasks.append({"id": str(task.get("id")), "title": str(task.get("title") or ""),
                                "due_at": task.get("dueAt"), "status": task.get("status") or "open"})
        return {"world": world.id, "applied": applied}

    @router.post("/office/changes")
    async def office_changes(request: Request) -> Dict[str, Any]:
        return {"applied": _apply_changes(office_of(request), await request.json())}

    # ── fault simulation on stored state (instrumented) ─────────────────────
    @router.post("/cards/{card_id}/tamper")
    async def tamper_card(request: Request, card_id: int) -> Dict[str, Any]:
        """Change a stored action behind its approval, with no human edit
        recorded: what a bug or a compromised component would do."""
        from app import chat_repository

        user = user_of(request)
        body = await request.json()
        row = chat_repository.get_tool_call(card_id, user_id=user.id)
        if not row:
            raise HTTPException(status_code=404, detail="Card not found.")
        changed = {**dict(row.get("input_payload") or {}), **dict(body.get("input") or {})}
        chat_repository.update_tool_call(card_id, user_id=user.id, input_payload=changed)
        return {"cardId": card_id, "instrumented": True, "changedFields": sorted(dict(body.get("input") or {}))}

    @router.post("/cards/{card_id}/interrupt")
    async def interrupt_card(request: Request, card_id: int) -> Dict[str, Any]:
        """Leave a card as a process that died mid-action leaves it:
        ``executing``, with or without the effect in the provider."""
        from app import chat_repository
        from desk_overlay.gateway import DeskUser

        user = user_of(request)
        body = await request.json()
        row = chat_repository.get_tool_call(card_id, user_id=user.id)
        if not row:
            raise HTTPException(status_code=404, detail="Card not found.")
        gate = desk["gate"]
        desk_user = DeskUser(id=int(user.id), email=user.email)
        run = gateway.get_run(desk_user, int(row.get("conversation_id") or 0))
        world = gate.world_for_run(desk_user, run)
        effect = None
        if body.get("effectApplied") and world is not None:
            # The provider did it; the process died before recording so.
            from desk_overlay.sandbox import parse_time

            data = dict(row.get("input_payload") or {})
            tool = str(row.get("tool_name") or "")
            if tool == "create_calendar_event":
                created = world.add_event(
                    provider=str(data.get("calendar_provider") or "google"),
                    title=str(data.get("title") or data.get("summary") or "Meeting"),
                    start=data.get("start"), end=data.get("end"),
                    account=data.get("provider_account_id"), attendees=list(data.get("attendees") or []))
                effect = created["id"]
            elif tool == "send_email":
                world.sent.append({
                    "id": f"sent-interrupted-{card_id}", "provider": str(data.get("provider") or "gmail"),
                    "provider_account_id": data.get("provider_account_id"), "to": data.get("to"),
                    "subject": str(data.get("subject") or ""), "text": str(data.get("body") or data.get("text") or ""),
                    "thread_id": data.get("thread_id"), "mode": "reply", "in_reply_to": data.get("email_id"),
                    "sent_at": world.now().isoformat()})
                effect = f"sent-interrupted-{card_id}"
            _ = parse_time
        chat_repository.update_tool_call(card_id, user_id=user.id, status="executing")
        return {"cardId": card_id, "instrumented": True, "status": "executing", "effectApplied": effect}

    @router.post("/runs/{run_id}/recover")
    async def recover_run(request: Request, run_id: int) -> Dict[str, Any]:
        """What the worker does for a run with a card left in flight."""
        from desk_overlay.gateway import DeskUser

        user = user_of(request)
        desk_user = DeskUser(id=int(user.id), email=user.email)
        run = gateway.get_run(desk_user, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        settled = desk["gate"].recover_stale(desk_user, run, older_than_seconds=-1)
        return {"runId": run_id, "instrumented": True, "settled": settled}

    app.include_router(router)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backend", required=True, help="the backend/ directory of a scriba-hackathon checkout")
    parser.add_argument("--port", default="8811")
    parser.add_argument("--demo", action="store_true", help="also start the backend's own demo worlds and worker")
    parser.add_argument("--model-key-file", help="a git-ignored file holding OPENAI_API_KEY=... (and optionally "
                                                 "OPENAI_BASE_URL=...), as backend/.env.model.local. Switches the real "
                                                 "model on for this sandbox backend. The key is never printed or stored")
    parser.add_argument("--agent-step", action="store_true", help="with a model: also switch on the bounded model step")
    args = parser.parse_args()

    backend = Path(args.backend).resolve()
    seeded = backend / "dev" / "seeded_desk_server.py"
    if not seeded.is_file():
        sys.exit(f"{seeded} not found: --backend must be the backend/ directory of a hackathon checkout.")
    scriba = os.environ.get("SCRIBA_BACKEND_PATH", "").strip()
    if not scriba:
        sys.exit("Set SCRIBA_BACKEND_PATH to the Gmail/ directory of a read-only Scriba checkout.")
    # A lab backend never calls a model unless the operator explicitly asks.
    if args.model_key_file:
        values = {}
        for line in Path(args.model_key_file).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip().strip("\"'")
        if values.get("OPENAI_API_KEY", "") in ("", "PASTE_KEY_HERE", "test-key", "test", "dummy", "sk-test"):
            sys.exit("--model-key-file holds no real key.")
        for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
            if values.get(name):
                os.environ[name] = values[name]
        os.environ["DESK_MODEL"] = "on"
        os.environ["DESK_UNDERSTANDING"] = "model"
        if args.agent_step:
            os.environ["DESK_AGENT"] = "on"
        print("[lab] a real model is ON for this sandbox backend: synthetic case mail will be sent to the model "
              "provider. No mailbox or calendar can be reached.", flush=True)
    os.environ.setdefault("DESK_MODEL", "off")

    info = {
        "backendPath": str(backend),
        "backendCommit": _git(backend, "rev-parse", "HEAD"),
        "backendDirty": bool(_git(backend, "status", "--porcelain", "--", ".")),
        "scribaCommit": _git(Path(scriba), "rev-parse", "HEAD"),
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    sys.path.insert(0, str(backend))
    import desk_overlay

    backend_install = desk_overlay.install

    def install_then_mount(app: Any, *a: Any, **k: Any) -> Any:
        result = backend_install(app, *a, **k)          # the backend, untouched
        mount_lab_routes(app, info)                     # then the lab's probe
        print(f"[lab] probe routes mounted on backend {info['backendCommit']}", flush=True)
        return result

    desk_overlay.install = install_then_mount
    sys.argv = [str(seeded), "--port", str(args.port), *(["--demo"] if args.demo else [])]
    runpy.run_path(str(seeded), run_name="__main__")


if __name__ == "__main__":
    main()
