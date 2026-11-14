"""What the Desk knows, read from records every time it is asked.

Nothing here is remembered by a model and nothing is kept in a variable
between requests. Each part is a read of persisted application data:

    meetings    the calendar Scriba mirrors (or the sandbox world's)
    tasks       the executive's open tasks
    waiting     follow-ups: replies awaited, how often reminded, overdue ones
    pending     action cards waiting for the executive's approval
    decisions   what the executive approved, rejected or edited (run evidence)
    done        actions that executed, with whether they were verified
    thread      earlier Desk runs about the same conversation

A part that could not be read is ``{"ok": false}`` with nothing in it:
unknown is never reported as empty.

The same snapshot serves three readers: ``GET /desk/memory`` (a person),
the duplicate check (code), and the bounded model step (as labelled records
it may rely on but cannot change).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Mapping, Optional

from .sandbox import parse_time

MEETING_DAYS = 14
RECENT = 20
_FINAL_NOTHING = ("CANCELLED", "FAILED")
_LIVE = ("awaiting_approval", "needs_info", "approved", "executing", "executed", "partially_executed")
_QUOTED_LINE = re.compile(r"^\s*(?:>|on .{0,80} wrote:|from:|sent:|-{2,}\s*original message)", re.I)
_RESEND = re.compile(r"\b(?:resending|re-sending|sending (?:this )?again|in case (?:this|it) (?:got|was) "
                     r"(?:buried|missed|lost)|following up on (?:my|the) (?:email|message|note) below|"
                     r"just checking|bumping this|gentle reminder|any update)\b[^.?!\n:,]{0,40}[:.,]?", re.I)
_WORD = re.compile(r"[a-z0-9]+")
_FILLER = frozenset("hi hello dear thanks thank you best regards kind the a an and or to of for in on at is it "
                    "this that please could would can we i me my your our with be do".split())


def own_words(text: Any) -> str:
    """A message without the earlier messages quoted under it."""
    kept = []
    for line in str(text or "").splitlines():
        if _QUOTED_LINE.match(line):
            break
        kept.append(line)
    return "\n".join(kept)


def request_words(text: Any) -> frozenset:
    """The words that carry a request: no greeting, no "resending" preamble,
    no quoted text."""
    cleaned = _RESEND.sub(" ", own_words(text).lower())
    return frozenset(word for word in _WORD.findall(cleaned) if word not in _FILLER and len(word) > 1)


def same_request(left: Any, right: Any) -> bool:
    """Two messages that ask for the same thing in nearly the same words."""
    a, b = request_words(left), request_words(right)
    if len(a) < 4 or len(b) < 4:
        return False
    return len(a & b) / len(a | b) >= 0.8


class Memory:
    def __init__(self, workflow: Any) -> None:
        self.workflow = workflow

    @property
    def gateway(self) -> Any:
        return self.workflow.gateway

    # ── the parts ───────────────────────────────────────────────────────────
    def _part(self, read: Any) -> Dict[str, Any]:
        try:
            return {"ok": True, "items": read()}
        except Exception as exc:
            return {"ok": False, "items": [], "error": type(exc).__name__}

    def meetings(self, user: Any, now: dt.datetime, *, sender: Optional[str] = None) -> Dict[str, Any]:
        def read() -> List[Dict[str, Any]]:
            events = self.gateway.calendar_events(user, now - dt.timedelta(hours=1),
                                                  now + dt.timedelta(days=MEETING_DAYS))
            rows = [{"id": e.get("id"), "title": e.get("title"), "start": e.get("start"), "end": e.get("end"),
                     "attendees": [str(a).lower() for a in e.get("attendees") or []],
                     "organizer": bool(e.get("is_organizer")), "provider": e.get("provider")}
                    for e in events if str(e.get("status") or "") != "cancelled"]
            if sender:
                rows = [row for row in rows if sender in row["attendees"]]
            return sorted(rows, key=lambda row: str(row["start"]))
        return self._part(read)

    def tasks(self, ctx: Any, user: Any, now: dt.datetime) -> Dict[str, Any]:
        def read() -> List[Dict[str, Any]]:
            rows = []
            for task in self.gateway.open_tasks(ctx, user, 100):
                due = parse_time(task.get("due_at"))
                rows.append({"id": str(task.get("id")), "title": task.get("title"),
                             "dueAt": due.isoformat() if due else None,
                             "overdue": bool(due is not None and now > due)})
            return rows
        return self._part(read)

    def waiting(self, ctx: Any, user: Any) -> Dict[str, Any]:
        def read() -> List[Dict[str, Any]]:
            listing = self.workflow.follow_ups(ctx, user, refresh=False)
            return [{key: follow.get(key) for key in ("id", "kind", "state", "waitingOn", "subject", "threadId",
                                                      "sentAt", "dueAt", "nudges", "nudgePending", "runId",
                                                      "source")}
                    for follow in listing["followUps"] if follow.get("state") in ("waiting", "overdue", "escalated")]
        return self._part(read)

    def runs(self, ctx: Any, user: Any, *, thread_id: Optional[str] = None,
             limit: int = RECENT) -> List[Dict[str, Any]]:
        """Earlier runs in this world, newest first, each with what it did and
        what the executive decided. From the runs' own evidence."""
        found = []
        for run in self.workflow.runs_in_scope(user, 100):
            meta = run["meta"]
            if thread_id is not None and str(meta.get("thread_id") or "") != str(thread_id):
                continue
            view = self.workflow.view(ctx, user, run["id"])
            decisions = []
            for item in view["timeline"]:
                data = item.get("data") or {}
                if item.get("kind") == "approval":
                    decisions.append({"at": item.get("at"), "decision": data.get("decision") or data.get("status"),
                                      "tool": data.get("tool"), "toolCallId": data.get("toolCallId")})
                elif item.get("kind") == "human":
                    decisions.append({"at": item.get("at"), "decision": data.get("action"),
                                      "fields": data.get("fields"), "toolCallId": data.get("toolCallId")})
            found.append({
                "runId": run["id"], "kind": view["kind"], "subject": meta.get("subject"),
                "from": meta.get("from_addr"), "threadId": meta.get("thread_id"),
                "messageId": meta.get("email_id"), "createdAt": meta.get("created_at"),
                "stage": view["lifecycle"]["stage"], "reason": view["lifecycle"].get("reason"),
                "actions": [{"tool": a["tool_name"], "purpose": a.get("purpose"), "status": a["status"],
                             "verified": a.get("verified"), "toolCallId": a["toolCallId"],
                             "start": (a.get("input") or {}).get("start"),
                             "title": (a.get("input") or {}).get("title")
                             or (a.get("target") or {}).get("title")} for a in view["actions"]],
                "taskUpdates": [{"taskId": u.get("taskId"), "state": u.get("state")}
                                for u in view.get("taskUpdates") or []],
                "decisions": decisions})
            if len(found) >= limit:
                break
        return found

    # ── the whole picture ───────────────────────────────────────────────────
    def snapshot(self, ctx: Any, user: Any, *, thread_id: Optional[str] = None,
                 sender: Optional[str] = None) -> Dict[str, Any]:
        now = self.workflow.service.now(user)
        runs = self._part(lambda: self.runs(ctx, user, thread_id=thread_id))
        pending, done, decisions = [], [], []
        for run in runs["items"]:
            for action in run["actions"]:
                entry = {"runId": run["runId"], "subject": run["subject"], **action}
                if action["status"] in ("awaiting_approval", "needs_info"):
                    pending.append(entry)
                elif action["status"] in ("executed", "partially_executed"):
                    done.append(entry)
            decisions.extend({"runId": run["runId"], "subject": run["subject"], **d} for d in run["decisions"])
        return {
            "account": user.email, "asOf": now.isoformat(),
            "scope": {"threadId": thread_id, "sender": sender},
            "meetings": self.meetings(user, now, sender=sender),
            "tasks": self.tasks(ctx, user, now),
            "waiting": self.waiting(ctx, user),
            "pending": {"ok": runs["ok"], "items": pending},
            "done": {"ok": runs["ok"], "items": done[:RECENT]},
            "decisions": {"ok": runs["ok"], "items": decisions[:RECENT]},
            "runs": {"ok": runs["ok"], "items": [{key: run[key] for key in (
                "runId", "kind", "subject", "from", "threadId", "createdAt", "stage", "reason")}
                for run in runs["items"]]},
        }

    def for_message(self, ctx: Any, user: Any, item: Mapping[str, Any], sender: Optional[str]) -> Dict[str, Any]:
        """The records that bear on one incoming message, small enough to
        show a model. Facts from storage; the model cannot change them."""
        now = self.workflow.service.now(user)
        meetings = self.meetings(user, now, sender=sender)
        tasks = self.tasks(ctx, user, now)
        waits = self.waiting(ctx, user)
        thread = str(item.get("threadId") or item.get("thread_id") or "")
        earlier = self._part(lambda: self.runs(ctx, user, thread_id=thread, limit=5) if thread else [])
        return {
            "meetings_with_the_sender": [{"title": m["title"], "start": m["start"], "end": m["end"]}
                                         for m in meetings["items"][:5]] if meetings["ok"] else "unknown",
            "open_tasks": [{"title": t["title"], "due": t["dueAt"], "overdue": t["overdue"]}
                           for t in tasks["items"][:15]] if tasks["ok"] else "unknown",
            "replies_awaited_from_the_sender": [
                {"subject": w["subject"], "state": w["state"], "due": w["dueAt"]}
                for w in waits["items"] if sender and w.get("waitingOn") == sender][:5] if waits["ok"] else "unknown",
            "already_done_in_this_conversation": [
                {"when": run["createdAt"], "stage": run["stage"],
                 "actions": [f"{a['tool']} ({a['status']})" for a in run["actions"]]}
                for run in earlier["items"] if str(run.get("messageId")) != str(item.get("id"))][:5]
            if earlier["ok"] else "unknown",
        }

    # ── a request that was already made ─────────────────────────────────────
    def earlier_same_request(self, ctx: Any, user: Any, item: Mapping[str, Any],
                             thread: List[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
        """An earlier message in this conversation, from the same sender,
        asking for the same thing in nearly the same words, that the Desk
        already took in and did not abandon. None when there is no such
        message, or when the earlier run was rejected or failed (then asking
        again is a new request and is handled as one)."""
        from .workflow import run_key, sender_address

        sender = sender_address(str(item.get("from_addr") or ""))
        mine = f"{item.get('body') or item.get('snippet') or ''}"
        if not sender:
            return None
        for earlier in reversed(thread):
            if earlier.get("own") or str(earlier.get("id")) == str(item.get("id")):
                continue
            if sender_address(str(earlier.get("from_addr") or "")) != sender:
                continue
            if not same_request(mine, earlier.get("body")):
                continue
            key = run_key(user.id, str(item.get("provider") or "gmail"), item.get("provider_account_id"),
                          str(earlier.get("id")), self.workflow._namespace(user))
            run = self.gateway.find_run(user, key)
            if run is None:
                continue
            earlier_view = self.workflow.view(ctx, user, run["id"], detail=False)
            stage = earlier_view["lifecycle"]["stage"]
            if stage in _FINAL_NOTHING:
                return None
            counts = earlier_view.get("actionCounts") or {}
            if not any(counts.get(status) for status in _LIVE):
                # The earlier message was taken in and nothing came of it (a
                # calendar could not be read, it was handed over). The Desk
                # does not "have" that request: this one is handled afresh.
                return None
            return {"runId": run["id"], "messageId": earlier.get("id"), "stage": stage,
                    "open": stage not in ("COMPLETED", "PARTIALLY_COMPLETED")}
        return None
