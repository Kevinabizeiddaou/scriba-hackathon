"""A local, isolated Chromium driven over the DevTools protocol.

Why this exists: Scriba's browser automation is a Chrome extension. Its page
side (``browser_extension/content/player.js`` and ``lib/``) applies one step to
a page; its service worker takes jobs from a server with a database and drives
tabs in the person's own Chrome. Neither the person's Chrome nor that server
exists in a Desk sandbox, and the extension cannot download a file or run
headlessly. So here the service worker's role (open a page, hand a step to the
page side, wait for the page) is played over the DevTools protocol, against a
Chromium that belongs to no one: no profile, no extension, nothing on disk
that outlives the process.

What runs IN the page is still Scriba's own code: ``scriba_page_bundle`` reads
the extension's modules from the Scriba checkout at run time and joins them in
memory. Nothing of them is stored in this repository.

This module knows nothing about tasks, approvals or policy. It offers: start
and stop a browser, an isolated context per caller, pages, navigation that
waits for the document, evaluation in an isolated world, and a gate through
which every network request of a page must pass (``Session.allow``).
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional

WORLD = "scriba-desk"
_ENV_BINARY = "DESK_BROWSER_BINARY"


class BrowserError(Exception):
    """The browser could not do what was asked. ``code`` is stable."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class ContextGone(BrowserError):
    """The page navigated (or closed) under the call. Not a failure by itself."""

    def __init__(self) -> None:
        super().__init__("context_gone", "The page changed while it was being read.")


def find_binary() -> Optional[str]:
    """A Chromium this machine already has. None when there is none: the
    Desk then says the browser is not available and does nothing."""
    chosen = (os.environ.get(_ENV_BINARY) or "").strip()
    if chosen:
        return chosen if os.path.isfile(chosen) else None
    roots = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
             os.path.expanduser("~/.cache/ms-playwright"), os.path.expanduser("~/Library/Caches/ms-playwright")]
    # The headless shell first: it needs nothing else installed. The newest build of whichever is found.
    for patterns in (("chromium_headless_shell-*/chrome-headless-shell*/chrome-headless-shell*",
                      "chromium_headless_shell-*/chrome-*/headless_shell*"),
                     ("chromium-*/chrome-*/chrome", "chromium-*/chrome-*/chrome.exe")):
        found = [p for root in roots for pattern in patterns for p in glob.glob(os.path.join(root, pattern))
                 if os.path.isfile(p)]
        if found:
            return sorted(found, key=lambda p: [int(n) for n in re.findall(r"-(\d+)", p)][:1] or [0])[-1]
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        path = shutil.which(name)
        if path:
            return path
    return None


def scriba_page_bundle(scriba_backend: str) -> str:
    """Scriba's page-side modules as one script that defines ``globalThis.__scriba``.

    Read from the Scriba checkout and joined in memory: each module becomes a
    function scope, its imports are bound to the modules it names, its exports
    are returned. The modules themselves are not changed."""
    base = os.path.join(scriba_backend, "browser_extension")
    order = [("semantics", "lib/semantics.js"), ("locators", "lib/locators.js"), ("steps", "lib/steps.js"),
             ("player", "content/player.js")]
    parts = []
    for name, relative in order:
        with open(os.path.join(base, relative), encoding="utf-8") as handle:
            source = handle.read()
        binds = []
        for names, module in re.findall(r"^import\s*\{([^}]*)\}\s*from\s*'[^']*?/(\w+)\.js'\s*;?\s*$", source, re.M):
            binds.append(f"const {{{names}}} = __m.{module};")
        source = re.sub(r"^import\s[^\n]*\n", "", source, flags=re.M)
        exported = re.findall(r"^export\s+(?:async\s+)?(?:function|const|let|class)\s+(\w+)", source, re.M)
        source = re.sub(r"^export\s+", "", source, flags=re.M)
        parts.append(f"__m.{name} = (function(){{ {' '.join(binds)}\n{source}\nreturn {{{', '.join(exported)}}}; }})();")
    return ("(function(){ if (globalThis.__scriba) return; const __m = {};\n" + "\n".join(parts)
            + "\nglobalThis.__scriba = {applyStep: __m.player.applyStep, captureLocator: __m.locators.captureLocator,"
              " resolveLocator: __m.locators.resolveLocator, originAllowed: __m.steps.originAllowed,"
              " riskySubstitution: __m.semantics.riskySubstitution}; })();")


