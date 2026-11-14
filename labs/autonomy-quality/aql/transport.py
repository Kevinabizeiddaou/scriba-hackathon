"""HTTP transport: one signed-in Scriba session.

Scriba authenticates with an HttpOnly session cookie and accepts credentialed
requests only from the Desk origin. A command-line client signs in with
``POST /auth/signin``, keeps the cookie in memory and sends the origin
itself. Nothing is written to disk and the cookie is never printed.

A request never retries a POST: a write is sent once (contract rule 7).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional, Tuple

from . import CONTRACT_VERSION

DESK_ORIGIN = "http://localhost:5173"


class TransportError(Exception):
    """No usable response: unreachable, timed out, or not JSON."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Session:
    def __init__(self, api_root: str, *, origin: str = DESK_ORIGIN, timeout: float = 60.0) -> None:
        self.root = api_root.rstrip("/")
        self.origin = origin
        self.timeout = timeout
        self._cookie: Optional[str] = None
        self.email: Optional[str] = None
        self.requests = 0
        self._lock = threading.Lock()

    def sign_in(self, email: str, password: str) -> None:
        request = urllib.request.Request(
            f"{self.root}/auth/signin", method="POST",
            data=json.dumps({"email": email, "password": password}).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json", "Origin": self.origin})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                pairs = [line.split(";")[0].strip() for line in response.headers.get_all("Set-Cookie") or []]
        except urllib.error.HTTPError as exc:
            raise TransportError("signin_refused", f"Sign-in failed with HTTP {exc.code}.") from None
        except OSError as exc:
            raise TransportError("unreachable", f"Could not reach {self.root}: {exc}") from None
        cookie = "; ".join(pair for pair in pairs if "=" in pair and not pair.endswith("="))
        if not cookie:
            raise TransportError("no_session", "The sign-in was accepted but no session cookie was set.")
        self._cookie, self.email = cookie, email

    def call(self, method: str, path: str, body: Any = None, *, timeout: Optional[float] = None) -> Tuple[int, Any]:
        """(status, parsed JSON or text). HTTP errors are returned, not raised."""
        headers = {"Accept": "application/json", "Origin": self.origin,
                   "X-Executive-Desk-Contract": CONTRACT_VERSION}
        if self._cookie:
            headers["Cookie"] = self._cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.root}{path}", data=data, method=method, headers=headers)
        with self._lock:
            self.requests += 1
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw, status = response.read(), response.status
        except urllib.error.HTTPError as exc:
            raw, status = exc.read(), exc.code
        except OSError as exc:
            raise TransportError("unreachable", f"{method} {path}: {exc}") from None
        if not raw:
            return status, None
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw[:500].decode("utf-8", "replace")

    def get(self, path: str, **kw: Any) -> Tuple[int, Any]:
        return self.call("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> Tuple[int, Any]:
        return self.call("POST", path, {} if body is None else body, **kw)

    def wait_until_up(self, seconds: float = 90.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                status, _ = self.get("/live", timeout=5)
                if status == 200:
                    return True
            except TransportError:
                pass
            time.sleep(1.0)
        return False


def error_code(payload: Any) -> Optional[str]:
    """The machine code of an error body, in either of the backend's shapes."""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("code") or "") or None
        if payload.get("errorCode"):
            return str(payload["errorCode"])
        if isinstance(error, str):
            return error
        if payload.get("detail"):
            return str(payload["detail"])[:120]
    return None
