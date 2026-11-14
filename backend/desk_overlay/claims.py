"""Claims: one Desk run per inbound message, across polls, processes and restarts.

A claim is taken BEFORE a run is opened and settled after. The key is the
identity of one message in one mailbox for one user (``workflow.run_key``:
user, provider, receiving account, provider message id), so the same message
delivered twice, seen by two overlapping polls, or met again after a restart
maps to the same claim.

Three stores share one small interface:

- ``MemoryClaims``         one process; for tests and the seeded backend,
                           whose runs are in memory too.
- ``SqliteClaims``         a local file. Atomic across threads, processes and
                           restarts. For a local runtime and for proving the
                           interface against a real database.
- ``ScribaReceiptClaims``  Scriba's own idempotency ledger
                           (``automation_action_receipts``, UNIQUE on user and
                           key) through the gateway. This is the durable store
                           on a real Scriba backend; it adds no table.

A claim is ``claimed`` (this caller owns it), ``done`` (a run exists; its id
is returned) or ``in_flight`` (another caller owns it, or one died holding
it). An in-flight claim older than the lease whose run does not exist may be
released and taken again: opening a run has no effect outside Scriba, so
taking over an abandoned claim cannot repeat an external action.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

UTC = dt.timezone.utc
LEASE_SECONDS = 300


@dataclass(frozen=True)
class Claim:
    state: str                      # claimed | done | in_flight
    token: Optional[Any] = None     # what settle/release need
    run_id: Optional[int] = None
    age_seconds: Optional[float] = None

    @property
    def claimed(self) -> bool:
        return self.state == "claimed"


def claim_key(run_key: str) -> str:
    return f"desk:intake:{run_key}"


class MemoryClaims:
    kind = "memory"
    durable = False

    def __init__(self, clock: Optional[Callable[[], dt.datetime]] = None) -> None:
        self._rows: Dict[Tuple[int, str], Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._clock = clock or (lambda: dt.datetime.now(UTC))

    def claim(self, user_id: int, key: str) -> Claim:
        now = self._clock()
        with self._lock:
            row = self._rows.get((int(user_id), key))
            if row is None or row["status"] == "failed":
                self._rows[(int(user_id), key)] = {"status": "pending", "run_id": None, "at": now}
                return Claim("claimed", token=key)
            if row["status"] == "succeeded":
                return Claim("done", token=key, run_id=row["run_id"])
            return Claim("in_flight", token=key, age_seconds=(now - row["at"]).total_seconds())

    def settle(self, user_id: int, key: str, token: Any, run_id: int) -> None:
        with self._lock:
            self._rows[(int(user_id), key)] = {"status": "succeeded", "run_id": int(run_id),
                                               "at": self._clock()}

    def release(self, user_id: int, key: str, token: Any) -> None:
        with self._lock:
            row = self._rows.get((int(user_id), key))
            if row and row["status"] == "pending":
                row["status"] = "failed"

    def count(self) -> Optional[int]:
        return len(self._rows)


class SqliteClaims:
    """A file-backed store. Each call opens its own connection, so it is safe
    from any thread and from several processes on the same file."""

    kind = "sqlite"
    durable = True

    def __init__(self, path: str, clock: Optional[Callable[[], dt.datetime]] = None) -> None:
        self.path = path
        self._clock = clock or (lambda: dt.datetime.now(UTC))
        with self._open() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS desk_claims ("
                " user_id INTEGER NOT NULL, key TEXT NOT NULL, status TEXT NOT NULL,"
                " run_id INTEGER, updated_at TEXT NOT NULL, PRIMARY KEY (user_id, key))")

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def claim(self, user_id: int, key: str) -> Claim:
        now = self._clock()
        conn = self._open()
        try:
            conn.execute("BEGIN IMMEDIATE")      # one writer decides at a time
            row = conn.execute("SELECT status, run_id, updated_at FROM desk_claims "
                               "WHERE user_id = ? AND key = ?", (int(user_id), key)).fetchone()
            if row is None:
                conn.execute("INSERT INTO desk_claims (user_id, key, status, updated_at) "
                             "VALUES (?, ?, 'pending', ?)", (int(user_id), key, now.isoformat()))
                conn.execute("COMMIT")
                return Claim("claimed", token=key)
            status, run_id, updated_at = row
            if status == "failed":
                conn.execute("UPDATE desk_claims SET status = 'pending', updated_at = ? "
                             "WHERE user_id = ? AND key = ?", (now.isoformat(), int(user_id), key))
                conn.execute("COMMIT")
                return Claim("claimed", token=key)
            conn.execute("COMMIT")
            if status == "succeeded":
                return Claim("done", token=key, run_id=run_id)
            age = (now - dt.datetime.fromisoformat(updated_at)).total_seconds()
            return Claim("in_flight", token=key, age_seconds=age)
        finally:
            conn.close()

    def settle(self, user_id: int, key: str, token: Any, run_id: int) -> None:
        with self._open() as conn:
            conn.execute("UPDATE desk_claims SET status = 'succeeded', run_id = ?, updated_at = ? "
                         "WHERE user_id = ? AND key = ?",
                         (int(run_id), self._clock().isoformat(), int(user_id), key))

    def release(self, user_id: int, key: str, token: Any) -> None:
        with self._open() as conn:
            conn.execute("UPDATE desk_claims SET status = 'failed', updated_at = ? "
                         "WHERE user_id = ? AND key = ? AND status = 'pending'",
                         (self._clock().isoformat(), int(user_id), key))

    def count(self) -> Optional[int]:
        with self._open() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM desk_claims").fetchone()[0])


class ScribaReceiptClaims:
    """Scriba's action-receipt ledger, reached through the gateway."""

    kind = "scriba_receipts"
    durable = True

    def __init__(self, gateway: Any, clock: Optional[Callable[[], dt.datetime]] = None) -> None:
        self.gateway = gateway
        self._clock = clock or (lambda: dt.datetime.now(UTC))

    def claim(self, user_id: int, key: str) -> Claim:
        outcome = self.gateway.claim_receipt(user_id, key, "desk.intake") or {}
        receipt = outcome.get("receipt") or {}
        if outcome.get("claimed"):
            return Claim("claimed", token=receipt.get("id"))
        if receipt.get("status") == "succeeded":
            run_id = receipt.get("object_id")
            return Claim("done", token=receipt.get("id"),
                         run_id=int(run_id) if str(run_id or "").isdigit() else None)
        updated = receipt.get("updated_at")
        age = None
        if isinstance(updated, dt.datetime):
            stamp = updated if updated.tzinfo else updated.replace(tzinfo=UTC)
            age = (self._clock() - stamp).total_seconds()
        return Claim("in_flight", token=receipt.get("id"), age_seconds=age)

    def settle(self, user_id: int, key: str, token: Any, run_id: int) -> None:
        if token is not None:
            self.gateway.finish_receipt(token, "succeeded", object_id=str(int(run_id)))

    def release(self, user_id: int, key: str, token: Any) -> None:
        if token is not None:
            self.gateway.finish_receipt(token, "failed")

    def count(self) -> Optional[int]:
        return None     # the ledger is shared with Scriba's automations; not counted here
