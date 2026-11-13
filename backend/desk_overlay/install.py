"""Attach the Desk routes to a Scriba FastAPI application."""
from __future__ import annotations

from typing import Any, Optional

_MARKER = "_desk_overlay_installed"


def install(app: Any, gateway: Optional[Any] = None) -> Any:
    """Mount ``/desk/*`` on ``app`` and return it. Safe to call twice.

    The routes are added to Scriba's own application object, so they sit
    behind Scriba's existing middleware: the session guard answers 401 for a
    request without a session, the cross-site check refuses state-changing
    requests from untrusted origins, and CORS is Scriba's.
    """
    if getattr(app.state, _MARKER, False):
        return app

    from .gateway import ScribaGateway
    from .routes import build_router

    app.include_router(build_router(gateway or ScribaGateway()))
    setattr(app.state, _MARKER, True)
    return app
