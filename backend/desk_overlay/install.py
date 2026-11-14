"""Attach the Desk routes, the execution gate, the worker and optionally the
Desk chat scope to a Scriba application."""
from __future__ import annotations

import os
from typing import Any, Mapping, Optional

_MARKER = "_desk_overlay_installed"


def _claims(gateway: Any, env: Mapping[str, str]) -> Any:
    """``DESK_CLAIMS``: ``scriba`` (default: Scriba's receipt ledger),
    ``sqlite:<path>`` (a local file) or ``memory`` (this process only)."""
    from .claims import MemoryClaims, ScribaReceiptClaims, SqliteClaims

    choice = str(env.get("DESK_CLAIMS") or "scriba").strip()
    if choice == "memory":
        return MemoryClaims()
    if choice.startswith("sqlite:"):
        return SqliteClaims(choice.split(":", 1)[1])
    return ScribaReceiptClaims(gateway)


def install(app: Any, gateway: Optional[Any] = None, *, chat_scope: Optional[bool] = None,
            registry: Optional[Any] = None, env: Optional[Mapping[str, str]] = None) -> Any:
    """Mount ``/desk/*`` on ``app`` and return it. Safe to call twice.

    The routes are added to Scriba's own application object, so they sit
    behind Scriba's existing middleware: the session guard answers 401 for a
    request without a session, the cross-site check refuses state-changing
    requests from untrusted origins, and CORS is Scriba's.

    The execution gate (``execution.py``) is always installed. It holds real
    mail and calendar writes for Desk runs unless ``readiness`` enables them,
    and sends approved actions to a sandbox world when one is in force.

    ``chat_scope`` narrows Scriba's chat agent to the Desk's tools for the
    WHOLE process (see ``chat_scope.py``). Default: on only when the
    ``DESK_CHAT_SCOPE`` environment variable asks for it. Enable it only in a
    process dedicated to the Desk.
    """
    if getattr(app.state, _MARKER, False):
        app.state.desk["gate"].install()      # idempotent; restores it after ``uninstall``
        return app

    from . import chat_scope as scope
    from .execution import ExecutionGate
    from .gateway import ScribaGateway
    from .routes import build_router
    from .sandbox import RoutedGateway, WorldRegistry
    from .service import AppContext
    from .worker import IntakeWorker

    env = env if env is not None else os.environ
    registry = registry or WorldRegistry()
    routed = RoutedGateway(gateway or ScribaGateway(), registry)

    gate = ExecutionGate(routed, registry, scope_enforced=scope.is_enabled, env=env).install()
    if scope.scope_requested() if chat_scope is None else chat_scope:
        scope.enable(app, routed)

    agent = None
    if str(env.get("DESK_AGENT") or "").strip().lower() in ("1", "true", "on"):
        from .agent import DeskAgent

        agent = DeskAgent(routed, env=env)
    from .jira.routes import build_jira_router, health as jira_health

    router = build_router(routed, registry=registry, claims=_claims(routed, env), env=env, agent=agent,
                          extra_health=lambda request: {**scope.status(), **jira_health(env)})
    desk = router.desk
    desk["gate"] = gate
    workflow = desk["workflow"]
    # Once an approved step has executed, propose what follows it at once.
    gate.on_settled = lambda user, run: workflow.advance(AppContext(app), user, run["id"])
    desk["worker"] = IntakeWorker(app, routed, workflow, env=env, registry=registry)
    desk["worker"].recover = gate.recover_stale
    # One structured model call reads a message's intents, when asked for and
    # when a model is really configured (never with a placeholder key).
    workflow.model_understanding = str(env.get("DESK_UNDERSTANDING") or "").strip().lower() == "model"
    app.include_router(router)
    # Jira (desk_overlay/jira). Always mounted; only /desk/jira/status answers
    # unless DESK_JIRA is on.
    jira_router = build_jira_router(routed, env=env)
    desk["jira"] = jira_router.jira
    app.include_router(jira_router)

    if str(env.get("DESK_EVAL_SANDBOX") or "").strip().lower() in ("1", "true", "on"):
        from .eval_api import build_eval_router

        app.include_router(build_eval_router(app, desk))

    app.state.desk = desk
    setattr(app.state, _MARKER, True)
    desk["worker"].start()
    return app


def uninstall(app: Any) -> None:
    """Take the process-wide pieces back off Scriba: the execution gate and
    the worker. The routes stay mounted. For tests, which share one Scriba
    application object."""
    desk = getattr(app.state, "desk", None)
    if not desk:
        return
    if desk.get("worker") is not None:
        desk["worker"].stop(timeout=1.0)
    if desk.get("gate") is not None:
        desk["gate"].uninstall()
