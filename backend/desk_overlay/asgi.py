"""ASGI entry point: Scriba's application with the Desk routes mounted.

Scriba starts ``uvicorn ${APP_MODULE}`` with ``APP_MODULE=app.main:app``.
Pointing ``APP_MODULE`` at ``desk_overlay.asgi:app`` (with this package and
Scriba's ``Gmail/`` directory both on ``PYTHONPATH``) starts the same
application, unchanged, plus ``/desk/*``.
"""
from app.main import app as _scriba_app  # Scriba's application, unmodified

from . import install

app = install(_scriba_app)
