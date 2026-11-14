"""The browser as a tool of the Desk: a task on an authorised site, carried
out step by step, each step looked up on the live page and verified.

What is Scriba's and what is the Desk's
---------------------------------------
Scriba's browser automation replays a recording: its page-side player applies
one step to an element, its step cleaner and site confinement guard the
recording, its lexicon says which labels commit something, its content guard
finds text written to an assistant, its readers open files. All of those are
used here as they are (see ``docs/handoff/BROWSER_AGENT.md``).

What Scriba does not have, and this module adds: a task that is not a
recording (steps name what to do; the element is found on the page as it is
now), waiting on the page instead of on a clock, a download, reading values
and tables, recovering when a dialog is in the way or the page is slow, and
an account of every step.

Rules this module keeps
-----------------------
- **Only authorised sites.** A task belongs to one site. Every request of its
  page passes the same gate: the site's exact origin, nothing else. A link or
  script that leads elsewhere is refused and recorded.
- **No internal addresses.** A site on a private, loopback, link-local or
  metadata address is refused. The one exception is a synthetic site on
  loopback inside a sandbox world.
- **A page is data.** Nothing a page says changes the task. Text written to
  an assistant is reported; while it is there, nothing is submitted.
- **Reading is free, changing is not.** Opening, following a link, reading
  and downloading run without asking. Filling and submitting run only with
  an approval bound to the exact site, fields, values and buttons.
- **A password is never typed.** The only exception is the made-up account
  of a synthetic site.
- **An uncertain submission is never repeated.** It is read back.
- Model calls: none. Every decision here is a rule.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from . import browser_cdp, files
from .browser_cdp import BrowserError, ContextGone
from .browser_page import DESK_PAGE_JS

OPS = ("open", "follow", "read", "find_row", "download", "fill", "submit", "expect")
WRITE_OPS = ("fill", "submit")
CHECKS = ("url_contains", "text_present")
# VERIFIED: every download was opened and every submission read back. COMPLETED: the task only
# looked and read; there was nothing to verify beyond the values it returns.
STATES = ("VERIFIED", "COMPLETED", "FAILED", "NEEDS_APPROVAL", "HELD", "OUTCOME_UNKNOWN", "NOT_APPLIED",
          "INTERRUPTED", "CANCELLED")
MAX_OPS = 40
MAX_DOWNLOAD = files.MAX_FILE_BYTES
ELEMENT_WAIT_MS = 5000
NAVIGATION_SECONDS = 15.0
TASK_SECONDS = 60.0
# A dialog may be closed without asking only by a button that says so and commits nothing.
_DISMISS = re.compile(r"^(close|dismiss|not now|no,? thanks|later|skip|decline|reject( all)?|got it|ok|×|x)$", re.I)
_PERIOD = re.compile(r"\bQ([1-4])\s*(20\d\d)\b|\b(20\d\d)-(\d\d)(?:-(\d\d))?\b", re.I)


# ── which sites ──────────────────────────────────────────────────────────────
def origin_of(url: str) -> Optional[str]:
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    default = {"http": 80, "https": 443}[parts.scheme]
    port = "" if parts.port in (None, default) else f":{parts.port}"
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme}://{host}{port}"


def _addresses(host: str) -> List[Any]:
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass
    try:
        found = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return []
    return [ipaddress.ip_address(item.split("%")[0]) for item in found]


def site_problems(site: Mapping[str, Any], *, sandbox: bool) -> List[str]:
    """Why this site may not be browsed, or []. Scriba's own checks refuse an
    ambiguous address and a metadata or link-local host; the Desk adds what
    they leave out: private and loopback addresses, by name too."""
    from app.ai import egress

    origin = str(site.get("origin") or "")
    parts = urlsplit(origin)
    if origin_of(origin) != origin or parts.path not in ("", "/") or parts.query or parts.fragment:
        return ["The site's address must be an origin: scheme, host and port, nothing more."]
    if egress.ambiguous_url(origin):
        return ["The site's address is written in a way that can be read two ways."]
    host = parts.hostname or ""
    if egress.metadata_or_link_local(host):
        return ["That address is a metadata or link-local address. It is never browsed."]
    addresses = _addresses(host)
    if not addresses:
        return ["The site's name does not resolve to an address."]
    synthetic = bool(site.get("synthetic")) and sandbox
    for address in addresses:
        if address.is_loopback and synthetic:
            continue
        if not address.is_global or address.is_multicast:
            return ["That address is inside a private network or on this machine. It is not browsed."]
    if parts.scheme != "https" and not synthetic:
        return ["A real site must be reached over https."]
    return []


# ── which task ───────────────────────────────────────────────────────────────
def _text(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def validate(task: Any) -> Tuple[Dict[str, Any], List[str]]:
    """The task in a fixed shape, and what is wrong with it. Nothing is
    repaired: a step with a problem is a reason not to start."""
    problems: List[str] = []
    if not isinstance(task, Mapping) or not isinstance(task.get("ops"), list) or not task["ops"]:
        return {}, ["A browser task needs at least one step."]
    if len(task["ops"]) > MAX_OPS:
        return {}, [f"A browser task has at most {MAX_OPS} steps."]
    clean: List[Dict[str, Any]] = []
    for index, raw in enumerate(task["ops"], start=1):
        where = f"Step {index}"
        if not isinstance(raw, Mapping) or raw.get("op") not in OPS:
            problems.append(f"{where}: op must be one of {', '.join(OPS)}.")
            continue
        op = str(raw["op"])
        entry: Dict[str, Any] = {"op": op}
        expect = raw.get("expect")
        if expect is not None:
            if not isinstance(expect, Mapping) or expect.get("check") not in CHECKS or not _text(expect.get("text")):
                problems.append(f"{where}: expect needs a check ({', '.join(CHECKS)}) and a text.")
                continue
            entry["expect"] = {"check": expect["check"], "text": _text(expect["text"], 500)}
        if op == "open":
            path = _text(raw.get("path"), 1000)
            # A path, never an address: a task cannot name another site.
            if not path.startswith("/") or path.startswith("//") or "\\" in path:
                problems.append(f"{where}: path must start with one slash; a task cannot name another site.")
                continue
            entry["path"] = path
        elif op in ("follow", "submit", "download"):
            entry["name"] = _text(raw.get("name"))
            if not entry["name"]:
                problems.append(f"{where}: name the link or button as the page shows it.")
                continue
            if op == "follow" and raw.get("pick") is not None:
                if raw.get("pick") != "latest":
                    problems.append(f"{where}: pick can only be \"latest\".")
                    continue
                entry["pick"] = "latest"
            if op == "download":
                entry["kind"] = _text(raw.get("kind"), 10).lower() or None
                entry["checksum"] = _text(raw.get("checksum"), 100) or None
            if op == "submit" and raw.get("readback") is not None:
                back = raw["readback"]
                if not isinstance(back, Mapping) or not str(back.get("path") or "").startswith("/") \
                        or not (isinstance(back.get("fields"), Mapping) or _text(back.get("text"))):
                    problems.append(f"{where}: readback needs a path and the fields or text that show the change.")
                    continue
                entry["readback"] = {"path": _text(back["path"], 1000),
                                     "fields": {_text(k): str(v)[:2000] for k, v in (back.get("fields") or {}).items()},
                                     "text": _text(back.get("text"), 500) or None}
        elif op == "read":
            entry["label"], entry["name"] = _text(raw.get("label")), _text(raw.get("name") or raw.get("label"), 80)
            if not entry["label"]:
                problems.append(f"{where}: name the label whose value is wanted.")
                continue
        elif op == "find_row":
            entry.update(table=_text(raw.get("table")), match=_text(raw.get("match")),
                         name=_text(raw.get("name") or "row", 80))
            if not entry["match"]:
                problems.append(f"{where}: say what the row contains.")
                continue
        elif op == "fill":
            fields = raw.get("fields")
            if not isinstance(fields, Mapping) or not fields or len(fields) > 40 \
                    or any(not _text(k) or not isinstance(v, (str, int, float)) or isinstance(v, bool)
                           for k, v in fields.items()):
                problems.append(f"{where}: fields must map each field's label to a text or a number.")
                continue
            entry["fields"] = {_text(k): str(v)[:2000] for k, v in fields.items()}
        elif op == "expect":
            if "expect" not in entry:
                problems.append(f"{where}: expect needs a check and a text.")
                continue
        clean.append(entry)
    return {"goal": _text(task.get("goal"), 200), "ops": clean}, problems


def writes(task: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [dict(op) for op in task.get("ops") or [] if op.get("op") in WRITE_OPS]


def binding(site: Mapping[str, Any], task: Mapping[str, Any]) -> Optional[str]:
    """What an approval of a change on a site is bound to: this origin, these
    fields with these values, these buttons, in this order. None for a task
    that only reads."""
    changing = writes(task)
    if not changing:
        return None
    material = json.dumps({"origin": site.get("origin"), "writes": changing}, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def describe_writes(site: Mapping[str, Any], task: Mapping[str, Any]) -> Dict[str, Any]:
    """What a person approves, in full: where, which fields get which values,
    which buttons are pressed."""
    return {"site": site.get("name"), "origin": site.get("origin"), "binding": binding(site, task),
            "fields": [{"label": label, "value": value} for op in writes(task) if op["op"] == "fill"
                       for label, value in op["fields"].items()],
            "buttons": [op["name"] for op in writes(task) if op["op"] == "submit"]}


def commits(name: str, tag: str = "button") -> bool:
    """Does a control with this label commit, send, pay or destroy something?
    Scriba's own lexicon and rule (``recording_risk.committing_clicks``)."""
    from app.services import recording_risk

    return bool(recording_risk.committing_clicks([{"action": "click", "locator": {"text": name, "tag": tag}}]))


