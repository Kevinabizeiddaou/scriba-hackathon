"""Jira's JSON as the shapes the Desk serves. Pure.

Jira returns large, nested, site-specific objects: a status is four levels
deep, a sprint lives in a custom field whose id differs on every site, and a
description is an ADF tree. Everything the Desk serves under ``/desk/jira/``
is built here, once, in one flat camelCase shape, so no client learns a
custom field id or walks ADF.

Nothing here is trusted as instructions: a summary, a description and a
comment are text written by other people. They are carried as data only.

Personal data is kept to what a row needs: a display name, an avatar and the
accountId that an assignment or a mention must name. Email addresses, which
Jira hides for most users anyway, are not copied.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import adf

STALE_AFTER_DAYS = 7
_BLOCKED_STATUS = re.compile(r"\b(block(ed)?|impediment|on hold|waiting)\b", re.IGNORECASE)
_CATEGORY = {"new": "todo", "indeterminate": "in_progress", "done": "done"}
_PRIORITY_RANK = {"highest": 1, "blocker": 1, "critical": 1, "high": 2, "major": 2, "medium": 3,
                  "normal": 3, "low": 4, "minor": 4, "lowest": 5, "trivial": 5}

# The fields of a list row, and the extra ones an issue page needs.
LIST_FIELDS: Tuple[str, ...] = (
    "summary", "status", "priority", "assignee", "reporter", "issuetype", "project", "labels",
    "components", "fixVersions", "created", "updated", "resolutiondate", "duedate", "parent",
    "timetracking", "subtasks",
)
DETAIL_FIELDS: Tuple[str, ...] = LIST_FIELDS + (
    "description", "comment", "attachment", "issuelinks", "watches", "votes", "worklog",
    "resolution", "environment", "versions", "creator",
)


@dataclass(frozen=True)
class FieldMap:
    """The custom field ids of one Jira site, found by what each field IS
    (its schema), not by a name an administrator may have changed."""

    sprint: Optional[str] = None
    story_points: Tuple[str, ...] = ()
    epic_link: Optional[str] = None
    rank: Optional[str] = None
    flagged: Optional[str] = None
    start_date: Optional[str] = None
    team: Optional[str] = None

    @classmethod
    def from_fields(cls, fields: Iterable[Mapping[str, Any]]) -> "FieldMap":
        found: Dict[str, Any] = {"story_points": []}
        for row in fields or []:
            if not isinstance(row, Mapping) or not row.get("custom"):
                continue
            field_id = str(row.get("id") or "")
            schema = row.get("schema") if isinstance(row.get("schema"), Mapping) else {}
            kind = str(schema.get("custom") or "")
            name = str(row.get("name") or "").strip().lower()
            if kind.endswith(":gh-sprint"):
                found.setdefault("sprint", field_id)
            elif kind.endswith(":gh-epic-link"):
                found.setdefault("epic_link", field_id)
            elif kind.endswith(":gh-lexo-rank"):
                found.setdefault("rank", field_id)
            elif kind.endswith(":jsw-story-points") or name in ("story points", "story point estimate"):
                # Company-managed and team-managed projects use different
                # fields for the same thing; an issue fills at most one.
                found["story_points"].append(field_id)
            elif name == "flagged":
                found.setdefault("flagged", field_id)
            elif name == "start date":
                found.setdefault("start_date", field_id)
            elif kind.endswith(":atlassian-team") or name == "team":
                found.setdefault("team", field_id)
        found["story_points"] = tuple(found["story_points"])
        return cls(**found)

    def ids(self) -> List[str]:
        """Every known custom field id, to add to a search's field list."""
        single = [self.sprint, self.epic_link, self.flagged, self.start_date]
        return [field_id for field_id in (*single, *self.story_points) if field_id]

    def as_dict(self) -> Dict[str, Any]:
        return {"sprint": self.sprint, "storyPoints": list(self.story_points), "epicLink": self.epic_link,
                "rank": self.rank, "flagged": self.flagged, "startDate": self.start_date, "team": self.team}


