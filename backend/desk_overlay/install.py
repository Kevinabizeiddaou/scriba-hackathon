"""Attach the Desk routes, and optionally the Desk chat scope, to a Scriba application."""
from __future__ import annotations

from typing import Any, Optional

_MARKER = "_desk_overlay_installed"


def install(app: Any, gateway: Optional[Any] = None, *, chat_scope: Optional[bool] = None) -> Any:
    """Mount ``/desk/*`` on ``app`` and return it. Safe to call twice.

    The routes are added to Scriba's own application object, so they sit
    behind Scriba's existing middleware: the session guard answers 401 for a
    request without a session, the cross-site check refuses state-changing
    requests from untrusted origins, and CORS is Scriba's.

    ``chat_scope`` narrows Scriba's chat agent to the Desk's tools for the
    WHOLE process (see ``chat_scope.py``). Default: on only when the
    ``DESK_CHAT_SCOPE`` environment variable asks for it. Enable it only in a
    process dedicated to the Desk.
    """
    if getattr(app.state, _MARKER, False):
        return app

    from . import chat_scope as scope
    from .gateway import ScribaGateway
    from .routes import build_router

    gateway = gateway or ScribaGateway()
    if scope.scope_requested() if chat_scope is None else chat_scope:
        scope.enable(app, gateway)
    app.include_router(build_router(gateway, extra_health=lambda request: scope.status()))
    setattr(app.state, _MARKER, True)
    return app
