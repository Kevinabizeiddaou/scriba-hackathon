"""The HTTP transport for Jira Cloud: one site, one person's token.

``JiraClient`` (``client.py``) knows the REST API; this knows how a request
gets there. They are separate so the client is tested against a scripted
transport and the demo runs against a synthetic site (``sandbox.py``) through
exactly the code that talks to the real one.

An OAuth 2.0 (3LO) token is not sent to the site's own address. Every
product API of a site is reached through Atlassian's gateway under the
site's cloud id:

    https://api.atlassian.com/ex/jira/{cloudId}/rest/api/3/...        platform
    https://api.atlassian.com/ex/jira/{cloudId}/rest/agile/1.0/...    boards and sprints
    https://api.atlassian.com/ex/jira/{cloudId}/rest/software/1.0/... the issues on them
    https://api.atlassian.com/ex/jira/{cloudId}/rest/servicedeskapi/... service management

Nothing here stores, logs or returns a token. The token comes from a
callable the gateway supplies (Scriba's own refresh), asked for once per
request so a long operation never runs on an expired one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Protocol

GATEWAY = "https://api.atlassian.com"
API_ROOTS: Dict[str, str] = {
    "platform": "/rest/api/3",
    "agile": "/rest/agile/1.0",
    "software": "/rest/software/1.0",
    "servicedesk": "/rest/servicedeskapi",
}
TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class JiraResponse:
    status: int
    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def header(self, name: str) -> Optional[str]:
        wanted = name.lower()
        for key, value in self.headers.items():
            if str(key).lower() == wanted:
                return str(value)
        return None


class Transport(Protocol):
    def request(self, method: str, api: str, path: str, *, params: Optional[Mapping[str, Any]] = None,
                json: Any = None, files: Any = None,
                headers: Optional[Mapping[str, str]] = None) -> JiraResponse: ...


class NotConnected(Exception):
    """There is no usable Jira token for this person. ``code`` is safe to show."""

    def __init__(self, code: str = "not_connected", detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def url_for(cloud_id: str, api: str, path: str) -> str:
    if api not in API_ROOTS:
        raise ValueError(f"unknown Jira API {api!r}")
    return f"{GATEWAY}/ex/jira/{cloud_id}{API_ROOTS[api]}/{str(path).lstrip('/')}"


class GatewayTransport:
    """Requests through Atlassian's gateway with a bearer token.

    ``token`` returns a valid access token or None; ``send`` is
    ``requests.request`` in production and a stub in tests. ``on_unreachable``
    is told when the gateway itself refuses the site (the grant was revoked
    or the site is gone), so the connection can be marked for reconnection.
    """

    def __init__(self, *, cloud_id: str, token: Callable[[], Optional[str]], send: Callable[..., Any],
                 on_unreachable: Optional[Callable[[int], None]] = None) -> None:
        self.cloud_id = str(cloud_id or "").strip()
        self._token = token
        self._send = send
        self._on_unreachable = on_unreachable

    def request(self, method: str, api: str, path: str, *, params: Optional[Mapping[str, Any]] = None,
                json: Any = None, files: Any = None,
                headers: Optional[Mapping[str, str]] = None) -> JiraResponse:
        if not self.cloud_id:
            raise NotConnected("site_missing", "The Jira connection has no site.")
        token = self._token()
        if not token:
            raise NotConnected("reconnect_required", "Jira is not connected, or its access has expired.")
        sent_headers: Dict[str, str] = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if files is not None:
            # An upload is multipart, and Jira refuses it without this header.
            sent_headers["X-Atlassian-Token"] = "no-check"
        elif json is not None:
            sent_headers["Content-Type"] = "application/json"
        sent_headers.update(dict(headers or {}))
        response = self._send(
            method.upper(), url_for(self.cloud_id, api, path),
            params={key: value for key, value in dict(params or {}).items() if value is not None} or None,
            json=json if files is None else None, files=files, headers=sent_headers,
            timeout=TIMEOUT_SECONDS,
        )
        status = int(getattr(response, "status_code", 0) or 0)
        body: Any = None
        if status != 204 and getattr(response, "content", b""):
            try:
                body = response.json()
            except Exception:
                body = {"message": str(getattr(response, "text", "") or "")[:300]}
        result = JiraResponse(status=status, body=body,
                              headers=dict(getattr(response, "headers", {}) or {}))
        if self._on_unreachable is not None and gateway_refused(result):
            try:
                self._on_unreachable(status)
            except Exception:
                pass
        return result


def gateway_refused(response: JiraResponse) -> bool:
    """True when the GATEWAY, not Jira, answered 401/403/404: an unknown cloud
    id, a removed site, a revoked grant. Jira's own errors ("issue does not
    exist", "you do not have permission") carry ``errorMessages`` or
    ``errors`` and are a fact about one resource, not about the connection."""
    if response.status not in (401, 403, 404):
        return False
    body = response.body
    if not isinstance(body, Mapping):
        return response.status == 401
    if "errorMessages" in body or "errors" in body:
        return False
    message = str(body.get("message") or "").strip().lower()
    if scope_refused(response):
        return False
    if response.status == 401:
        return True
    return message == "no message available" or str(body.get("path") or "").startswith("/ex/jira/")


def scope_refused(response: JiraResponse) -> bool:
    """The gateway's "Unauthorized; scope does not match": the token is good
    but was not granted the scope this endpoint needs. The connection is fine;
    reconnecting only helps once the scope has been added to the app."""
    if response.status not in (401, 403) or not isinstance(response.body, Mapping):
        return False
    return "scope" in str(response.body.get("message") or "").lower()
