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

    import uvicorn

    serve = uvicorn.run

    def serve_with_desk(app, *args, **kwargs):
        from desk_overlay import install

        install(app)
        return serve(app, *args, **kwargs)

    uvicorn.run = serve_with_desk
    sys.argv = [str(seeded), *sys.argv[1:]]
    runpy.run_path(str(seeded), run_name="__main__")


if __name__ == "__main__":
    main()
