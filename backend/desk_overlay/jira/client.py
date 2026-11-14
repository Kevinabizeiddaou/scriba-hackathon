"""Every Jira Cloud REST call the Desk makes, over an injected transport.

One method per endpoint, each returning Jira's own JSON: ``models.py`` turns
that into what the Desk serves. The paths and the request bodies live here
and nowhere else, so an endpoint Atlassian retires is changed in one place.

Three APIs, one client:

- **platform** (``/rest/api/3``): issues, search, projects, users, filters
- **agile** (``/rest/agile/1.0``): boards and sprints themselves
- **software** (``/rest/software/1.0``): the issues on a board, a backlog or
  a sprint, paged by token
- **servicedesk** (``/rest/servicedeskapi``): requests, approvals, queues

Choices that are deliberate:

- Search is ``POST /search/jql`` only. The older ``/search`` was removed from
  Jira Cloud in 2025. The new one pages by ``nextPageToken`` and returns no
  total; a count is a separate, approximate call.
- The issues of a board, a backlog and a sprint are read from
  ``/rest/software/1.0``. The ``/rest/agile/1.0`` forms of those listings are
  deprecated (removal announced for November 2026); they are tried only when
  the new path answers "not found", so a site on either side of the removal
  works.
- ``GET /priority`` and ``GET /resolution`` are deprecated and not used: the
  values a field allows come from the create, edit and transition metadata.
- People are named by ``accountId`` only. Jira Cloud accepts nothing else.
- A 429 is honoured, not hammered: one wait of at most ``MAX_WAIT_SECONDS``
  when Jira says how long, otherwise the error goes back with ``retryAfter``.
- There is no ``delete_issue``. The Desk does not delete other people's work.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .transport import JiraResponse, NotConnected, Transport, gateway_refused, scope_refused

MAX_WAIT_SECONDS = 4.0
MAX_PAGE = 100
_CODES = {400: "invalid_request", 401: "reconnect_required", 403: "forbidden", 404: "not_found",
          409: "conflict", 413: "too_large", 429: "rate_limited"}


class JiraError(Exception):
    """A Jira call that did not succeed. ``code`` and ``message`` are safe to
    show; the raw upstream body is never passed on."""

    def __init__(self, status: int, code: str, message: str, *, retry_after: Optional[float] = None,
                 fields: Optional[Mapping[str, str]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.fields = dict(fields or {})

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "status": self.status,
                "retryAfter": self.retry_after, "fields": self.fields or None}


def _message(response: JiraResponse) -> str:
    """Jira's structured error, shortened. Never the whole upstream body."""
    body = response.body
    if isinstance(body, Mapping):
        messages = body.get("errorMessages")
        if isinstance(messages, list) and messages:
            return "; ".join(str(item) for item in messages if item)[:300]
        errors = body.get("errors")
        if isinstance(errors, Mapping) and errors:
            return "; ".join(f"{key}: {value}" for key, value in errors.items())[:300]
        if body.get("errorMessage"):                       # the service desk API's shape
            return str(body["errorMessage"])[:300]
        if body.get("message"):
            return str(body["message"])[:300]
    return f"Jira answered {response.status}."


def _retry_after(response: JiraResponse) -> Optional[float]:
    raw = response.header("Retry-After")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


def error_from(response: JiraResponse) -> JiraError:
    status = response.status
    fields = response.body.get("errors") if isinstance(response.body, Mapping) else None
    if scope_refused(response):
        return JiraError(status, "scope_missing",
                         "This Jira connection was not granted the permission this needs. Add the "
                         "scope to the Atlassian app, then reconnect Jira.")
    if gateway_refused(response):
        return JiraError(status, "reconnect_required",
                         "The Desk can't reach your Jira site anymore. Reconnect Jira.")
    if status >= 500:
        return JiraError(status, "jira_unavailable", "Jira did not answer. Try again in a moment.",
                         retry_after=_retry_after(response))
    return JiraError(status, _CODES.get(status, "jira_error"), _message(response),
                     retry_after=_retry_after(response),
                     fields=fields if isinstance(fields, Mapping) else None)


def _page(max_results: Optional[int], default: int = 50) -> int:
    return max(1, min(int(max_results or default), MAX_PAGE))


