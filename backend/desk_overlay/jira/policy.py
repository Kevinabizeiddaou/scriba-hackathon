"""The switches for Jira, and which OAuth scopes each part of it needs. Pure.

Three questions, kept apart exactly as ``readiness.py`` keeps them for mail
and calendars:

- **Is Jira part of this Desk at all?** ``DESK_JIRA``. Off by default: with
  it off the Desk is the four-capability product it was, and nothing in any
  existing payload mentions Jira.
- **Can it reach Jira?** Scriba must hold the app's credentials
  (``JIRA_CLIENT_ID``, ``JIRA_CLIENT_SECRET``) and the person must have
  connected their site. Reading needs nothing more.
- **May an approved write reach a real Jira site?** ``DESK_JIRA_WRITES`` and
  the name of who switched it on. Off by default: an approved proposal is
  then HELD, and says so. In a sandbox world it runs against the synthetic
  site instead, and is labelled simulated.

The scope tables are what the setup screen and docs/jira/SETUP.md are
generated from, so the scopes requested and the features offered cannot
drift apart.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ENV_SWITCH = "DESK_JIRA"
ENV_WRITES = "DESK_JIRA_WRITES"
ENV_WRITES_AUTHORIZED_BY = "DESK_JIRA_WRITES_AUTHORIZED_BY"
HELD_CODE = "jira_writes_disabled"

# What Scriba must be given for sign-in to work. The names are Scriba's.
SCRIBA_ENV = ("JIRA_CLIENT_ID", "JIRA_CLIENT_SECRET")
SCRIBA_ENV_OPTIONAL = ("JIRA_REDIRECT_URI", "JIRA_SCOPES")
CALLBACK_PATH = "/auth/jira/callback"
LOGIN_PATH = "/auth/jira/login"
DISCONNECT_PATH = "/auth/jira/disconnect"


def _on(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "on", "enabled", "yes")


def is_on(env: Mapping[str, str]) -> bool:
    return _on(env.get(ENV_SWITCH))


# ── scopes ─────────────────────────────────────────────────────────────────
# Each group is one capability of the integration. ``any_of`` lists the
# alternatives that grant it: a classic scope, or the granular scopes that
# together cover the same calls. Jira Software's API (boards, sprints) and
# Jira Service Management's have their own scopes; ``read:jira-work`` does
# not reach them.

class ScopeGroup:
    def __init__(self, group_id: str, label: str, any_of: Sequence[Sequence[str]], *,
                 product: str = "jira", write: bool = False, optional: bool = False) -> None:
        self.id = group_id
        self.label = label
        self.any_of: Tuple[Tuple[str, ...], ...] = tuple(tuple(option) for option in any_of)
        self.product = product            # jira | software | servicedesk
        self.write = write
        self.optional = optional

    def granted_by(self, scopes: Iterable[str]) -> bool:
        held = set(scopes)
        return any(set(option) <= held for option in self.any_of)

    def missing(self, scopes: Iterable[str]) -> List[str]:
        """The shortest list of scopes that would grant this group."""
        held = set(scopes)
        if self.granted_by(held):
            return []
        return sorted(min((set(option) - held for option in self.any_of), key=len))


SCOPE_GROUPS: Tuple[ScopeGroup, ...] = (
    ScopeGroup("core_read", "Read issues, projects, filters and comments", [["read:jira-work"]]),
    ScopeGroup("users", "Find people to assign and mention", [["read:jira-user"]]),
    ScopeGroup("core_write", "Create and change issues, comment, log time", [["write:jira-work"]], write=True),
    ScopeGroup("offline", "Stay connected without signing in again", [["offline_access"]]),
    # Jira Software has no classic scopes: these are granular, and the two
    # kinds are mixed in one app. Atlassian asks for fewer than 50 in total.
    ScopeGroup("software_read", "Read boards, backlogs, sprints and epics",
               [["read:board-scope:jira-software", "read:sprint:jira-software", "read:epic:jira-software",
                 "read:issue-details:jira", "read:jql:jira", "read:project:jira"]],
               product="software", optional=True),
    ScopeGroup("software_board_config", "Read a board's columns and its estimate field",
               [["read:board-scope.admin:jira-software", "read:project:jira"]],
               product="software", optional=True),
    ScopeGroup("software_write", "Plan sprints: move, rank, start and complete",
               [["write:sprint:jira-software", "write:board-scope:jira-software",
                 "write:issue:jira-software"]],
               product="software", write=True, optional=True),
    ScopeGroup("project_admin", "Create and release versions", [["manage:jira-project"]],
               write=True, optional=True),
    ScopeGroup("servicedesk_read", "Read service requests and approvals waiting on you",
               [["read:servicedesk-request"]], product="servicedesk", optional=True),
    ScopeGroup("servicedesk_write", "Answer approvals on service requests",
               [["write:servicedesk-request"]], product="servicedesk", write=True, optional=True),
    ScopeGroup("webhooks", "Be told when issues change, instead of asking", [["manage:jira-webhook"]],
               optional=True),
)
GROUP_BY_ID: Dict[str, ScopeGroup] = {group.id: group for group in SCOPE_GROUPS}


def recommended_scopes(*, software: bool = True, servicedesk: bool = False, admin: bool = False,
                       webhooks: bool = False) -> List[str]:
    """The value for Scriba's ``JIRA_SCOPES`` (space separated), in a stable order."""
    wanted = ["core_read", "users", "core_write", "offline"]
    if software:
        wanted += ["software_read", "software_board_config", "software_write"]
    if admin:
        wanted.append("project_admin")
    if servicedesk:
        wanted += ["servicedesk_read", "servicedesk_write"]
    if webhooks:
        wanted.append("webhooks")
    out: List[str] = []
    for group_id in wanted:
        for scope in GROUP_BY_ID[group_id].any_of[0]:
            if scope not in out:
                out.append(scope)
    return out


