"""Whether this backend may perform real mail and calendar writes. Pure.

Three separate questions, never merged into one flag:

- **sandbox execution**: can approved actions run against an isolated
  provider world? (Simulated. Always safe.)
- **external write capability**: is the code path to a real provider present
  and guarded in this process?
- **external write authorization**: has every condition for real writes been
  met AND has the project lead switched them on?

``externalWrites.enabled`` is true only when every check passes. It is false
today on every backend, by construction: ``VERIFIED_SCRIBA_REVISIONS`` is
empty, and adding a revision to it is a reviewed code change made after the
fixes for sending and calendar writes are confirmed active in that Scriba
revision and isolated provider tests have passed. Passing unit tests or the
presence of the Desk's own guards never enables writes.

The gate that enforces this is in ``execution.py``; this module only decides.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

# Scriba revisions in which the outbound fixes (reply target and thread,
# sending mailbox, recipient provenance, approve and retry idempotency,
# duplicate calendar events, Outlook create idempotency) were verified active
# by isolated provider tests. EMPTY: no revision has been verified.
VERIFIED_SCRIBA_REVISIONS: frozenset = frozenset()

# Tools whose execution reaches somebody outside the user's own records.
EXTERNAL_WRITE_TOOLS = frozenset({
    "send_email", "draft_email_reply", "create_calendar_event", "update_calendar_event",
    "cancel_calendar_event",
})
# Tools that only write the user's own Scriba records.
INTERNAL_WRITE_TOOLS = frozenset({"create_task", "create_reminder"})

ENV_SWITCH = "DESK_EXTERNAL_WRITES"
ENV_AUTHORIZED_BY = "DESK_EXTERNAL_WRITES_AUTHORIZED_BY"
ENV_PROVIDER_TEST_REPORT = "DESK_ISOLATED_PROVIDER_TEST_REPORT"


def _on(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "on", "enabled")


def external_write_checks(env: Mapping[str, str], *, guards_installed: bool,
                          scriba_commit: Optional[str]) -> List[Dict[str, Any]]:
    commit = str(scriba_commit or "").strip()
    verified = bool(commit) and any(commit.startswith(rev) or rev.startswith(commit)
                                    for rev in VERIFIED_SCRIBA_REVISIONS)
    report = str(env.get(ENV_PROVIDER_TEST_REPORT) or "").strip()
    lead = str(env.get(ENV_AUTHORIZED_BY) or "").strip()
    return [
        {"id": "desk_guards_installed", "ok": bool(guards_installed),
         "detail": "The Desk's approval gate, safeguards and booking gate are enforced in this process."
         if guards_installed else
         "The Desk chat scope is off, so the Desk's guards are not enforced process-wide."},
        {"id": "scriba_fixes_verified", "ok": verified,
         "detail": f"Scriba revision {commit} is in the verified list." if verified else
         "No Scriba revision has been verified to contain the outbound fixes"
         + (f" (this backend reports {commit})." if commit else " (this backend reports no revision).")},
        {"id": "isolated_provider_tests", "ok": bool(report) and verified,
         "detail": f"Isolated provider test report: {report}." if report else
         "No isolated provider test report is recorded."},
        {"id": "lead_authorization", "ok": bool(lead) and _on(env.get(ENV_SWITCH)),
         "detail": "Authorized by the project lead." if lead and _on(env.get(ENV_SWITCH)) else
         "The project lead has not authorized external writes."},
    ]


def readiness(env: Mapping[str, str], *, guards_installed: bool, scriba_commit: Optional[str],
              sandbox_worlds: int = 0) -> Dict[str, Any]:
    """The readiness block of ``GET /desk/health``."""
    checks = external_write_checks(env, guards_installed=guards_installed, scriba_commit=scriba_commit)
    enabled = all(check["ok"] for check in checks)
    failing = [check for check in checks if not check["ok"]]
    return {
        # Kept for clients of contract 0.2: nothing is written to a provider.
        "writes": enabled,
        "externalWrites": {
            "enabled": enabled,
            # The path to a real provider exists only behind the Desk's guards.
            "capable": bool(guards_installed),
            "authorized": bool(checks[-1]["ok"]),
            "revision": str(scriba_commit or "") or None if enabled else None,
            "reason": None if enabled else failing[0]["id"],
            "message": None if enabled else failing[0]["detail"],
            "checks": checks,
        },
        "sandboxExecution": {
            "available": sandbox_worlds > 0,
            "worlds": int(sandbox_worlds),
            "note": "Approved actions run against an isolated provider world. No mailbox or "
                    "calendar is reached." if sandbox_worlds > 0 else
                    "No isolated provider world is active in this process.",
        },
    }


def is_enabled(env: Mapping[str, str], *, guards_installed: bool, scriba_commit: Optional[str]) -> bool:
    return all(check["ok"] for check in external_write_checks(
        env, guards_installed=guards_installed, scriba_commit=scriba_commit))
