"""A synthetic Jira site, for the demo and for the tests.

``JiraSite`` is a transport (``transport.py``): it answers the same REST
paths Jira Cloud answers, in Jira's own JSON shapes, from data held in
memory. So the demo and the tests run through exactly the client, the
normalization and the proposal code that talk to a real site. Nothing here
is reachable from a real connection and nothing here opens a socket.

It is a stand-in, not an emulator. It knows the endpoints the Desk calls and
the JQL the Desk builds (``jql.py``); a query outside that grammar is
refused with a message saying so, the way Jira refuses JQL it cannot parse.
Permissions, screens, workflows per project and notification are not
modelled: every issue shares one workflow and the person can do anything.

A site belongs to one sandbox world (``sandbox.py`` of the overlay) and
lives exactly as long as it. Everything written to it is listed in
``site.log``: a simulated change is never reported as a real one.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import threading
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import adf
from .transport import JiraResponse

SITE_URL = "https://desk-sandbox.jira.example"
SITE_NAME = "Desk sandbox"
CLOUD_ID = "sandbox-site"

F_SPRINT, F_POINTS, F_FLAGGED, F_START, F_RANK = (
    "customfield_10020", "customfield_10016", "customfield_10021", "customfield_10015", "customfield_10019")

_CATEGORIES = {"new": {"id": 2, "key": "new", "name": "To Do"},
               "indeterminate": {"id": 4, "key": "indeterminate", "name": "In Progress"},
               "done": {"id": 3, "key": "done", "name": "Done"}}
_STATUSES = {"To Do": ("10000", "new"), "In Progress": ("10001", "indeterminate"),
             "In Review": ("10002", "indeterminate"), "Blocked": ("10003", "indeterminate"),
             "Done": ("10004", "done")}
_TRANSITIONS = (("11", "To Do", "To Do"), ("21", "Start progress", "In Progress"),
                ("31", "Send to review", "In Review"), ("41", "Block", "Blocked"), ("51", "Done", "Done"))
_PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")
_RESOLUTIONS = ("Done", "Won't Do", "Duplicate")
_TYPES = (("10001", "Epic", False, 1), ("10002", "Story", False, 0), ("10003", "Task", False, 0),
          ("10004", "Bug", False, 0), ("10005", "Sub-task", True, -1))
_LINK_TYPES = (("10000", "Blocks", "is blocked by", "blocks"),
               ("10001", "Relates", "relates to", "relates to"),
               ("10002", "Duplicate", "is duplicated by", "duplicates"))


class _Refused(Exception):
    def __init__(self, status: int, message: str, errors: Optional[Mapping[str, str]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = {"errorMessages": [message] if message else [], "errors": dict(errors or {})}


def _status(name: str) -> Dict[str, Any]:
    status_id, category = _STATUSES[name]
    return {"id": status_id, "name": name, "statusCategory": dict(_CATEGORIES[category])}


def _type(name: str) -> Dict[str, Any]:
    for type_id, type_name, subtask, level in _TYPES:
        if type_name.lower() == str(name).lower():
            return {"id": type_id, "name": type_name, "subtask": subtask, "hierarchyLevel": level}
    raise _Refused(400, "", {"issuetype": "Specify a valid issue type"})


class JiraSite:
    """One synthetic site. Thread-safe; ``now`` is the owning world's clock."""

    def __init__(self, *, owner_email: str = "you@desk.example",
                 now: Optional[Callable[[], dt.datetime]] = None, seed: bool = True) -> None:
        self._now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self._lock = threading.RLock()
        self.site_url, self.site_name, self.cloud_id = SITE_URL, SITE_NAME, CLOUD_ID
        name = owner_email.split("@")[0].replace(".", " ").title() or "You"
        self.users: Dict[str, Dict[str, Any]] = {}
        self.me = self._user("sbx-me", name)
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.issues: Dict[str, Dict[str, Any]] = {}
        self.sprints: Dict[int, Dict[str, Any]] = {}
        self.boards: Dict[int, Dict[str, Any]] = {}
        self.versions: Dict[str, Dict[str, Any]] = {}
        self.links: List[Dict[str, Any]] = []
        self.watchers: Dict[str, List[str]] = {}
        self.approvals: Dict[str, Dict[str, Any]] = {}
        self.filters: List[Dict[str, Any]] = []
        self.log: List[Dict[str, Any]] = []
        self.faults: List[Tuple[int, Optional[str]]] = []
        self.requests = 0
        self._counters: Dict[str, int] = {}
        self._ids = 20000
        if seed:
            self._seed()

    # ── construction ────────────────────────────────────────────────────────
    def now(self) -> dt.datetime:
        return self._now().astimezone(dt.timezone.utc)

    def _stamp(self, when: Optional[dt.datetime] = None) -> str:
        return (when or self.now()).strftime("%Y-%m-%dT%H:%M:%S.000+0000")

    def _day(self, offset: int) -> str:
        return (self.now() + dt.timedelta(days=offset)).date().isoformat()

    def _id(self) -> str:
        self._ids += 1
        return str(self._ids)

    def _user(self, account_id: str, name: str) -> Dict[str, Any]:
        self.users[account_id] = {"accountId": account_id, "displayName": name, "active": True,
                                  "accountType": "atlassian", "avatarUrls": {}}
        return self.users[account_id]

    def add_project(self, key: str, name: str, kind: str = "software") -> Dict[str, Any]:
        self.projects[key] = {"id": self._id(), "key": key, "name": name, "projectTypeKey": kind,
                              "style": "classic", "lead": self.me, "avatarUrls": {},
                              "components": [], "archived": False}
        self._counters[key] = 0
        return self.projects[key]

    def add_issue(self, project: str, summary: str, *, kind: str = "Task", status: str = "To Do",
                  priority: str = "Medium", assignee: Optional[str] = None, reporter: Optional[str] = None,
                  due: Optional[int] = None, updated: int = 0, created: int = -10, labels: Sequence[str] = (),
                  parent: Optional[str] = None, sprint: Optional[int] = None, points: Optional[float] = None,
                  flagged: bool = False, description: str = "", fix_versions: Sequence[str] = (),
                  components: Sequence[str] = ()) -> Dict[str, Any]:
        self._counters[project] += 1
        key = f"{project}-{self._counters[project]}"
        done = _STATUSES[status][1] == "done"
        changed = self.now() + dt.timedelta(days=updated)
        self.issues[key] = {
            "id": self._id(), "key": key, "self": f"{SITE_URL}/rest/api/3/issue/{key}",
            "fields": {
                "summary": summary, "description": adf.to_adf(description) if description else None,
                "issuetype": _type(kind), "status": _status(status), "priority": {"id": str(_PRIORITIES.index(priority) + 1), "name": priority},
                "project": {k: self.projects[project][k] for k in ("id", "key", "name", "projectTypeKey")},
                "assignee": self.users.get(assignee) if assignee else None,
                "reporter": self.users.get(reporter or "sbx-me"), "creator": self.users.get(reporter or "sbx-me"),
                "labels": list(labels),
                "components": [{"name": name} for name in components],
                "fixVersions": [{"id": self._version_id(project, name), "name": name} for name in fix_versions],
                "versions": [],
                "created": self._stamp(self.now() + dt.timedelta(days=created)),
                "updated": self._stamp(changed),
                "resolutiondate": self._stamp(changed) if done else None,
                "resolution": {"name": "Done"} if done else None,
                "duedate": self._day(due) if due is not None else None,
                "parent": {"key": parent} if parent else None,
                "timetracking": {}, "environment": None,
                "comment": {"comments": [], "total": 0}, "worklog": {"worklogs": [], "total": 0},
                "attachment": [], "votes": {"votes": 0},
                F_SPRINT: [sprint] if sprint else None, F_POINTS: points,
                F_FLAGGED: [{"value": "Impediment"}] if flagged else None, F_START: None,
            },
            "_rank": len(self.issues), "_history": [],
        }
        return self.issues[key]

    def _version_id(self, project: str, name: str) -> Optional[str]:
        return next((vid for vid, row in self.versions.items()
                     if row["name"] == name and row["_project"] == project), None)

    def add_version(self, project: str, name: str, *, released: bool = False,
                    release_in_days: Optional[int] = None) -> Dict[str, Any]:
        version_id = self._id()
        self.versions[version_id] = {
            "id": version_id, "name": name, "released": released, "archived": False,
            "projectId": int(self.projects[project]["id"]), "_project": project, "description": None,
            "releaseDate": self._day(release_in_days) if release_in_days is not None else None}
        return self.versions[version_id]

    def add_sprint(self, board: int, name: str, state: str, *, start: int, end: int,
                   goal: Optional[str] = None) -> Dict[str, Any]:
        sprint_id = len(self.sprints) + 1
        self.sprints[sprint_id] = {
            "id": sprint_id, "name": name, "state": state, "originBoardId": board, "goal": goal,
            "startDate": self._stamp(self.now() + dt.timedelta(days=start)),
            "endDate": self._stamp(self.now() + dt.timedelta(days=end)),
            "completeDate": self._stamp(self.now() + dt.timedelta(days=end)) if state == "closed" else None}
        return self.sprints[sprint_id]

    def comment(self, key: str, author: str, text: str, *, days_ago: int = 0) -> Dict[str, Any]:
        block = self.issues[key]["fields"]["comment"]
        when = self._stamp(self.now() - dt.timedelta(days=days_ago))
        row = {"id": self._id(), "author": self.users[author], "body": adf.to_adf(text),
               "created": when, "updated": when}
        block["comments"].append(row)
        block["total"] = len(block["comments"])
        return row

    def link(self, type_name: str, *, outward: str, inward: str) -> None:
        self.links.append({"id": self._id(), "type": type_name, "outward": outward, "inward": inward})

    def _seed(self) -> None:
        """A small team mid-sprint: something late, something blocked,
        something stalled, something waiting on the person."""
        for account_id, name in (("sbx-priya", "Priya Raman"), ("sbx-tomas", "Tomas Lindqvist"),
                                 ("sbx-aiko", "Aiko Mori"), ("sbx-sam", "Sam Okafor")):
            self._user(account_id, name)
        self.add_project("DESK", "Executive Desk")
        self.add_project("OPS", "Operations")
        self.add_project("HELP", "Help Centre", "service_desk")
        self.boards[1] = {"id": 1, "name": "DESK board", "type": "scrum",
                          "location": {"projectKey": "DESK", "projectName": "Executive Desk"}}
        self.boards[2] = {"id": 2, "name": "OPS board", "type": "kanban",
                          "location": {"projectKey": "OPS", "projectName": "Operations"}}
        self.add_sprint(1, "Sprint 7", "closed", start=-24, end=-10)
        self.add_sprint(1, "Sprint 8", "active", start=-9, end=5, goal="Ship the approval flow")
        self.add_sprint(1, "Sprint 9", "future", start=5, end=19)
        self.add_version("DESK", "1.3", released=True, release_in_days=-30)
        self.add_version("DESK", "1.4", release_in_days=6)

        add = self.add_issue
        add("DESK", "Approval flow", kind="Epic", status="In Progress", priority="High", assignee="sbx-me",
            created=-40, updated=-1, description="Everything a person approves before it is sent.")
        add("DESK", "Approve a change from the phone", kind="Story", status="In Progress", priority="High",
            assignee="sbx-me", due=2, sprint=2, points=5, parent="DESK-1", updated=-1, fix_versions=["1.4"],
            description="As an executive I approve a proposed change in two taps.\n\n- shows what will change\n- shows who is notified")
        add("DESK", "Held actions say why they are held", kind="Story", status="In Review", priority="Medium",
            assignee="sbx-priya", due=1, sprint=2, points=3, parent="DESK-1", updated=-2, fix_versions=["1.4"])
        add("DESK", "Calendar conflict is missed across time zones", kind="Bug", status="Blocked",
            priority="Highest", assignee="sbx-tomas", due=-2, sprint=2, points=3, updated=-3, flagged=True,
            labels=["customer"], fix_versions=["1.4"],
            description="A meeting proposed in Lisbon time is checked against the Tokyo calendar an hour off.")
        add("DESK", "Time zone data for the availability service", kind="Task", status="To Do", priority="High",
            assignee=None, sprint=2, points=2, updated=-6)
        add("DESK", "Read-back after every calendar write", kind="Story", status="In Progress", priority="Medium",
            assignee="sbx-aiko", sprint=2, points=5, updated=-9, fix_versions=["1.4"])
        add("DESK", "Audit trail export", kind="Story", status="Done", priority="Medium", assignee="sbx-priya",
            sprint=2, points=3, updated=-4, fix_versions=["1.4"])
        add("DESK", "Retry never duplicates a sent reply", kind="Bug", status="Done", priority="High",
            assignee="sbx-me", sprint=2, points=2, updated=-5, fix_versions=["1.4"])
        add("DESK", "Briefing lists what is waiting on me", kind="Story", status="To Do", priority="Medium",
            assignee="sbx-me", due=9, sprint=3, points=5, updated=-2)
        add("DESK", "Slack digest of the briefing", kind="Story", status="To Do", priority="Low",
            assignee=None, updated=-20, points=None)
        add("DESK", "Write the copy for the approval screen", kind="Sub-task", status="To Do", priority="Medium",
            assignee="sbx-sam", parent="DESK-2", sprint=2, updated=-1)
        add("OPS", "Renew the TLS certificate for the API", status="To Do", priority="Highest",
            assignee="sbx-me", due=-1, updated=-1, labels=["security"])
        add("OPS", "Rotate the staging database password", status="In Progress", priority="High",
            assignee="sbx-sam", due=3, updated=-8)
        add("OPS", "Quarterly access review", status="To Do", priority="Medium", assignee="sbx-me", due=6, updated=-3)
        add("OPS", "Decommission the old build agents", status="Done", priority="Low", assignee="sbx-tomas", updated=-2)
        add("HELP", "Laptop replacement for a new hire", kind="Task", status="To Do", priority="Medium",
            assignee="sbx-sam", reporter="sbx-aiko", updated=-1,
            description="Needs sign-off from the budget owner before it is ordered.")
        self.approvals["HELP-1"] = {"id": "1", "name": "Budget owner approval", "finalDecision": "pending",
                                    "canAnswerApproval": True, "approvers": [{"approver": self.me,
                                                                              "approverDecision": "pending"}]}

        self.link("Blocks", outward="DESK-5", inward="DESK-4")      # DESK-5 blocks DESK-4
        self.link("Relates", outward="DESK-3", inward="DESK-2")
        self.comment("DESK-4", "sbx-tomas", "Blocked until we have the time zone data from DESK-5. "
                     "[~accountid:sbx-me] can you find an owner for it?", days_ago=3)
        self.comment("DESK-2", "sbx-priya", "The preview reads well. One question on wording, see DESK-11.", days_ago=1)
        self.comment("OPS-1", "sbx-sam", "The certificate expired yesterday; the API is on the fallback one.", days_ago=1)
        self.watchers = {"DESK-4": ["sbx-me", "sbx-tomas"], "DESK-2": ["sbx-me"], "OPS-1": ["sbx-me"]}
        self.filters = [{"id": "10010", "name": "Release 1.4, still open", "favourite": True, "owner": self.me,
                         "jql": 'project = "DESK" AND fixVersion = "1.4" AND statusCategory != Done ORDER BY priority DESC',
                         "description": "Everything standing between us and 1.4."}]
        self.log.clear()

    # ── the transport ───────────────────────────────────────────────────────
    def fail_next(self, status: int, retry_after: Optional[str] = None, times: int = 1) -> None:
        self.faults.extend([(status, retry_after)] * times)

    def request(self, method: str, api: str, path: str, *, params: Optional[Mapping[str, Any]] = None,
                json: Any = None, files: Any = None, headers: Optional[Mapping[str, str]] = None) -> JiraResponse:
        with self._lock:
            self.requests += 1
            if self.faults:
                status, retry_after = self.faults.pop(0)
                return JiraResponse(status, {"errorMessages": ["The sandbox was asked to fail this request."]},
                                    {"Retry-After": retry_after} if retry_after else {})
            query = {key: value for key, value in dict(params or {}).items() if value is not None}
            route = f"{method.upper()} {api} {str(path).strip('/')}"
            try:
                for pattern, handler in self._routes():
                    match = pattern.fullmatch(route)
                    if match:
                        body = handler(*match.groups(), query=query, body=json)
                        return JiraResponse(204 if body is None else 200, copy.deepcopy(body))
                raise _Refused(404, f"The sandbox has no {method.upper()} {api}/{path}.")
            except _Refused as exc:
                return JiraResponse(exc.status, exc.body)

    def _routes(self) -> List[Tuple[Any, Callable[..., Any]]]:
        if getattr(self, "_table", None) is None:
            key, num, word = r"([A-Za-z][A-Za-z0-9_]*-\d+)", r"(\d+)", r"([A-Za-z][A-Za-z0-9_]*)"
            table = {
                "GET platform myself": lambda query, body: self.me,
                "GET platform serverInfo": lambda query, body: {"baseUrl": SITE_URL, "deploymentType": "Cloud",
                                                                "serverTitle": SITE_NAME},
                "GET platform field": lambda query, body: self._fields(),
                "GET platform label": lambda query, body: self._labels(),
                "GET platform issueLinkType": lambda query, body: {"issueLinkTypes": [
                    {"id": i, "name": n, "inward": inward, "outward": outward} for i, n, inward, outward in _LINK_TYPES]},
                "POST platform issueLink": lambda query, body: self._create_link(body or {}),
                "GET platform project/search": self._project_search,
                f"GET platform project/{word}": lambda project, query, body: self._project(project, full=True),
                f"GET platform project/{word}/components": lambda project, query, body: self._project(project)["components"],
                f"GET platform project/{word}/version": self._project_versions,
                f"GET platform project/{word}/statuses": lambda project, query, body: [
                    {"name": name, "statuses": [_status(s) for s in _STATUSES]} for _, name, _, _ in _TYPES],
                f"GET platform version/{num}": lambda version, query, body: self._version(version),
                f"GET platform version/{num}/relatedIssueCounts": lambda version, query, body: self._version_counts(version),
                f"GET platform version/{num}/unresolvedIssueCount": lambda version, query, body: self._version_counts(version),
                "POST platform version": lambda query, body: self._create_version(body or {}),
                f"PUT platform version/{num}": lambda version, query, body: self._update_version(version, body or {}),
                "POST platform search/jql": lambda query, body: self._search(body or {}),
                "POST platform search/approximate-count": lambda query, body: {
                    "count": len(self._match(str((body or {}).get("jql") or "")))},
                "POST platform issue": lambda query, body: self._create_issue(body or {}),
                f"GET platform issue/createmeta/{word}/issuetypes": lambda project, query, body: {
                    "issueTypes": [dict(_type(name)) for _, name, _, _ in _TYPES if self._project(project)]},
                f"GET platform issue/createmeta/{word}/issuetypes/{num}": lambda project, type_id, query, body: {
                    "fields": self._create_fields()},
                f"GET platform issue/{key}": self._get_issue,
                f"PUT platform issue/{key}": self._edit_issue,
                f"GET platform issue/{key}/editmeta": lambda issue, query, body: {"fields": self._edit_fields(issue)},
                f"GET platform issue/{key}/transitions": lambda issue, query, body: {
                    "transitions": self._transitions(issue)},
                f"POST platform issue/{key}/transitions": self._transition,
                f"PUT platform issue/{key}/assignee": self._assign,
                f"GET platform issue/{key}/comment": self._comments,
                f"POST platform issue/{key}/comment": self._add_comment,
                f"GET platform issue/{key}/worklog": lambda issue, query, body: self._issue(issue)["fields"]["worklog"],
                f"POST platform issue/{key}/worklog": self._add_worklog,
                f"GET platform issue/{key}/watchers": lambda issue, query, body: {
                    "watchCount": len(self.watchers.get(self._issue(issue)["key"], [])),
                    "isWatching": "sbx-me" in self.watchers.get(issue.upper(), []),
                    "watchers": [self.users[a] for a in self.watchers.get(issue.upper(), [])]},
                f"POST platform issue/{key}/watchers": lambda issue, query, body: self._watch(issue, body, True),
                f"DELETE platform issue/{key}/watchers": lambda issue, query, body: self._watch(
                    issue, query.get("accountId"), False),
                f"GET platform issue/{key}/changelog": lambda issue, query, body: {
                    "values": list(self._issue(issue)["_history"]), "total": len(self._issue(issue)["_history"])},
                f"GET platform issue/{key}/remotelink": lambda issue, query, body: [],
                "GET platform user/assignable/search": lambda query, body: self._people(query),
                "GET platform user/search": lambda query, body: self._people(query),
                "GET platform user/viewissue/search": lambda query, body: self._people(query),
                "GET platform filter/my": lambda query, body: list(self.filters),
                "GET platform filter/favourite": lambda query, body: [f for f in self.filters if f.get("favourite")],
                f"GET platform filter/{num}": lambda filter_id, query, body: self._filter(filter_id),
                "GET platform dashboard": lambda query, body: {"dashboards": [
                    {"id": "10000", "name": "Team overview", "isFavourite": True,
                     "view": f"{SITE_URL}/jira/dashboards/10000"}], "total": 1},
                "GET agile board": self._boards,
                f"GET agile board/{num}": lambda board, query, body: self._board(board),
                f"GET agile board/{num}/configuration": lambda board, query, body: self._board_config(board),
                f"GET agile board/{num}/sprint": self._board_sprints,
                f"GET agile board/{num}/epic": lambda board, query, body: {"values": [
                    {"id": int(row["id"]), "key": row["key"], "name": row["fields"]["summary"],
                     "summary": row["fields"]["summary"],
                     "done": row["fields"]["status"]["statusCategory"]["key"] == "done"}
                    for row in self._board_issues(board) if row["fields"]["issuetype"]["name"] == "Epic"]},
                f"GET software board/{num}/issue": lambda board, query, body: self._listing(
                    self._board_issues(board), query),
                f"GET software board/{num}/backlog": lambda board, query, body: self._listing(
                    self._backlog(board), query),
                f"GET agile sprint/{num}": lambda sprint, query, body: self._sprint(sprint),
                f"GET software sprint/{num}/issue": lambda sprint, query, body: self._listing(
                    self._sprint_issues(sprint), query),
                "POST agile sprint": lambda query, body: self._create_sprint(body or {}),
                f"POST agile sprint/{num}": lambda sprint, query, body: self._update_sprint(sprint, body or {}),
                f"POST agile sprint/{num}/issue": lambda sprint, query, body: self._move(body or {}, int(sprint)),
                "POST agile backlog/issue": lambda query, body: self._move(body or {}, None),
                "PUT agile issue/rank": lambda query, body: self._rank(body or {}),
                "GET servicedesk servicedesk": lambda query, body: {"values": [
                    {"id": "1", "projectKey": "HELP", "projectName": "Help Centre"}], "isLastPage": True},
                "GET servicedesk request": self._requests,
                f"GET servicedesk request/{key}/approval": lambda issue, query, body: {
                    "values": [self.approvals[issue.upper()]] if issue.upper() in self.approvals else []},
                f"POST servicedesk request/{key}/approval/{num}": self._answer_approval,
            }
            self._table = [(re.compile(route), handler) for route, handler in table.items()]
        return self._table

    # ── lookups ─────────────────────────────────────────────────────────────
    def _issue(self, key: str) -> Dict[str, Any]:
        issue = self.issues.get(str(key).upper())
        if issue is None:
            raise _Refused(404, "Issue does not exist or you do not have permission to see it.")
        return issue

    def _project(self, key: str, full: bool = False) -> Dict[str, Any]:
        project = self.projects.get(str(key).upper())
        if project is None:
            raise _Refused(404, f"No project could be found with key '{key}'.")
        if full:
            return {**project, "issueTypes": [dict(_type(name)) for _, name, _, _ in _TYPES]}
        return project

    def _sprint(self, sprint_id: Any) -> Dict[str, Any]:
        sprint = self.sprints.get(int(sprint_id))
        if sprint is None:
            raise _Refused(404, "Sprint does not exist.")
        return sprint

    def _board(self, board_id: Any) -> Dict[str, Any]:
        board = self.boards.get(int(board_id))
        if board is None:
            raise _Refused(404, "Board does not exist.")
        return board

    def _fields(self) -> List[Dict[str, Any]]:
        custom = "com.pyxis.greenhopper.jira"
        system = [{"id": name, "name": name.title(), "custom": False} for name in ("summary", "status", "priority")]
        return system + [
            {"id": F_SPRINT, "name": "Sprint", "custom": True, "schema": {"custom": f"{custom}:gh-sprint"}},
            {"id": F_POINTS, "name": "Story point estimate", "custom": True,
             "schema": {"custom": f"{custom}:jsw-story-points"}},
            {"id": F_RANK, "name": "Rank", "custom": True, "schema": {"custom": f"{custom}:gh-lexo-rank"}},
            {"id": F_FLAGGED, "name": "Flagged", "custom": True,
             "schema": {"custom": "com.atlassian.jira.plugin.system.customfieldtypes:multicheckboxes"}},
            {"id": F_START, "name": "Start date", "custom": True,
             "schema": {"custom": "com.atlassian.jira.plugin.system.customfieldtypes:datepicker"}},
        ]

    def _labels(self) -> Dict[str, Any]:
        labels = sorted({label for issue in self.issues.values() for label in issue["fields"]["labels"]})
        return {"values": labels, "total": len(labels), "isLast": True}

    def _create_fields(self) -> List[Dict[str, Any]]:
        def row(field_id: str, name: str, required: bool = False, allowed: Sequence[str] = ()) -> Dict[str, Any]:
            return {"fieldId": field_id, "key": field_id, "name": name, "required": required,
                    "hasDefaultValue": field_id in ("priority", "reporter"),
                    "allowedValues": [{"name": value} for value in allowed]}
        return [row("project", "Project", True), row("issuetype", "Issue Type", True),
                row("summary", "Summary", True), row("description", "Description"),
                row("priority", "Priority", False, _PRIORITIES), row("assignee", "Assignee"),
                row("labels", "Labels"), row("components", "Components"), row("fixVersions", "Fix versions"),
                row("duedate", "Due date"), row("parent", "Parent"), row(F_POINTS, "Story point estimate"),
                row(F_SPRINT, "Sprint"), row(F_START, "Start date")]

    def _edit_fields(self, key: str) -> Dict[str, Any]:
        self._issue(key)
        return {row["fieldId"]: {"name": row["name"], "required": row["required"],
                                 "allowedValues": row["allowedValues"]}
                for row in self._create_fields() if row["fieldId"] not in ("project", "issuetype")}

    def _people(self, query: Mapping[str, Any]) -> List[Dict[str, Any]]:
        text = str(query.get("query") or "").strip().lower()
        people = [user for user in self.users.values() if text in user["displayName"].lower()]
        return people[: int(query.get("maxResults") or 50)]

    def _filter(self, filter_id: str) -> Dict[str, Any]:
        for row in self.filters:
            if row["id"] == str(filter_id):
                return row
        raise _Refused(404, "The selected filter is not available to you.")

    # ── reading issues ──────────────────────────────────────────────────────
    def _render(self, issue: Mapping[str, Any], names: Optional[Sequence[str]] = None,
                expand: str = "") -> Dict[str, Any]:
        key = issue["key"]
        fields = dict(issue["fields"])
        sprints = [self.sprints[sprint_id] for sprint_id in (fields.get(F_SPRINT) or []) if sprint_id in self.sprints]
        fields[F_SPRINT] = sprints or None
        if (fields.get("parent") or {}).get("key") in self.issues:
            fields["parent"] = self._brief(fields["parent"]["key"])
        fields["subtasks"] = [self._brief(other["key"]) for other in self.issues.values()
                              if (other["fields"].get("parent") or {}).get("key") == key
                              and other["fields"]["issuetype"]["subtask"]]
        fields["issuelinks"] = self._links_of(key)
        watching = self.watchers.get(key, [])
        fields["watches"] = {"watchCount": len(watching), "isWatching": "sbx-me" in watching}
        if names is not None:
            wanted = set(names)
            fields = {name: value for name, value in fields.items() if name in wanted}
        out: Dict[str, Any] = {"id": issue["id"], "key": key, "self": issue["self"], "fields": fields}
        if "transitions" in expand:
            out["transitions"] = self._transitions(key)
        if "changelog" in expand:
            out["changelog"] = {"histories": list(issue["_history"])}
        if "editmeta" in expand:
            out["editmeta"] = {"fields": self._edit_fields(key)}
        return out

    def _brief(self, key: str) -> Dict[str, Any]:
        fields = self.issues[key]["fields"]
        return {"id": self.issues[key]["id"], "key": key,
                "fields": {name: fields[name] for name in ("summary", "status", "issuetype", "priority")}}

    def _links_of(self, key: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for link in self.links:
            kind = next(({"id": i, "name": n, "inward": inward, "outward": outward}
                         for i, n, inward, outward in _LINK_TYPES if n == link["type"]), None)
            if kind is None:
                continue
            if link["outward"] == key and link["inward"] in self.issues:
                out.append({"id": link["id"], "type": kind, "outwardIssue": self._brief(link["inward"])})
            elif link["inward"] == key and link["outward"] in self.issues:
                out.append({"id": link["id"], "type": kind, "inwardIssue": self._brief(link["outward"])})
        return out

    def _get_issue(self, key: str, query: Mapping[str, Any], body: Any) -> Dict[str, Any]:
        names = [name.strip() for name in str(query.get("fields") or "").split(",") if name.strip()] or None
        return self._render(self._issue(key), names, str(query.get("expand") or ""))

    def _page(self, rows: List[Dict[str, Any]], token: Any, size: Any, names: Optional[Sequence[str]],
              expand: str = "") -> Dict[str, Any]:
        start = int(token) if str(token or "").isdigit() else 0
        size = max(1, min(int(size or 50), 100))
        chunk = rows[start:start + size]
        last = start + size >= len(rows)
        page: Dict[str, Any] = {"issues": [self._render(issue, names, expand) for issue in chunk], "isLast": last}
        if not last:
            page["nextPageToken"] = str(start + size)
        return page

    def _search(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        return self._page(self._match(str(body.get("jql") or "")), body.get("nextPageToken"),
                          body.get("maxResults"), body.get("fields") or ["id"], str(body.get("expand") or ""))

    def _listing(self, rows: List[Dict[str, Any]], query: Mapping[str, Any]) -> Dict[str, Any]:
        names = [name.strip() for name in str(query.get("fields") or "").split(",") if name.strip()] or None
        if query.get("jql"):
            keys = {issue["key"] for issue in self._match(str(query["jql"]))}
            rows = [issue for issue in rows if issue["key"] in keys]
        return self._page(rows, query.get("nextPageToken"), query.get("maxResults"), names)

    # ── JQL: exactly the grammar jql.py emits ───────────────────────────────
    def _match(self, text: str) -> List[Dict[str, Any]]:
        query, _, ordering = re.sub(r"\s+", " ", text.strip()).partition(" ORDER BY ")
        if query.upper().startswith("ORDER BY") or not query:
            raise _Refused(400, "Unbounded JQL queries are not allowed here. Please add a search restriction to your query.")
        tests = [self._clause(part) for part in _split(query, " AND ")]
        rows = [issue for issue in self.issues.values() if all(test(issue) for test in tests)]
        for part in reversed([item.strip() for item in ordering.split(",") if item.strip()]):
            name, _, direction = part.partition(" ")
            rows.sort(key=lambda issue: self._sort_key(issue, name.lower()), reverse=direction.strip().upper() == "DESC")
        return rows

    def _sort_key(self, issue: Mapping[str, Any], name: str) -> Any:
        fields = issue["fields"]
        if name == "priority":
            return -_PRIORITIES.index(fields["priority"]["name"])      # DESC puts Highest first
        if name in ("updated", "created"):
            return fields[name]
        if name == "resolved":
            return fields.get("resolutiondate") or ""
        if name == "duedate":
            return fields.get("duedate") or "9999-12-31"
        if name == "rank":
            return issue["_rank"]
        if name == "status":
            return fields["status"]["name"]
        if name == "assignee":
            return (fields.get("assignee") or {}).get("displayName") or ""
        return (issue["key"].split("-")[0], int(issue["key"].split("-")[1]))

    def _clause(self, clause: str) -> Callable[[Mapping[str, Any]], bool]:
        clause = clause.strip()
        if clause.startswith("(") and clause.endswith(")"):
            options = [self._clause(part) for part in _split(clause[1:-1], " OR ")]
            return lambda issue: any(option(issue) for option in options)
        match = re.fullmatch(r"(\w+) (is not|is|not in|in|!=|>=|<=|=|<|>|~) (.+)", clause, re.IGNORECASE)
        if not match:
            raise _Refused(400, f"The sandbox understands the Desk's own filters only, not: {clause}")
        name, operator, raw = match.group(1).lower(), match.group(2).lower(), match.group(3).strip()
        values = [_unquote(part) for part in _split(raw[1:-1], ",")] if raw.startswith("(") else [_unquote(raw)]
        now = self.now()

        def people(value: str) -> str:
            return "sbx-me" if value.lower() == "currentuser()" else value

        def get(issue: Mapping[str, Any]) -> List[str]:
            fields = issue["fields"]
            if name == "project":
                return [fields["project"]["key"]]
            if name in ("assignee", "reporter"):
                return [(fields.get(name) or {}).get("accountId") or ""]
            if name == "watcher":
                return list(self.watchers.get(issue["key"], []))
            if name == "status":
                return [fields["status"]["name"]]
            if name == "statuscategory":
                return [fields["status"]["statusCategory"]["name"]]
            if name == "issuetype":
                return [fields["issuetype"]["name"]]
            if name == "priority":
                return [fields["priority"]["name"]]
            if name == "labels":
                return list(fields["labels"])
            if name == "component":
                return [row["name"] for row in fields["components"]]
            if name == "fixversion":
                return [row["name"] for row in fields["fixVersions"]]
            if name == "parent":
                return [(fields.get("parent") or {}).get("key") or ""]
            if name == "key":
                return [issue["key"]]
            if name == "flagged":
                return ["flagged"] if fields.get(F_FLAGGED) else []
            raise _Refused(400, f"Field '{name}' does not exist or you do not have permission to view it.")

        if name in ("updated", "created", "resolved", "duedate"):
            field_name = {"resolved": "resolutiondate"}.get(name, name)
            if raw.lower() == "startofday()":
                bound = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif raw.lower() == "now()":
                bound = now
            else:
                offset = re.fullmatch(r"(-?\d+)d", raw)
                if not offset:
                    raise _Refused(400, f"The sandbox cannot read the date {raw!r}.")
                bound = now + dt.timedelta(days=int(offset.group(1)))
                if name == "duedate":
                    bound = bound.replace(hour=23, minute=59, second=59)

            def dated(issue: Mapping[str, Any]) -> bool:
                value = issue["fields"].get(field_name)
                if not value:
                    return False
                text = value if "T" in value else f"{value}T00:00:00.000+0000"
                when = dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.000%z")
                return {"<": when < bound, "<=": when <= bound, ">": when > bound, ">=": when >= bound}[operator]
            return dated
        if name == "sprint":
            if raw.lower().endswith("sprints()"):
                state = {"open": "active", "future": "future", "closed": "closed"}[raw.lower()[:-len("sprints()")]]
                chosen = {sprint_id for sprint_id, sprint in self.sprints.items() if sprint["state"] == state}
            else:
                chosen = {int(value) for value in values if value.isdigit()}
            return lambda issue: bool(chosen & set(issue["fields"].get(F_SPRINT) or []))
        if name == "text":
            needle = values[0].lower()

            def texted(issue: Mapping[str, Any]) -> bool:
                fields = issue["fields"]
                comments = fields["comment"]["comments"]
                if needle == "currentuser()":
                    return any("sbx-me" in adf.mentioned_account_ids(row["body"]) for row in comments)
                blob = " ".join([fields["summary"], adf.to_text(fields.get("description")),
                                 *(adf.to_text(row["body"]) for row in comments)]).lower()
                return needle in blob
            return texted
        if name == "approvals":
            return lambda issue: (self.approvals.get(issue["key"]) or {}).get("finalDecision") == "pending"
        wanted = {people(value).lower() for value in values}
        if operator in ("is", "is not"):
            empty = operator == "is"
            return lambda issue: (not any(get(issue))) == empty
        if operator in ("=", "in"):
            return lambda issue: bool(wanted & {value.lower() for value in get(issue)})
        if operator in ("!=", "not in"):
            return lambda issue: not (wanted & {value.lower() for value in get(issue)})
        raise _Refused(400, f"The operator '{operator}' is not supported by the '{name}' field.")

    # ── writing ─────────────────────────────────────────────────────────────
    def _record(self, issue: Dict[str, Any], op: str, changes: Sequence[Tuple[str, Any, Any]] = (),
                detail: Optional[str] = None) -> None:
        issue["fields"]["updated"] = self._stamp()
        if changes:
            issue["_history"].append({"id": self._id(), "author": self.me, "created": self._stamp(),
                                      "items": [{"field": name, "fromString": _plain(old), "toString": _plain(new)}
                                                for name, old, new in changes]})
        self.log.append({"at": self._stamp(), "op": op, "issue": issue["key"],
                         "detail": detail or "; ".join(f"{name}: {_plain(old)} -> {_plain(new)}"
                                                       for name, old, new in changes)})

    def _apply_fields(self, issue: Dict[str, Any], incoming: Mapping[str, Any]) -> List[Tuple[str, Any, Any]]:
        fields = issue["fields"]
        project = fields["project"]["key"]
        changes: List[Tuple[str, Any, Any]] = []
        for name, value in incoming.items():
            if name in ("project", "issuetype"):
                continue
            old = fields.get(name)
            if name == "summary":
                if not str(value or "").strip():
                    raise _Refused(400, "", {"summary": "You must specify a summary of the issue."})
                new: Any = str(value)
            elif name == "priority":
                if value and value.get("name") not in _PRIORITIES:
                    raise _Refused(400, "", {"priority": "The priority selected is invalid."})
                new = {"id": str(_PRIORITIES.index(value["name"]) + 1), "name": value["name"]} if value else old
            elif name == "assignee":
                account_id = (value or {}).get("accountId")
                if account_id and account_id not in self.users:
                    raise _Refused(400, "", {"assignee": f"User '{account_id}' cannot be assigned issues."})
                new = self.users.get(account_id) if account_id else None
            elif name == "labels":
                new = [str(label) for label in (value or [])]
            elif name in ("components", "fixVersions"):
                new = [{"name": row.get("name")} for row in (value or [])]
                if name == "fixVersions":
                    for row in new:
                        row["id"] = self._version_id(project, row["name"])
                        if row["id"] is None:
                            raise _Refused(400, "", {"fixVersions": f"Version name '{row['name']}' is not valid"})
            elif name == "parent":
                parent_key = str((value or {}).get("key") or "").upper()
                if parent_key and parent_key not in self.issues:
                    raise _Refused(400, "", {"parent": "Could not find issue by id or key."})
                new = {"key": parent_key} if parent_key else None
            elif name in ("description", "environment", "duedate", F_POINTS, F_START, F_FLAGGED):
                new = value
            elif name == F_SPRINT:
                new = [int(value)] if value else None
            else:
                raise _Refused(400, "", {name: f"Field '{name}' cannot be set. It is not on the appropriate "
                                               "screen, or unknown."})
            fields[name] = new
            changes.append((name, old, new))
        return changes

    def _create_issue(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        incoming = dict(body.get("fields") or {})
        project = str((incoming.get("project") or {}).get("key") or "").upper()
        self._project(project)
        kind = incoming.get("issuetype") or {}
        name = next((n for i, n, _, _ in _TYPES if i == str(kind.get("id")) or n.lower() == str(kind.get("name") or "").lower()), None)
        if name is None:
            raise _Refused(400, "", {"issuetype": "Specify a valid issue type"})
        if not str(incoming.get("summary") or "").strip():
            raise _Refused(400, "", {"summary": "You must specify a summary of the issue."})
        issue = self.add_issue(project, str(incoming["summary"]), kind=name, created=0)
        self._apply_fields(issue, {k: v for k, v in incoming.items() if k != "summary"})
        self._record(issue, "issue.create", detail=f"{name}: {issue['fields']['summary']}")
        return {"id": issue["id"], "key": issue["key"], "self": issue["self"]}

    def _edit_issue(self, key: str, query: Mapping[str, Any], body: Any) -> None:
        issue = self._issue(key)
        body = body or {}
        changes = self._apply_fields(issue, body.get("fields") or {})
        for name, operations in (body.get("update") or {}).items():
            if name != "labels":
                raise _Refused(400, "", {name: "The sandbox applies update operations to labels only."})
            old = list(issue["fields"]["labels"])
            new = list(old)
            for operation in operations:
                if "add" in operation and operation["add"] not in new:
                    new.append(operation["add"])
                if "remove" in operation and operation["remove"] in new:
                    new.remove(operation["remove"])
            issue["fields"]["labels"] = new
            changes.append(("labels", old, new))
        self._record(issue, "issue.edit", changes)

    def _transitions(self, key: str) -> List[Dict[str, Any]]:
        current = self._issue(key)["fields"]["status"]["name"]
        return [{"id": transition_id, "name": name, "to": _status(to), "hasScreen": to == "Done",
                 "fields": {"resolution": {"name": "Resolution", "required": False,
                                           "allowedValues": [{"name": value} for value in _RESOLUTIONS]}}
                 if to == "Done" else {}}
                for transition_id, name, to in _TRANSITIONS if to != current]

    def _transition(self, key: str, query: Mapping[str, Any], body: Any) -> None:
        issue = self._issue(key)
        wanted = str(((body or {}).get("transition") or {}).get("id") or "")
        chosen = next((row for row in self._transitions(key) if row["id"] == wanted), None)
        if chosen is None:
            raise _Refused(400, "Transition id is not valid for this issue's current status.")
        fields = issue["fields"]
        old = fields["status"]["name"]
        fields["status"] = _status(chosen["to"]["name"])
        done = chosen["to"]["name"] == "Done"
        resolution = ((body or {}).get("fields") or {}).get("resolution") or {}
        fields["resolution"] = {"name": resolution.get("name") or "Done"} if done else None
        fields["resolutiondate"] = self._stamp() if done else None
        for operation in ((body or {}).get("update") or {}).get("comment") or []:
            if "add" in operation:
                self._add_comment(key, {}, operation["add"], quiet=True)
        self._record(issue, "issue.transition", [("status", old, chosen["to"]["name"])])

    def _assign(self, key: str, query: Mapping[str, Any], body: Any) -> None:
        issue = self._issue(key)
        changes = self._apply_fields(issue, {"assignee": {"accountId": (body or {}).get("accountId")}})
        self._record(issue, "issue.assign", changes)

    def _comments(self, key: str, query: Mapping[str, Any], body: Any) -> Dict[str, Any]:
        rows = list(self._issue(key)["fields"]["comment"]["comments"])
        if str(query.get("orderBy") or "").startswith("-"):
            rows.reverse()
        start = int(query.get("startAt") or 0)
        size = int(query.get("maxResults") or 50)
        return {"comments": rows[start:start + size], "startAt": start, "maxResults": size, "total": len(rows)}

    def _add_comment(self, key: str, query: Mapping[str, Any], body: Any, quiet: bool = False) -> Dict[str, Any]:
        issue = self._issue(key)
        document = (body or {}).get("body")
        if not isinstance(document, Mapping) or document.get("type") != "doc" or adf.is_empty(document):
            raise _Refused(400, "", {"comment": "Comment body can not be empty!"})
        block = issue["fields"]["comment"]
        row = {"id": self._id(), "author": self.me, "body": dict(document), "created": self._stamp(),
               "updated": self._stamp()}
        for item in (body or {}).get("properties") or []:
            if item.get("key") == "sd.public.comment":
                row["jsdPublic"] = not (item.get("value") or {}).get("internal")
        block["comments"].append(row)
        block["total"] = len(block["comments"])
        if not quiet:
            self._record(issue, "comment.add", detail=adf.excerpt(document, 120))
        return row

    def _add_worklog(self, key: str, query: Mapping[str, Any], body: Any) -> Dict[str, Any]:
        issue = self._issue(key)
        seconds = int((body or {}).get("timeSpentSeconds") or 0)
        if seconds <= 0:
            raise _Refused(400, "", {"timeLogged": "You must indicate the time spent working."})
        block = issue["fields"]["worklog"]
        row = {"id": self._id(), "author": self.me, "timeSpentSeconds": seconds,
               "started": (body or {}).get("started") or self._stamp(), "comment": (body or {}).get("comment")}
        block["worklogs"].append(row)
        block["total"] = len(block["worklogs"])
        tracking = issue["fields"]["timetracking"]
        tracking["timeSpentSeconds"] = int(tracking.get("timeSpentSeconds") or 0) + seconds
        self._record(issue, "worklog.add", detail=f"{seconds // 60} minutes")
        return row

    def _watch(self, key: str, account_id: Any, watching: bool) -> None:
        issue = self._issue(key)
        account_id = str(account_id or "sbx-me")
        current = self.watchers.setdefault(issue["key"], [])
        if watching and account_id not in current:
            current.append(account_id)
        if not watching and account_id in current:
            current.remove(account_id)
        self.log.append({"at": self._stamp(), "op": "issue.watch" if watching else "issue.unwatch",
                         "issue": issue["key"], "detail": account_id})

    def _create_link(self, body: Mapping[str, Any]) -> None:
        name = str((body.get("type") or {}).get("name") or "")
        if name not in [row[1] for row in _LINK_TYPES]:
            raise _Refused(404, f"No issue link type with name '{name}' found.")
        inward = self._issue((body.get("inwardIssue") or {}).get("key") or "")
        outward = self._issue((body.get("outwardIssue") or {}).get("key") or "")
        self.link(name, outward=outward["key"], inward=inward["key"])
        self._record(outward, "issue.link", detail=f"{outward['key']} {name} {inward['key']}")

    # ── projects, versions ──────────────────────────────────────────────────
    def _project_search(self, query: Mapping[str, Any], body: Any) -> Dict[str, Any]:
        text = str(query.get("query") or "").lower()
        rows = [row for row in self.projects.values() if text in row["name"].lower() or text in row["key"].lower()]
        return {"values": rows, "startAt": 0, "maxResults": 50, "total": len(rows), "isLast": True}

    def _project_versions(self, project: str, query: Mapping[str, Any], body: Any) -> Dict[str, Any]:
        self._project(project)
        rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in self.versions.values()
                if row["_project"] == project.upper()]
        return {"values": rows, "startAt": 0, "maxResults": 50, "total": len(rows), "isLast": True}

    def _version(self, version_id: str) -> Dict[str, Any]:
        version = self.versions.get(str(version_id))
        if version is None:
            raise _Refused(404, "Could not find version for id.")
        return {key: value for key, value in version.items() if not key.startswith("_")}

    def _version_counts(self, version_id: str) -> Dict[str, Any]:
        self._version(version_id)
        rows = [issue for issue in self.issues.values()
                if any(row.get("id") == str(version_id) for row in issue["fields"]["fixVersions"])]
        open_rows = [issue for issue in rows if issue["fields"]["status"]["statusCategory"]["key"] != "done"]
        return {"issuesFixedCount": len(rows), "issuesAffectedCount": 0, "issuesCount": len(rows),
                "issuesUnresolvedCount": len(open_rows)}

    def _create_version(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        project = next((key for key, row in self.projects.items() if int(row["id"]) == int(body.get("projectId") or 0)), None)
        if project is None or not str(body.get("name") or "").strip():
            raise _Refused(400, "", {"name": "You must specify a valid version name and project."})
        version = self.add_version(project, str(body["name"]))
        version.update({key: body.get(key) for key in ("description", "startDate", "releaseDate")})
        self.log.append({"at": self._stamp(), "op": "version.create", "issue": None, "detail": f"{project} {body['name']}"})
        return {k: v for k, v in version.items() if not k.startswith("_")}

    def _update_version(self, version_id: str, body: Mapping[str, Any]) -> Dict[str, Any]:
        version = self.versions.get(str(version_id))
        if version is None:
            raise _Refused(404, "Could not find version for id.")
        version.update({key: value for key, value in body.items() if key in ("released", "releaseDate", "name", "description")})
        self.log.append({"at": self._stamp(), "op": "version.update", "issue": None,
                         "detail": f"{version['name']}: {dict(body)}"})
        return {k: v for k, v in version.items() if not k.startswith("_")}

    # ── boards and sprints ──────────────────────────────────────────────────
    def _boards(self, query: Mapping[str, Any], body: Any) -> Dict[str, Any]:
        project, kind = str(query.get("projectKeyOrId") or "").upper(), str(query.get("type") or "")
        rows = [board for board in self.boards.values()
                if (not project or board["location"]["projectKey"] == project) and (not kind or board["type"] == kind)]
        return {"values": rows, "startAt": 0, "maxResults": 50, "total": len(rows), "isLast": True}

    def _board_config(self, board_id: str) -> Dict[str, Any]:
        self._board(board_id)
        return {"id": int(board_id), "columnConfig": {"columns": [
            {"name": "To Do", "statuses": [{"id": "10000"}]},
            {"name": "In Progress", "statuses": [{"id": "10001"}, {"id": "10003"}]},
            {"name": "In Review", "statuses": [{"id": "10002"}]},
            {"name": "Done", "statuses": [{"id": "10004"}]}]},
            "estimation": {"type": "field", "field": {"fieldId": F_POINTS, "displayName": "Story point estimate"}}}

    def _board_issues(self, board_id: Any) -> List[Dict[str, Any]]:
        project = self._board(board_id)["location"]["projectKey"]
        return sorted((issue for issue in self.issues.values() if issue["fields"]["project"]["key"] == project),
                      key=lambda issue: issue["_rank"])

    def _backlog(self, board_id: Any) -> List[Dict[str, Any]]:
        live = {sprint_id for sprint_id, sprint in self.sprints.items() if sprint["state"] in ("active", "future")}
        return [issue for issue in self._board_issues(board_id)
                if issue["fields"]["status"]["statusCategory"]["key"] != "done"
                and issue["fields"]["issuetype"]["name"] != "Epic"
                and not (live & set(issue["fields"].get(F_SPRINT) or []))]

    def _board_sprints(self, board_id: str, query: Mapping[str, Any], body: Any) -> Dict[str, Any]:
        self._board(board_id)
        states = {state.strip() for state in str(query.get("state") or "").split(",") if state.strip()}
        rows = [sprint for sprint in self.sprints.values()
                if sprint["originBoardId"] == int(board_id) and (not states or sprint["state"] in states)]
        return {"values": rows, "startAt": 0, "maxResults": 50, "isLast": True}

    def _sprint_issues(self, sprint_id: Any) -> List[Dict[str, Any]]:
        self._sprint(sprint_id)
        return sorted((issue for issue in self.issues.values()
                       if int(sprint_id) in (issue["fields"].get(F_SPRINT) or [])),
                      key=lambda issue: issue["_rank"])

    def _create_sprint(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        self._board(body.get("originBoardId") or 0)
        if not str(body.get("name") or "").strip():
            raise _Refused(400, "", {"name": "The sprint name is required."})
        sprint = self.add_sprint(int(body["originBoardId"]), str(body["name"]), "future", start=0, end=14,
                                 goal=body.get("goal"))
        sprint.update({"startDate": body.get("startDate"), "endDate": body.get("endDate")})
        self.log.append({"at": self._stamp(), "op": "sprint.create", "issue": None, "detail": sprint["name"]})
        return sprint

    def _update_sprint(self, sprint_id: str, body: Mapping[str, Any]) -> Dict[str, Any]:
        sprint = self._sprint(sprint_id)
        state = body.get("state")
        allowed = {("future", "active"), ("active", "closed")}
        if state and state != sprint["state"] and (sprint["state"], state) not in allowed:
            raise _Refused(400, f"A sprint cannot go from {sprint['state']} to {state}.")
        if state == "active" and any(other["state"] == "active" and other["originBoardId"] == sprint["originBoardId"]
                                     and other is not sprint for other in self.sprints.values()):
            raise _Refused(400, "Another sprint is already running on this board.")
        sprint.update({key: value for key, value in body.items() if key in ("state", "startDate", "endDate", "goal", "name")})
        if state == "closed":
            sprint["completeDate"] = self._stamp()
            for issue in self._sprint_issues(sprint_id):
                # What a person sees in Jira: unfinished work leaves the closed sprint.
                if issue["fields"]["status"]["statusCategory"]["key"] != "done":
                    issue["fields"][F_SPRINT] = None
        self.log.append({"at": self._stamp(), "op": "sprint.update", "issue": None,
                         "detail": f"{sprint['name']}: {state or 'edited'}"})
        return sprint

    def _move(self, body: Mapping[str, Any], sprint_id: Optional[int]) -> None:
        if sprint_id is not None and self._sprint(sprint_id)["state"] == "closed":
            raise _Refused(400, "Issues cannot be moved into a closed sprint.")
        for key in body.get("issues") or []:
            issue = self._issue(key)
            old = issue["fields"].get(F_SPRINT)
            issue["fields"][F_SPRINT] = [sprint_id] if sprint_id else None
            name = self.sprints[sprint_id]["name"] if sprint_id else "Backlog"
            self._record(issue, "sprint.move", [("Sprint", old, name)])

    def _rank(self, body: Mapping[str, Any]) -> None:
        anchor = self._issue(body.get("rankBeforeIssue") or body.get("rankAfterIssue") or "")
        ordered = sorted(self.issues.values(), key=lambda issue: issue["_rank"])
        moving = [self._issue(key) for key in body.get("issues") or []]
        rest = [issue for issue in ordered if issue not in moving]
        at = rest.index(anchor) + (0 if body.get("rankBeforeIssue") else 1)
        for position, issue in enumerate(rest[:at] + moving + rest[at:]):
            issue["_rank"] = position
        self.log.append({"at": self._stamp(), "op": "issue.rank", "issue": None,
                         "detail": f"{[issue['key'] for issue in moving]} near {anchor['key']}"})

    # ── service management ──────────────────────────────────────────────────
    def _requests(self, query: Mapping[str, Any], body: Any) -> Dict[str, Any]:
        rows = []
        for key, approval in self.approvals.items():
            if query.get("approvalStatus") == "MY_PENDING_APPROVAL" and approval["finalDecision"] != "pending":
                continue
            fields = self.issues[key]["fields"]
            rows.append({"issueId": self.issues[key]["id"], "issueKey": key,
                         "requestFieldValues": [{"fieldId": "summary", "value": fields["summary"]}],
                         "currentStatus": {"status": fields["status"]["name"]},
                         "reporter": fields["reporter"], "createdDate": {"iso8601": fields["created"]},
                         "serviceDesk": {"id": "1", "projectName": "Help Centre"},
                         "requestType": {"name": "Hardware request"}})
        return {"values": rows, "size": len(rows), "start": 0, "limit": 50, "isLastPage": True}

    def _answer_approval(self, key: str, approval_id: str, query: Mapping[str, Any], body: Any) -> Dict[str, Any]:
        approval = self.approvals.get(key.upper())
        if approval is None or approval["id"] != str(approval_id):
            raise _Refused(404, "The approval could not be found.")
        if approval["finalDecision"] != "pending":
            raise _Refused(400, "This approval has already been answered.")
        decision = str((body or {}).get("decision") or "")
        if decision not in ("approve", "decline"):
            raise _Refused(400, "decision must be approve or decline.")
        approval.update({"finalDecision": "approved" if decision == "approve" else "declined",
                         "canAnswerApproval": False})
        self._record(self._issue(key), "approval.answer", detail=approval["finalDecision"])
        return approval

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"site": self.site_name, "url": self.site_url, "issues": len(self.issues),
                    "requests": self.requests, "log": list(self.log)}


def _plain(value: Any) -> Optional[str]:
    if value is None or value == []:
        return None
    if isinstance(value, Mapping):
        if value.get("type") == "doc":
            return adf.excerpt(value, 80)
        return str(value.get("displayName") or value.get("name") or value.get("key") or value)
    if isinstance(value, list):
        return ", ".join(str(_plain(item)) for item in value)
    return str(value)


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


def _split(text: str, separator: str) -> List[str]:
    """Split on a separator that is outside quotes and outside parentheses."""
    parts: List[str] = []
    depth, quoted, start, index = 0, False, 0, 0
    while index < len(text):
        char = text[index]
        if char == "\\" and quoted:
            index += 2
            continue
        if char == '"':
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        elif not quoted and depth == 0 and text.startswith(separator, index):
            parts.append(text[start:index])
            index += len(separator)
            start = index
            continue
        index += 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


class JiraSites:
    """One synthetic site per sandbox world, made the first time it is asked for."""

    def __init__(self) -> None:
        self._sites: Dict[str, JiraSite] = {}
        self._lock = threading.Lock()

    def for_world(self, world: Any) -> JiraSite:
        with self._lock:
            site = self._sites.get(world.id)
            if site is None:
                site = self._sites[world.id] = JiraSite(
                    owner_email=str(getattr(world, "owner_email", "") or "you@desk.example"), now=world.now)
            return site

    def drop(self, world_id: str) -> None:
        with self._lock:
            self._sites.pop(world_id, None)
