"""A stand-in backend that does nothing, or misbehaves on purpose.

For testing THE SIMULATOR, never for producing a result about the Desk:

- ``FakeDesk()`` answers every call the runner makes and never opens a run.
  A day played against it must come out as "every request missed": that is
  the proof that the oracle gives nothing away for free.
- ``FakeDesk(broken={...})`` answers chosen routes with an error, with text
  that is not JSON, or with JSON that lacks the expected keys, so the
  runner's handling of an unexpected backend response can be tested.

Standard library only. Listens on 127.0.0.1 on a free port.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import urlparse

from .office import build_office

Answer = Tuple[int, Any]          # (HTTP status, JSON-serialisable body or raw bytes)


def empty_world(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """The office at 08:00 in the shape of ``/sim/state``, with no mail."""
    return {
        "id": spec["worldId"], "label": "fake", "now": spec["startsAt"], "timezone": spec["timezone"],
        "preferences": dict(spec["preferences"]),
        "accounts": {"gmail": list(spec["accounts"]["gmail"]), "outlook": spec["accounts"]["outlook"]},
        "mail": {"gmail": [], "outlook": []}, "sent": [dict(row) for row in spec["sent"]], "drafts": [],
        "events": [{**event, "status": "confirmed", "show_as": "busy", "description": ""}
                   for event in spec["calendar"]],
        "tasks": [dict(task) for task in spec["tasks"]], "reminders": [dict(r) for r in spec["reminders"]],
        "followUps": [dict(f) for f in spec["followUps"]], "faults": [], "unreadable": {},
        "operations": [], "isolationViolations": [], "simulated": True,
    }


class FakeDesk:
    def __init__(self, spec: Optional[Mapping[str, Any]] = None,
                 broken: Optional[Mapping[Tuple[str, str], Callable[[int], Optional[Answer]]]] = None) -> None:
        self.spec = dict(spec or build_office())
        self.world = empty_world(self.spec)
        self.broken = dict(broken or {})
        self.hits: Dict[Tuple[str, str], int] = {}
        self.delivered: list = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:      # keep test output quiet
                pass

            def _serve(self, method: str) -> None:
                path = urlparse(self.path).path
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                status, answer = fake.answer(method, path, body)
                raw = answer if isinstance(answer, bytes) else json.dumps(answer).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:       # noqa: N802
                self._serve("GET")

            def do_POST(self) -> None:      # noqa: N802
                self._serve("POST")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> "FakeDesk":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()

    def answer(self, method: str, path: str, body: Mapping[str, Any]) -> Answer:
        key = (method, path)
        self.hits[key] = self.hits.get(key, 0) + 1
        override = self.broken.get(key)
        if override is not None:
            forced = override(self.hits[key])
            if forced is not None:
                return forced
        if key == ("POST", "/auth/signin"):
            return 200, {"email": self.spec["scribaUser"]}
        if key == ("GET", "/live"):
            return 200, {"ok": True}
        if key == ("GET", "/sim/meta"):
            return 200, {"control": "fake", "deskBackend": "fake", "claims": "memory", "simulated": True}
        if key == ("GET", "/desk/health"):
            return 200, {"version": "fake", "executionMode": "sandbox", "externalWrites": {"enabled": False},
                         "model": {"configured": False}}
        if key == ("GET", "/sim/state"):
            return 200, {"world": self.world, "gate": {}}
        if key == ("POST", "/sim/clock"):
            self.world["now"] = body.get("now")
            return 200, {"now": body.get("now")}
        if key == ("POST", "/sim/deliver"):
            self.delivered.append(dict(body))
            return 200, {"delivered": True, "duplicateNotification": False, "id": body.get("message_id")}
        if key == ("POST", "/sim/worker/tick"):
            return 200, {"tick": {"status": "completed", "users": [{"status": "ok", "opened": 0}]}, "worker": {}}
        if key == ("GET", "/desk/runs"):
            return 200, {"runs": []}
        if key == ("GET", "/desk/follow-ups"):
            return 200, {"followUps": [], "counts": {"waiting": 0, "overdue": 0, "satisfied": 0, "closed": 0}}
        if key == ("GET", "/desk/briefing"):
            return 200, {"headline": "", "counts": {"meetings_today": 0, "open_tasks": 0},
                         "inbox_complete": True, "unavailable": []}
        if path.startswith("/sim/"):
            return 200, {}
        return 404, {"detail": "not found"}