class _Connection:
    """One websocket to the browser. A reader thread hands answers to their
    callers, queues events, and lets ``on_event`` answer at once (a paused
    request must not wait for whoever is busy)."""

    def __init__(self, url: str) -> None:
        from websockets.sync.client import connect

        self.ws = connect(url, max_size=None, open_timeout=10)
        self._next = 0
        self._lock = threading.Lock()
        self._answers: Dict[int, Dict[str, Any]] = {}
        self._arrived = threading.Condition()
        self._handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self.closed = False
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        try:
            for raw in self.ws:
                message = json.loads(raw)
                if "id" in message:
                    with self._arrived:
                        self._answers[message["id"]] = message
                        self._arrived.notify_all()
                    continue
                handler = self._handlers.get(message.get("sessionId") or "")
                if handler is not None:
                    try:
                        handler(message)
                    except Exception:                 # a handler must never kill the reader
                        pass
        except Exception:
            pass
        finally:
            self.closed = True
            with self._arrived:
                self._arrived.notify_all()

    def listen(self, session: str, handler: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        if handler is None:
            self._handlers.pop(session, None)
        else:
            self._handlers[session] = handler

    def post(self, method: str, params: Optional[Dict[str, Any]] = None, session: Optional[str] = None) -> int:
        """Send without waiting for the answer."""
        with self._lock:
            self._next += 1
            message: Dict[str, Any] = {"id": self._next, "method": method, "params": params or {}}
            if session:
                message["sessionId"] = session
            self.ws.send(json.dumps(message))
            return self._next

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, session: Optional[str] = None,
             timeout: float = 30.0) -> Dict[str, Any]:
        if self.closed:
            raise BrowserError("browser_gone", "The browser is no longer running.")
        sent = self.post(method, params, session)
        deadline = time.monotonic() + timeout
        with self._arrived:
            while sent not in self._answers:
                left = deadline - time.monotonic()
                if self.closed:
                    raise BrowserError("browser_gone", "The browser stopped while it was working.")
                if left <= 0:
                    raise BrowserError("timeout", f"{method} did not answer in {timeout:.0f} s.")
                self._arrived.wait(min(left, 0.5))
            answer = self._answers.pop(sent)
        if "error" in answer:
            text = str(answer["error"].get("message") or "")
            if re.search(r"context was destroyed|Cannot find context|Inspected target navigated|"
                         r"Session with given id not found|No frame for given id", text, re.I):
                raise ContextGone()
            raise BrowserError("protocol_error", f"{method}: {text}")
        return answer.get("result") or {}

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