def parse_instant(value: Any) -> Optional[dt.datetime]:
    """Jira's timestamps (``2026-11-14T09:30:00.000+0100``) and plain dates."""
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text += "T00:00:00+00:00"
    text = text.replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)      # +0100 to +01:00
    text = re.sub(r"\.(\d{1,6})\d*", r".\1", text)             # at most six fractional digits
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.timezone.utc)


def _iso(value: Any) -> Optional[str]:
    parsed = parse_instant(value)
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z") if parsed else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _names(values: Any) -> List[str]:
    return [str(_mapping(item).get("name") or "").strip() for item in (values or [])
            if _mapping(item).get("name")]


def user_view(raw: Any) -> Optional[Dict[str, Any]]:
    user = _mapping(raw)
    if not user.get("accountId") and not user.get("displayName"):
        return None
    avatars = _mapping(user.get("avatarUrls"))
    return {
        "accountId": user.get("accountId"),
        "displayName": str(user.get("displayName") or "").strip() or "Unknown",
        "avatarUrl": avatars.get("48x48") or avatars.get("32x32"),
        "active": bool(user.get("active", True)),
    }


def status_view(raw: Any) -> Dict[str, Any]:
    status = _mapping(raw)
    category = str(_mapping(status.get("statusCategory")).get("key") or "").strip().lower()
    return {"id": status.get("id"), "name": str(status.get("name") or "").strip() or "Unknown",
            "category": _CATEGORY.get(category, "todo")}


def priority_view(raw: Any) -> Optional[Dict[str, Any]]:
    priority = _mapping(raw)
    name = str(priority.get("name") or "").strip()
    if not name:
        return None
    return {"id": priority.get("id"), "name": name, "rank": _PRIORITY_RANK.get(name.lower(), 3),
            "iconUrl": priority.get("iconUrl")}


def type_view(raw: Any) -> Dict[str, Any]:
    kind = _mapping(raw)
    return {"id": kind.get("id"), "name": str(kind.get("name") or "").strip() or "Issue",
            "subtask": bool(kind.get("subtask")), "hierarchyLevel": kind.get("hierarchyLevel"),
            "iconUrl": kind.get("iconUrl")}


def sprint_view(raw: Any) -> Optional[Dict[str, Any]]:
    sprint = _mapping(raw)
    if sprint.get("id") is None:
        return None
    return {
        "id": sprint.get("id"), "name": str(sprint.get("name") or "").strip(),
        "state": str(sprint.get("state") or "").strip().lower() or None,
        "startDate": _iso(sprint.get("startDate")), "endDate": _iso(sprint.get("endDate")),
        "completeDate": _iso(sprint.get("completeDate")), "goal": sprint.get("goal") or None,
        "boardId": sprint.get("originBoardId") or sprint.get("boardId"),
    }


def _current_sprint(value: Any) -> Optional[Dict[str, Any]]:
    """An issue lists every sprint it was ever in: the running one, else the
    next one, else the last one it was closed in."""
    sprints = [view for view in (sprint_view(item) for item in (value or [])) if view]
    for state in ("active", "future"):
        chosen = [sprint for sprint in sprints if sprint["state"] == state]
        if chosen:
            return chosen[-1]
    return sprints[-1] if sprints else None


def issue_url(site_url: Optional[str], key: Any) -> Optional[str]:
    base = str(site_url or "").strip().rstrip("/")
    return f"{base}/browse/{key}" if base and key else None


