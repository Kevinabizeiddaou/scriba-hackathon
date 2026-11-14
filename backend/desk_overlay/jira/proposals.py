"""A proposed change to Jira, from preview to approval to outcome.

The rule of the Desk is that nothing is sent or changed before a person
approves it. For Jira that rule lives here:

    propose   the input is checked, what only Jira knows is read and pinned,
              and the result is recorded with a one-sentence preview.
              Nothing is written.
    approve   a person's decision. The proposal is claimed (two approvals
              run it once), the write switch is checked (off: HELD, nothing
              sent), the issue is checked not to have moved on, the write is
              made, and the result is read back.
    reject    a person's decision. Nothing is written, ever.

What is approved is what was proposed: an approval carries no new input.
Changing a proposal means rejecting it and proposing again.

Outcomes are never rounded up. A write Jira accepted but whose read-back
disagrees is ``executed`` with ``verification.verified = False``; a write
whose request died on the way is ``outcome_unknown`` and is not retried
until the person says they looked.

The store is a seam. ``MemoryProposals`` keeps proposals in this process: a
restart forgets the ones still waiting, and the status endpoint says so
(``durable: false``). Every decision and every write is also sent to
``audit``, which is Scriba's audit log in production, so the record of what
was done outlives the process even though the queue does not.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import threading
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from . import actions, policy
from .client import JiraError

logger = logging.getLogger(__name__)

OPEN = ("awaiting_approval", "outcome_unknown")
SETTLED = ("executed", "failed", "rejected")
STATUSES = OPEN + ("executing",) + SETTLED
MAX_PER_USER = 300
STALE_EXECUTING_SECONDS = 300


class ProposalNotFound(LookupError):
    pass


class ProposalConflict(Exception):
    """The proposal is not in a state that allows this. ``code`` is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MemoryProposals:
    """Proposals in this process, per user. Not durable; thread-safe."""

    kind = "memory"
    durable = False

    def __init__(self) -> None:
        self._rows: Dict[int, Dict[str, Dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._next = 0

    def add(self, user_id: int, record: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._next += 1
            record["id"] = f"jp-{self._next}"
            rows = self._rows.setdefault(int(user_id), {})
            rows[record["id"]] = record
            settled = [row for row in rows.values() if row["status"] in SETTLED]
            for row in sorted(settled, key=lambda row: row["createdAt"])[: max(0, len(rows) - MAX_PER_USER)]:
                rows.pop(row["id"], None)
            return record

    def get(self, user_id: int, proposal_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._rows.get(int(user_id), {}).get(str(proposal_id))

    def list(self, user_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._rows.get(int(user_id), {}).values())

    def claim(self, user_id: int, proposal_id: str, expected: Sequence[str], status: str) -> Optional[Dict[str, Any]]:
        """Move a proposal to ``status`` if, and only if, it is in ``expected``.
        This is what makes two simultaneous approvals one execution."""
        with self._lock:
            row = self._rows.get(int(user_id), {}).get(str(proposal_id))
            if row is None or row["status"] not in expected:
                return None
            row["status"] = status
            return row

    def find_open(self, user_id: int, fingerprint: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for row in self._rows.get(int(user_id), {}).values():
                if row["fingerprint"] == fingerprint and row["status"] == "awaiting_approval":
                    return row
        return None


def fingerprint(action: str, data: Mapping[str, Any]) -> str:
    body = json.dumps({"action": action, "input": actions.public(data)}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def view(row: Mapping[str, Any]) -> Dict[str, Any]:
    """A proposal as a client sees it. What ``resolve`` pinned is shown only
    where it explains the preview: the state the issue was in, and where a
    move leads."""
    data = row.get("data") or {}
    return {
        "id": row["id"], "action": row["action"], "label": row["label"], "risk": row["risk"],
        "status": row["status"], "summary": row["summary"], "input": actions.public(data),
        "targets": row.get("targets") or [],
        "before": data.get("_before"), "to": data.get("_to"),
        "origin": row.get("origin"), "reason": row.get("reason"),
        "simulated": bool(row.get("simulated")), "site": row.get("site"),
        "createdAt": row["createdAt"], "decidedAt": row.get("decidedAt"), "decidedBy": row.get("decidedBy"),
        "held": row.get("held"), "result": row.get("result"), "verification": row.get("verification"),
        "error": row.get("error"), "undo": row.get("undo"), "events": list(row.get("events") or []),
    }


class ProposalDesk:
    def __init__(self, store: Any = None, *, clock: Optional[Callable[[], dt.datetime]] = None,
                 audit: Optional[Callable[[Any, Dict[str, Any], Dict[str, Any]], None]] = None) -> None:
        self.store = store or MemoryProposals()
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.audit = audit

    def _now(self) -> str:
        return self.clock().astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    def _event(self, user: Any, row: Dict[str, Any], kind: str, **data: Any) -> None:
        event = {"at": self._now(), "kind": kind, "by": getattr(user, "email", None), **data}
        row.setdefault("events", []).append(event)
        logger.warning("desk_jira_proposal id=%s action=%s kind=%s simulated=%s user_id=%s",
                       row.get("id"), row.get("action"), kind, bool(row.get("simulated")),
                       getattr(user, "id", None))
        if self.audit is not None:
            try:
                self.audit(user, row, event)
            except Exception:
                logger.exception("desk_jira_audit_failed id=%s kind=%s", row.get("id"), kind)

    # ── propose ─────────────────────────────────────────────────────────────
    def propose(self, user: Any, ctx: actions.Context, action_name: str, raw: Mapping[str, Any], *,
                scopes: Any, simulated: bool, site: Optional[str] = None, origin: str = "user",
                reason: Optional[str] = None) -> Dict[str, Any]:
        """Record a change for approval. Reads Jira; writes nothing to it.

        Raises ``actions.InvalidAction`` when the input cannot be proposed and
        ``JiraError`` when Jira could not be read.
        """
        action = actions.ACTION_BY_NAME.get(str(action_name or "").strip())
        if action is None:
            raise actions.InvalidAction([{"field": "action", "message": f"There is no action {action_name!r}."}])
        if not simulated and not policy.allows(scopes, action.needs):
            group = policy.GROUP_BY_ID[action.needs]
            raise JiraError(403, "scope_missing",
                            f"This Jira connection was not granted what '{action.label}' needs "
                            f"({', '.join(group.missing(policy.normalize_scopes(scopes)))}). "
                            "Add the scope to the Atlassian app, then reconnect Jira.")
        data = action.clean(raw)
        if action.resolve is not None:
            data = action.resolve(ctx, data)
        mark = fingerprint(action.name, data)
        existing = self.store.find_open(user.id, mark)
        if existing is not None:
            return view(existing)                      # the same change, asked for twice
        row = self.store.add(user.id, {
            "action": action.name, "label": action.label, "risk": action.risk, "status": "awaiting_approval",
            "data": data, "summary": action.preview(data), "targets": action.targets(data),
            "fingerprint": mark, "simulated": bool(simulated), "site": site,
            "origin": origin if origin in ("user", "assistant") else "user",
            "reason": (str(reason).strip()[:500] or None) if reason else None,
            "undo": action.undo or None, "createdAt": self._now(), "events": [],
        })
        self._event(user, row, "proposed", summary=row["summary"])
        return view(row)

    # ── read ────────────────────────────────────────────────────────────────
    def get(self, user: Any, proposal_id: str) -> Dict[str, Any]:
        row = self.store.get(user.id, proposal_id)
        if row is None:
            raise ProposalNotFound(proposal_id)
        return view(row)

    def list(self, user: Any, *, status: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        self._release_stale(user)
        rows = sorted(self.store.list(user.id), key=lambda row: row["createdAt"], reverse=True)
        wanted = {"open": OPEN + ("executing",), "settled": SETTLED}.get(str(status or ""), None)
        if status and wanted is None:
            wanted = (str(status),)
        chosen = [row for row in rows if wanted is None or row["status"] in wanted]
        return {
            "proposals": [view(row) for row in chosen[:limit]],
            "counts": {name: sum(1 for row in rows if row["status"] == name) for name in STATUSES},
            "waiting": sum(1 for row in rows if row["status"] in OPEN),
            "store": {"kind": getattr(self.store, "kind", "unknown"),
                      "durable": bool(getattr(self.store, "durable", False))},
        }

    def _release_stale(self, user: Any) -> None:
        """A proposal left ``executing`` (the process died mid-write) is not
        known to have happened or not: it becomes ``outcome_unknown``."""
        cutoff = self.clock() - dt.timedelta(seconds=STALE_EXECUTING_SECONDS)
        for row in self.store.list(user.id):
            started = row.get("startedAt")
            if row["status"] == "executing" and started and dt.datetime.fromisoformat(
                    started.replace("Z", "+00:00")) < cutoff:
                if self.store.claim(user.id, row["id"], ("executing",), "outcome_unknown") is not None:
                    row["error"] = {"code": "outcome_unknown",
                                    "message": "This change was started and never reported back. "
                                               "Check the issue in Jira before trying again."}
                    self._event(user, row, "outcome_unknown")

    # ── decide ──────────────────────────────────────────────────────────────
    def reject(self, user: Any, proposal_id: str) -> Dict[str, Any]:
        row = self.store.claim(user.id, proposal_id, OPEN, "rejected")
        if row is None:
            return self._refused(user, proposal_id, "reject")
        row.update({"decidedAt": self._now(), "decidedBy": user.email, "held": None})
        self._event(user, row, "rejected")
        return view(row)

    def _refused(self, user: Any, proposal_id: str, verb: str) -> Dict[str, Any]:
        row = self.store.get(user.id, proposal_id)
        if row is None:
            raise ProposalNotFound(proposal_id)
        if row["status"] == "executing":
            raise ProposalConflict("in_progress", "This change is being made right now.")
        raise ProposalConflict("already_decided",
                               f"This change was already {row['status'].replace('_', ' ')}; "
                               f"it cannot be {verb}ed again.")

    def approve(self, user: Any, ctx: actions.Context, proposal_id: str, *, writes: Mapping[str, Any],
                confirmed: bool = False) -> Dict[str, Any]:
        """A person approves. ``writes`` is ``policy.writes`` for this person;
        ``confirmed`` says they checked Jira after an unknown outcome."""
        current = self.store.get(user.id, proposal_id)
        if current is None:
            raise ProposalNotFound(proposal_id)
        action = actions.ACTION_BY_NAME[current["action"]]
        simulated = bool(current.get("simulated"))

        # A proposal made in a sandbox runs in a sandbox or not at all, and
        # the reverse: it never changes worlds between proposal and approval.
        if simulated != bool(writes.get("simulated")):
            raise ProposalConflict("world_changed", "This change was prepared for a different Jira site "
                                                    "than the one in use now. Propose it again.")
        if writes.get("mode") == "held":
            if current["status"] in OPEN:
                current["held"] = {"code": policy.HELD_CODE, "message": writes.get("message"),
                                   "at": self._now(), "reason": writes.get("reason")}
                self._event(user, current, "held", code=policy.HELD_CODE)
                return view(current)
            return self._refused(user, proposal_id, "approv")
        if current["status"] == "outcome_unknown" and not confirmed:
            raise ProposalConflict("confirm_checked",
                                   "It is not known whether this change was made. Look at the issue in "
                                   "Jira, then approve again and confirm you checked.")

        row = self.store.claim(user.id, proposal_id, OPEN, "executing")
        if row is None:
            return self._refused(user, proposal_id, "approv")
        row.update({"decidedAt": self._now(), "decidedBy": user.email, "startedAt": self._now(),
                    "held": None, "error": None})
        self._event(user, row, "approved", mode=writes.get("mode"))
        data = row["data"]
        try:
            problem = action.guard(ctx, data) if action.guard is not None else None
            if problem:
                row.update({"status": "failed", "error": {"code": "issue_changed", "message": problem}})
                self._event(user, row, "failed", code="issue_changed")
                return view(row)
            result = action.run(ctx, data)
        except JiraError as exc:
            # A timeout or a 5xx may have arrived after Jira applied the change.
            unknown = exc.status >= 500 or exc.code in ("jira_unavailable", "timeout")
            row.update({"status": "outcome_unknown" if unknown else "failed", "error": exc.as_dict()})
            self._event(user, row, "outcome_unknown" if unknown else "failed", code=exc.code)
            return view(row)
        except Exception as exc:                        # a transport failure: nothing is known
            logger.exception("desk_jira_write_failed id=%s action=%s", row["id"], row["action"])
            row.update({"status": "outcome_unknown",
                        "error": {"code": "outcome_unknown", "message": "The request to Jira did not "
                                  "complete. Check the issue in Jira before trying again.",
                                  "kind": type(exc).__name__}})
            self._event(user, row, "outcome_unknown", code=type(exc).__name__)
            return view(row)

        row.update({"status": "executed", "result": result})
        self._event(user, row, "executed", result=result)
        verification: Dict[str, Any] = {"verified": None, "detail": "This change is not read back."}
        if action.check is not None:
            try:
                verification = action.check(ctx, data, result)
            except Exception as exc:
                verification = {"verified": None,
                                "detail": "Jira accepted the change, but it could not be read back.",
                                "error": type(exc).__name__}
        row["verification"] = {**verification, "at": self._now()}
        self._event(user, row, "verified" if verification.get("verified") else "unverified",
                    detail=verification.get("detail"))
        return view(row)
