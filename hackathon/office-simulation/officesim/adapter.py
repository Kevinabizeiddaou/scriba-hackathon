"""The sandbox API adapter: the only place the simulator talks to the Desk.

``DeskClient`` is a thin HTTP client over three existing surfaces:

- Scriba's own routes   ``/auth/signin``, ``/chat/tool-calls/{id}`` (read,
                        approve, cancel, retry): the approval path;
- the Desk overlay      ``/desk/*``: health, runs, intake, sweep, briefing,
                        follow-ups, the sandbox world's operation log;
- the simulator control ``/sim/*``: clock, mail delivery, faults, one worker
                        pass, the world's state (``control.py``).

It decides nothing. Standard library only, so the simulator runs on any
Python that can run the backend.

``SandboxServer`` starts and stops the sandbox backend process.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

DESK_ORIGIN = "http://localhost:5173"      # the origin Scriba trusts for the Desk


def seeded_password() -> str:
    """The password of Scriba's seeded test user.

    It is defined by Scriba's own seeded server (an in-memory fixture with no
    real account behind it), not by this repository, so it is read from
    there: ``OFFICESIM_PASSWORD``, or ``ALICE_PASSWORD`` in the configured
    Scriba checkout's ``e2e/seeded_server.py``. No credential, even a test
    fixture's, is written in this repository.
    """
    import re

    if os.environ.get("OFFICESIM_PASSWORD"):
        return os.environ["OFFICESIM_PASSWORD"]
    scriba = load_config().get("SCRIBA_BACKEND_PATH") or ""
    seeded = Path(scriba) / "e2e" / "seeded_server.py"
    if scriba and seeded.is_file():
        found = re.search(r"^ALICE_PASSWORD\s*=\s*[\"']([^\"']+)[\"']", seeded.read_text(encoding="utf-8"), re.M)
        if found:
            return found.group(1)
    raise RuntimeError("No sign-in password for the seeded test user: set OFFICESIM_PASSWORD, or "
                       "SCRIBA_BACKEND_PATH to a Scriba checkout (see python -m officesim doctor).")


class DeskApiError(RuntimeError):
    """The backend answered with an error, or with something that is not JSON."""

    def __init__(self, method: str, path: str, status: Optional[int], body: Any) -> None:
        detail = body if isinstance(body, str) else json.dumps(body)[:400]
        super().__init__(f"{method} {path} -> {status}: {detail}")
        self.method, self.path, self.status, self.body = method, path, status, body


class DeskClient:
    def __init__(self, base_url: str, *, origin: str = DESK_ORIGIN, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.origin = origin
        self.timeout = timeout
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar), urllib.request.ProxyHandler({}))
        self.calls = 0

    # ── transport ───────────────────────────────────────────────────────────
    def request(self, method: str, path: str, body: Optional[Mapping[str, Any]] = None,
                *, expect_json: bool = True) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Origin": self.origin, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        elif method != "GET":
            data = b""
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        self.calls += 1
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw, status = response.read(), response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed: Any = json.loads(raw.decode("utf-8"))
            except Exception:
                parsed = raw.decode("utf-8", "replace")[:400]
            raise DeskApiError(method, path, exc.code, parsed) from None
        except (urllib.error.URLError, OSError) as exc:
            raise DeskApiError(method, path, None, f"unreachable: {exc}") from None
        if not expect_json:
            return raw
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise DeskApiError(method, path, status, f"not JSON: {raw[:200]!r}") from None

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Optional[Mapping[str, Any]] = None) -> Any:
        return self.request("POST", path, body)

    # ── session ─────────────────────────────────────────────────────────────
    def sign_in(self, email: str, password: Optional[str] = None) -> Dict[str, Any]:
        return self.post("/auth/signin", {"email": email,
                                          "password": password if password is not None else seeded_password()})

    def live(self) -> bool:
        try:
            return bool(self.get("/live").get("ok"))
        except DeskApiError:
            return False

    # ── Desk overlay (read) ─────────────────────────────────────────────────
    def health(self) -> Dict[str, Any]:
        return self.get("/desk/health")

    def runs(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self.get(f"/desk/runs?limit={limit}")["runs"]

    def run(self, run_id: int) -> Dict[str, Any]:
        return self.get(f"/desk/runs/{int(run_id)}")

    def briefing(self) -> Dict[str, Any]:
        return self.get("/desk/briefing")

    def follow_ups(self, refresh: bool = True) -> Dict[str, Any]:
        return self.get(f"/desk/follow-ups?refresh={'true' if refresh else 'false'}&limit=200")

    def worker(self) -> Dict[str, Any]:
        return self.get("/desk/worker")

    def inbox(self, limit: int = 100) -> Dict[str, Any]:
        return self.get(f"/desk/inbox?limit={limit}")

    def sandbox(self) -> Dict[str, Any]:
        return self.get("/desk/sandbox")

    # ── Desk overlay (workflow) ─────────────────────────────────────────────
    def intake(self, provider: str, message_id: str) -> Dict[str, Any]:
        return self.post("/desk/intake", {"provider": provider, "id": message_id})

    def sweep(self, max_new: int = 10) -> Dict[str, Any]:
        return self.post("/desk/intake/sweep", {"max_new": max_new, "limit": 50})

    def advance(self, run_id: int) -> Dict[str, Any]:
        return self.post(f"/desk/runs/{int(run_id)}/advance")

    def close_follow_up(self, run_id: int, follow_id: str) -> Dict[str, Any]:
        return self.post(f"/desk/runs/{int(run_id)}/follow-ups/{follow_id}/close")

    # ── Scriba's approval path ──────────────────────────────────────────────
    def tool_call(self, tool_call_id: int) -> Dict[str, Any]:
        return self.get(f"/chat/tool-calls/{int(tool_call_id)}")

    def approve(self, tool_call_id: int, *, idempotency_key: str,
                payload_overrides: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"idempotency_key": idempotency_key}
        if payload_overrides:
            body["payload_overrides"] = dict(payload_overrides)
        return self.post(f"/chat/tool-calls/{int(tool_call_id)}/approve", body)

    def reject(self, tool_call_id: int) -> Dict[str, Any]:
        return self.post(f"/chat/tool-calls/{int(tool_call_id)}/cancel")

    def retry(self, tool_call_id: int) -> Dict[str, Any]:
        return self.post(f"/chat/tool-calls/{int(tool_call_id)}/retry")

    # ── simulator control (the outside world) ───────────────────────────────
    def sim_meta(self) -> Dict[str, Any]:
        return self.get("/sim/meta")

    def sim_state(self) -> Dict[str, Any]:
        return self.get("/sim/state")

    def sim_clock(self, now_iso: str) -> Dict[str, Any]:
        return self.post("/sim/clock", {"now": now_iso})

    def sim_deliver(self, message: Mapping[str, Any]) -> Dict[str, Any]:
        return self.post("/sim/deliver", dict(message))

    def sim_fault(self, tool: str, mode: str = "fail_times", times: int = 1,
                  error: str = "provider_error") -> Dict[str, Any]:
        return self.post("/sim/fault", {"tool": tool, "mode": mode, "times": times, "error": error})

    def sim_clear_faults(self) -> Dict[str, Any]:
        return self.post("/sim/faults/clear")

    def sim_unreadable(self, key: str, code: Optional[str]) -> Dict[str, Any]:
        return self.post("/sim/unreadable", {"key": key, "code": code})

    def sim_worker_tick(self) -> Dict[str, Any]:
        return self.post("/sim/worker/tick")

    def sim_worker_restart(self) -> Dict[str, Any]:
        return self.post("/sim/worker/restart")

    def sim_remove_event(self, event_id: str) -> Dict[str, Any]:
        return self.post("/sim/world/remove-event", {"eventId": event_id})

    def sim_interrupt(self, tool_call_id: int) -> Dict[str, Any]:
        return self.post("/sim/interrupt", {"toolCallId": int(tool_call_id)})


# ── the sandbox backend process ─────────────────────────────────────────────

LOCAL_CONFIG = ".officesim.local.json"


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config() -> Dict[str, str]:
    """Where the Scriba checkout, the Desk backend and the Python that can run
    them are. Environment first, then ``.officesim.local.json`` (untracked),
    then this repository's own ``backend/``."""
    config: Dict[str, str] = {}
    local = package_root() / LOCAL_CONFIG
    if local.is_file():
        try:
            config.update({k: str(v) for k, v in json.loads(local.read_text(encoding="utf-8")).items()})
        except Exception:
            pass
    for key in ("SCRIBA_BACKEND_PATH", "DESK_BACKEND_PATH", "SCRIBA_PYTHON", "DESK_FRONTEND_PATH"):
        if os.environ.get(key):
            config[key] = os.environ[key]
    config.setdefault("DESK_BACKEND_PATH", str(package_root().parents[1] / "backend"))
    config.setdefault("SCRIBA_PYTHON", sys.executable)
    return config