class JiraClient:
    def __init__(self, transport: Transport, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.transport = transport
        self._sleep = sleep
        self.calls = 0
        # What Jira last said about this app's quota. An OAuth app spends
        # points per request and per object returned, shared across sites.
        self.rate: Dict[str, Any] = {}

    def _note_rate(self, response: JiraResponse) -> None:
        remaining, reset = response.header("X-RateLimit-Remaining"), response.header("X-RateLimit-Reset")
        if remaining is None and reset is None and response.status != 429:
            return
        self.rate = {"remaining": int(remaining) if str(remaining or "").isdigit() else None,
                     "resetAt": reset, "nearLimit": response.header("X-RateLimit-NearLimit") == "true",
                     "reason": response.header("RateLimit-Reason")}

    # ── plumbing ────────────────────────────────────────────────────────────
    def _call(self, method: str, api: str, path: str, *, params: Optional[Mapping[str, Any]] = None,
              json: Any = None, files: Any = None) -> Any:
        for attempt in (1, 2):
            self.calls += 1
            try:
                response = self.transport.request(method, api, path, params=params, json=json, files=files)
            except NotConnected as exc:
                raise JiraError(401, exc.code, str(exc))
            self._note_rate(response)
            if response.ok:
                return response.body
            wait = _retry_after(response)
            # A 429 means the request was not processed, so sending it once
            # more is safe for a write too. Only when Jira names a short wait.
            if response.status == 429 and attempt == 1 and wait is not None and wait <= MAX_WAIT_SECONDS:
                self._sleep(wait)
                continue
            raise error_from(response)
        raise JiraError(429, "rate_limited", "Jira is limiting requests. Try again in a moment.")

    def _get(self, api: str, path: str, **params: Any) -> Any:
        return self._call("GET", api, path, params=params)

    # ── identity and site ───────────────────────────────────────────────────
    def myself(self) -> Dict[str, Any]:
        return self._get("platform", "myself")

    def server_info(self) -> Dict[str, Any]:
        return self._get("platform", "serverInfo")

    def my_permissions(self, permissions: Sequence[str], *, project_key: Optional[str] = None,
                       issue_key: Optional[str] = None) -> Dict[str, Any]:
        return self._get("platform", "mypermissions", permissions=",".join(permissions),
                         projectKey=project_key, issueKey=issue_key)

    # ── projects ────────────────────────────────────────────────────────────
    def search_projects(self, *, query: Optional[str] = None, start_at: int = 0,
                        max_results: int = 50, order_by: str = "name") -> Dict[str, Any]:
        return self._get("platform", "project/search", query=query or None, startAt=start_at,
                         maxResults=_page(max_results), orderBy=order_by, expand="lead")

    def get_project(self, key: str) -> Dict[str, Any]:
        return self._get("platform", f"project/{key}", expand="lead,issueTypes")

    def project_components(self, key: str) -> List[Dict[str, Any]]:
        return self._get("platform", f"project/{key}/components") or []

    def project_versions(self, key: str, *, start_at: int = 0, max_results: int = 50,
                         status: Optional[str] = None) -> Dict[str, Any]:
        return self._get("platform", f"project/{key}/version", startAt=start_at,
                         maxResults=_page(max_results), status=status, orderBy="-releaseDate")

    def project_statuses(self, key: str) -> List[Dict[str, Any]]:
        return self._get("platform", f"project/{key}/statuses") or []

    def version(self, version_id: Any) -> Dict[str, Any]:
        return self._get("platform", f"version/{version_id}")

    def version_issue_counts(self, version_id: Any) -> Dict[str, Any]:
        return self._get("platform", f"version/{version_id}/relatedIssueCounts")

    def version_unresolved_count(self, version_id: Any) -> Dict[str, Any]:
        return self._get("platform", f"version/{version_id}/unresolvedIssueCount")

    # ── search ──────────────────────────────────────────────────────────────
    def search(self, jql: str, *, fields: Sequence[str], max_results: int = 50,
               next_page_token: Optional[str] = None, expand: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"jql": jql, "fields": list(fields), "maxResults": _page(max_results)}
        if next_page_token:
            body["nextPageToken"] = next_page_token
        if expand:
            body["expand"] = expand
        return self._call("POST", "platform", "search/jql", json=body) or {}

    def count(self, jql: str) -> Optional[int]:
        """An approximate count: the search itself no longer returns a total."""
        result = self._call("POST", "platform", "search/approximate-count", json={"jql": jql}) or {}
        return result.get("count") if isinstance(result.get("count"), int) else None

    def parse_jql(self, queries: Sequence[str]) -> Dict[str, Any]:
        return self._call("POST", "platform", "jql/parse", params={"validation": "strict"},
                          json={"queries": list(queries)}) or {}

    # ── one issue ───────────────────────────────────────────────────────────
    def get_issue(self, key: str, *, fields: Optional[Sequence[str]] = None,
                  expand: Optional[str] = None) -> Dict[str, Any]:
        return self._get("platform", f"issue/{key}", fields=",".join(fields) if fields else None,
                         expand=expand)

    def create_issue(self, fields: Mapping[str, Any], *, update: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"fields": dict(fields)}
        if update:
            body["update"] = dict(update)
        return self._call("POST", "platform", "issue", json=body) or {}

    def edit_issue(self, key: str, *, fields: Optional[Mapping[str, Any]] = None,
                   update: Optional[Mapping[str, Any]] = None, notify: bool = True) -> None:
        body: Dict[str, Any] = {}
        if fields:
            body["fields"] = dict(fields)
        if update:
            body["update"] = dict(update)
        self._call("PUT", "platform", f"issue/{key}", params={"notifyUsers": str(notify).lower()}, json=body)

    def create_meta_types(self, project_key: str) -> Dict[str, Any]:
        return self._get("platform", f"issue/createmeta/{project_key}/issuetypes", maxResults=MAX_PAGE)

    def create_meta_fields(self, project_key: str, issue_type_id: Any) -> Dict[str, Any]:
        return self._get("platform", f"issue/createmeta/{project_key}/issuetypes/{issue_type_id}",
                         maxResults=MAX_PAGE)

    def edit_meta(self, key: str) -> Dict[str, Any]:
        return self._get("platform", f"issue/{key}/editmeta")

    def transitions(self, key: str) -> Dict[str, Any]:
        return self._get("platform", f"issue/{key}/transitions", expand="transitions.fields")

    def transition(self, key: str, transition_id: Any, *, fields: Optional[Mapping[str, Any]] = None,
                   update: Optional[Mapping[str, Any]] = None) -> None:
        body: Dict[str, Any] = {"transition": {"id": str(transition_id)}}
        if fields:
            body["fields"] = dict(fields)
        if update:
            body["update"] = dict(update)
        self._call("POST", "platform", f"issue/{key}/transitions", json=body)

    def assign(self, key: str, account_id: Optional[str]) -> None:
        """``None`` unassigns. ``"-1"`` would mean the project's default assignee."""
        self._call("PUT", "platform", f"issue/{key}/assignee", json={"accountId": account_id})

    def changelog(self, key: str, *, start_at: int = 0, max_results: int = 50) -> Dict[str, Any]:
        return self._get("platform", f"issue/{key}/changelog", startAt=start_at, maxResults=_page(max_results))

    # ── comments ────────────────────────────────────────────────────────────
    def comments(self, key: str, *, start_at: int = 0, max_results: int = 50,
                 newest_first: bool = True) -> Dict[str, Any]:
        return self._get("platform", f"issue/{key}/comment", startAt=start_at, maxResults=_page(max_results),
                         orderBy="-created" if newest_first else "created")

    def add_comment(self, key: str, body: Mapping[str, Any], *,
                    visibility: Optional[Mapping[str, Any]] = None,
                    properties: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"body": dict(body)}
        if visibility:
            payload["visibility"] = dict(visibility)
        if properties:
            payload["properties"] = [dict(item) for item in properties]
        return self._call("POST", "platform", f"issue/{key}/comment", json=payload) or {}

    def update_comment(self, key: str, comment_id: Any, body: Mapping[str, Any]) -> Dict[str, Any]:
        return self._call("PUT", "platform", f"issue/{key}/comment/{comment_id}", json={"body": dict(body)}) or {}

    def delete_comment(self, key: str, comment_id: Any) -> None:
        self._call("DELETE", "platform", f"issue/{key}/comment/{comment_id}")

    # ── worklogs, watchers, votes ───────────────────────────────────────────
    def worklogs(self, key: str, *, start_at: int = 0, max_results: int = 50) -> Dict[str, Any]:
        return self._get("platform", f"issue/{key}/worklog", startAt=start_at, maxResults=_page(max_results))

    def add_worklog(self, key: str, *, seconds: int, started: Optional[str] = None,
                    comment: Optional[Mapping[str, Any]] = None,
                    adjust_estimate: str = "auto") -> Dict[str, Any]:
        body: Dict[str, Any] = {"timeSpentSeconds": int(seconds)}
        if started:
            body["started"] = started
        if comment:
            body["comment"] = dict(comment)
        return self._call("POST", "platform", f"issue/{key}/worklog",
                          params={"adjustEstimate": adjust_estimate}, json=body) or {}

    def watchers(self, key: str) -> Dict[str, Any]:
        return self._get("platform", f"issue/{key}/watchers")

    def add_watcher(self, key: str, account_id: str) -> None:
        # The body of this endpoint is a bare JSON string, not an object.
        self._call("POST", "platform", f"issue/{key}/watchers", json=account_id)

    def remove_watcher(self, key: str, account_id: str) -> None:
        self._call("DELETE", "platform", f"issue/{key}/watchers", params={"accountId": account_id})

    def vote(self, key: str) -> None:
        self._call("POST", "platform", f"issue/{key}/votes")

    def unvote(self, key: str) -> None:
        self._call("DELETE", "platform", f"issue/{key}/votes")

    # ── links and attachments ───────────────────────────────────────────────
    def link_types(self) -> Dict[str, Any]:
        return self._get("platform", "issueLinkType")

    def link_issues(self, *, type_name: str, inward_key: str, outward_key: str,
                    comment: Optional[Mapping[str, Any]] = None) -> None:
        """``outward`` does the thing to ``inward``: for "Blocks", the outward
        issue blocks the inward one."""
        body: Dict[str, Any] = {"type": {"name": type_name}, "inwardIssue": {"key": inward_key},
                                "outwardIssue": {"key": outward_key}}
        if comment:
            body["comment"] = {"body": dict(comment)}
        self._call("POST", "platform", "issueLink", json=body)

    def delete_link(self, link_id: Any) -> None:
        self._call("DELETE", "platform", f"issueLink/{link_id}")

    def remote_links(self, key: str) -> List[Dict[str, Any]]:
        return self._get("platform", f"issue/{key}/remotelink") or []

    def add_remote_link(self, key: str, *, url: str, title: str) -> Dict[str, Any]:
        return self._call("POST", "platform", f"issue/{key}/remotelink",
                          json={"object": {"url": url, "title": title}}) or {}

    def add_attachment(self, key: str, *, filename: str, content: bytes,
                       mime_type: str = "application/octet-stream") -> List[Dict[str, Any]]:
        return self._call("POST", "platform", f"issue/{key}/attachments",
                          files={"file": (filename, content, mime_type)}) or []

    # ── people ──────────────────────────────────────────────────────────────
    def assignable_users(self, *, issue_key: Optional[str] = None, project_key: Optional[str] = None,
                         query: Optional[str] = None, max_results: int = 20) -> List[Dict[str, Any]]:
        return self._get("platform", "user/assignable/search", issueKey=issue_key,
                         project=None if issue_key else project_key, query=query or None,
                         maxResults=_page(max_results, 20)) or []

    def search_users(self, query: str, *, max_results: int = 20) -> List[Dict[str, Any]]:
        return self._get("platform", "user/search", query=query, maxResults=_page(max_results, 20)) or []

    def mentionable_users(self, query: str, *, issue_key: Optional[str] = None,
                          max_results: int = 10) -> List[Dict[str, Any]]:
        """People who can see the issue, which is who a mention can notify."""
        if issue_key:
            return self._get("platform", "user/viewissue/search", issueKey=issue_key, query=query or None,
                             maxResults=_page(max_results, 10)) or []
        return self.search_users(query, max_results=max_results)

    # ── site metadata ───────────────────────────────────────────────────────
    def fields(self) -> List[Dict[str, Any]]:
        return self._get("platform", "field") or []

    def statuses(self) -> List[Dict[str, Any]]:
        return self._get("platform", "status") or []

    def labels(self, *, start_at: int = 0, max_results: int = 100) -> Dict[str, Any]:
        return self._get("platform", "label", startAt=start_at, maxResults=max(1, min(max_results, 1000)))

    # ── saved filters and dashboards ────────────────────────────────────────
    def my_filters(self) -> List[Dict[str, Any]]:
        return self._get("platform", "filter/my", expand="jql", includeFavourites="true") or []

    def favourite_filters(self) -> List[Dict[str, Any]]:
        return self._get("platform", "filter/favourite", expand="jql") or []

    def get_filter(self, filter_id: Any) -> Dict[str, Any]:
        return self._get("platform", f"filter/{filter_id}")

    def dashboards(self, *, scope: str = "favourite", start_at: int = 0, max_results: int = 20) -> Dict[str, Any]:
        return self._get("platform", "dashboard", filter=scope, startAt=start_at, maxResults=_page(max_results, 20))

    # ── versions (releases) ─────────────────────────────────────────────────
    def create_version(self, *, project_id: Any, name: str, description: Optional[str] = None,
                       start_date: Optional[str] = None, release_date: Optional[str] = None) -> Dict[str, Any]:
        body = {"projectId": int(project_id), "name": name, "description": description,
                "startDate": start_date, "releaseDate": release_date}
        return self._call("POST", "platform", "version",
                          json={key: value for key, value in body.items() if value is not None}) or {}

    def update_version(self, version_id: Any, changes: Mapping[str, Any]) -> Dict[str, Any]:
        return self._call("PUT", "platform", f"version/{version_id}", json=dict(changes)) or {}

    # ── boards and sprints (Jira Software) ──────────────────────────────────
    def boards(self, *, project_key: Optional[str] = None, kind: Optional[str] = None,
               name: Optional[str] = None, start_at: int = 0, max_results: int = 50) -> Dict[str, Any]:
        return self._get("agile", "board", projectKeyOrId=project_key, type=kind, name=name,
                         startAt=start_at, maxResults=_page(max_results))

    def board(self, board_id: Any) -> Dict[str, Any]:
        return self._get("agile", f"board/{board_id}")

    def board_configuration(self, board_id: Any) -> Dict[str, Any]:
        return self._get("agile", f"board/{board_id}/configuration")

    def board_sprints(self, board_id: Any, *, state: Optional[str] = "active,future",
                      start_at: int = 0, max_results: int = 50) -> Dict[str, Any]:
        return self._get("agile", f"board/{board_id}/sprint", state=state, startAt=start_at,
                         maxResults=_page(max_results))

    def _listing(self, path: str, *, jql: Optional[str], fields: Sequence[str],
                 next_page_token: Optional[str], max_results: int) -> Dict[str, Any]:
        """The issues of a board, backlog or sprint. Token-paged on the current
        API; the deprecated offset-paged one is tried only on "not found"."""
        try:
            return self._get("software", path, jql=jql, fields=",".join(fields) or None,
                             nextPageToken=next_page_token, maxResults=_page(max_results)) or {}
        except JiraError as exc:
            if exc.status not in (404, 410) or next_page_token:
                raise
        return self._get("agile", path, jql=jql, fields=",".join(fields) or None,
                         maxResults=_page(max_results)) or {}

    def board_issues(self, board_id: Any, *, jql: Optional[str] = None, fields: Sequence[str] = (),
                     next_page_token: Optional[str] = None, max_results: int = 50) -> Dict[str, Any]:
        return self._listing(f"board/{board_id}/issue", jql=jql, fields=fields,
                             next_page_token=next_page_token, max_results=max_results)

    def board_backlog(self, board_id: Any, *, fields: Sequence[str] = (),
                      next_page_token: Optional[str] = None, max_results: int = 50) -> Dict[str, Any]:
        return self._listing(f"board/{board_id}/backlog", jql=None, fields=fields,
                             next_page_token=next_page_token, max_results=max_results)

    def board_epics(self, board_id: Any, *, done: Optional[bool] = False, start_at: int = 0,
                    max_results: int = 50) -> Dict[str, Any]:
        return self._get("agile", f"board/{board_id}/epic", startAt=start_at, maxResults=_page(max_results),
                         done=None if done is None else str(done).lower())

    def sprint(self, sprint_id: Any) -> Dict[str, Any]:
        return self._get("agile", f"sprint/{sprint_id}")

    def sprint_issues(self, sprint_id: Any, *, fields: Sequence[str] = (),
                      next_page_token: Optional[str] = None, max_results: int = 100) -> Dict[str, Any]:
        return self._listing(f"sprint/{sprint_id}/issue", jql=None, fields=fields,
                             next_page_token=next_page_token, max_results=max_results)

    def create_sprint(self, *, board_id: Any, name: str, goal: Optional[str] = None,
                      start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        body = {"originBoardId": int(board_id), "name": name, "goal": goal,
                "startDate": start_date, "endDate": end_date}
        return self._call("POST", "agile", "sprint",
                          json={key: value for key, value in body.items() if value is not None}) or {}

    def update_sprint(self, sprint_id: Any, changes: Mapping[str, Any]) -> Dict[str, Any]:
        """A partial update. ``{"state": "active"}`` starts a sprint and
        ``{"state": "closed"}`` completes it."""
        return self._call("POST", "agile", f"sprint/{sprint_id}", json=dict(changes)) or {}

    def move_to_sprint(self, sprint_id: Any, issue_keys: Sequence[str]) -> None:
        self._call("POST", "agile", f"sprint/{sprint_id}/issue", json={"issues": list(issue_keys)[:50]})

    def move_to_backlog(self, issue_keys: Sequence[str]) -> None:
        self._call("POST", "agile", "backlog/issue", json={"issues": list(issue_keys)[:50]})

    def rank(self, issue_keys: Sequence[str], *, before: Optional[str] = None,
             after: Optional[str] = None) -> None:
        body: Dict[str, Any] = {"issues": list(issue_keys)[:50]}
        if before:
            body["rankBeforeIssue"] = before
        elif after:
            body["rankAfterIssue"] = after
        self._call("PUT", "agile", "issue/rank", json=body)

    # ── Jira Service Management ─────────────────────────────────────────────
    def service_desks(self) -> Dict[str, Any]:
        return self._get("servicedesk", "servicedesk", limit=50)

    def my_requests(self, *, ownership: Optional[str] = None, approval: Optional[str] = None,
                    status: Optional[str] = None, start: int = 0, limit: int = 50) -> Dict[str, Any]:
        """``ownership="APPROVER", approval="MY_PENDING_APPROVAL"``: the
        requests waiting on this person's decision."""
        return self._get("servicedesk", "request", requestOwnership=ownership, approvalStatus=approval,
                         requestStatus=status, start=start, limit=_page(limit),
                         expand="requestType,serviceDesk,status")

    def request_approvals(self, request_key: str) -> Dict[str, Any]:
        return self._get("servicedesk", f"request/{request_key}/approval")

    def answer_approval(self, request_key: str, approval_id: Any, decision: str) -> Dict[str, Any]:
        return self._call("POST", "servicedesk", f"request/{request_key}/approval/{approval_id}",
                          json={"decision": decision}) or {}

    def request_sla(self, request_key: str) -> Dict[str, Any]:
        return self._get("servicedesk", f"request/{request_key}/sla")

    def queues(self, service_desk_id: Any) -> Dict[str, Any]:
        return self._get("servicedesk", f"servicedesk/{service_desk_id}/queue", includeCount="true")

    # ── webhooks registered by this OAuth app ───────────────────────────────
    def webhooks(self) -> Dict[str, Any]:
        return self._get("platform", "webhook")

    def register_webhooks(self, url: str, webhooks: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        return self._call("POST", "platform", "webhook",
                          json={"url": url, "webhooks": [dict(item) for item in webhooks]}) or {}

    def refresh_webhooks(self, webhook_ids: Sequence[int]) -> Dict[str, Any]:
        """A dynamic webhook expires after 30 days unless refreshed."""
        return self._call("PUT", "platform", "webhook/refresh", json={"webhookIds": list(webhook_ids)}) or {}

    def delete_webhooks(self, webhook_ids: Sequence[int]) -> None:
        self._call("DELETE", "platform", "webhook", json={"webhookIds": list(webhook_ids)})
