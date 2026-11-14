"""Every Jira feature a person might expect, and how far the Desk covers it. Pure.

This is the honest map of the skeleton. A feature is in exactly one state:

- ``ready``    served by ``/desk/jira/*`` and shown in the Jira workspace
- ``api``      served by ``/desk/jira/*``; the workspace has no screen for it yet
- ``planned``  catalogued with the Jira endpoint it needs; not built
- ``excluded`` left out on purpose, with the reason

The list is what Jira's own home page, boards and issue view offer, plus what
people who run teams look at (docs/jira/README.md gives the sources). It is
served at ``GET /desk/jira/features`` with, for each feature, whether this
person's connection was granted the scopes it needs, so the workspace can
say "reconnect to add boards" instead of failing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import policy

READY, API, PLANNED, EXCLUDED = "ready", "api", "planned", "excluded"

# (id, area, label, state, scope group, Desk route or action, Jira endpoint, note)
_ROWS: Tuple[Tuple[str, str, str, str, Optional[str], str, str, str], ...] = (
    # ── connection ──────────────────────────────────────────────────────────
    ("connect", "Connection", "Sign in with Atlassian (OAuth 2.0)", READY, None, "/auth/jira/login",
     "auth.atlassian.com/authorize", "Scriba's own flow, token store and refresh."),
    ("status", "Connection", "Connection, site and granted scopes", READY, None, "GET /desk/jira/status",
     "oauth/token/accessible-resources, /myself", ""),
    ("disconnect", "Connection", "Disconnect and revoke", READY, None, "POST /auth/jira/disconnect",
     "auth.atlassian.com/oauth/revoke", "Scriba's own route."),
    ("multi_site", "Connection", "Choose between several Jira sites", PLANNED, None, "",
     "oauth/token/accessible-resources", "Scriba keeps the first site of a grant; a picker needs a Scriba change."),
    ("api_token", "Connection", "Connect with an API token instead of OAuth", EXCLUDED, None, "", "",
     "An app used by several people should not collect personal API tokens."),

    # ── my work ─────────────────────────────────────────────────────────────
    ("my_open", "My work", "Assigned to me", READY, "core_read", "GET /desk/jira/issues?view=my_open",
     "POST /search/jql", ""),
    ("due", "My work", "Due this week and overdue", READY, "core_read", "GET /desk/jira/issues?view=overdue",
     "POST /search/jql", ""),
    ("reported_watching", "My work", "Reported by me, and watching", READY, "core_read",
     "GET /desk/jira/issues?view=watching", "POST /search/jql", ""),
    ("mentions", "My work", "Issues that mention me", READY, "core_read", "GET /desk/jira/issues?view=mentions",
     "POST /search/jql", "The JQL is common practice, not documented: a site may refuse it."),
    ("briefing", "My work", "Briefing: late, blocked, stalled, unowned", READY, "core_read",
     "GET /desk/jira/briefing", "POST /search/jql", "Derived by the Desk from what Jira returns."),
    ("counts", "My work", "Counts without loading the issues", API, "core_read", "GET /desk/jira/issues?count=true",
     "POST /search/approximate-count", "Approximate by design: search no longer returns a total."),
    ("recent", "My work", "Recently viewed, and starred", PLANNED, "core_read", "", "",
     "Jira's API exposes neither list to an OAuth app."),
    ("notifications", "My work", "The notification bell", EXCLUDED, None, "", "",
     "Jira has no API for the in-app notification feed."),

    # ── search ──────────────────────────────────────────────────────────────
    ("search_filters", "Search", "Filter by project, status, assignee, type, label, text", READY, "core_read",
     "GET /desk/jira/issues", "POST /search/jql", ""),
    ("search_jql", "Search", "Write JQL", READY, "core_read", "GET /desk/jira/issues?jql=", "POST /search/jql", ""),
    ("saved_filters", "Search", "My saved and starred filters", READY, "core_read", "GET /desk/jira/filters",
     "GET /filter/my, /filter/favourite", ""),
    ("save_filter", "Search", "Save a search as a filter", PLANNED, "core_write", "", "POST /filter", ""),
    ("dashboards", "Search", "My dashboards", API, "core_read", "GET /desk/jira/dashboards", "GET /dashboard",
     "Names and links only: Jira returns a gadget's settings, not its data."),

    # ── projects ────────────────────────────────────────────────────────────
    ("projects", "Projects", "Projects I can see", READY, "projects_read", "GET /desk/jira/projects",
     "GET /project/search", "Feeds the project picker when creating an issue."),
    ("project_detail", "Projects", "A project: lead, issue types and components", READY, "projects_read",
     "GET /desk/jira/projects/{key}", "GET /project/{key}, GET /project/{key}/components", ""),

    # ── one issue ───────────────────────────────────────────────────────────
    ("issue_view", "Issue", "Read an issue: fields, description, people", READY, "core_read",
     "GET /desk/jira/issues/{key}", "GET /issue/{key}", ""),
    ("issue_comments", "Issue", "Read the comment thread", READY, "core_read",
     "GET /desk/jira/issues/{key}/comments", "GET /issue/{key}/comment", ""),
    ("issue_history", "Issue", "History: who changed what", READY, "core_read",
     "GET /desk/jira/issues/{key}/history", "GET /issue/{key}/changelog", ""),
    ("hierarchy", "Issue", "Parent, epic, sub-tasks and links", READY, "core_read", "GET /desk/jira/issues/{key}",
     "GET /issue/{key}", ""),
    ("create_issue", "Issue", "Create an issue or a sub-task", READY, "core_write", "action create_issue",
     "POST /issue, GET /issue/createmeta/{project}/issuetypes", "Fields a project requires beyond the common ones are refused with their names."),
    ("edit_issue", "Issue", "Edit summary, description, priority, labels, dates, estimate", READY, "core_write",
     "action edit_issue", "PUT /issue/{key}, GET /issue/{key}/editmeta", ""),
    ("transition", "Issue", "Move along the workflow, with a resolution", READY, "core_write",
     "action transition_issue", "POST /issue/{key}/transitions", "Moves whose screen requires other fields are refused with their names."),
    ("assign", "Issue", "Assign and unassign", READY, "core_write", "action assign_issue",
     "PUT /issue/{key}/assignee, GET /user/assignable/search", ""),
    ("comment", "Issue", "Comment, with @mentions and internal notes", READY, "core_write", "action add_comment",
     "POST /issue/{key}/comment", ""),
    ("comment_edit", "Issue", "Edit or delete my own comment", PLANNED, "core_write", "",
     "PUT, DELETE /issue/{key}/comment/{id}", "The client has the calls; no action yet."),
    ("worklog", "Issue", "Log time", READY, "core_write", "action log_work", "POST /issue/{key}/worklog", ""),
    ("links", "Issue", "Link issues: blocks, relates, duplicates", READY, "core_write", "action link_issues",
     "POST /issueLink, GET /issueLinkType", ""),
    ("watch", "Issue", "Watch and stop watching", READY, "core_write", "action watch_issue",
     "POST, DELETE /issue/{key}/watchers", ""),
    ("attachments_read", "Issue", "See what is attached", READY, "core_read", "GET /desk/jira/issues/{key}",
     "GET /issue/{key}", "Names and sizes; a file is opened in Jira."),
    ("attachments_write", "Issue", "Attach a file", PLANNED, "core_write", "", "POST /issue/{key}/attachments",
     "The client has the call; an upload needs its own proposal shape."),
    ("flag", "Issue", "Flag as an impediment", PLANNED, "core_write", "", "PUT /issue/{key}",
     "The flag is read today; setting it differs between project styles."),
    ("vote", "Issue", "Vote", PLANNED, "core_write", "", "POST /issue/{key}/votes", ""),
    ("bulk", "Issue", "Change many issues at once", PLANNED, "core_write", "", "POST /bulk/issues/fields",
     "Held back until a proposal can show every row it will change."),
    ("delete_issue", "Issue", "Delete an issue", EXCLUDED, None, "", "",
     "The Desk does not delete other people's work."),

    # ── boards and sprints ──────────────────────────────────────────────────
    ("boards", "Boards and sprints", "Boards", READY, "software_read", "GET /desk/jira/boards",
     "GET /rest/agile/1.0/board", ""),
    ("board_view", "Boards and sprints", "A board's columns and what is in them", READY, "software_read",
     "GET /desk/jira/boards/{id}", "GET /rest/agile/1.0/board/{id}/configuration", ""),
    ("backlog", "Boards and sprints", "Backlog", READY, "software_read", "GET /desk/jira/boards/{id}/backlog",
     "GET /rest/software/1.0/board/{id}/backlog", ""),
    ("sprints", "Boards and sprints", "Sprints, and what is in each", READY, "software_read",
     "GET /desk/jira/sprints/{id}", "GET /rest/software/1.0/sprint/{id}/issue", ""),
    ("sprint_health", "Boards and sprints", "Sprint health: work done against time gone", READY, "software_read",
     "GET /desk/jira/sprints/{id}", "", "Derived by the Desk."),
    ("sprint_move", "Boards and sprints", "Move issues to a sprint or the backlog, and reorder", READY,
     "software_write", "action move_to_sprint", "POST /rest/agile/1.0/sprint/{id}/issue", ""),
    ("sprint_manage", "Boards and sprints", "Create, start and complete a sprint", READY, "software_write",
     "action start_sprint", "POST /rest/agile/1.0/sprint/{id}", ""),
    ("epics", "Boards and sprints", "Epics and their progress", API, "software_read",
     "GET /desk/jira/issues?parent=KEY", "POST /search/jql", "By parent, which works in both project styles."),
    ("reports", "Boards and sprints", "Burndown, velocity, cumulative flow", PLANNED, "software_read", "", "",
     "Jira has no API for report data: it would be computed from sprint issues and their history."),

    # ── releases ────────────────────────────────────────────────────────────
    ("releases", "Releases", "Versions and how far along they are", READY, "core_read",
     "GET /desk/jira/projects/{key}/releases", "GET /project/{key}/version", ""),
    ("release_manage", "Releases", "Create and release a version", READY, "project_admin", "action release_version",
     "POST, PUT /version", ""),
    ("components", "Releases", "Components", API, "projects_read", "GET /desk/jira/projects/{key}",
     "GET /project/{key}/components", ""),

    # ── service management ──────────────────────────────────────────────────
    ("approvals", "Service management", "Requests waiting for my approval", READY, "servicedesk_read",
     "GET /desk/jira/approvals", "GET /rest/servicedeskapi/request", ""),
    ("approve", "Service management", "Approve or decline a request", READY, "servicedesk_write",
     "action answer_approval", "POST /rest/servicedeskapi/request/{key}/approval/{id}", ""),
    ("queues", "Service management", "Queues and SLA", PLANNED, "servicedesk_read", "",
     "GET /rest/servicedeskapi/servicedesk/{id}/queue", "The client has the calls."),

    # ── change feed ─────────────────────────────────────────────────────────
    ("webhooks", "Staying current", "Be told when an issue changes", PLANNED, "webhooks", "",
     "POST /rest/api/3/webhook", "Five per person, 30-day expiry, and a public receiver to verify."),
    ("incoming_work", "Staying current", "Jira issues as incoming work for the secretary", PLANNED, "core_read", "",
     "", "The seam is the Desk's intake worker; nothing reads Jira in the background yet."),
    ("chat", "Staying current", "Ask the secretary about Jira in chat", PLANNED, "core_read", "", "",
     "The Desk's chat scope leaves Scriba's four Jira tools out until writes there go through this gate."),

    # ── not reachable ───────────────────────────────────────────────────────
    ("automation", "Outside the API", "Automation rules", EXCLUDED, None, "", "",
     "Atlassian's automation API refuses OAuth apps."),
    ("plans", "Outside the API", "Plans (advanced roadmaps)", EXCLUDED, None, "", "",
     "Experimental and for Jira administrators only."),
)


def catalogue(scopes: Any = None, *, simulated: bool = False) -> List[Dict[str, Any]]:
    """The features, with whether this connection's scopes allow each."""
    held = policy.normalize_scopes(scopes)
    out: List[Dict[str, Any]] = []
    for feature_id, area, label, state, needs, route, endpoint, note in _ROWS:
        group = policy.GROUP_BY_ID.get(needs) if needs else None
        granted = True if (simulated or group is None) else group.granted_by(held)
        out.append({
            "id": feature_id, "area": area, "label": label, "state": state, "needs": needs,
            "write": bool(group and group.write), "route": route or None, "jira": endpoint or None,
            "note": note or None, "granted": granted,
            "missingScopes": [] if granted or group is None else group.missing(held),
        })
    return out


def summary(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return {state: sum(1 for row in rows if row["state"] == state) for state in (READY, API, PLANNED, EXCLUDED)}