def _path(url: Any) -> str:
    """Where a step happened, without a query string (it may carry a token)."""
    parts = urlsplit(str(url or ""))
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.netloc else str(url or "")[:200]


def _period_rank(text: str) -> Optional[Tuple[int, int, int]]:
    found = [(int(y), int(q) * 3, 0) if q else (int(year), int(month), int(day or 0))
             for q, y, year, month, day in _PERIOD.findall(text or "")]
    return max(found) if found else None


# ── a session: one person on one site ────────────────────────────────────────
class Session:
    """One page of one owner on one site, kept between tasks so that a second
    task needs neither a new browser nor a new sign-in."""

    def __init__(self, sessions: "Sessions", owner: str, site: Mapping[str, Any]) -> None:
        self.sessions, self.owner, self.site = sessions, owner, dict(site)
        self.origin = str(site["origin"])
        self.page: Optional[browser_cdp.Page] = None
        self.signed_in = False
        self.learned: Dict[str, Dict[str, Any]] = {}       # per step signature: a Scriba locator that worked
        self.timings: Dict[str, float] = {}
        self.lock = threading.RLock()

    def allow(self, url: str) -> bool:
        return origin_of(url) == self.origin

    def ensure(self) -> browser_cdp.Page:
        browser = self.sessions.browser
        if self.page is not None and browser.running:
            return self.page
        self.signed_in = self.signed_in and browser.running
        self.timings["browserStartMs"] = round(browser.start(), 1)
        began = time.perf_counter()
        self.page = browser.page(f"{self.owner}|{self.site.get('id')}", self.allow, self.sessions.bundle)
        self.timings["pageMs"] = round((time.perf_counter() - began) * 1000, 1)
        return self.page

    def close(self) -> None:
        if self.page is not None:
            try:
                self.page.close()
            except Exception:
                pass
        self.page = None


