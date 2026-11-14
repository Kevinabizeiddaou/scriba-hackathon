"""The operations behind ``/desk/jira/*``.

Every operation starts the same way: decide WHICH Jira this person is
talking to. If a sandbox world is in force for them it is that world's
synthetic site, and nothing below can reach a real one. Otherwise it is the
site they connected through Scriba, with the token Scriba refreshes.

Reads return the shapes of ``models.py``. Writes are never made here: they
are handed to ``proposals.py``.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from . import JIRA_SKELETON_VERSION, actions, features, insights, jql, models, policy
from .client import JiraClient, JiraError
from .proposals import ProposalDesk
from .sandbox import JiraSites
from .transport import GatewayTransport

FIELD_MAP_TTL = 600
BRIEFING_ROWS = 100


class NotReady(Exception):
    """Jira cannot be used right now. ``code`` says why; it is safe to show."""

    MESSAGES = {
        "not_configured": "Jira is not set up on this server yet.",
        "not_connected": "Jira is not connected. Connect it to continue.",
        "reconnect_required": "Jira needs to be reconnected.",
    }

    def __init__(self, code: str) -> None:
        super().__init__(self.MESSAGES.get(code, code))
        self.code = code
        self.message = self.MESSAGES.get(code, code)


@dataclass
class Session:
    client: JiraClient
    simulated: bool
    site_url: Optional[str]
    site_name: Optional[str]
    scopes: List[str]
    me: Optional[str]
    field_map: models.FieldMap = field(default_factory=models.FieldMap)
    site: Any = None                         # the synthetic site, in a sandbox

    def context(self) -> actions.Context:
        return actions.Context(client=self.client, field_map=self.field_map, me=self.me,
                               site_url=self.site_url)

    def allows(self, group: str) -> bool:
        return self.simulated or policy.allows(self.scopes, group)

    def fields(self, *extra: str, detail: bool = False) -> List[str]:
        base = models.DETAIL_FIELDS if detail else models.LIST_FIELDS
        return list(dict.fromkeys([*base, *self.field_map.ids(), *extra]))


class JiraService:
    def __init__(self, gateway: Any, *, env: Mapping[str, str],
                 clock: Optional[Callable[[], dt.datetime]] = None, sites: Optional[JiraSites] = None,
                 proposals: Optional[ProposalDesk] = None) -> None:
        self.gateway = gateway
        self.env = env
        self._clock = clock
        self.sites = sites or JiraSites()
        self.proposals = proposals or ProposalDesk(clock=clock, audit=self._audit)
        self._field_maps: Dict[str, Any] = {}
        self._lock = threading.Lock()

    # ── which Jira ──────────────────────────────────────────────────────────
    def now(self, user: Any = None) -> dt.datetime:
        world = self._world(user)
        if world is not None:
            return world.now()
        return self._clock() if self._clock else dt.datetime.now(dt.timezone.utc)

    def _world(self, user: Any) -> Any:
        finder = getattr(self.gateway, "world_for", None)
        return finder(user) if callable(finder) and user is not None else None

    def _audit(self, user: Any, row: Dict[str, Any], event: Dict[str, Any]) -> None:
        if row.get("simulated") or event["kind"] == "proposed":
            return
        audit = getattr(self.gateway, "audit", None)
        if callable(audit):
            audit(user, f"desk_jira_{event['kind']}", ",".join(row.get("targets") or []) or row["id"],
                  {"proposal": row["id"], "action": row["action"], "summary": row["summary"]})

    def session(self, user: Any) -> Session:
        world = self._world(user)
        if world is not None:
            site = self.sites.for_world(world)
            client = JiraClient(site, sleep=lambda seconds: None)
            return Session(client=client, simulated=True, site_url=site.site_url, site_name=site.site_name,
                           scopes=policy.recommended_scopes(servicedesk=True, admin=True, webhooks=True),
                           me=site.me["accountId"], field_map=self._field_map(f"sandbox:{world.id}", client),
                           site=site)
        connection = self.gateway.jira_connection(user)
        if not connection.get("configured"):
            raise NotReady("not_configured")
        if not connection.get("hasAccount"):
            raise NotReady("not_connected")
        if not connection.get("connected") or not connection.get("cloudId"):
            raise NotReady("reconnect_required")
        transport = GatewayTransport(cloud_id=str(connection["cloudId"]),
                                     token=lambda: self.gateway.jira_token(user),
                                     send=self.gateway.jira_send())
        client = JiraClient(transport)
        scopes = policy.normalize_scopes(connection.get("scopes"))
        return Session(client=client, simulated=False, site_url=connection.get("siteUrl"),
                       site_name=connection.get("siteName"), scopes=scopes, me=connection.get("accountId"),
                       field_map=self._field_map(f"{user.id}:{connection['cloudId']}", client))

    def _field_map(self, key: str, client: JiraClient) -> models.FieldMap:
        with self._lock:
            cached = self._field_maps.get(key)
        if cached and time.monotonic() - cached[0] < FIELD_MAP_TTL:
            return cached[1]
        try:
            found = models.FieldMap.from_fields(client.fields())
        except JiraError:
            return cached[1] if cached else models.FieldMap()     # degrade: no sprint or points columns
        with self._lock:
            self._field_maps[key] = (time.monotonic(), found)
        return found

    def _view(self, session: Session, user: Any, raw: Any, *, detail: bool = False) -> Dict[str, Any]:
        return models.issue_view(raw, site_url=session.site_url, field_map=session.field_map,
                                 now=self.now(user), me=session.me, detail=detail)

    def _rows(self, session: Session, user: Any, page: Mapping[str, Any]) -> List[Dict[str, Any]]:
        return [self._view(session, user, raw) for raw in (page.get("issues") or [])]

    def _need(self, session: Session, group: str) -> None:
        if not session.allows(group):
            missing = policy.GROUP_BY_ID[group].missing(session.scopes)
            raise JiraError(403, "scope_missing",
                            f"This Jira connection was not granted: {', '.join(missing)}. "
                            "Add the scope to the Atlassian app, then reconnect Jira.")

    # ── status ──────────────────────────────────────────────────────────────
    def status(self, user: Any) -> Dict[str, Any]:
        """Where Jira stands for this person. Never raises: this is the
        screen that explains what is missing."""
        world = self._world(user)
        base: Dict[str, Any] = {
            "enabled": True, "version": JIRA_SKELETON_VERSION, "loginPath": policy.LOGIN_PATH,
            "disconnectPath": policy.DISCONNECT_PATH, "views": jql.describe_views(),
            "defaultView": jql.DEFAULT_VIEW,
        }
        listing = self.proposals.list(user, limit=0)
        base["proposals"] = {"waiting": listing["waiting"], **listing["store"]}
        if world is not None:
            site = self.sites.for_world(world)
            return {**base, "mode": "sandbox", "state": "connected", "configured": True, "connected": True,
                    "site": {"name": site.site_name, "url": site.site_url},
                    "account": {"accountId": site.me["accountId"], "displayName": site.me["displayName"]},
                    "scopes": policy.scope_report(policy.recommended_scopes(servicedesk=True, admin=True, webhooks=True)),
                    "writes": policy.writes(self.env, sandbox=True), "setup": None, "reason": None}
        try:
            connection = self.gateway.jira_connection(user)
        except Exception:
            connection = {"configured": False, "missingEnv": [], "error": True}
        state = ("not_configured" if not connection.get("configured")
                 else "not_connected" if not connection.get("hasAccount")
                 else "connected" if connection.get("connected") and connection.get("cloudId")
                 else "reconnect_required")
        return {
            **base, "mode": "live", "state": state, "configured": bool(connection.get("configured")),
            "connected": state == "connected",
            "reason": None if state == "connected" else NotReady.MESSAGES[state],
            "site": {"name": connection.get("siteName"), "url": connection.get("siteUrl")}
            if connection.get("hasAccount") else None,
            "account": {"accountId": connection.get("accountId"), "displayName": connection.get("displayName")}
            if connection.get("hasAccount") else None,
            "scopes": policy.scope_report(connection.get("scopes")) if connection.get("hasAccount") else [],
            "writes": policy.writes(self.env, sandbox=False),
            "setup": policy.setup(public_api_base=connection.get("publicApiBase"),
                                  configured=bool(connection.get("configured")),
                                  missing_env=connection.get("missingEnv") or [],
                                  redirect_uri=connection.get("redirectUri"),
                                  requested_scopes=connection.get("requestedScopes") or []),
        }

    def feature_list(self, user: Any) -> Dict[str, Any]:
        try:
            session: Optional[Session] = self.session(user)
        except (NotReady, JiraError):
            session = None
        rows = features.catalogue(session.scopes if session else [], simulated=bool(session and session.simulated))
        return {"features": rows, "summary": features.summary(rows), "connected": session is not None,
                "actions": [action.describe() for action in actions.ACTIONS]}

    # ── projects ────────────────────────────────────────────────────────────
    def projects(self, user: Any, *, query: Optional[str], start_at: int, limit: int) -> Dict[str, Any]:
        session = self.session(user)
        page = session.client.search_projects(query=query, start_at=start_at, max_results=limit)
        rows = [models.project_view(raw, site_url=session.site_url) for raw in (page.get("values") or [])]
        return {"projects": rows, "page": models.page_of(rows, start_at=start_at, total=page.get("total"),
                                                         is_last=page.get("isLast"))}

    def project(self, user: Any, key: str) -> Dict[str, Any]:
        session = self.session(user)
        key = jql.project_key(key)
        raw = session.client.get_project(key)
        types = session.client.create_meta_types(key).get("issueTypes") or []
        return {"project": models.project_view(raw, site_url=session.site_url),
                "issueTypes": [models.type_view(kind) for kind in types],
                "components": [{"id": row.get("id"), "name": row.get("name")}
                               for row in session.client.project_components(key)]}

    def create_fields(self, user: Any, key: str, issue_type: str) -> Dict[str, Any]:
        """What the create form for one issue type asks for."""
        session = self.session(user)
        key = jql.project_key(key)
        types = session.client.create_meta_types(key).get("issueTypes") or []
        wanted = issue_type.strip().lower()
        kind = next((row for row in types if str(row.get("id")) == issue_type.strip()
                     or str(row.get("name") or "").lower() == wanted), None)
        if kind is None:
            raise JiraError(404, "not_found", f"{key} has no issue type {issue_type!r}.")
        rows = session.client.create_meta_fields(key, kind.get("id")).get("fields") or []
        return {"project": key, "issueType": models.type_view(kind), "fields": [
            {"id": row.get("fieldId") or row.get("key"), "name": row.get("name"),
             "required": bool(row.get("required")), "hasDefault": bool(row.get("hasDefaultValue")),
             "allowedValues": [str(value.get("name") or value.get("value"))
                               for value in (row.get("allowedValues") or [])
                               if isinstance(value, Mapping) and (value.get("name") or value.get("value"))][:100]}
            for row in rows]}

    def releases(self, user: Any, key: str, *, limit: int = 12) -> Dict[str, Any]:
        session = self.session(user)
        key = jql.project_key(key)
        now = self.now(user)
        page = session.client.project_versions(key, max_results=limit)
        out: List[Dict[str, Any]] = []
        for raw in page.get("values") or []:
            version = models.version_view(raw, now=now)
            entry: Dict[str, Any] = {"version": version, "progress": None, "atRisk": False, "reasons": []}
            if not version["released"] and not version["archived"]:
                # Only open releases cost the two extra reads.
                counts = session.client.version_unresolved_count(version["id"])
                total, open_count = int(counts.get("issuesCount") or 0), int(counts.get("issuesUnresolvedCount") or 0)
                entry["progress"] = {"total": total, "done": total - open_count, "open": open_count,
                                     "percentDone": round(100 * (total - open_count) / total) if total else None}
                if version["overdue"]:
                    entry["reasons"].append("The release date has passed and the version is not released.")
                elif version["daysToRelease"] is not None and version["daysToRelease"] <= 7 and open_count:
                    entry["reasons"].append(f"{open_count} open with {version['daysToRelease']} days to the release date.")
                entry["atRisk"] = bool(entry["reasons"])
            out.append(entry)
        return {"project": key, "releases": out,
                "page": models.page_of(out, start_at=0, total=page.get("total"), is_last=page.get("isLast"))}

    # ── issues ──────────────────────────────────────────────────────────────
    def issues(self, user: Any, params: Mapping[str, Any]) -> Dict[str, Any]:
        """A named view, structured filters, or JQL a person wrote."""
        session = self.session(user)
        raw_jql = str(params.get("jql") or "").strip()
        view_id = str(params.get("view") or "").strip()
        filters = jql.Filters.from_params(params)
        order = str(params.get("order") or "").strip() or None
        if raw_jql:
            query, source = jql.checked(raw_jql), "jql"
        elif view_id:
            query, source = jql.view_jql(view_id, filters, order=order), f"view:{view_id}"
            needs = jql.VIEW_BY_ID[view_id].needs
            if needs:
                self._need(session, {"software": "software_read", "servicedesk": "servicedesk_read"}[needs])
        else:
            query, source = jql.build(filters, order=order), "filters"
        limit = max(1, min(int(params.get("limit") or 25), 100))
        page = session.client.search(query, fields=session.fields(), max_results=limit,
                                     next_page_token=str(params.get("pageToken") or "") or None)
        rows = self._rows(session, user, page)
        out = {"issues": rows, "jql": query, "source": source, "simulated": session.simulated,
               "page": models.page_of(rows, next_page_token=page.get("nextPageToken"),
                                      is_last=page.get("isLast"))}
        if str(params.get("count") or "").lower() in ("1", "true"):
            try:
                out["approximateCount"] = session.client.count(query)
            except JiraError:
                out["approximateCount"] = None
        return out

    def issue(self, user: Any, key: str) -> Dict[str, Any]:
        session = self.session(user)
        key = jql.issue_key(key)
        raw = session.client.get_issue(key, fields=session.fields(detail=True),
                                       expand="transitions,changelog,editmeta")
        if not raw.get("transitions"):
            try:
                raw["transitions"] = session.client.transitions(key).get("transitions") or []
            except JiraError:
                raw["transitions"] = []
        return {"issue": self._view(session, user, raw, detail=True), "simulated": session.simulated,
                "canWrite": session.allows("core_write")}

    def comments(self, user: Any, key: str, *, start_at: int, limit: int) -> Dict[str, Any]:
        session = self.session(user)
        page = session.client.comments(jql.issue_key(key), start_at=start_at, max_results=limit)
        rows = [models.comment_view(raw, me=session.me) for raw in (page.get("comments") or [])]
        return {"comments": rows, "page": models.page_of(rows, start_at=start_at, total=page.get("total"))}

    def history(self, user: Any, key: str) -> Dict[str, Any]:
        session = self.session(user)
        return {"history": models.history_view(session.client.changelog(jql.issue_key(key), max_results=100))}

    def people(self, user: Any, *, issue: Optional[str], project: Optional[str], query: str,
               purpose: str) -> Dict[str, Any]:
        """Who can be assigned (``purpose=assign``) or mentioned (``mention``)."""
        session = self.session(user)
        self._need(session, "users")
        issue_key = jql.issue_key(issue) if issue else None
        if purpose == "mention":
            raw = session.client.mentionable_users(query, issue_key=issue_key)
        else:
            raw = session.client.assignable_users(issue_key=issue_key, query=query,
                                                  project_key=jql.project_key(project) if project else None)
        rows = [view for view in (models.user_view(item) for item in raw) if view and view["active"]]
        return {"people": rows, "me": session.me}

    # ── filters, dashboards ─────────────────────────────────────────────────
    def filters(self, user: Any) -> Dict[str, Any]:
        session = self.session(user)
        seen: Dict[str, Dict[str, Any]] = {}
        for raw in [*session.client.favourite_filters(), *session.client.my_filters()]:
            view = models.filter_view(raw)
            if view["id"] and view["id"] not in seen:
                seen[str(view["id"])] = view
        return {"filters": list(seen.values())}

    def filter_issues(self, user: Any, filter_id: int, params: Mapping[str, Any]) -> Dict[str, Any]:
        session = self.session(user)
        saved = models.filter_view(session.client.get_filter(filter_id))
        if not saved.get("jql"):
            raise JiraError(404, "not_found", "That filter has no query you can read.")
        return {**self.issues(user, {**dict(params), "jql": saved["jql"], "view": ""}), "filter": saved}

    def dashboards(self, user: Any) -> Dict[str, Any]:
        session = self.session(user)
        page = session.client.dashboards()
        return {"dashboards": [{"id": row.get("id"), "name": row.get("name"), "url": row.get("view"),
                                "favourite": bool(row.get("isFavourite"))}
                               for row in (page.get("dashboards") or [])]}

    # ── boards and sprints ──────────────────────────────────────────────────
    def boards(self, user: Any, *, project: Optional[str]) -> Dict[str, Any]:
        session = self.session(user)
        self._need(session, "software_read")
        page = session.client.boards(project_key=jql.project_key(project) if project else None)
        rows = [models.board_view(raw) for raw in (page.get("values") or [])]
        return {"boards": rows, "page": models.page_of(rows, start_at=0, total=page.get("total"),
                                                       is_last=page.get("isLast"))}

    def board(self, user: Any, board_id: int) -> Dict[str, Any]:
        """A board: its sprints, its columns, and the health of what is running."""
        session = self.session(user)
        self._need(session, "software_read")
        board = models.board_view(session.client.board(board_id))
        sprints: List[Dict[str, Any]] = []
        if board["type"] != "kanban":
            sprints = [view for view in (models.sprint_view(raw) for raw in
                                         (session.client.board_sprints(board_id).get("values") or [])) if view]
        columns: Optional[List[Dict[str, Any]]] = None
        if session.allows("software_board_config"):
            try:
                config = session.client.board_configuration(board_id)
                columns = [{"name": column.get("name"),
                            "statusIds": [str(status.get("id")) for status in (column.get("statuses") or [])]}
                           for column in ((config.get("columnConfig") or {}).get("columns") or [])]
            except JiraError:
                columns = None
        active = next((sprint for sprint in sprints if sprint["state"] == "active"), None)
        out: Dict[str, Any] = {"board": board, "sprints": sprints, "columns": columns, "activeSprint": None,
                               "simulated": session.simulated, "canPlan": session.allows("software_write")}
        if active is not None:
            out["activeSprint"] = self._sprint_detail(session, user, active)
        elif board["type"] == "kanban":
            page = session.client.board_issues(board_id, fields=session.fields(), max_results=100,
                                               jql="statusCategory != Done")
            rows = self._rows(session, user, page)
            out["issues"] = rows
            out["page"] = models.page_of(rows, next_page_token=page.get("nextPageToken"),
                                         is_last=page.get("isLast"), start_at=page.get("startAt"),
                                         total=page.get("total"))
        return out

    def backlog(self, user: Any, board_id: int, *, page_token: Optional[str], limit: int) -> Dict[str, Any]:
        session = self.session(user)
        self._need(session, "software_read")
        page = session.client.board_backlog(board_id, fields=session.fields(), next_page_token=page_token,
                                            max_results=limit)
        rows = self._rows(session, user, page)
        return {"issues": rows, "page": models.page_of(rows, next_page_token=page.get("nextPageToken"),
                                                       is_last=page.get("isLast"), start_at=page.get("startAt"),
                                                       total=page.get("total"))}

    def _sprint_detail(self, session: Session, user: Any, sprint: Mapping[str, Any]) -> Dict[str, Any]:
        page = session.client.sprint_issues(sprint["id"], fields=session.fields("issuelinks"), max_results=100)
        rows = self._rows(session, user, page)
        complete = page.get("isLast", True) is not False and not page.get("nextPageToken") and \
            (page.get("total") is None or page.get("total") <= len(rows))
        return {**insights.sprint_health(sprint, rows, now=self.now(user), complete=complete),
                "issues": rows, "workload": insights.workload(rows)}

    def sprint(self, user: Any, sprint_id: int) -> Dict[str, Any]:
        session = self.session(user)
        self._need(session, "software_read")
        sprint = models.sprint_view(session.client.sprint(sprint_id))
        if sprint is None:
            raise JiraError(404, "not_found", "That sprint does not exist.")
        return {**self._sprint_detail(session, user, sprint), "simulated": session.simulated,
                "canPlan": session.allows("software_write")}

    # ── service management ──────────────────────────────────────────────────
    def approvals(self, user: Any) -> Dict[str, Any]:
        """Service requests waiting on this person's decision."""
        session = self.session(user)
        self._need(session, "servicedesk_read")
        page = session.client.my_requests(ownership="APPROVER", approval="MY_PENDING_APPROVAL")
        out: List[Dict[str, Any]] = []
        for request in (page.get("values") or [])[:25]:
            key = request.get("issueKey")
            summary = next((str(value.get("value") or "") for value in (request.get("requestFieldValues") or [])
                            if value.get("fieldId") == "summary"), "")
            pending = [row for row in (session.client.request_approvals(key).get("values") or [])
                       if row.get("finalDecision") == "pending" and row.get("canAnswerApproval", True)]
            for approval in pending:
                out.append({"issue": key, "summary": summary, "approvalId": approval.get("id"),
                            "approvalName": approval.get("name"), "url": models.issue_url(session.site_url, key),
                            "requestType": (request.get("requestType") or {}).get("name"),
                            "reporter": models.user_view(request.get("reporter")),
                            "created": (request.get("createdDate") or {}).get("iso8601"),
                            "status": (request.get("currentStatus") or {}).get("status")})
        return {"approvals": out, "canAnswer": session.allows("servicedesk_write"), "simulated": session.simulated}

    # ── the briefing ────────────────────────────────────────────────────────
    def briefing(self, user: Any) -> Dict[str, Any]:
        """What needs this person in Jira today. Each part is read on its
        own: one that fails is named in ``unavailable`` and the rest stand."""
        session = self.session(user)
        unavailable: List[Dict[str, str]] = []

        def part(name: str, call: Callable[[], Any], default: Any = None) -> Any:
            try:
                return call()
            except JiraError as exc:
                unavailable.append({"part": name, "code": exc.code, "message": exc.message})
                return default

        def search(query: str) -> Dict[str, Any]:
            return session.client.search(query, fields=session.fields("issuelinks"), max_results=BRIEFING_ROWS)

        mine = part("mine", lambda: search(jql.view_jql("my_open")), {})
        team = part("team", lambda: search(
            "statusCategory != Done AND updated >= -30d ORDER BY priority DESC, updated DESC"), {})
        rows: Dict[str, Dict[str, Any]] = {}
        for page in (mine, team):
            for row in self._rows(session, user, page or {}):
                rows.setdefault(row["key"], row)
        complete = all(not (page or {}).get("nextPageToken") for page in (mine, team))
        out: Dict[str, Any] = {**insights.digest(rows.values(), me=session.me, complete=complete),
                               "generatedAt": self.now(user).isoformat(), "simulated": session.simulated,
                               "site": {"name": session.site_name, "url": session.site_url},
                               "sprints": [], "approvals": None}
        if session.allows("software_read"):
            for board in (part("boards", lambda: session.client.boards(kind="scrum", max_results=5), {})
                          .get("values") or [])[:3]:
                active = part("sprints", lambda: session.client.board_sprints(board.get("id"), state="active"), {})
                for raw in (active.get("values") or [])[:1]:
                    sprint = models.sprint_view(raw)
                    detail = part("sprint", lambda: self._sprint_detail(session, user, sprint))
                    if detail:
                        detail.pop("issues", None)
                        out["sprints"].append({"board": models.board_view(board), **detail})
        if session.allows("servicedesk_read"):
            approvals = part("approvals", lambda: self.approvals(user))
            out["approvals"] = (approvals or {}).get("approvals")
        out["unavailable"] = unavailable
        out["proposalsWaiting"] = self.proposals.list(user, limit=0)["waiting"]
        return out

    # ── proposals ───────────────────────────────────────────────────────────
    def propose(self, user: Any, action: str, payload: Mapping[str, Any], *, reason: Optional[str],
                origin: str = "user") -> Dict[str, Any]:
        session = self.session(user)
        return self.proposals.propose(user, session.context(), action, payload, scopes=session.scopes,
                                      simulated=session.simulated, site=session.site_name, origin=origin,
                                      reason=reason)

    def approve(self, user: Any, proposal_id: str, *, confirmed: bool) -> Dict[str, Any]:
        session = self.session(user)
        return self.proposals.approve(user, session.context(), proposal_id,
                                      writes=policy.writes(self.env, sandbox=session.simulated),
                                      confirmed=confirmed)
