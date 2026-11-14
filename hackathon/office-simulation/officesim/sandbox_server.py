"""The Desk's isolated sandbox backend, holding the fictional office.

Runs Scriba's own seeded test server (the real FastAPI application with every
storage boundary in memory: no database, no provider network), mounts the
Desk overlay from Agent 1's backend on it exactly as that backend's own dev
server does, gives the signed-in user ONE sandbox world built from the office
specification, and adds the simulator's control routes (``control.py``).

Nothing in Scriba or in the Desk backend is modified or copied: both are
imported from where they are.

    SCRIBA_BACKEND_PATH   the Gmail/ directory of a Scriba checkout (read only)
    DESK_BACKEND_PATH     the backend/ directory that contains desk_overlay

    <python with Scriba's dependencies> -m officesim.sandbox_server \
        --port 8914 --spec office.json [--worker manual|thread] [--claims memory|sqlite:<path>]

No model is called unless the operator sets ``DESK_MODEL=on`` with a real key
in the environment. No real mailbox or calendar exists behind this process.
"""
from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

REQUIRED_DESK_MODULES = ("sandbox.py", "execution.py", "worker.py", "install.py", "workflow.py")


def missing_contract(desk_backend: Path) -> list:
    """What this simulator needs from the Desk backend that is not there."""
    overlay = desk_backend / "desk_overlay"
    return [name for name in REQUIRED_DESK_MODULES if not (overlay / name).is_file()]


def _commit(path: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8914)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--spec", required=True, help="office specification (JSON, from officesim.office)")
    parser.add_argument("--worker", choices=("manual", "thread"), default="manual",
                        help="manual: the simulator runs each worker pass; thread: the Desk's own timer")
    parser.add_argument("--claims", default="memory", help="memory, or sqlite:<path>")
    args = parser.parse_args()

    scriba = Path(os.environ.get("SCRIBA_BACKEND_PATH", "").strip() or ".")
    seeded = scriba / "e2e" / "seeded_server.py"
    if not seeded.is_file():
        sys.exit("Set SCRIBA_BACKEND_PATH to the Gmail/ directory of a Scriba checkout.")
    desk_backend = Path(os.environ.get("DESK_BACKEND_PATH", "").strip() or ".")
    missing = missing_contract(desk_backend)
    if missing:
        sys.exit("DESK_BACKEND_PATH must be a Desk backend with the sandbox engine. Missing: "
                 + ", ".join(f"desk_overlay/{name}" for name in missing)
                 + ". See docs/INTEGRATION_REQUESTS.md.")

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    here = Path(__file__).resolve().parents[1]
    for entry in (str(here), str(desk_backend / "dev"), str(desk_backend)):
        if entry not in sys.path:
            sys.path.insert(0, entry)

    # The same process settings the Desk's own dev server uses.
    os.environ.setdefault("DESK_CHAT_SCOPE", "on")
    os.environ["DESK_CLAIMS"] = args.claims
    os.environ.setdefault("DESK_MODEL", "off")       # no model unless the operator asks for one
    os.environ.setdefault("DESK_EVAL_SANDBOX", "off")
    # A simulated day arrives in seconds of real time; the worker's real-time
    # limits are set wide so they do not shape the result.
    os.environ.setdefault("DESK_INTAKE_MAX_NEW", "10")
    os.environ.setdefault("DESK_INTAKE_MAX_PER_HOUR", "500")
    os.environ.setdefault("DESK_INTAKE_MAX_PENDING", "500")
    if args.worker == "thread":
        os.environ.setdefault("DESK_INTAKE_WORKER", "on")
        os.environ.setdefault("DESK_INTAKE_INTERVAL", "15")
    else:
        os.environ["DESK_INTAKE_WORKER"] = "off"

    import uvicorn

    serve = uvicorn.run

    def serve_with_office(app, *a, **kw):
        from desk_overlay import install
        from desk_overlay.sandbox import SandboxWorld, WorldRegistry
        from seeded_desk_server import _seeded_chat_store_shims    # Agent 1's seeded-backend shims

        from officesim.control import build_control_router, build_world

        _seeded_chat_store_shims()
        registry = WorldRegistry()
        world = registry.add(build_world(SandboxWorld, spec), default=True)
        install(app, registry=registry)
        options = {"worker": args.worker, "claims": args.claims,
                   "deskBackendCommit": _commit(desk_backend),
                   "model": os.environ.get("DESK_MODEL", "off")}
        app.include_router(build_control_router(app, spec, world, options))
        print(f"[officesim] sandbox world {world.id} for {world.owner_email}: "
              f"{len(world.events)} events, {len(world.tasks)} tasks; worker={args.worker}; "
              f"claims={args.claims}; model={options['model']} (synthetic office, no provider)",
              flush=True)
        return serve(app, *a, **kw)

    uvicorn.run = serve_with_office
    sys.argv = [str(seeded), "--port", str(args.port), "--host", args.host]
    runpy.run_path(str(seeded), run_name="__main__")


if __name__ == "__main__":
    main()