class SandboxServer:
    """Starts ``officesim.sandbox_server`` and stops it. One process per
    simulated day: every run starts from the same clean state."""

    def __init__(self, spec_path: Path, *, port: int = 8914, worker: str = "manual",
                 claims: str = "memory", log_path: Optional[Path] = None,
                 extra_env: Optional[Mapping[str, str]] = None) -> None:
        self.spec_path, self.port, self.worker, self.claims = Path(spec_path), int(port), worker, claims
        self.log_path = log_path or (self.spec_path.parent / "server.log")
        self.extra_env = dict(extra_env or {})
        self.process: Optional[subprocess.Popen] = None
        self._log = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def problems(self) -> List[str]:
        """Why the sandbox cannot be started here, if it cannot."""
        from .sandbox_server import missing_contract

        config = load_config()
        found: List[str] = []
        scriba = Path(config.get("SCRIBA_BACKEND_PATH", ""))
        if not config.get("SCRIBA_BACKEND_PATH") or not (scriba / "e2e" / "seeded_server.py").is_file():
            found.append("SCRIBA_BACKEND_PATH is not the Gmail/ directory of a Scriba checkout")
        missing = missing_contract(Path(config["DESK_BACKEND_PATH"]))
        if missing:
            found.append(f"DESK_BACKEND_PATH ({config['DESK_BACKEND_PATH']}) has no sandbox engine "
                         f"(missing desk_overlay/{', desk_overlay/'.join(missing)})")
        if not Path(config["SCRIBA_PYTHON"]).exists():
            found.append("SCRIBA_PYTHON does not exist")
        return found

    @property
    def pid_file(self) -> Path:
        return self.spec_path.parent / f"sandbox-{self.port}.pid"

    def _stop_stale(self) -> None:
        """A sandbox this simulator started and never stopped (a crashed run)
        is stopped, so a new day always starts clean. Anything else on the
        port is left alone."""
        if not self.pid_file.is_file():
            return
        try:
            pid = int(self.pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = 0
        if pid and DeskClient(self.base_url, timeout=3).live():
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, timeout=30)
            else:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
            for _ in range(20):
                if not DeskClient(self.base_url, timeout=2).live():
                    break
                time.sleep(0.5)
        self.pid_file.unlink(missing_ok=True)

    def start(self, wait_seconds: float = 90.0) -> "SandboxServer":
        problems = self.problems()
        if problems:
            raise RuntimeError("The sandbox backend cannot be started: " + "; ".join(problems))
        self._stop_stale()
        if DeskClient(self.base_url, timeout=3).live():
            raise RuntimeError(f"Port {self.port} is already serving. Stop that process or use --port.")
        config = load_config()
        env = {**os.environ, **self.extra_env,
               "SCRIBA_BACKEND_PATH": config["SCRIBA_BACKEND_PATH"],
               "DESK_BACKEND_PATH": config["DESK_BACKEND_PATH"],
               # Leave the read-only Scriba checkout and the Desk backend untouched.
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "w", encoding="utf-8")
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.process = subprocess.Popen(
            [config["SCRIBA_PYTHON"], "-m", "officesim.sandbox_server", "--port", str(self.port),
             "--spec", str(self.spec_path), "--worker", self.worker, "--claims", self.claims],
            cwd=str(package_root()), env=env, stdout=self._log, stderr=subprocess.STDOUT,
            creationflags=flags)
        self.pid_file.write_text(str(self.process.pid), encoding="utf-8")
        client = DeskClient(self.base_url, timeout=3)
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"The sandbox backend exited at start. See {self.log_path}")
            if client.live():
                return self
            time.sleep(0.5)
        self.stop()
        raise RuntimeError(f"The sandbox backend did not answer within {wait_seconds:.0f}s. See {self.log_path}")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/F", "/T"],
                               capture_output=True, timeout=30)
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        self.pid_file.unlink(missing_ok=True)
        if self._log is not None:
            self._log.close()
            self._log = None

    def __enter__(self) -> "SandboxServer":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()
