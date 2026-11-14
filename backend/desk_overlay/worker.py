"""The Desk's background intake worker.

With the worker on, new actionable mail becomes a Desk run with no client
open: nothing has to call ``POST /desk/intake``.

What it reuses. Mail reaches Scriba through Scriba's own ingestion (Gmail
push and history catch-up, Outlook subscriptions and sync); the worker does
not poll a provider. It reads the user's recent inbox through the runtime
behind ``GET /emails`` and hands each message to the same ``DeskWorkflow``
the routes use, so a run opened by the worker is exactly a run opened by a
click. Deduplication is the claim store (``claims.py``), not a process lock.

What it does on each tick, per enrolled user, acting as that user and nobody
else:

1. take in recent mail that needs a run and has none (bounded);
2. propose the confirmation reply of any run whose calendar change has
   executed;
3. check follow-ups: close the ones that were answered, mark and propose a
   reminder for the ones that are overdue.

It only ever PROPOSES. Approval stays with the person.

It is opt-in and refuses to start in a production process:

    DESK_INTAKE_WORKER=on            start it
    DESK_INTAKE_USERS=a@x,b@y        the Scriba users it serves (explicit)
    DESK_INTAKE_INTERVAL=60          seconds between ticks (minimum 15)
    DESK_INTAKE_MAX_NEW=3            runs opened per user per tick
    DESK_INTAKE_MAX_PER_HOUR=30      runs opened per user per hour
    DESK_INTAKE_MAX_PENDING=20       stop opening runs while this many await the user

Users who have a sandbox world in this process (the demo server) are served
too: their mail is synthetic.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional

from .gateway import acting_as
from .service import AppContext

logger = logging.getLogger(__name__)
UTC = dt.timezone.utc
MAX_BACKOFF_SECONDS = 900


def _int(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(int(str(env.get(name) or default)), high))
    except (TypeError, ValueError):
        return default


class IntakeWorker:
    def __init__(self, app: Any, gateway: Any, workflow: Any, *, env: Mapping[str, str],
                 registry: Any = None, clock: Optional[Callable[[], dt.datetime]] = None,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.app = app
        self.gateway = gateway
        self.workflow = workflow
        self.registry = registry
        self.env = env
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.monotonic = monotonic
        self.requested = str(env.get("DESK_INTAKE_WORKER") or "").strip().lower() in ("1", "true", "on")
        self.interval = _int(env, "DESK_INTAKE_INTERVAL", 60, 15, 3600)
        self.max_new = _int(env, "DESK_INTAKE_MAX_NEW", 3, 1, 10)
        self.max_per_hour = _int(env, "DESK_INTAKE_MAX_PER_HOUR", 30, 1, 500)
        self.max_pending = _int(env, "DESK_INTAKE_MAX_PENDING", 20, 1, 500)
        self.addresses = [a.strip().lower() for a in str(env.get("DESK_INTAKE_USERS") or "").split(",")
                          if a.strip()]
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._tick_lock = threading.Lock()
        self._users: Dict[str, Dict[str, Any]] = {}
        # Set by the process that has an execution gate: settles actions a
        # stopped process left in flight. ``recover(user, run) -> int``.
        self.recover: Optional[Callable[[Any, Dict[str, Any]], int]] = None
        self.state: Dict[str, Any] = {
            "running": False, "reason": "not_requested" if not self.requested else "not_started",
            "ticks": 0, "skippedTicks": 0, "lastTickAt": None, "lastTickMs": None,
            "opened": 0, "existing": 0, "failed": 0, "deferred": 0, "advanced": 0, "lastError": None,
        }

    # ── lifecycle ───────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Start the loop if it was asked for and is allowed. Returns whether it runs."""
        if not self.requested:
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        if self.gateway.is_production():
            # Never on a production Scriba process, whatever the environment says.
            self.state.update(running=False, reason="refused_production")
            logger.error("desk_intake_worker_refused reason=production")
            return False
        if not self._enrolled():
            self.state.update(running=False, reason="no_users")
            logger.warning("desk_intake_worker_idle reason=no_users (set DESK_INTAKE_USERS)")
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="desk-intake-worker", daemon=True)
        self._thread.start()
        self.state.update(running=True, reason=None)
        logger.warning("desk_intake_worker_started interval=%ss users=%d", self.interval,
                       len(self._enrolled()))
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self.state.update(running=False, reason="stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:        # the loop itself never dies
                self.state["lastError"] = type(exc).__name__
                logger.exception("desk intake worker tick failed")
            self._stop.wait(self.interval)

    def _enrolled(self) -> List[Any]:
        users = list(self.gateway.enrolled_users(self.addresses))
        seen = {user.email for user in users}
        if self.registry is not None:
            for world in self.registry.defaults():
                if world.owner_email not in seen:
                    found = self.gateway.user_for_email(world.owner_email)
                    if found is not None:
                        users.append(found)
                        seen.add(found.email)
        return users

    # ── one pass ────────────────────────────────────────────────────────────
    def tick(self) -> Dict[str, Any]:
        """One pass over every enrolled user. A tick that would overlap a
        running one is skipped, not queued."""
        if not self._tick_lock.acquire(blocking=False):
            self.state["skippedTicks"] += 1
            return {"status": "already_running"}
        started = self.monotonic()
        summary: Dict[str, Any] = {"status": "completed", "users": []}
        try:
            for user in self._enrolled():
                summary["users"].append(self._serve(user))
            return summary
        finally:
            self.state["ticks"] += 1
            self.state["lastTickAt"] = self.clock().isoformat()
            self.state["lastTickMs"] = int((self.monotonic() - started) * 1000)
            self._tick_lock.release()

    def _slot(self, user: Any) -> Dict[str, Any]:
        return self._users.setdefault(user.email, {
            "failures": 0, "notBefore": 0.0, "lastStatus": None, "lastAt": None, "openedAt": [],
            "opened": 0, "incomplete": False})

    def _serve(self, user: Any) -> Dict[str, Any]:
        slot = self._slot(user)
        now = self.monotonic()
        if now < slot["notBefore"]:
            slot["lastStatus"] = "backing_off"
            return {"user": user.email, "status": "backing_off"}
        ctx = AppContext(self.app)
        result: Dict[str, Any] = {"user": user.email, "status": "ok", "opened": 0}
        # ``acting_as`` is the user boundary: every read below is made with
        # this user's identity passed explicitly.
        with acting_as(user):
            try:
                # Rate limit: runs opened for this user in the last hour.
                slot["openedAt"] = [t for t in slot["openedAt"] if now - t < 3600]
                budget = min(self.max_new, self.max_per_hour - len(slot["openedAt"]))
                pending = self.workflow.counts(ctx, user, 50).get("AWAITING_APPROVAL", 0)
                if pending >= self.max_pending:
                    budget, result["status"] = 0, "backpressure"
                elif budget <= 0:
                    budget, result["status"] = 0, "rate_limited"
                if budget > 0:
                    swept = self.workflow.sweep(ctx, user, max_new=budget, trigger="worker")
                    if swept["status"] == "already_running":
                        result["status"] = "sweep_in_progress"
                    else:
                        result["opened"] = len(swept["opened"])
                        slot["openedAt"].extend([now] * len(swept["opened"]))
                        slot["opened"] += len(swept["opened"])
                        slot["incomplete"] = not swept["complete"]
                        for key in ("existing",):
                            self.state[key] += int(swept[key])
                        self.state["opened"] += len(swept["opened"])
                        self.state["failed"] += len(swept["failed"])
                        self.state["deferred"] += len(swept["deferred"])
                        if not swept["complete"]:
                            # A connected mailbox could not be read. What was
                            # readable was handled; say so and slow down.
                            result["status"] = "mailbox_unreadable"
                            result["sources"] = [s for s in swept["sources"] if not s.get("ok")]
                self.state["advanced"] += self._continue_runs(ctx, user)
            except Exception as exc:
                slot["failures"] += 1
                delay = min(self.interval * (2 ** slot["failures"]), MAX_BACKOFF_SECONDS)
                slot["notBefore"] = now + delay
                slot["lastStatus"], slot["lastAt"] = "failed", self.clock().isoformat()
                self.state["lastError"] = type(exc).__name__
                logger.warning("desk_intake_worker_user_failed error=%s retry_in=%ss",
                               type(exc).__name__, delay)
                return {"user": user.email, "status": "failed", "error": type(exc).__name__,
                        "retryInSeconds": delay}
        if result["status"] == "mailbox_unreadable":
            slot["failures"] += 1
            slot["notBefore"] = now + min(self.interval * (2 ** slot["failures"]), MAX_BACKOFF_SECONDS)
        else:
            slot["failures"], slot["notBefore"] = 0, 0.0
        slot["lastStatus"], slot["lastAt"] = result["status"], self.clock().isoformat()
        return result

    def _continue_runs(self, ctx: Any, user: Any) -> int:
        """Propose what follows an executed step, and look after follow-ups."""
        moved = 0
        for run in self.gateway.list_runs(user, 50):
            try:
                view = self.workflow.view(ctx, user, run["id"], detail=False)
                if callable(self.recover) and (view["actionCounts"].get("executing")
                                               or view["actionCounts"].get("approved")):
                    self.state["recovered"] = self.state.get("recovered", 0) + int(self.recover(user, run))
                    view = self.workflow.view(ctx, user, run["id"], detail=False)
                waiting = any(f.get("state") in ("waiting", "overdue") for f in view["followUps"])
                executed = view["actionCounts"].get("executed", 0) > 0
                if "advance" in view["next"] or waiting or executed:
                    before = sum(view["actionCounts"].values())
                    after = self.workflow.advance(ctx, user, run["id"])
                    moved += int(sum(after["actionCounts"].values()) > before)
            except Exception:
                logger.exception("desk intake worker could not continue a run")
        return moved

    # ── status ──────────────────────────────────────────────────────────────
    def status(self, user: Any = None) -> Dict[str, Any]:
        alive = bool(self._thread is not None and self._thread.is_alive())
        body: Dict[str, Any] = {
            "enabled": self.requested, "running": alive,
            "reason": None if alive else self.state.get("reason"),
            "intervalSeconds": self.interval,
            "limits": {"maxNewPerTick": self.max_new, "maxPerHour": self.max_per_hour,
                       "maxPending": self.max_pending},
            "claims": {"store": getattr(self.workflow.claims, "kind", "unknown"),
                       "durable": bool(getattr(self.workflow.claims, "durable", False))},
            "users": len(self._users) if alive or self._users else len(self.addresses),
            **{key: self.state[key] for key in (
                "ticks", "skippedTicks", "lastTickAt", "lastTickMs", "opened", "existing", "failed",
                "deferred", "advanced", "lastError")},
            "recovered": self.state.get("recovered", 0),
        }
        if user is not None:
            slot = self._users.get(user.email)
            # Only the caller's own row: one user never sees another's.
            body["you"] = {
                "served": bool(slot) or user.email in self.addresses,
                "lastStatus": (slot or {}).get("lastStatus"), "lastAt": (slot or {}).get("lastAt"),
                "opened": (slot or {}).get("opened", 0),
                "mailboxUnreadable": bool((slot or {}).get("incomplete")),
                "consecutiveFailures": (slot or {}).get("failures", 0),
            }
        return body