def _brief(raw: Any, site_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """A linked, parent or child issue: enough to show a row and open it."""
    issue = _mapping(raw)
    if not issue.get("key"):
        return None
    fields = _mapping(issue.get("fields"))
    return {"key": issue.get("key"), "summary": str(fields.get("summary") or "").strip(),
            "status": status_view(fields.get("status")), "type": type_view(fields.get("issuetype")),
            "priority": priority_view(fields.get("priority")), "url": issue_url(site_url, issue.get("key"))}


def signals(issue: Mapping[str, Any], now: dt.datetime) -> Dict[str, Any]:
    """What makes a row need attention. Derived; nothing here is Jira's own."""
    open_ = issue["status"]["category"] != "done"
    due = parse_instant(issue.get("due"))
    due_in_days = (due.date() - now.astimezone(dt.timezone.utc).date()).days if due else None
    updated = parse_instant(issue.get("updated"))
    idle_days = (now - updated).days if updated else None
    blocked_by = [link for link in issue.get("links") or []
                  if link.get("blocksThis") and (link.get("issue") or {}).get("status", {}).get("category") != "done"]
    return {
        "overdue": bool(open_ and due_in_days is not None and due_in_days < 0),
        "dueInDays": due_in_days if open_ else None,
        "blocked": bool(open_ and (issue.get("flagged") or blocked_by
                                   or _BLOCKED_STATUS.search(issue["status"]["name"]))),
        "stale": bool(issue["status"]["category"] == "in_progress" and idle_days is not None
                      and idle_days >= STALE_AFTER_DAYS),
        "idleDays": idle_days,
        "unassigned": bool(open_ and issue.get("assignee") is None),
    }


def link_view(raw: Any, site_url: Optional[str]) -> Optional[Dict[str, Any]]:
    link = _mapping(raw)
    kind = _mapping(link.get("type"))
    outward = link.get("outwardIssue") is not None
    other = _brief(link.get("outwardIssue") if outward else link.get("inwardIssue"), site_url)
    if other is None:
        return None
    label = str(kind.get("outward" if outward else "inward") or kind.get("name") or "relates to").strip()
    return {"id": link.get("id"), "type": kind.get("name"), "direction": "outward" if outward else "inward",
            "label": label, "issue": other,
            # "is blocked by": the other issue stands in the way of this one.
            "blocksThis": (not outward) and "block" in label.lower()}


def comment_view(raw: Any, *, me: Optional[str] = None) -> Dict[str, Any]:
    comment = _mapping(raw)
    body = comment.get("body")
    mentioned = adf.mentioned_account_ids(body)
    visibility = _mapping(comment.get("visibility"))
    return {
        "id": comment.get("id"), "author": user_view(comment.get("author")),
        "body": adf.to_text(body), "created": _iso(comment.get("created")),
        "updated": _iso(comment.get("updated")), "mentions": mentioned,
        "mentionsMe": bool(me and me in mentioned),
        # A comment restricted to a role or group, or internal on a service request.
        "restrictedTo": visibility.get("value") or visibility.get("identifier"),
        "internal": comment.get("jsdPublic") is False,
    }


def attachment_view(raw: Any) -> Dict[str, Any]:
    item = _mapping(raw)
    return {"id": item.get("id"), "filename": item.get("filename"), "size": item.get("size"),
            "mimeType": item.get("mimeType"), "created": _iso(item.get("created")),
            "author": user_view(item.get("author"))}


def worklog_view(raw: Any) -> Dict[str, Any]:
    item = _mapping(raw)
    return {"id": item.get("id"), "author": user_view(item.get("author")),
            "timeSpentSeconds": item.get("timeSpentSeconds"), "timeSpent": item.get("timeSpent"),
            "started": _iso(item.get("started")), "comment": adf.to_text(item.get("comment"))}


def transition_view(raw: Any) -> Dict[str, Any]:
    """One move the workflow allows from here, and what it asks for."""
    item = _mapping(raw)
    required: List[Dict[str, Any]] = []
    for field_id, spec in _mapping(item.get("fields")).items():
        spec = _mapping(spec)
        if spec.get("required"):
            allowed = [str(_mapping(value).get("name") or _mapping(value).get("value") or "")
                       for value in (spec.get("allowedValues") or [])]
            required.append({"id": field_id, "name": spec.get("name") or field_id,
                             "allowedValues": [value for value in allowed if value][:50]})
    return {"id": str(item.get("id") or ""), "name": str(item.get("name") or "").strip(),
            "to": status_view(item.get("to")), "hasScreen": bool(item.get("hasScreen")),
            "requiredFields": required}


def history_view(raw: Any, limit: int = 50) -> List[Dict[str, Any]]:
    """An issue's changelog, newest first: who changed which field, from what, to what."""
    entries = _mapping(raw).get("histories") or _mapping(raw).get("values") or []
    out: List[Dict[str, Any]] = []
    for entry in entries:
        entry = _mapping(entry)
        changes = [{"field": item.get("field"), "from": item.get("fromString"), "to": item.get("toString")}
                   for item in (entry.get("items") or []) if isinstance(item, Mapping)]
        if changes:
            out.append({"id": entry.get("id"), "author": user_view(entry.get("author")),
                        "at": _iso(entry.get("created")), "changes": changes})
    out.sort(key=lambda row: row["at"] or "", reverse=True)
    return out[:limit]


def issue_view(raw: Any, *, site_url: Optional[str] = None, field_map: Optional[FieldMap] = None,
               now: Optional[dt.datetime] = None, me: Optional[str] = None,
               detail: bool = False) -> Dict[str, Any]:
    """One issue. ``detail`` adds the text, the comments and everything an issue page shows."""
    issue = _mapping(raw)
    fields = _mapping(issue.get("fields"))
    fmap = field_map or FieldMap()
    now = now or dt.datetime.now(dt.timezone.utc)
    key = issue.get("key")

    points: Optional[float] = None
    for field_id in fmap.story_points:
        value = fields.get(field_id)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            points = float(value)
            break
    tracking = _mapping(fields.get("timetracking"))
    parent = _brief(fields.get("parent"), site_url)
    if parent is None and fmap.epic_link and fields.get(fmap.epic_link):
        # Older company-managed projects name the epic in a custom field.
        epic_key = str(fields.get(fmap.epic_link))
        parent = {"key": epic_key, "summary": "", "status": None, "type": {"name": "Epic"},
                  "priority": None, "url": issue_url(site_url, epic_key)}
    links = [view for view in (link_view(item, site_url) for item in (fields.get("issuelinks") or [])) if view]
    subtasks = [view for view in (_brief(item, site_url) for item in (fields.get("subtasks") or [])) if view]
    comments_raw = _mapping(fields.get("comment"))
    project = _mapping(fields.get("project"))

    view: Dict[str, Any] = {
        "key": key, "id": issue.get("id"), "url": issue_url(site_url, key),
        "summary": str(fields.get("summary") or "").strip(),
        "type": type_view(fields.get("issuetype")), "status": status_view(fields.get("status")),
        "priority": priority_view(fields.get("priority")),
        "project": {"key": project.get("key"), "name": project.get("name")},
        "assignee": user_view(fields.get("assignee")), "reporter": user_view(fields.get("reporter")),
        "labels": [str(label) for label in (fields.get("labels") or [])],
        "components": _names(fields.get("components")), "fixVersions": _names(fields.get("fixVersions")),
        "created": _iso(fields.get("created")), "updated": _iso(fields.get("updated")),
        "resolved": _iso(fields.get("resolutiondate")),
        "due": str(fields.get("duedate") or "").strip() or None,
        "startDate": (str(fields.get(fmap.start_date) or "").strip() or None) if fmap.start_date else None,
        "parent": parent,
        "sprint": _current_sprint(fields.get(fmap.sprint)) if fmap.sprint else None,
        "storyPoints": points,
        "flagged": bool(fields.get(fmap.flagged)) if fmap.flagged else False,
        "timeTracking": {
            "originalEstimateSeconds": tracking.get("originalEstimateSeconds"),
            "remainingEstimateSeconds": tracking.get("remainingEstimateSeconds"),
            "timeSpentSeconds": tracking.get("timeSpentSeconds"),
        } if tracking else None,
        "links": links,
        "counts": {
            "subtasks": len(subtasks),
            "subtasksDone": sum(1 for item in subtasks if (item.get("status") or {}).get("category") == "done"),
            "comments": comments_raw.get("total") if comments_raw else None,
            "attachments": len(fields.get("attachment") or []) if "attachment" in fields else None,
            "links": len(links) if "issuelinks" in fields else None,
            "watchers": _mapping(fields.get("watches")).get("watchCount"),
        },
    }
    view["signals"] = signals(view, now)
    if not detail:
        view.pop("links")
        return view

    comments = [comment_view(item, me=me) for item in (comments_raw.get("comments") or [])]
    worklog = _mapping(fields.get("worklog"))
    view.update({
        "description": adf.to_text(fields.get("description")),
        "environment": adf.to_text(fields.get("environment")) or None,
        "resolution": _mapping(fields.get("resolution")).get("name"),
        "affectsVersions": _names(fields.get("versions")),
        "creator": user_view(fields.get("creator")),
        "subtasks": subtasks,
        "comments": comments,
        "commentsTruncated": bool(comments_raw.get("total") and comments_raw.get("total") > len(comments)),
        "attachments": [attachment_view(item) for item in (fields.get("attachment") or [])],
        "worklogs": [worklog_view(item) for item in (worklog.get("worklogs") or [])][-20:],
        "watching": bool(_mapping(fields.get("watches")).get("isWatching")),
        "votes": _mapping(fields.get("votes")).get("votes"),
        "transitions": [transition_view(item) for item in (issue.get("transitions") or [])],
        "history": history_view(issue.get("changelog")) if issue.get("changelog") else None,
        "editable": sorted(_mapping(_mapping(issue.get("editmeta")).get("fields")))
        if issue.get("editmeta") else None,
    })
    return view


def project_view(raw: Any, *, site_url: Optional[str] = None) -> Dict[str, Any]:
    project = _mapping(raw)
    avatars = _mapping(project.get("avatarUrls"))
    key = project.get("key")
    base = str(site_url or "").rstrip("/")
    return {
        "id": project.get("id"), "key": key, "name": project.get("name"),
        # software | service_desk | business | product_discovery
        "kind": project.get("projectTypeKey"),
        "style": project.get("style"),                 # classic (company-managed) | next-gen (team-managed)
        "lead": user_view(project.get("lead")),
        "avatarUrl": avatars.get("48x48"), "archived": bool(project.get("archived")),
        "url": f"{base}/browse/{key}" if base and key else None,
    }


def version_view(raw: Any, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    version = _mapping(raw)
    now = now or dt.datetime.now(dt.timezone.utc)
    release = parse_instant(version.get("releaseDate"))
    released = bool(version.get("released"))
    return {
        "id": version.get("id"), "name": version.get("name"), "description": version.get("description"),
        "released": released, "archived": bool(version.get("archived")),
        "startDate": version.get("startDate"), "releaseDate": version.get("releaseDate"),
        "overdue": bool(version.get("overdue") or (release and not released and release.date() < now.date())),
        "daysToRelease": (release.date() - now.date()).days if release and not released else None,
    }


def board_view(raw: Any) -> Dict[str, Any]:
    board = _mapping(raw)
    location = _mapping(board.get("location"))
    return {"id": board.get("id"), "name": board.get("name"),
            "type": str(board.get("type") or "").lower() or None,       # scrum | kanban | simple
            "projectKey": location.get("projectKey"), "projectName": location.get("projectName")}


def filter_view(raw: Any) -> Dict[str, Any]:
    item = _mapping(raw)
    return {"id": item.get("id"), "name": item.get("name"), "description": item.get("description"),
            "jql": item.get("jql"), "favourite": bool(item.get("favourite")),
            "owner": user_view(item.get("owner"))}


def page_of(rows: Sequence[Any], *, next_page_token: Optional[str] = None, is_last: Optional[bool] = None,
            start_at: Optional[int] = None, total: Optional[int] = None) -> Dict[str, Any]:
    """How a list says whether there is more. Search pages by token and has no
    total; the older endpoints page by offset. A client reads ``more`` and
    passes back whichever cursor it was given."""
    more = bool(next_page_token) if is_last is None else not is_last
    if next_page_token is None and start_at is not None and total is not None:
        more = start_at + len(rows) < total
    return {"count": len(rows), "more": more, "nextPageToken": next_page_token,
            "nextStartAt": (start_at + len(rows)) if (more and start_at is not None) else None,
            "total": total}