class Page:
    """One tab. Every request it makes passes ``allow(url)``; a refused one
    never leaves the machine and is recorded in ``blocked``."""

    def __init__(self, connection: _Connection, target: str, session: str, allow: Callable[[str], bool],
                 bundle: str) -> None:
        self.c, self.target, self.session, self.allow = connection, target, session, allow
        self.blocked: List[str] = []
        self.requests = 0
        self.url = "about:blank"
        self._frame: Optional[str] = None
        self._world: Optional[int] = None
        self._loads = 0                    # documents that reached DOMContentLoaded
        self._full_loads = 0               # documents that finished loading everything
        self._failures = 0                 # documents that could not be loaded
        self._navigations = 0              # navigations that started
        self._changed = threading.Condition()
        self.remote_addresses: List[str] = []
        connection.listen(session, self._on_event)
        for method, params in (("Page.enable", {}), ("Runtime.enable", {}),
                               ("Page.setLifecycleEventsEnabled", {"enabled": True}),
                               ("Network.enable", {}),
                               ("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}),
                               ("Page.addScriptToEvaluateOnNewDocument", {"source": bundle, "worldName": WORLD})):
            self.c.call(method, params, session)
        self._frame = self.c.call("Page.getFrameTree", {}, session)["frameTree"]["frame"]["id"]

    # ── events (reader thread) ──────────────────────────────────────────
    def _on_event(self, message: Dict[str, Any]) -> None:
        method, params = message.get("method"), message.get("params") or {}
        if method == "Fetch.requestPaused":
            url = str((params.get("request") or {}).get("url") or "")
            self.requests += 1
            if url.startswith(("data:", "blob:", "about:", "chrome-error:")) or self.allow(url):
                self.c.post("Fetch.continueRequest", {"requestId": params["requestId"]}, self.session)
            else:
                self.blocked.append(url.split("?")[0][:200])
                self.c.post("Fetch.failRequest", {"requestId": params["requestId"],
                                                  "errorReason": "BlockedByClient"}, self.session)
            return
        with self._changed:
            if method == "Runtime.executionContextCreated":
                context = params.get("context") or {}
                aux = context.get("auxData") or {}
                if context.get("name") == WORLD and aux.get("frameId") == self._frame:
                    self._world = context.get("id")
            elif method == "Runtime.executionContextsCleared":
                self._world = None
            elif method == "Runtime.executionContextDestroyed":
                if params.get("executionContextId") == self._world:
                    self._world = None
            elif method in ("Page.frameStartedLoading", "Page.frameRequestedNavigation"):
                if params.get("frameId") == self._frame:
                    self._navigations += 1
            elif method == "Page.frameNavigated":
                frame = params.get("frame") or {}
                if frame.get("id") == self._frame:
                    self.url = str(frame.get("url") or self.url)
            elif method == "Page.navigatedWithinDocument":
                if params.get("frameId") == self._frame:
                    self.url = str(params.get("url") or self.url)
            elif method == "Page.lifecycleEvent":
                if params.get("frameId") == self._frame and params.get("name") == "DOMContentLoaded":
                    self._loads += 1
                elif params.get("frameId") == self._frame and params.get("name") == "load":
                    self._full_loads += 1
            elif method == "Network.loadingFailed":
                if params.get("type") == "Document":
                    self._failures += 1
            elif method == "Network.responseReceived":
                address = str((params.get("response") or {}).get("remoteIPAddress") or "")
                if address and address not in self.remote_addresses:
                    self.remote_addresses.append(address)
            else:
                return
            self._changed.notify_all()

    def _wait(self, ready: Callable[[], bool], timeout: float, what: str) -> None:
        deadline = time.monotonic() + timeout
        with self._changed:
            while not ready():
                left = deadline - time.monotonic()
                if self.c.closed:
                    raise BrowserError("browser_gone", "The browser stopped while it was working.")
                if left <= 0:
                    raise BrowserError("timeout", f"{what} did not happen in {timeout:.1f} s.")
                self._changed.wait(min(left, 0.25))

    # ── navigation ──────────────────────────────────────────────────────
    def marks(self) -> tuple:
        with self._changed:
            return self._navigations, self._loads, self._failures

    def wait_ready(self, timeout: float = 15.0) -> None:
        """Wait until the current document can be looked at."""
        self._wait(lambda: self._world is not None, timeout, "The page")

    def goto(self, url: str, *, timeout: float = 15.0) -> None:
        """Navigate and return when the new document's DOM is ready (not when
        every image has loaded: the next step waits for what it needs)."""
        if not self.allow(url):
            raise BrowserError("origin_not_allowed", "That address is not one of this task's sites.")
        loads = self.marks()[1]
        answer = self.c.call("Page.navigate", {"url": url}, self.session, timeout=timeout)
        if answer.get("errorText"):
            code = "origin_not_allowed" if "BLOCKED_BY_CLIENT" in answer["errorText"] else "navigation_failed"
            raise BrowserError(code, f"The page could not be opened ({answer['errorText']}).")
        self._wait(lambda: self._loads > loads and self._world is not None, timeout, "The page")

    def settle(self, before: tuple, *, timeout: float = 15.0) -> bool:
        """After an action: did the page start to navigate? If so wait for the
        new document. One short round trip instead of a fixed pause."""
        try:
            self.evaluate("new Promise(r => setTimeout(r, 0))", timeout=5.0)
        except ContextGone:
            pass
        if self.marks()[0] == before[0] and self._world is not None:
            return False
        self._wait(lambda: (self._loads > before[1] and self._world is not None) or self._failures > before[2],
                   timeout, "The next page")
        if self._loads <= before[1] or self.url.startswith("chrome-error:"):
            raise BrowserError("no_answer", "The site did not answer.")
        return True

    def stop_loading(self) -> None:
        try:
            self.c.call("Page.stopLoading", {}, self.session, timeout=5.0)
        except BrowserError:
            pass

    # ── the page's isolated world ───────────────────────────────────────
    def evaluate(self, expression: str, *, timeout: float = 15.0) -> Any:
        """Evaluate in the isolated world where Scriba's page code lives. The
        page's own scripts cannot see or change that world."""
        world = self._world
        if world is None:
            self._wait(lambda: self._world is not None, min(timeout, 5.0), "The page's script world")
            world = self._world
        try:
            answer = self.c.call("Runtime.evaluate", {"expression": expression, "contextId": world,
                                                      "awaitPromise": True, "returnByValue": True},
                                 self.session, timeout=timeout)
        except ContextGone:
            self._forget(world)
            raise
        if answer.get("exceptionDetails"):
            detail = answer["exceptionDetails"]
            text = str((detail.get("exception") or {}).get("description") or detail.get("text") or "")
            if re.search(r"context was destroyed|navigat", text, re.I):
                self._forget(world)
                raise ContextGone()
            raise BrowserError("script_error", text[:300])
        return (answer.get("result") or {}).get("value")

    def _forget(self, world: Optional[int]) -> None:
        with self._changed:
            if self._world == world:
                self._world = None

    def call_function(self, name: str, *args: Any, timeout: float = 15.0) -> Any:
        return self.evaluate(f"{name}({', '.join(json.dumps(a) for a in args)})", timeout=timeout)

    def close(self) -> None:
        self.c.listen(self.session, None)
        try:
            self.c.call("Target.closeTarget", {"targetId": self.target}, timeout=5.0)
        except BrowserError:
            pass


class Browser:
    """One Chromium process, started on first use and kept. Each caller gets
    its own context: cookies of one never reach another, and none is written
    to disk."""

    def __init__(self, binary: Optional[str] = None) -> None:
        self.binary = binary or find_binary()
        self._process: Optional[subprocess.Popen] = None
        self._connection: Optional[_Connection] = None
        self._profile: Optional[str] = None
        self._contexts: Dict[str, str] = {}
        self._lock = threading.RLock()
        self.started_ms: Optional[float] = None

    @property
    def available(self) -> bool:
        return bool(self.binary)

    @property
    def running(self) -> bool:
        return bool(self._process and self._process.poll() is None and self._connection
                    and not self._connection.closed)

    def start(self) -> float:
        """Start the browser if it is not running. Returns how long that took
        in milliseconds (0.0 when it was already there)."""
        with self._lock:
            if self.running:
                return 0.0
            if not self.binary:
                raise BrowserError("no_browser", "No Chromium was found on this machine.")
            self.stop()
            began = time.perf_counter()
            self._profile = tempfile.mkdtemp(prefix="desk-browser-")
            arguments = [self.binary, "--remote-debugging-port=0", f"--user-data-dir={self._profile}",
                         "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
                         "--disable-background-networking", "--disable-default-apps", "--disable-component-update",
                         "--disable-gpu", "--mute-audio", "--no-proxy-server", "--password-store=basic",
                         "--disable-features=Translate,MediaRouter,OptimizationHints", "about:blank"]
            if "headless" not in os.path.basename(self.binary).lower():
                arguments.insert(1, "--headless=new")
            self._process = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            port_file = os.path.join(self._profile, "DevToolsActivePort")
            deadline = time.monotonic() + 20
            port = path = ""
            while not (port and path):
                # The browser writes this file as it starts listening. Until it is whole, wait.
                try:
                    with open(port_file, encoding="utf-8") as handle:
                        lines = handle.read().splitlines()
                    if len(lines) >= 2 and lines[0].strip().isdigit() and lines[1].strip():
                        port, path = lines[0], lines[1]
                        break
                except OSError:
                    pass
                if self._process.poll() is not None:
                    raise BrowserError("no_browser", "The browser exited as it started.")
                if time.monotonic() > deadline:
                    raise BrowserError("timeout", "The browser did not start in 20 s.")
                time.sleep(0.01)
            self._connection = _Connection(f"ws://127.0.0.1:{port.strip()}{path.strip()}")
            self._contexts = {}
            self.started_ms = (time.perf_counter() - began) * 1000
            return self.started_ms

    def page(self, owner: str, allow: Callable[[str], bool], bundle: str) -> Page:
        """A new tab in ``owner``'s context (made on first use)."""
        with self._lock:
            self.start()
            assert self._connection is not None
            context = self._contexts.get(owner)
            if context is None:
                context = self._connection.call("Target.createBrowserContext", {"disposeOnDetach": False})[
                    "browserContextId"]
                self._contexts[owner] = context
            target = self._connection.call("Target.createTarget", {"url": "about:blank",
                                                                   "browserContextId": context})["targetId"]
            session = self._connection.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            return Page(self._connection, target, session, allow, bundle)

    def forget(self, owner: str) -> None:
        """Drop a caller's context: its cookies and storage are gone."""
        with self._lock:
            context = self._contexts.pop(owner, None)
            if context and self._connection and not self._connection.closed:
                try:
                    self._connection.call("Target.disposeBrowserContext", {"browserContextId": context}, timeout=5.0)
                except BrowserError:
                    pass

    def kill(self) -> None:
        """Stop the process abruptly (used to test an interrupted run)."""
        if self._process and self._process.poll() is None:
            self._process.kill()
            self._process.wait(timeout=10)

    def stop(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    if not self._connection.closed:
                        self._connection.call("Browser.close", {}, timeout=3.0)
                except BrowserError:
                    pass
                self._connection.close()
                self._connection = None
            if self._process is not None:
                try:
                    self._process.wait(timeout=5)
                except Exception:
                    self._process.kill()
                self._process = None
            if self._profile:
                shutil.rmtree(self._profile, ignore_errors=True)
                self._profile = None
            self._contexts = {}