class Sessions:
    """The Desk's browser: one Chromium, started on first use, and the
    sessions in it. Nothing here outlives the process: no profile, no cookie
    file."""

    def __init__(self, scriba_backend: str, binary: Optional[str] = None) -> None:
        self.browser = browser_cdp.Browser(binary)
        self.scriba_backend = scriba_backend
        self._bundle: Optional[str] = None
        self._sessions: Dict[Tuple[str, str], Session] = {}
        self._lock = threading.RLock()

    @property
    def bundle(self) -> str:
        if self._bundle is None:
            self._bundle = browser_cdp.scriba_page_bundle(self.scriba_backend) + "\n" + DESK_PAGE_JS
        return self._bundle

    def status(self) -> Dict[str, Any]:
        if not self.browser.available:
            return {"available": False, "reason": "no_browser", "running": False,
                    "message": "No Chromium was found on this backend, so nothing can be browsed."}
        try:
            _ = self.bundle
        except OSError:
            return {"available": False, "reason": "scriba_player_missing", "running": False,
                    "message": "Scriba's browser extension is not in this Scriba checkout."}
        return {"available": True, "reason": None, "running": self.browser.running, "message": None}

    def session(self, owner: str, site: Mapping[str, Any]) -> Session:
        key = (str(owner), str(site.get("id") or site.get("origin")))
        with self._lock:
            found = self._sessions.get(key)
            if found is None or found.origin != site.get("origin"):
                found = self._sessions[key] = Session(self, key[0], site)
            return found

    def forget(self, owner: str) -> None:
        with self._lock:
            for key in [k for k in self._sessions if k[0] == str(owner)]:
                session = self._sessions.pop(key)
                session.close()
                self.browser.forget(f"{key[0]}|{session.site.get('id')}")

    def stop(self) -> None:
        with self._lock:
            self._sessions.clear()
            self.browser.stop()


# ── carrying a task out ──────────────────────────────────────────────────────
class _Stop(Exception):
    def __init__(self, state: str, code: str, message: str) -> None:
        super().__init__(message)
        self.state, self.code, self.message = state, code, message


