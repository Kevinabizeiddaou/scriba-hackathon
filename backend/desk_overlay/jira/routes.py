"""``/desk/jira/*``. Reads go to Jira; a write is only ever a proposal.

- ``/desk/jira/status``      always answers, even with Jira off: it is how a
                             client learns whether to show Jira at all
- ``/desk/jira/features``    what is covered, and what this connection allows
- ``/desk/jira/briefing``    late, blocked, stalled, sprints at risk, approvals
- ``/desk/jira/issues``      a named view, filters, or JQL; one issue; its
                             comments and history
- ``/desk/jira/projects``, ``/boards``, ``/sprints``, ``/filters``, ``/approvals``
- ``/desk/jira/proposals``   propose a change, list, approve, reject

Errors carry ``detail`` (a sentence), ``errorCode`` and ``details``, the
shape the Desk's client already reads. A Jira-side authentication problem is
never a 401 here: to the Desk's client a 401 means the Scriba session is
gone. It is a 409 with ``errorCode`` ``not_connected`` or
``reconnect_required``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import JIRA_SKELETON_VERSION, jql, policy
from .actions import InvalidAction
from .client import JiraError
from .proposals import ProposalConflict, ProposalNotFound
from .service import JiraService, NotReady

JIRA_CAPABILITY = "jira"
_STATUS = {"scope_missing": 403, "forbidden": 403, "not_found": 404, "invalid_request": 400,
           "conflict": 409, "rate_limited": 429, "jira_unavailable": 502, "too_large": 413,
           "reconnect_required": 409, "not_connected": 409, "site_missing": 409, "identity_unknown": 409}


class ProposalBody(BaseModel):
    action: str = Field(min_length=1, max_length=60)
    input: Dict[str, Any] = Field(default_factory=dict)
    # Why this change, in the proposer's words. Shown beside the preview.
    reason: Optional[str] = Field(default=None, max_length=500)


class ApproveBody(BaseModel):
    # After an outcome that is not known: "I looked at the issue in Jira".
    confirmChecked: bool = False


def _error(status: int, code: str, message: str, details: Any = None, headers: Optional[Dict[str, str]] = None) -> JSONResponse:
    return JSONResponse(status_code=status, headers=headers,
                        content={"detail": message, "errorCode": code, "details": details})


def build_jira_router(gateway: Any, *, env: Mapping[str, str], service: Optional[JiraService] = None,
                      clock: Any = None) -> APIRouter:
    """The router is always mounted. With ``DESK_JIRA`` off only ``/status``
    answers (``enabled: false``); every other route is a 404."""
    router = APIRouter(prefix="/desk/jira", tags=["desk-jira"])
    enabled = policy.is_on(env)
    jira = service or JiraService(gateway, env=env, clock=clock)
    router.jira = jira  # type: ignore[attr-defined]

    def run(request: Request, call: Callable[[Any], Any]) -> Any:
        user = gateway.current_user(request)          # 401/403 as every Desk route
        if not enabled:
            return _error(404, "jira_off", "Jira is not part of this Desk.")
        try:
            return call(user)
        except NotReady as exc:
            return _error(409, exc.code, exc.message)
        except (jql.InvalidQuery,) as exc:
            return _error(400, "invalid_query", str(exc))
        except InvalidAction as exc:
            return _error(422, "invalid_action", "This change cannot be proposed as it stands.",
                          {"problems": exc.problems})
        except ProposalNotFound:
            return _error(404, "not_found", "There is no such proposal.")
        except ProposalConflict as exc:
            return _error(409, exc.code, exc.message)
        except JiraError as exc:
            headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None
            return _error(_STATUS.get(exc.code, 502 if exc.status >= 500 else 400), exc.code, exc.message,
                          {"fields": exc.fields} if exc.fields else None, headers)

    @router.get("/status")
    def jira_status(request: Request) -> Any:
        user = gateway.current_user(request)
        if not enabled:
            return {"enabled": False, "version": JIRA_SKELETON_VERSION}
        return jira.status(user)

    @router.get("/features")
    def jira_features(request: Request) -> Any:
        return run(request, jira.feature_list)

    @router.get("/briefing")
    def jira_briefing(request: Request) -> Any:
        return run(request, jira.briefing)

    # ── issues ──────────────────────────────────────────────────────────────
    @router.get("/issues")
    def jira_issues(request: Request) -> Any:
        """``view``, or filters (``project``, ``assignee``, ``status``,
        ``statusCategory``, ``type``, ``priority``, ``label``, ``component``,
        ``fixVersion``, ``sprint``, ``parent``, ``text``, ``overdue``,
        ``dueWithinDays``, ``updatedWithinDays``), or ``jql``. Also ``order``,
        ``limit``, ``pageToken`` and ``count``."""
        return run(request, lambda user: jira.issues(user, dict(request.query_params)))

    @router.get("/issues/{key}")
    def jira_issue(request: Request, key: str) -> Any:
        return run(request, lambda user: jira.issue(user, key))

    @router.get("/issues/{key}/comments")
    def jira_comments(request: Request, key: str, startAt: int = Query(default=0, ge=0),
                      limit: int = Query(default=50, ge=1, le=100)) -> Any:
        return run(request, lambda user: jira.comments(user, key, start_at=startAt, limit=limit))

    @router.get("/issues/{key}/history")
    def jira_history(request: Request, key: str) -> Any:
        return run(request, lambda user: jira.history(user, key))

    @router.get("/people")
    def jira_people(request: Request, issue: Optional[str] = None, project: Optional[str] = None,
                    query: str = Query(default="", max_length=100),
                    purpose: str = Query(default="assign", pattern="^(assign|mention)$")) -> Any:
        return run(request, lambda user: jira.people(user, issue=issue, project=project, query=query,
                                                     purpose=purpose))

    # ── projects, releases ──────────────────────────────────────────────────
    @router.get("/projects")
    def jira_projects(request: Request, query: Optional[str] = Query(default=None, max_length=100),
                      startAt: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100)) -> Any:
        return run(request, lambda user: jira.projects(user, query=query, start_at=startAt, limit=limit))

    @router.get("/projects/{key}")
    def jira_project(request: Request, key: str) -> Any:
        return run(request, lambda user: jira.project(user, key))

    @router.get("/projects/{key}/create-fields")
    def jira_create_fields(request: Request, key: str, issueType: str = Query(min_length=1, max_length=60)) -> Any:
        return run(request, lambda user: jira.create_fields(user, key, issueType))

    @router.get("/projects/{key}/releases")
    def jira_releases(request: Request, key: str) -> Any:
        return run(request, lambda user: jira.releases(user, key))

    # ── filters, dashboards ─────────────────────────────────────────────────
    @router.get("/filters")
    def jira_filters(request: Request) -> Any:
        return run(request, jira.filters)

    @router.get("/filters/{filter_id}/issues")
    def jira_filter_issues(request: Request, filter_id: int) -> Any:
        return run(request, lambda user: jira.filter_issues(user, filter_id, dict(request.query_params)))

    @router.get("/dashboards")
    def jira_dashboards(request: Request) -> Any:
        return run(request, jira.dashboards)

    # ── boards and sprints ──────────────────────────────────────────────────
    @router.get("/boards")
    def jira_boards(request: Request, project: Optional[str] = None) -> Any:
        return run(request, lambda user: jira.boards(user, project=project))

    @router.get("/boards/{board_id}")
    def jira_board(request: Request, board_id: int) -> Any:
        return run(request, lambda user: jira.board(user, board_id))

    @router.get("/boards/{board_id}/backlog")
    def jira_backlog(request: Request, board_id: int, pageToken: Optional[str] = None,
                     limit: int = Query(default=50, ge=1, le=100)) -> Any:
        return run(request, lambda user: jira.backlog(user, board_id, page_token=pageToken, limit=limit))

    @router.get("/sprints/{sprint_id}")
    def jira_sprint(request: Request, sprint_id: int) -> Any:
        return run(request, lambda user: jira.sprint(user, sprint_id))

    # ── service management ──────────────────────────────────────────────────
    @router.get("/approvals")
    def jira_approvals(request: Request) -> Any:
        return run(request, jira.approvals)

    # ── proposals: the only way anything in Jira changes ────────────────────
    @router.get("/proposals")
    def jira_proposals(request: Request, status: Optional[str] = Query(default=None, max_length=40),
                       limit: int = Query(default=100, ge=1, le=300)) -> Any:
        return run(request, lambda user: jira.proposals.list(user, status=status, limit=limit))

    @router.post("/proposals")
    def jira_propose(request: Request, body: ProposalBody) -> Any:
        """Check a change and record it for approval. Reads Jira; changes nothing."""
        return run(request, lambda user: jira.propose(user, body.action, body.input, reason=body.reason))

    @router.get("/proposals/{proposal_id}")
    def jira_proposal(request: Request, proposal_id: str) -> Any:
        return run(request, lambda user: jira.proposals.get(user, proposal_id))

    @router.post("/proposals/{proposal_id}/approve")
    def jira_approve(request: Request, proposal_id: str, body: Optional[ApproveBody] = None) -> Any:
        """The person's decision. Held, with nothing sent, while Jira writes are off."""
        return run(request, lambda user: jira.approve(user, proposal_id,
                                                      confirmed=bool(body and body.confirmChecked)))

    @router.post("/proposals/{proposal_id}/reject")
    def jira_reject(request: Request, proposal_id: str) -> Any:
        return run(request, lambda user: jira.proposals.reject(user, proposal_id))

    return router


def health(env: Mapping[str, str]) -> Dict[str, Any]:
    """What ``/desk/health`` adds when Jira is on. Nothing at all when it is
    off: the health payload of a Desk without Jira does not name it."""
    if not policy.is_on(env):
        return {}
    return {JIRA_CAPABILITY: {"enabled": True, "version": JIRA_SKELETON_VERSION,
                              "writes": policy.writes(env, sandbox=False)["mode"]}}