def normalize_scopes(scopes: Any) -> List[str]:
    """Scriba stores the granted scopes as a list, or as the space-separated
    string Atlassian returned after a token refresh."""
    if isinstance(scopes, str):
        scopes = scopes.split()
    return sorted({str(scope).strip() for scope in (scopes or []) if str(scope).strip()})


def scope_report(scopes: Any) -> List[Dict[str, Any]]:
    held = normalize_scopes(scopes)
    return [{"id": group.id, "label": group.label, "product": group.product, "write": group.write,
             "optional": group.optional, "granted": group.granted_by(held), "missing": group.missing(held)}
            for group in SCOPE_GROUPS]


def allows(scopes: Any, group_id: str) -> bool:
    group = GROUP_BY_ID.get(group_id)
    return bool(group) and group.granted_by(normalize_scopes(scopes))


# ── writes ─────────────────────────────────────────────────────────────────

def write_checks(env: Mapping[str, str]) -> List[Dict[str, Any]]:
    lead = str(env.get(ENV_WRITES_AUTHORIZED_BY) or "").strip()
    return [
        {"id": "jira_writes_switch", "ok": _on(env.get(ENV_WRITES)),
         "detail": f"{ENV_WRITES} is on." if _on(env.get(ENV_WRITES))
         else f"{ENV_WRITES} is not set: approved Jira changes are held, not made."},
        {"id": "jira_writes_authorized_by", "ok": bool(lead),
         "detail": f"Switched on by {lead}." if lead
         else f"{ENV_WRITES_AUTHORIZED_BY} does not name who switched real Jira writes on."},
    ]


def writes(env: Mapping[str, str], *, sandbox: bool) -> Dict[str, Any]:
    """What approving a Jira proposal does for this person, and why.

    ``mode`` is ``sandbox`` (applied to the synthetic site, simulated),
    ``external`` (sent to the real site) or ``held`` (refused, nothing sent).
    """
    checks = write_checks(env)
    if sandbox:
        return {"mode": "sandbox", "enabled": False, "simulated": True, "checks": checks, "reason": None,
                "message": "Approved changes are applied to a synthetic Jira site. Nothing real changes."}
    failed = next((check for check in checks if not check["ok"]), None)
    if failed is None:
        return {"mode": "external", "enabled": True, "simulated": False, "checks": checks, "reason": None,
                "message": "Approved changes are made on your Jira site."}
    return {"mode": "held", "enabled": False, "simulated": False, "checks": checks, "reason": failed["id"],
            "message": "Changing Jira is switched off on this Desk. You can prepare and review a change; "
                       "approving it makes no change."}


def setup(*, public_api_base: Optional[str], configured: bool, missing_env: Sequence[str],
          redirect_uri: Optional[str], requested_scopes: Sequence[str]) -> Dict[str, Any]:
    """What an operator still has to do, in order. Names only: never a value."""
    base = str(public_api_base or "").rstrip("/")
    callback = redirect_uri or (f"{base}{CALLBACK_PATH}" if base else None)
    return {
        "configured": bool(configured),
        "missingEnv": list(missing_env),
        "requiredEnv": list(SCRIBA_ENV),
        "optionalEnv": list(SCRIBA_ENV_OPTIONAL),
        "callbackUrl": callback,
        "requestedScopes": list(requested_scopes),
        "recommendedScopes": recommended_scopes(),
        "scopesToAdd": [scope for scope in recommended_scopes() if scope not in set(requested_scopes)],
        "console": "https://developer.atlassian.com/console/myapps/",
    }
