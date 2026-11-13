"""Scriba Executive Desk backend overlay.

Desk-specific backend code that runs INSIDE Scriba's existing API process.
It adds routes under ``/desk/`` to Scriba's FastAPI application and reaches
Scriba's session, provider connections, mail listing, calendar clients and
preferences through one seam (``gateway.py``). It owns no authentication, no
database and no provider registration.

Run it with Scriba's own environment:

    APP_MODULE=desk_overlay.asgi:app   (see backend/README.md)
"""

__version__ = "0.2.0"

from .install import install  # noqa: E402,F401
