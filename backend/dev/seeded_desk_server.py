"""Scriba's seeded test backend with the Desk overlay mounted.

Runs Scriba's own ``e2e/seeded_server.py`` (the real FastAPI application with
every storage boundary in memory: no database, no provider network, no model)
and adds the ``/desk/*`` routes to it. Nothing in Scriba is modified: the
overlay is attached to the application object just before it starts serving.

    set SCRIBA_BACKEND_PATH=<path to a Scriba checkout>\\Gmail
    <scriba python> backend/dev/seeded_desk_server.py --port 8788

Seeded sign-in users are documented at the top of Scriba's seeded_server.py.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def main() -> None:
    scriba = os.environ.get("SCRIBA_BACKEND_PATH", "").strip()
    seeded = Path(scriba) / "e2e" / "seeded_server.py"
    if not scriba or not seeded.is_file():
        sys.exit("Set SCRIBA_BACKEND_PATH to the Gmail/ directory of a Scriba checkout.")

    sys.path.insert(0, str(BACKEND))
    # This process serves only the Desk, so Scriba's chat agent is scoped to
    # the Desk's tools here. Set DESK_CHAT_SCOPE=off to run without the scope.
    os.environ.setdefault("DESK_CHAT_SCOPE", "on")

    import uvicorn

    serve = uvicorn.run

    def serve_with_desk(app, *args, **kwargs):
        from desk_overlay import install

        _keep_conversation_metadata()
        install(app)
        return serve(app, *args, **kwargs)

    uvicorn.run = serve_with_desk
    sys.argv = [str(seeded), *sys.argv[1:]]
    runpy.run_path(str(seeded), run_name="__main__")


def _keep_conversation_metadata() -> None:
    """Seeded-backend shim only.

    Scriba's real repository stores a conversation's ``metadata`` (the Desk
    keeps a run's identity there). The seeded server's in-memory stand-in
    drops it, so here it is remembered beside that stand-in. A real Scriba
    backend does not need or load this.
    """
    import app.chat_repository as chat_repo

    kept = {}
    create, get, listing = (chat_repo.create_conversation, chat_repo.get_conversation,
                            chat_repo.list_conversations)

    def with_metadata(row):
        if row and row.get("id") in kept and not row.get("metadata"):
            row = {**row, "metadata": kept[row["id"]]}
        return row

    def create_conversation(**kwargs):
        row = create(**kwargs)
        if row and kwargs.get("metadata"):
            kept[row["id"]] = dict(kwargs["metadata"])
        return with_metadata(row)

    chat_repo.create_conversation = create_conversation
    chat_repo.get_conversation = lambda *a, **k: with_metadata(get(*a, **k))
    chat_repo.list_conversations = lambda *a, **k: [with_metadata(r) for r in listing(*a, **k)]


if __name__ == "__main__":
    main()