class Run:
    """One task, on one session. ``record`` is told about each step as it
    ends, and about a submission BEFORE it is made, so that whoever keeps the
    record can tell "never sent" from "sent, answer unknown"."""

    def __init__(self, session: Session, task: Mapping[str, Any], *, approval: Optional[str] = None,
                 record: Optional[Callable[[Dict[str, Any]], None]] = None,
                 cancelled: Optional[Callable[[], bool]] = None, submitted: Optional[List[int]] = None,
                 use_learned: bool = True, budget: float = TASK_SECONDS) -> None:
        self.s, self.task, self.approval = session, task, approval
        self.record = record or (lambda step: None)
        self.cancelled = cancelled or (lambda: False)
        # Steps whose submission was already made in an earlier attempt: read back, never pressed again.
        self.submitted = set(submitted or [])
        self.use_learned = use_learned
        self.deadline = time.monotonic() + budget
        self.steps: List[Dict[str, Any]] = []
        self.values: Dict[str, Any] = {}
        self.downloads: List[Dict[str, Any]] = []
        self.findings: List[Dict[str, Any]] = []
        self.ignored: List[Dict[str, Any]] = []
        self.actions = 0
        self._scanned: set = set()
        self._began = time.perf_counter()

    # ── plumbing ────────────────────────────────────────────────────────
    @property
    def page(self) -> browser_cdp.Page:
        assert self.s.page is not None
        return self.s.page

    def _desk(self, function: str, *arguments: Any, timeout: float = 15.0) -> Any:
        """Call a page helper. A page that navigates under the call is looked at again, once."""
        for attempt in (1, 2):
            try:
                return self.page.call_function(f"__desk.{function}", *arguments, timeout=timeout)
            except ContextGone:
                if attempt == 2:
                    raise BrowserError("page_changed", "The page kept changing while it was being read.")
                self.page.wait_ready(NAVIGATION_SECONDS)
        return None

    def _check(self) -> None:
        if self.cancelled():
            raise _Stop("CANCELLED", "cancelled", "The task was cancelled. Steps already done are listed.")
        if time.monotonic() > self.deadline:
            raise _Stop("INTERRUPTED", "task_budget_exceeded", "The task took longer than it is allowed.")

    def _scan(self) -> None:
        """Hand the page's text to Scriba's content guard, once per page. What
        it finds is reported; it never becomes an instruction."""
        from app.services import content_guard

        texts = self._desk("texts")
        where = _path(texts.get("url"))
        if where in self._scanned:
            return
        self._scanned.add(where)
        for part in ("visible", "hidden"):
            for finding in content_guard.scan_untrusted_text(str(texts.get(part) or ""))[:5]:
                self.findings.append({"url": where, "where": part, "finding": str(finding)[:200]})

    def _goto(self, url: str, evidence: Dict[str, Any]) -> None:
        """Open an address of the site. One slow answer is tried once more."""
        for attempt in (1, 2):
            try:
                self.page.goto(url, timeout=min(NAVIGATION_SECONDS, max(1.0, self.deadline - time.monotonic())))
                return
            except BrowserError as error:
                if error.code != "timeout" or attempt == 2:
                    raise
                self.page.stop_loading()
                evidence.setdefault("recovered", []).append("slow_page_tried_again")

    def _sign_in(self, evidence: Dict[str, Any]) -> None:
        """A synthetic site's made-up account, and nothing else. A real site
        that asks for a sign-in stops the task: the Desk holds no passwords."""
        entry = self.s.site.get("signIn") or {}
        if not (self.s.site.get("synthetic") and entry.get("synthetic") and entry.get("fields")):
            raise _Stop("FAILED", "sign_in_required",
                        "The site asks for a sign-in. The Desk holds no passwords and does not type one.")
        for label, value in entry["fields"].items():
            seen = self._desk("look", "field", label, ELEMENT_WAIT_MS)
            if not seen["candidates"]:
                raise _Stop("FAILED", "sign_in_failed", "The sign-in page does not look as expected.")
            done = self._desk("act", "found", seen["candidates"][0]["i"], {"action": "fill", "text": value},
                              [self.s.origin])
            if (done.get("out") or {}).get("error") or not done.get("out"):
                raise _Stop("FAILED", "sign_in_failed", "The sign-in page could not be filled in.")
        seen = self._desk("look", "button", entry.get("submit") or "Sign in", ELEMENT_WAIT_MS)
        if not seen["candidates"]:
            raise _Stop("FAILED", "sign_in_failed", "The sign-in page has no sign-in button.")
        before = self.page.marks()
        self._desk("act", "found", seen["candidates"][0]["i"], {"action": "click"}, [self.s.origin])
        self.page.settle(before, timeout=NAVIGATION_SECONDS)
        if urlsplit(self.page.url).path == entry.get("path"):
            raise _Stop("FAILED", "sign_in_failed", "The site did not accept the sign-in.")
        self.s.signed_in = True
        evidence.setdefault("recovered", []).append("signed_in")

    def _at_sign_in(self) -> bool:
        path = (self.s.site.get("signIn") or {}).get("path")
        return bool(path) and urlsplit(self.page.url).path == path

    def _dismiss(self, dialog: Mapping[str, Any], evidence: Dict[str, Any]) -> bool:
        """Close a dialog that is in the way, by a button that only closes."""
        for button in dialog.get("buttons") or []:
            name = str(button.get("name") or "")
            if _DISMISS.match(name) and not commits(name) and not button.get("submits"):
                self._desk("act", "dialog", button["i"], {"action": "click"}, [self.s.origin])
                self.actions += 1
                evidence.setdefault("recovered", []).append(f"closed_dialog:{dialog.get('name')}")
                return True
        return False

    def _expect(self, expect: Mapping[str, Any]) -> bool:
        out = self.page.call_function("__scriba.applyStep", {"action": "verify", "check": expect["check"],
                                                              "text": expect["text"]}, [self.s.origin])
        return bool(out and out.get("check") == "passed")

    # ── finding and pressing ────────────────────────────────────────────
    def _find(self, kind: str, op: Mapping[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
        """The one control this step means, on the page as it is now."""
        name = op["name"]
        for attempt in (1, 2, 3):
            self._check()
            seen = self._desk("look", kind, name, ELEMENT_WAIT_MS if attempt == 1 else 1500,
                              timeout=ELEMENT_WAIT_MS / 1000 + 10)
            dialog = seen.get("dialog")
            candidates = seen.get("candidates") or []
            if dialog and not any(c.get("inDialog") for c in candidates):
                # Something is in front of the page. Deal with that first, then look again.
                if not self._dismiss(dialog, evidence):
                    raise _Stop("FAILED", "blocked_by_dialog",
                                f"A dialog (\"{dialog.get('name')}\") is in the way and none of its buttons only "
                                "closes it. It is left for you.")
                continue
            here, elsewhere = [], []
            for candidate in candidates:
                target = candidate.get("href") or candidate.get("formAction")
                (here if not target or self.s.allow(target) else elsewhere).append(candidate)
            for candidate in elsewhere:
                self.ignored.append({"name": candidate["name"], "reason": "leads_to_another_site",
                                     "origin": origin_of(candidate.get("href") or candidate.get("formAction") or "")})
            if not here:
                if attempt < 3 and self._at_sign_in():
                    self._sign_in(evidence)
                    continue
                if attempt < 2:
                    continue
                shown = self._desk("page")
                evidence["page"] = {k: shown.get(k) for k in ("title", "headings", "links", "buttons")}
                raise _Stop("FAILED", "target_not_found",
                            f"The page has no {kind} called \"{name}\"." if not elsewhere else
                            f"The only {kind} called \"{name}\" leads to another site, so it was not used.")
            if op.get("pick") == "latest":
                ranked = sorted(((_period_rank(c["name"]) or _period_rank(c.get("context") or ""), c) for c in here),
                                key=lambda pair: pair[0] or (0, 0, 0), reverse=True)
                if ranked[0][0] is None or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
                    raise _Stop("FAILED", "ambiguous_target", f"Which \"{name}\" is the latest cannot be told from the page.")
                evidence["picked"] = {"name": ranked[0][1]["name"], "from": len(here)}
                return ranked[0][1]
            best = [c for c in here if c["score"] == here[0]["score"]]
            if len(best) > 1:
                raise _Stop("FAILED", "ambiguous_target",
                            f"The page has {len(best)} {kind}s called \"{name}\". None was chosen.")
            return best[0]
        raise _Stop("FAILED", "target_not_found", f"The page has no {kind} called \"{name}\".")

    def _press(self, kind: str, op: Mapping[str, Any], evidence: Dict[str, Any], *, key: str,
               allow_commit: bool) -> None:
        """Find, check and press one control; say how it was found."""
        from app.services import web_steps

        hint = self.s.learned.get(key) if self.use_learned and not op.get("pick") else None
        if hint:
            # A locator that worked before, through Scriba's own resolver. It is used only if the
            # control it points at is still called what the step says.
            before = self.page.marks()
            done = self._desk("replay", {"action": "click", "locator": hint}, [self.s.origin], 300, op["name"])
            if not done.get("missing") and (done.get("out") or {}).get("done"):
                self.actions += 1
                evidence.update(how="kept_locator", matchedBy=done.get("matchedBy"), healed=bool(done.get("healed")),
                                navigated=self.page.settle(before, timeout=NAVIGATION_SECONDS))
                return
            self.s.learned.pop(key, None)
            evidence.setdefault("recovered", []).append("kept_locator_no_longer_fits")
        target = self._find(kind, op, evidence)
        if target.get("disabled"):
            raise _Stop("FAILED", "target_disabled", f"\"{target['name']}\" is there and cannot be used.")
        committing = bool(target.get("submits")) or target.get("formMethod") == "post" \
            or commits(target["name"], target.get("tag") or "button")
        if committing and not allow_commit:
            raise _Stop("NEEDS_APPROVAL", "would_commit",
                        f"\"{target['name']}\" would submit or change something. That needs your approval first.")
        evidence["destination"] = _path(target.get("formAction") or target.get("href") or self.page.url)
        before = self.page.marks()
        done = self._desk("act", "found", target["i"], {"action": "click"}, [self.s.origin])
        if done.get("stale") or done.get("ambiguous"):
            raise BrowserError("page_changed", "The page changed between looking and pressing.")
        out = done.get("out") or {}
        if out.get("error"):
            raise _Stop("FAILED", "step_refused", str(out["error"])[:300])
        self.actions += 1
        if not committing and not op.get("pick"):
            try:                              # kept for next time, cleaned by Scriba's own step cleaner
                self.s.learned[key] = web_steps.sanitize_web_steps(
                    [{"action": "click", "locator": done.get("locator")}])[0]["locator"]
            except ValueError:
                pass
        evidence.update(how="looked_up", matchedBy=done.get("matchedBy"),
                        navigated=self.page.settle(before, timeout=NAVIGATION_SECONDS))

    # ── the steps ───────────────────────────────────────────────────────
    def _open(self, op: Mapping[str, Any], evidence: Dict[str, Any], index: int) -> None:
        self._goto(self.s.origin + op["path"], evidence)
        if self._at_sign_in() and urlsplit(op["path"]).path != (self.s.site.get("signIn") or {}).get("path"):
            self._sign_in(evidence)
            if urlsplit(self.page.url).path != urlsplit(op["path"]).path:
                self._goto(self.s.origin + op["path"], evidence)
        if "expect" in op and not self._expect(op["expect"]):
            raise _Stop("FAILED", "not_as_expected", f"The page does not show \"{op['expect']['text']}\".")

    def _follow(self, op: Mapping[str, Any], evidence: Dict[str, Any], index: int) -> None:
        was = self.page.url
        for attempt in (1, 2):
            self._press("control", op, evidence, key=f"{index}:{op['name']}", allow_commit=False)
            moved = evidence.get("navigated") or self.page.url != was
            if ("expect" in op and self._expect(op["expect"])) or ("expect" not in op and moved):
                return
            # Nothing seems to have happened. Look at the page again before doing anything else.
            dialog = (self._desk("page") or {}).get("dialog")
            if "expect" not in op and self.page.url != was:
                return                        # it did move; the page was only slow to say so
            if attempt == 1 and dialog and self._dismiss(dialog, evidence):
                self.s.learned.pop(f"{index}:{op['name']}", None)
                continue
            if "expect" in op and moved:
                raise _Stop("FAILED", "not_as_expected", f"The next page does not show \"{op['expect']['text']}\".")
            raise _Stop("FAILED", "no_effect", f"Pressing \"{op['name']}\" changed nothing on the page.")

    def _read(self, op: Mapping[str, Any], evidence: Dict[str, Any], index: int) -> None:
        found = self._desk("read", op["label"], ELEMENT_WAIT_MS, timeout=ELEMENT_WAIT_MS / 1000 + 10)
        if not found.get("found"):
            raise _Stop("FAILED", "value_not_found", f"The page shows no value for \"{op['label']}\".")
        self.values[op["name"]] = found["value"]
        evidence.update(how=found.get("how"), value=found["value"][:200])

    def _find_row(self, op: Mapping[str, Any], evidence: Dict[str, Any], index: int) -> None:
        first = self._desk("table", op["table"], ELEMENT_WAIT_MS, timeout=ELEMENT_WAIT_MS / 1000 + 10)
        if not first.get("found"):
            raise _Stop("FAILED", "table_not_found", f"The page has no table called \"{op['table']}\".")
        want = op["match"].lower()
        pages = [first]
        here = urlsplit(str(first.get("url"))).query or "page=1"
        others = [url for url in first.get("pages") or [] if urlsplit(url).query != here and self.s.allow(url)][:20]

        def hit(tables: List[Dict[str, Any]]) -> Optional[Tuple[Dict[str, Any], List[str]]]:
            for entry in tables:
                for row in entry.get("rows") or []:
                    if any(want == cell.lower() for cell in row) or any(want in cell.lower() for cell in row):
                        return entry, row
            return None

        found = hit(pages)
        if found is None and others:
            # The other pages of the same table, read at once: reads only, same site, same session.
            pages += self._desk("tables", others, op["table"], timeout=30.0)
            found = hit(pages)
        evidence["pagesRead"] = len(pages)
        if found is None:
            raise _Stop("FAILED", "row_not_found", f"No row of \"{op['table']}\" contains \"{op['match']}\".")
        entry, row = found
        headers = entry.get("headers") or first.get("headers") or []
        self.values[op["name"]] = dict(zip(headers, row)) if len(headers) == len(row) else list(row)
        where = urlsplit(str(entry.get("url")))
        evidence.update(foundOn=where.path + (f"?{where.query}" if where.query else ""), row=row[:12])

    def _download(self, op: Mapping[str, Any], evidence: Dict[str, Any], index: int) -> None:
        target = self._find("link", op, evidence)
        url = str(target.get("href") or "")
        stated = None
        if op.get("checksum"):
            shown = self._desk("read", op["checksum"], 0)
            stated = re.sub(r"\s+", "", str(shown.get("value") or "")).lower() if shown.get("found") else None
        problem = "download_failed"
        for attempt in (1, 2):
            self._check()
            got = self._desk("download", url, MAX_DOWNLOAD, timeout=60.0)
            self.actions += 1
            content = base64.b64decode(got.get("b64") or "") if got.get("ok") else b""
            name = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", str(got.get("disposition") or ""), re.I)
            filename = re.sub(r"[^\w.\- ()]", "_", (name.group(1) if name else urlsplit(url).path.rsplit("/", 1)[-1])
                              or "download")[:120]
            info = files.inspect(filename, content) if content else {"ok": False, "code": "empty"}
            opened = files.read(filename, content) if info.get("ok") else {"read": False}
            digest = files.sha256(content) if content else None
            if not got.get("ok"):
                problem = "download_failed"
            elif _path(got.get("url")) != _path(url):
                problem = "answered_from_another_page"      # a sign-in page instead of the file, for one
            elif not info.get("ok") or not opened.get("read"):
                problem = "not_a_readable_file"
            elif op.get("kind") and info.get("kind") != op["kind"]:
                problem = "not_the_expected_type"
            elif stated and digest != stated:
                problem = "checksum_differs"
            else:
                self.downloads.append({"name": op["name"], "filename": filename, "content": content,
                                       "sizeBytes": len(content), "sha256": digest, "kind": info.get("kind"),
                                       "mimeType": info.get("mime") or got.get("type"), "from": _path(url),
                                       "verified": True,
                                       "checksum": "matches_the_page" if stated else "not_stated_by_the_page"})
                evidence.update(filename=filename, sizeBytes=len(content), sha256=digest, kind=info.get("kind"),
                                verification={"verified": True, "method": "file_opened",
                                              "checksum": "matches_the_page" if stated else "not_stated_by_the_page"})
                return
            if attempt == 1:
                evidence.setdefault("recovered", []).append(f"download_tried_again:{problem}")
                gate = (self.s.site.get("signIn") or {}).get("path")
                if problem == "answered_from_another_page" and gate and urlsplit(str(got.get("url"))).path == gate:
                    # The site forgot the sign-in. Sign in again, come back to this page, then ask once more.
                    here = self.page.url
                    self._goto(self.s.origin + gate, evidence)
                    self._sign_in(evidence)
                    self._goto(here, evidence)
        evidence["verification"] = {"verified": False, "reason": problem}
        raise _Stop("FAILED", "download_not_verified",
                    f"The file could not be verified ({problem.replace('_', ' ')}). Nothing was kept.")

    def _fill(self, op: Mapping[str, Any], evidence: Dict[str, Any], index: int) -> None:
        filled = []
        for label, value in op["fields"].items():
            target = self._find("field", {"name": label}, evidence)
            if target.get("password"):
                raise _Stop("FAILED", "password_field", f"\"{label}\" is a password field. The Desk does not type one.")
            action = {"action": "select", "value": value} if target.get("tag") == "select" \
                else {"action": "fill", "text": value}
            done = self._desk("act", "found", target["i"], action, [self.s.origin])
            out = done.get("out") or {}
            if done.get("stale") or done.get("ambiguous") or out.get("error"):
                raise _Stop("FAILED", "step_refused", str(out.get("error") or "The field could not be filled in.")[:300])
            self.actions += 1
            back = self._desk("read", label, 0)
            if not back.get("found") or str(back.get("value")) != str(value):
                raise _Stop("FAILED", "field_not_set", f"\"{label}\" does not hold the value that was approved.")
            filled.append(label)
        evidence["fields"] = filled

    def _readback(self, op: Mapping[str, Any], evidence: Dict[str, Any]) -> Optional[bool]:
        """Does the site show the change? True, False, or None when the step names nothing to look at."""
        back = op.get("readback")
        if not back:
            return None
        self._goto(self.s.origin + back["path"], evidence)
        if self._at_sign_in():
            self._sign_in(evidence)
            self._goto(self.s.origin + back["path"], evidence)
        for label, value in (back.get("fields") or {}).items():
            shown = self._desk("read", label, 1500)
            if not shown.get("found") or str(shown.get("value")) != str(value):
                return False
        if back.get("text") and not self._expect({"check": "text_present", "text": back["text"]}):
            return False
        return True

    def _submit(self, op: Mapping[str, Any], evidence: Dict[str, Any], index: int) -> None:
        if index in self.submitted:
            # Pressed in an earlier attempt whose answer is not on record. Look; do not press again.
            shown = self._readback(op, evidence)
            evidence["verification"] = {"verified": bool(shown), "method": "read_back", "pressedAgain": False}
            if shown:
                return
            raise _Stop("OUTCOME_UNKNOWN" if shown is None else "NOT_APPLIED", "earlier_submission",
                        "This was submitted before and the site does not show the change. It was not submitted again.")
        if self.findings:
            raise _Stop("HELD", "untrusted_instructions",
                        "A page of this site carries text written to an assistant. Nothing was submitted.")
        self.record({"index": index, "op": "submit", "name": op["name"], "state": "submitting",
                     "url": _path(self.page.url)})
        uncertain = None
        try:
            self._press("button", op, evidence, key=f"{index}:{op['name']}", allow_commit=True)
        except BrowserError as error:
            uncertain = error                 # the press may have gone out; what came back is not known
        answered = uncertain is None and not self.page.url.startswith("chrome-error:")
        try:
            expected = answered and ("expect" not in op or self._expect(op["expect"]))
        except BrowserError:
            answered = expected = False       # the page that came back cannot even be read
        # Whatever came back, the press is not repeated. What the site now shows decides.
        shown = self._readback(op, evidence) if op.get("readback") else None
        evidence["verification"] = {"verified": bool(shown) or (shown is None and bool(expected) and "expect" in op),
                                    "method": "read_back" if shown is not None else "page_after_submit",
                                    "answered": answered, "pressedAgain": False}
        if expected and shown is not False:
            return
        if shown:
            evidence.setdefault("recovered", []).append("answer_missing_or_unexpected_read_back_instead")
            return
        if shown is False and expected:
            raise _Stop("FAILED", "verification_failed", "The site answered, and reading it back does not show the change.")
        if shown is False:
            raise _Stop("NOT_APPLIED", "no_answer" if not answered else "not_as_expected",
                        "The submission did not go through as expected, and reading the site back shows no "
                        "change. It was not submitted again.")
        if not answered:
            raise _Stop("OUTCOME_UNKNOWN", "no_answer", "The site did not answer the submission and nothing says "
                                                        "whether it took effect. It was not submitted again.")
        raise _Stop("FAILED", "not_as_expected", f"After \"{op['name']}\" the page does not show "
                                                 f"\"{op['expect']['text']}\".")

    def _expect_step(self, op: Mapping[str, Any], evidence: Dict[str, Any], index: int) -> None:
        if not self._expect(op["expect"]):
            raise _Stop("FAILED", "not_as_expected", f"The page does not show \"{op['expect']['text']}\".")

    # ── the whole task ──────────────────────────────────────────────────
    def run(self) -> Dict[str, Any]:
        site, task = self.s.site, self.task
        bound = binding(site, task)
        if bound and self.approval != bound:
            return self._result("NEEDS_APPROVAL", "approval_required",
                                "This task fills in or submits something. It runs only with your approval of "
                                "exactly these fields, values and buttons.", approval=describe_writes(site, task))
        handlers = {"open": self._open, "follow": self._follow, "read": self._read, "find_row": self._find_row,
                    "download": self._download, "fill": self._fill, "submit": self._submit,
                    "expect": self._expect_step}
        checked = any(op["op"] in ("download", "submit") for op in task["ops"])
        state, code, message = ("VERIFIED" if checked else "COMPLETED"), None, None
        with self.s.lock:
            try:
                try:
                    self.s.ensure()
                except BrowserError as error:
                    raise _Stop("FAILED", error.code, str(error)[:300])
                for index, op in enumerate(task["ops"], start=1):
                    evidence: Dict[str, Any] = {"index": index, "op": op["op"],
                                                "name": op.get("name") or op.get("label") or op.get("path")}
                    began = time.perf_counter()
                    try:
                        self._check()
                        handlers[op["op"]](op, evidence, index)
                        if op["op"] in ("open", "follow", "submit"):
                            self._scan()
                        evidence["state"] = "done"
                    except _Stop as stop:
                        evidence.update(state="stopped", error=stop.code, message=stop.message)
                        raise
                    except BrowserError as error:
                        gone = error.code in ("browser_gone", "timeout", "page_changed", "no_answer")
                        evidence.update(state="stopped", error=error.code, message=str(error)[:300])
                        raise _Stop("INTERRUPTED" if gone else "FAILED", error.code, str(error)[:300])
                    finally:
                        evidence["ms"] = round((time.perf_counter() - began) * 1000, 1)
                        evidence["url"] = _path(self.page.url) if self.s.page is not None else None
                        self.steps.append(evidence)
                        self.record(dict(evidence))
            except _Stop as stop:
                state, code, message = stop.state, stop.code, stop.message
            except BrowserError as error:
                state, code, message = "INTERRUPTED", error.code, str(error)[:300]
        return self._result(state, code, message)

    def _result(self, state: str, code: Optional[str], message: Optional[str], **extra: Any) -> Dict[str, Any]:
        page = self.s.page
        blocked = sorted({str(origin_of(url) or url)[:120] for url in (page.blocked if page else [])})
        return {"state": state, "error": code, "message": message, "site": self.s.site.get("name"),
                "origin": self.s.origin, "goal": self.task.get("goal"),
                "steps": self.steps, "stepsDone": sum(1 for step in self.steps if step.get("state") == "done"),
                "stepsTotal": len(self.task.get("ops") or []), "values": self.values, "downloads": self.downloads,
                "untrustedFindings": self.findings, "ignored": self.ignored, "blockedOrigins": blocked,
                "actions": self.actions, "requests": page.requests if page else 0, "modelCalls": 0,
                "ms": round((time.perf_counter() - self._began) * 1000, 1), "timings": dict(self.s.timings), **extra}


def run_task(session: Session, task: Mapping[str, Any], **options: Any) -> Dict[str, Any]:
    """Validate and carry out one task. Never raises for what a site does."""
    clean, problems = validate(task)
    if problems:
        return {"state": "FAILED", "error": "invalid_task", "message": " ".join(problems), "steps": [],
                "stepsDone": 0, "stepsTotal": 0, "values": {}, "downloads": [], "untrustedFindings": [],
                "ignored": [], "blockedOrigins": [], "actions": 0, "requests": 0, "modelCalls": 0, "ms": 0.0}
    return Run(session, clean, **options).run()
