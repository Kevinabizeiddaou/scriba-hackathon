"""Scriba's seeded test backend with the Desk overlay mounted.

Runs Scriba's own ``e2e/seeded_server.py`` (the real FastAPI application with
every storage boundary in memory: no database, no provider network, no model)
and adds the ``/desk/*`` routes to it. Nothing in Scriba is modified: the
overlay is attached to the application object just before it starts serving.

    set SCRIBA_BACKEND_PATH=<path to a Scriba checkout>\\Gmail
    <scriba python> backend/dev/seeded_desk_server.py --port 8788
    <scriba python> backend/dev/seeded_desk_server.py --port 8788 --demo

``--demo`` gives the seeded users Alice and Bob an isolated provider world
each (``demo_world.py``): synthetic Gmail and Outlook mail, a Google and an
Outlook calendar, and the background intake worker switched on. Mail in it
becomes Desk runs by itself, and approving an action executes it against the
world. No mailbox or calendar exists behind it. Without ``--demo`` the server
behaves as before: Scriba's own seeded inbox, nothing to execute.

Seeded sign-in users are documented at the top of Scriba's seeded_server.py.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEMO_USERS = ("alice@example.com", "bob@example.com")


def main() -> None:
    scriba = os.environ.get("SCRIBA_BACKEND_PATH", "").strip()
    seeded = Path(scriba) / "e2e" / "seeded_server.py"
    if not scriba or not seeded.is_file():
        sys.exit("Set SCRIBA_BACKEND_PATH to the Gmail/ directory of a Scriba checkout.")

    demo = "--demo" in sys.argv
    if demo:
        sys.argv.remove("--demo")
    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    # This process serves only the Desk, so Scriba's chat agent is scoped to
    # the Desk's tools here. Set DESK_CHAT_SCOPE=off to run without the scope.
    os.environ.setdefault("DESK_CHAT_SCOPE", "on")
    # Runs live in memory here, so claims do too.
    os.environ.setdefault("DESK_CLAIMS", "memory")
    # No model unless the operator asks for one: Scriba's test harness sets a
    # placeholder key, and a call with it would be an outbound request that
    # can only fail. To use a real model: DESK_MODEL=on and a real key.
    os.environ.setdefault("DESK_MODEL", "off")
    # The evaluation routes exist only in a process that asks for them.
    os.environ.setdefault("DESK_EVAL_SANDBOX", "on")
    if demo:
        os.environ.setdefault("DESK_INTAKE_WORKER", "on")
        os.environ.setdefault("DESK_INTAKE_INTERVAL", "15")

    import uvicorn

    serve = uvicorn.run

    def serve_with_desk(app, *args, **kwargs):
        from desk_overlay import install
        from desk_overlay.sandbox import WorldRegistry

        _seeded_chat_store_shims()
        registry = WorldRegistry()
        if demo:
            from demo_world import install_demo_worlds

            worlds = install_demo_worlds(registry, list(DEMO_USERS))
            print(f"[desk] demo worlds: {', '.join(w.owner_email for w in worlds)} "
                  "(synthetic mail and calendars; the intake worker is on)", flush=True)
        install(app, registry=registry)
        return serve(app, *args, **kwargs)

    uvicorn.run = serve_with_desk
    sys.argv = [str(seeded), *sys.argv[1:]]
    runpy.run_path(str(seeded), run_name="__main__")


def _seeded_chat_store_shims() -> None:
    """Seeded-backend shims only. A real Scriba backend loads none of this.

    Scriba's real chat repository (a) stores a conversation's ``metadata``,
    where the Desk keeps a run's identity, and (b) MERGES an update's
    ``output_payload_patch`` into the card's output. The seeded server's
    in-memory stand-in drops the first and stores the second unmerged, so
    here both are done beside that stand-in, the way the real repository does.
    """
    import app.chat_repository as chat_repo

    kept = {}
    create, get, listing = (chat_repo.create_conversation, chat_repo.get_conversation,
                            chat_repo.list_conversations)
    update_card, get_card = chat_repo.update_tool_call, chat_repo.get_tool_call
    stale = tuple(getattr(chat_repo, "_STALE_QUESTION_KEYS", ()))

    def with_metadata(row):
        if row and row.get("id") in kept and not row.get("metadata"):
            row = {**row, "metadata": kept[row["id"]]}
        return row

    def create_conversation(**kwargs):
        row = create(**kwargs)
        if row and kwargs.get("metadata"):
            kept[row["id"]] = dict(kwargs["metadata"])
        return with_metadata(row)

    def update_tool_call(tool_call_id, *, user_id=None, output_payload_patch=None,
                         input_payload=None, **fields):
        before = get_card(tool_call_id, user_id=user_id)
        if before is None:
            return None
        if output_payload_patch is not None or fields.get("status") in ("executed", "partially_executed"):
            merged = dict(before.get("output_payload") or {})
            if fields.get("status") in ("executed", "partially_executed"):
                for key in stale:
                    merged.pop(key, None)
            merged.update(output_payload_patch or {})
            fields["output_payload"] = merged
        if input_payload is not None:
            fields["input_payload"] = dict(input_payload)
        return update_card(tool_call_id, user_id=user_id, **fields)

    chat_repo.create_conversation = create_conversation
    chat_repo.get_conversation = lambda *a, **k: with_metadata(get(*a, **k))
    chat_repo.list_conversations = lambda *a, **k: [with_metadata(r) for r in listing(*a, **k)]
    chat_repo.update_tool_call = update_tool_call


if __name__ == "__main__":
    main()
