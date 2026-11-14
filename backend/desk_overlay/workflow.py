"""The Desk workflow for one incoming email.

    incoming email -> classify -> gather thread and calendar context -> plan
        -> propose actions -> wait for approval -> execute -> verify
        -> follow up -> record

The Desk owns everything up to the proposal, and the follow-up. Approval,
execution and the action record are Scriba's: every proposal is a Scriba chat
action card, created through Scriba's own validation gate and approved
through Scriba's existing ``/chat/tool-calls/{id}/approve`` route, which
claims the card atomically and runs it through Scriba's execution engine. A
run is a Scriba chat conversation; its evidence is an append-only list of
events on that conversation (``lifecycle.py``).

Nothing here sends mail or writes a calendar. What is proposed:

- Actionable email: a task card, with the deadline when one is written out.
- New meeting request at a time verified free: a calendar-event card. The
  confirmation reply is proposed only AFTER the event has executed.
- A time that is busy, or that could not be read from the message: a reply
  card offering times verified free on every calendar.
- Reschedule: the original event is found among the SENDER's meetings; a
  card that moves THAT event (never a second event) is proposed when the new
  time is verified free.
- Cancellation: the same search; a cancellation card for that event.
- Anything the Desk cannot verify is held and handed to the person.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import threading
from typing import Any, Dict, List, Mapping, Optional

from . import files, lifecycle, planning, plans, reading, requests, understanding, workbooks
from .availability import InvalidAvailabilityRequest, parse_instant, resolve_zone
from .claims import LEASE_SECONDS, MemoryClaims, claim_key
from .commands import Commands, reply_text
from .memory import Memory
from .service import DeskService, NotFound

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# An action that took full effect; one that took effect only in part.
_DONE = ("executed",)
_PARTIAL = ("partially_executed",)
_EFFECT = _DONE + _PARTIAL
_OPEN = ("pending", "needs_info", "draft", "awaiting_approval", "approved", "executing")
# Messages a sweep opens a run for. Informational and automated mail is left alone.
SWEEP_CATEGORIES = ("meeting_request", "action_item", "needs_reply")
SWEEP_MAX_NEW = 5
TRIGGERS = ("manual", "sweep", "worker", "evaluation", "chat")
# How long the Desk waits for an answer before it proposes a reminder.
FOLLOW_UP_DAYS = 2
MAX_REQUESTED_TASKS = 3
EVENT_SEARCH_DAYS = 45
# A reminder (nudge) is not a new wait: it belongs to the follow-up it chases.
REPLY_PURPOSES_AWAITING = ("offer_times", "clarify")


# A person saying outright that nothing is asked of the reader.
_NEWS = re.compile(
    r"\b(?:fyi|for (?:your )?info(?:rmation)?|no (?:further )?action (?:is )?(?:needed|required|necessary)|"
    r"nothing (?:is )?(?:needed|required) (?:from|of) you|no need to (?:reply|respond|do anything)|"
    r"just (?:an update|a heads[- ]up|to let you know|keeping you (?:posted|in the loop)|so you know)|"
    r"for the record|keeping you (?:posted|in the loop)|thank you|thanks(?: again)?|"
    r"received,? (?:with )?thanks|noted|sounds good|see you (?:then|there|on))\b", re.I)


class InvalidRequest(ValueError):
    """The request is not well formed. Nothing was done."""


class Conflict(RuntimeError):
    """The request cannot be carried out as things stand. Nothing was done."""


class IntakeBusy(RuntimeError):
    """Another worker holds the claim for this message right now."""


def sender_address(from_addr: str) -> Optional[str]:
    """The address in a From header. The only attendee the Desk adds on its own."""
    match = _EMAIL_RE.search(str(from_addr or ""))
    return match.group(0).lower() if match else None


def run_key(user_id: int, provider: str, account: Optional[str], item_id: str,
            namespace: str = "") -> str:
    """Identity of one inbound message for one user: the same message is one run.

    User, provider, receiving account and provider message id: a provider id
    is unique only inside one mailbox. ``namespace`` keeps one evaluation
    case's synthetic messages apart from another's.
    """
    raw = f"{int(user_id)}|{provider}|{(account or '').strip().lower()}|{item_id}"
    if namespace:
        raw = f"{namespace}|{raw}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class DeskWorkflow:
    def __init__(self, service: DeskService, gateway: Any, claims: Any = None,
                 agent: Any = None) -> None:
        self.service = service
        self.gateway = gateway
        self.claims = claims or MemoryClaims()
        # An optional model-driven planner (``agent.DeskAgent``). It may refine
        # a plan; every proposal it makes passes the same checks as below.
        self.agent = agent
        # Off unless the process asks for it (DESK_UNDERSTANDING=model) and a
        # model is really configured: one structured call reads the message's
        # intents. With it off, the rules and Scriba's extraction do.
        self.model_understanding = False
        self.commands = Commands(self)
        self.memory = Memory(self)
        self._locks: Dict[str, Any] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, key: str) -> Any:
        # Re-entrant: an approval made while a run is being opened (a task the
        # policy approves at once) comes back into ``advance`` on this thread.
        with self._locks_guard:
            return self._locks.setdefault(key, threading.RLock())

    def _namespace(self, user: Any) -> str:
        namespace = getattr(self.gateway, "key_namespace", None)
        return namespace(user) if callable(namespace) else ""

    def _world_id(self, user: Any) -> Optional[str]:
        world_for = getattr(self.gateway, "world_for", None)
        world = world_for(user) if callable(world_for) else None
        return world.id if world is not None else None

    def _is_evaluation(self, user: Any) -> bool:
        world_for = getattr(self.gateway, "world_for", None)
        world = world_for(user) if callable(world_for) else None
        return bool(world is not None and world.evaluation)

    def runs_in_scope(self, user: Any, limit: int = 50) -> List[Dict[str, Any]]:
        """The user's runs in the world now in force (their real accounts, or
        one sandbox world). Work done in one world is never read as history
        in another."""
        world = self._world_id(user)
        try:
            runs = self.gateway.list_runs(user, 200, include_evaluation=self._is_evaluation(user))
        except TypeError:
            runs = self.gateway.list_runs(user, 200)
        return [run for run in runs if run["meta"].get("sandbox") == world][:limit]

    def _record(self, user: Any, run: Dict[str, Any], kind: str, data: Dict[str, Any]) -> None:
        lifecycle.record(self.gateway, user, run, kind, data, at=self.service.now(user).isoformat())

    # ── an instruction from the executive ───────────────────────────────────
    def command(self, ctx: Any, user: Any, text: str, *, request_id: Optional[str] = None,
                trigger: str = "chat") -> Dict[str, Any]:
        """Open a run for work the executive asked for in their own words.
        See ``commands.py``. Proposes; sends nothing and changes no calendar."""
        return self.commands.run(ctx, user, text, request_id=request_id, trigger=trigger)

    # ── intake ──────────────────────────────────────────────────────────────
    def intake(self, ctx: Any, user: Any, *, provider: str, item_id: str,
               mailbox: Optional[str] = None, trigger: str = "manual") -> Dict[str, Any]:
        detail = self.service.inbox_item(ctx, user, provider=provider, item_id=item_id, mailbox=mailbox)
        item = detail["item"]
        key = run_key(user.id, provider, item.get("provider_account_id"), item_id, self._namespace(user))

        # The process lock keeps two threads of this process apart cheaply. The
        # claim is what holds across processes and restarts.
        with self._lock(key):
            claim = self._claim(user, key)
            if claim.state == "done":
                existing = (self.gateway.get_run(user, claim.run_id) if claim.run_id else None) \
                    or self.gateway.find_run(user, key)
                if existing is not None:
                    return self.view(ctx, user, existing["id"], duplicate=True)
                # The ledger says a run exists and Scriba has none (it was
                # deleted). Take the message again rather than lose it.
                self.claims.reopen(user.id, claim_key(key), claim.token)
                claim = self._claim(user, key)
            if not claim.claimed:
                raise IntakeBusy("This message is being taken in by another worker.")
            try:
                existing = self.gateway.find_run(user, key)
                if existing is not None:      # opened before claims existed, or by a peer
                    self.claims.settle(user.id, claim_key(key), claim.token, existing["id"])
                    return self.view(ctx, user, existing["id"], duplicate=True)
                run = self._open(ctx, user, provider, item, detail, key, trigger)
            except Exception:
                self.claims.release(user.id, claim_key(key), claim.token)
                raise
            self.claims.settle(user.id, claim_key(key), claim.token, run["id"])
        return self.view(ctx, user, run["id"])

    def _claim(self, user: Any, key: str) -> Any:
        claim = self.claims.claim(user.id, claim_key(key))
        if claim.state == "in_flight" and (claim.age_seconds or 0) > LEASE_SECONDS \
                and self.gateway.find_run(user, key) is None:
            # Its holder died before opening a run. Nothing outside Scriba has
            # happened, so the claim can be taken over.
            self.claims.release(user.id, claim_key(key), claim.token)
            claim = self.claims.claim(user.id, claim_key(key))
        return claim

    def _open(self, ctx: Any, user: Any, provider: str, item: Dict[str, Any],
              detail: Dict[str, Any], key: str, trigger: str) -> Dict[str, Any]:
        triage = item["triage"]
        now = self.service.now(user).isoformat()
        meta: Dict[str, Any] = {
            "key": key,
            "provider": provider,
            "email_id": item.get("id"),
            "thread_id": item.get("threadId"),
            "provider_account_id": item.get("provider_account_id"),
            "from_addr": item.get("from_addr"),
            "subject": item.get("subject"),
            "received_at": item.get("timestamp"),
            "category": triage["category"],
            "outcome": triage["outcome"],
            "created_at": now,
            "trigger": trigger if trigger in TRIGGERS else "manual",
            "sandbox": self._world_id(user),
            "evaluation": self._is_evaluation(user),
            "held": None,
            "draft_request": detail.get("draftRequest"),
        }
        plan = self._plan(ctx, user, item, detail)
        found = plan.get("understanding") or understanding.from_rules(item)
        typed = plans.build(meta=meta, understanding=found, plan=plan)
        meta["held"] = plan["held"]
        if plan.get("unresolved"):
            # Requests that were identified and not acted on. While any is
            # open the run is not complete, whatever else was done.
            meta["unresolved"] = [{"id": f"u{index}", **entry}
                                  for index, entry in enumerate(plan["unresolved"], start=1)]
        if plan.get("flags"):
            meta["flags"] = plan["flags"]
        if plan.get("requester_timezone"):
            meta["requester_timezone"] = plan["requester_timezone"]
        run = self.gateway.open_run(
            user, title=f"Desk: {str(item.get('subject') or 'incoming email')[:80]}", meta=meta,
            summary=_summary(meta, plan["proposals"]))

        self._record(user, run, "stage", {
            "stage": "RECEIVED", "trigger": meta["trigger"], "provider": provider,
            "account": meta["provider_account_id"], "messageId": meta["email_id"],
            "threadId": meta["thread_id"], "receivedAt": meta["received_at"]})
        self._record(user, run, "stage", {
            "stage": "UNDERSTANDING", "category": triage["category"], "outcome": triage["outcome"],
            "priority": plan.get("priority") or triage.get("priority"),
            "reasons": triage.get("reasons") or [],
            "meetingIntent": triage.get("meeting_intent"), "flags": plan.get("flags") or [],
            "source": found.get("source"),
            "intents": [{"type": i.get("type"), "confidence": i.get("confidence")}
                        for i in found.get("intents") or []]})
        self._record(user, run, "stage", {"stage": "INVESTIGATING",
                                          "threadMessages": (detail.get("thread") or {}).get("count")})
        self._record(user, run, "read", {"tool": "email.read_thread", "ok": True,
                                         "threadId": meta["thread_id"],
                                         "count": (detail.get("thread") or {}).get("count")})
        for read in plan["reads"]:
            self._record(user, run, "read", read)
        for closed in [*(plan.get("closed_follow_ups") or []), *(plan.get("kept_follow_ups") or [])]:
            self._record(user, run, "followup", closed)
        self._record(user, run, "stage", {"stage": "PLANNING", "planner": plan["planner"]})
        self._record(user, run, "plan", typed)
        for usage in plan.get("usage") or []:
            self._record(user, run, "usage", usage)
        for decision in plan["decisions"]:
            self._record(user, run, "decision", decision)
        for proposal in plan["proposals"]:
            self._propose(user, run, proposal)
        self._apply_task_updates(ctx, user, run, plan)
        return run

    def _propose(self, user: Any, run: Dict[str, Any], proposal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        meta = run["meta"]
        card = self.gateway.propose_action(
            user, run, tool_name=proposal["tool_name"], tool_input=proposal["tool_input"],
            email_id=meta.get("email_id"), thread_id=meta.get("thread_id"), provider=meta.get("provider"))
        self._record(user, run, "proposal", {
            "toolCallId": (card or {}).get("id"), "tool": proposal["tool_name"],
            "stepId": proposal.get("stepId"), "binding": _binding(proposal["tool_name"], (card or {}).get("input")
                                                               or proposal["tool_input"]),
            "purpose": proposal.get("purpose"), "reason": proposal.get("reason"),
            "followUpId": proposal.get("followUpId"), "target": proposal.get("target"),
            "proposedSlots": proposal.get("proposedSlots"),
            "status": (card or {}).get("status")})
        self._auto_approve_internal(user, run, proposal["tool_name"], card)
        return card

    def _auto_approve_internal(self, user: Any, run: Dict[str, Any], tool_name: str,
                               card: Optional[Dict[str, Any]]) -> None:
        """Where the policy says so, a write to the person's OWN records (a
        task, a reminder) is approved by the Desk at once. This is a fixed rule
        in code for two named tools; a model cannot invoke it, and it never
        applies to mail or a calendar."""
        from .readiness import INTERNAL_WRITE_TOOLS

        policy = getattr(self.gateway, "auto_internal_writes", None)
        if tool_name not in INTERNAL_WRITE_TOOLS or not callable(policy) or not policy(user):
            return
        if not card or card.get("status") != "awaiting_approval":
            return
        self._record(user, run, "decision", {
            "decision": "auto_approve_internal", "toolCallId": card.get("id"), "tool": tool_name,
            "explanation": "This only writes your own records, and this Desk is set to do that "
                           "without asking."})
        try:
            self.gateway.approve_card(user, card.get("id"),
                                      idempotency_key=f"desk-auto:{run['meta'].get('key')}:{card.get('id')}")
        except Exception as exc:
            self._record(user, run, "error", {"message": "The automatic approval failed.",
                                              "code": type(exc).__name__, "toolCallId": card.get("id")})

    # ── planning ────────────────────────────────────────────────────────────
    def _plan(self, ctx: Any, user: Any, item: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
        """What to propose for this message, and why. Reads only."""
        triage = item["triage"]
        plan: Dict[str, Any] = {"proposals": [], "held": None, "decisions": [], "reads": [],
                                "usage": [], "flags": [], "planner": "rules"}
        text = str(item.get("body") or item.get("snippet") or "")
        calendar = detail.get("calendar")
        if calendar is not None:
            for entry in calendar.get("calendars") or []:
                plan["reads"].append({"tool": "calendar.find_free_slots", "provider": entry.get("provider"),
                                      "account": entry.get("account"), "ok": bool(entry.get("ok")),
                                      "error": entry.get("error"),
                                      "timeMin": (calendar.get("range") or {}).get("start"),
                                      "timeMax": (calendar.get("range") or {}).get("end"),
                                      "durationMinutes": calendar.get("duration_minutes")})

        if planning.injection_suspected(item.get("subject"), text):
            # Mail is data. Text that addresses the assistant is not obeyed,
            # and nothing is proposed on the strength of a message carrying it.
            return self._hand_over_untrusted(plan, source="rules")

        attached = self._read_attachments(user, item, plan)
        flagged = [f for f in attached if f.get("findings")]
        if flagged:
            # A file is data too. One that carries text written to an
            # assistant is not read to a model, not summarised and not acted
            # on: the message is handed over with the file named.
            return self._hand_over_untrusted(
                plan, source="attachment",
                evidence=[f"{f['filename']}: {finding}" for f in flagged for finding in f["findings"]][:6])

        try:
            earlier = self.memory.earlier_same_request(ctx, user, item, self.thread_context(user, item, detail))
        except Exception:
            earlier = None                  # history unreadable: handle the message on its own
        if earlier is not None:
            # The same sender already asked for this in this conversation and
            # the Desk has it. A second copy must not become a second action.
            plan["flags"].append("duplicate")
            reason = "already_in_progress" if earlier["open"] else "already_handled"
            plan["held"] = {
                "reason": reason, "slots": [], "calendars": [],
                "target": {"runId": earlier["runId"], "messageId": earlier["messageId"], "stage": earlier["stage"]},
                "message": "This repeats a request the same sender already made in this conversation, "
                           + ("which is being handled." if earlier["open"] else "which was handled.")
                           + " Nothing new is proposed."}
            plan["decisions"].append({"decision": "none", "reason": reason, "earlierRunId": earlier["runId"],
                                      "explanation": "The request repeats one already taken in."})
            return plan

        if reading.retracted(text):
            # "Cancel it. On second thought, keep it." Which half stands is the
            # writer's to say. No reader, rule or model, gets to pick, and no
            # task is made out of either half.
            self._hold(plan, user, item, calendar, "conflicting_instructions",
                       "The message gives an instruction and then takes it back, so nothing is "
                       "proposed. Read it and decide.")
            return plan

        self._close_awaited(user, item, plan)
        found = self._understand(user, item, detail, plan)
        plan["understanding"] = found
        if found.get("instructs_assistant"):
            # The rules did not recognise the wording; the model quoted text
            # in the message that addresses an assistant. A model can only
            # make the Desk stricter this way: nothing is proposed, and
            # whatever else it read in this message is not acted on.
            return self._hand_over_untrusted(plan, source="model", evidence=found["instructs_assistant"])
        self._note_finished_work(ctx, user, item, plan, found)
        if found["source"] == "model" and triage["category"] != "automated":
            self._plan_from_intents(ctx, user, item, calendar, plan, found)
        elif triage["category"] == "action_item":
            asked = [u for u in requests.units(item.get("subject"), text) if u["kind"] == "action"]
            if len(asked) >= 2:
                # Two things to do are two tasks, each with its own date.
                self._plan_requested_tasks(ctx, user, item, plan, asked)
            else:
                self._plan_task(ctx, user, item, plan)
        elif triage["category"] == "meeting_request":
            read = requests.units(item.get("subject"), text)
            asked = [u for u in read if u["kind"] == "action"]
            wishes = [u for u in read if u["kind"] == "scheduling"]
            if len({u.get("intent") for u in wishes}) > 1:
                # Two different things about the calendar in one message (cancel
                # this one, and could we meet then): the Desk acts on one. The
                # other is not forgotten.
                first = (triage.get("meeting_intent") or "new")
                for unit in wishes:
                    if unit.get("intent") != first:
                        plan.setdefault("unresolved", []).append({
                            "text": unit["text"][:300], "why": "second_scheduling_request"})
            if asked:
                # The meeting's time is read from the sentences about the
                # meeting. Another request's date is not the meeting's.
                plan["meeting_text"] = requests.without(text, [u["text"] for u in asked])
            self._plan_meeting(ctx, user, item, calendar, plan)
            if asked and (plan.get("held") or {}).get("reason") not in ("untrusted_instructions",
                                                                         "conflicting_instructions"):
                self._plan_requested_tasks(ctx, user, item, plan, asked)
        elif triage["category"] == "needs_reply":
            plan["decisions"].append({"decision": "escalate", "reason": "reply_needs_author",
                                      "explanation": "This needs a reply in your words. A draft can "
                                                     "be prepared for you to review."})
        elif triage["category"] == "informational" and not self._is_plainly_news(item, plan):
            # Written by a person, and the rules cannot say what it needs.
            # Filing it as dealt with would hide it: it is handed over.
            plan["held"] = {
                "reason": "needs_review", "slots": [], "calendars": [],
                "message": "This was written by a person and it is not clear what, if anything, it "
                           "needs from you. It was not filed as dealt with: read it and decide."}
            plan["decisions"].append({"decision": "escalate", "reason": "needs_review",
                                      "explanation": "The Desk could not place this message, so it "
                                                     "was handed to you instead of being filed."})
        else:
            plan["decisions"].append({"decision": "none", "reason": triage["category"],
                                      "explanation": "No action is needed for this message."})

        self._plan_file_review(user, item, plan, attached)

        if self.agent is not None:
            try:
                plan = self.agent.refine(ctx, user, item, detail, plan, workflow=self)
            except Exception as exc:   # the agent failing never loses the rule-based plan
                plan["decisions"].append({"decision": "agent_unavailable", "reason": type(exc).__name__,
                                          "explanation": "The model could not be used; the plan above "
                                                         "is rule-based."})
        asked = {str(i.get("type")) for i in found.get("intents") or []
                 if (i.get("confidence") or 0) >= understanding.MIN_CONFIDENCE}
        if found.get("source") == "model" and asked & {"reply_needed", "information_request"} \
                and plan["held"] is None and plan["proposals"] \
                and not any(p.get("tool_name") == "send_email" for p in plan["proposals"]):
            # Something else in the message was acted on, and the reply it
            # also needs was not drafted. The run is not complete without it.
            needing = next(i for i in found["intents"] if i.get("type") in ("reply_needed", "information_request"))
            plan.setdefault("unresolved", []).append({
                "text": str((needing.get("evidence") or ["a reply"])[0])[:300], "why": "reply_needs_author"})
        if found.get("source") == "model" and asked & {"reply_needed", "information_request"} \
                and plan["held"] is None and not plan["proposals"] and not plan.get("task_updates"):
            # A reply is needed and none was drafted. That is not "done":
            # the message is handed to the person, who writes it.
            plan["held"] = {
                "reason": "reply_needs_author", "slots": [], "calendars": [],
                "message": "This needs a reply in your words, and none could be drafted from what "
                           "the Desk can verify. It is yours to answer."}
        return plan

    # ── files that arrive with a message ────────────────────────────────────
    def _read_attachments(self, user: Any, item: Mapping[str, Any], plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Read every attachment of the message with Scriba's own readers and
        record each read. Returns the analyses (kept for planning only: file
        text is never written to the run's record)."""
        listing = getattr(self.gateway, "attachments", None)
        rows = listing(user, item) if callable(listing) else None
        if not rows:
            return []                       # none, or a mailbox whose attachments this backend cannot read
        found: List[Dict[str, Any]] = []
        for index, row in enumerate(rows):
            base = {"tool": "file.read_attachment", "attachmentId": row.get("id"), "filename": row.get("filename"),
                    "sizeBytes": row.get("sizeBytes")}
            if index >= files.MAX_ATTACHMENTS:
                plan["reads"].append({**base, "ok": False, "error": "too_many_attachments"})
                continue
            try:
                content = self.gateway.attachment_content(user, str(row.get("id")))
                analysis = files.analyse(str(row.get("filename") or "file"), content or b"")
            except Exception as exc:        # one unreadable file does not stop the message
                plan["reads"].append({**base, "ok": False, "error": type(exc).__name__})
                continue
            analysis["attachmentId"] = row.get("id")
            plan["reads"].append({
                **base, "ok": bool(analysis["read"]), "error": None if analysis["read"] else analysis.get("code"),
                "kind": analysis.get("kind"), "sha256": analysis.get("sha256"), "unit": analysis.get("unit"),
                "unitCount": analysis.get("unitCount"), "truncated": bool(analysis.get("truncated")),
                "unread": len(analysis.get("unread") or []), "findings": len(analysis.get("findings") or []),
                "unusual": len(analysis.get("unusual") or [])})
            found.append(analysis)
            if analysis["read"]:
                plan.setdefault("facts", []).append(
                    f"Read \"{analysis['filename']}\" ({analysis.get('label')}): "
                    f"{analysis.get('unitCount')} {analysis.get('unit')}(s).")
            else:
                plan.setdefault("missing", []).append(f"the content of \"{analysis['filename']}\"")
        return found

    def _plan_file_review(self, user: Any, item: Dict[str, Any], plan: Dict[str, Any],
                          attached: List[Dict[str, Any]]) -> None:
        """When a message asks for its file to be looked at: one review
        document per readable file (Scriba's ``create_document``), and, after
        the first one exists and was verified, a reply for approval."""
        readable = [f for f in attached if f.get("read")]
        if not readable or plan.get("held", None) and plan["held"].get("reason") not in ("needs_review",):
            return
        if not reading.file_request(str(item.get("subject") or ""), str(item.get("body") or item.get("snippet") or "")):
            return
        sender = str(item.get("from_addr") or "the sender")
        first = len(plan["proposals"])
        for analysis in readable[:3]:
            plan["proposals"].append({
                "tool_name": "create_document", "purpose": "review_file",
                "reason": f"The message asks for \"{analysis['filename']}\" to be looked at. "
                          "The review is built from the file itself, by fixed rules.",
                "tool_input": files.summary_document(analysis, sender=sender, subject=str(item.get("subject") or ""))})
        if plan.get("held") and plan["held"].get("reason") == "needs_review":
            plan["held"] = None             # the Desk can place it after all: it asks for a file to be reviewed
        plan["decisions"].append({
            "decision": "propose", "reason": "file_review_requested",
            "explanation": f"A review of {len(readable[:3])} attached file(s) is proposed. It writes only "
                           "your own records."})
        unusual = [f["finding"] for analysis in readable[:3] for f in analysis.get("unusual") or []]
        if sender_address(sender) and item["triage"].get("category") != "automated":
            plan.setdefault("deferred", []).append({
                "tool": "send_email", "purpose": "reply", "depends_on_index": first,
                "pending": {"tool_name": "send_email", "purpose": "reply",
                            "reason": "The file was reviewed, so the sender can be answered. You approve or change "
                                      "the wording.",
                            "tool_input": self._reply_input(item, planning.file_review_reply(
                                filenames=[a["filename"] for a in readable[:3]], findings=unusual))}})

    def _plan_requested_tasks(self, ctx: Any, user: Any, item: Dict[str, Any], plan: Dict[str, Any],
                              asked: List[Dict[str, Any]]) -> None:
        """One task per sentence that asks the executive to do something. What
        is identified and cannot be recorded is listed as unresolved: the run
        is then not complete until the person has seen it."""
        held_before = plan["held"]
        clear = [u for u in asked if u.get("separate") and not u.get("names_address")]
        for unit in asked:
            if unit not in clear:
                # Asked for, and not clearly a piece of work the Desk can
                # record by itself (or it names an address): the person sees
                # it before the run can count as done.
                plan.setdefault("unresolved", []).append({
                    "text": unit["text"][:300],
                    "why": "names_an_address" if unit.get("names_address") else "needs_your_decision"})
        asked = clear
        for unit in asked[:MAX_REQUESTED_TASKS]:
            title = requests.title_of(unit["text"])
            if any(_same_title(p.get("tool_input", {}).get("title"), title) for p in plan["proposals"]
                   if p.get("tool_name") == "create_task"):
                continue
            self._plan_task(ctx, user, item, plan, title=title, evidence=[unit["text"]], alone=False)
            if (plan["held"] or {}).get("reason") == "task_exists":
                plan["held"] = held_before       # that one is already recorded; the others still count
        for unit in asked[MAX_REQUESTED_TASKS:]:
            plan.setdefault("unresolved", []).append({"text": unit["text"][:300], "why": "not_recorded"})

    @staticmethod
    def _hand_over_untrusted(plan: Dict[str, Any], *, source: str,
                             evidence: Optional[List[str]] = None) -> Dict[str, Any]:
        plan["flags"].append("prompt_injection_suspected")
        plan["held"] = {
            "reason": "untrusted_instructions", "slots": [], "calendars": [],
            "message": "This message contains text written as instructions to an assistant. "
                       "Nothing is proposed automatically. Read it yourself before acting."}
        decision = {"decision": "escalate", "reason": "untrusted_instructions", "source": source,
                    "explanation": "The message tries to instruct the assistant, so it was handed to you."}
        if evidence:
            decision["evidence"] = list(evidence)
        plan["decisions"].append(decision)
        return plan

    @staticmethod
    def _time_in_doubt(intent: Mapping[str, Any], now: dt.datetime) -> Optional[str]:
        """Why a scheduling intent's time must not be used, or None."""
        details = intent.get("details") or {}
        if not details.get("requested_start"):
            return None
        for missing in intent.get("missing") or []:
            if re.search(r"\b(which|when|date|day)\b|\btime\b(?!\s*zone)", str(missing), re.I) \
                    and not re.search(r"\b(duration|length|end)\b", str(missing), re.I):
                return ("The reader gave a time and also reported the time as unclear "
                        f"(\"{missing}\"), so it was not used.")
        if intent.get("type") == "new_meeting":
            quoted = " ".join(str(quote) for quote in intent.get("evidence") or []).lower()
            days = reading._days(quoted, now.date())
            times, written_range = reading._times(quoted)
            if len(set(days)) > 1 or (len(set(times)) > 1 and not written_range):
                return "The message names more than one day or time for this meeting, so none was picked."
        return None

    @staticmethod
    def _is_plainly_news(item: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
        """"No action" has to be earned: the message says it is for
        information, or the Desk already recorded what it reports (a task it
        finished, an awaited answer it brought)."""
        if plan.get("task_updates") or plan.get("closed_follow_ups") or plan.get("kept_follow_ups"):
            return True
        return requests.no_work_established(item.get("subject"), item.get("body") or item.get("snippet"))

    def thread_context(self, user: Any, item: Mapping[str, Any],
                       detail: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """The conversation so far, oldest first: what arrived AND what the
        executive wrote. Read from the mailbox, never recalled. ``own`` marks
        the executive's messages; everything else is untrusted text."""
        thread_id = str(item.get("threadId") or item.get("thread_id") or "")
        rows: List[Dict[str, Any]] = [
            {"id": m.get("id"), "from_addr": m.get("from_addr"), "timestamp": m.get("timestamp"),
             "subject": m.get("subject"), "body": m.get("body") or m.get("snippet"), "own": False}
            for m in (detail.get("thread") or {}).get("messages") or []]
        if thread_id:
            try:
                sent = self.gateway.list_sent(None, user, str(item.get("provider") or "gmail"),
                                              item.get("provider_account_id")) or []
            except Exception:
                sent = []           # unknown is not "nothing was sent": the thread is just shorter
            for row in sent:
                if str(row.get("thread_id") or row.get("threadId") or "") == thread_id:
                    rows.append({"id": row.get("id"), "from_addr": user.email,
                                 "timestamp": row.get("sent_at") or row.get("timestamp"),
                                 "subject": row.get("subject"),
                                 "body": row.get("text") or row.get("body") or row.get("snippet"),
                                 "own": True})
        rows.sort(key=lambda row: (_moment(row.get("timestamp")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)))
        return rows

    def _understand(self, user: Any, item: Dict[str, Any], detail: Dict[str, Any],
                    plan: Dict[str, Any]) -> Dict[str, Any]:
        """The message's intents: from a model when one is configured and
        asked for, otherwise from the rules. A model that answers nothing
        usable leaves the rules' reading in place."""
        rules = understanding.from_rules(item)
        configured = getattr(self.gateway, "model_configured", None)
        if not self.model_understanding or not callable(configured) or not configured():
            return rules
        try:
            zone_name, _, _, _ = self.service.working_context(user, None, None, None)
        except InvalidAvailabilityRequest:
            return rules
        now = self.service.now(user).astimezone(resolve_zone(zone_name))
        with self.gateway.model_usage() as calls:
            found = understanding.from_model(
                self.gateway, item=item, thread=self.thread_context(user, item, detail),
                now=now, timezone=zone_name)
        plan["usage"].extend(calls)
        plan["reads"].append({"tool": "model.understand", "ok": bool(found and found["intents"]),
                              "error": None if found and found["intents"] else "no_supported_intent",
                              "dropped": len((found or {}).get("dropped") or [])})
        if not found or not found["intents"]:
            return {**rules, "dropped": (found or {}).get("dropped") or [],
                    "instructs_assistant": (found or {}).get("instructs_assistant") or []}
        plan["planner"] = "model+rules"
        return found

    def _plan_from_intents(self, ctx: Any, user: Any, item: Dict[str, Any],
                           calendar: Optional[Dict[str, Any]], plan: Dict[str, Any],
                           found: Dict[str, Any]) -> None:
        """One message, several requests: each supported intent is planned by
        the same checked code a single request goes through. The model says
        WHAT is asked; it never decides that a time is free, who is on a
        meeting, or that something may be sent."""
        intents = found["intents"]
        sure = [i for i in intents if (i.get("confidence") or 0) >= understanding.MIN_CONFIDENCE]
        if not sure:
            missing = sorted({m for i in intents for m in i.get("missing") or []})
            plan["missing"] = missing
            plan["held"] = {"reason": "intent_unclear", "slots": [], "calendars": [], "missing": missing,
                            "message": "It is not clear enough what this message asks for, so nothing "
                                       "is proposed. Read it and decide."}
            plan["decisions"].append({"decision": "hold", "reason": "intent_unclear",
                                      "explanation": "The request was not clear enough to act on."})
            return
        triage = item.get("triage") or {}
        floor = triage.get("meeting_intent") if triage.get("category") == "meeting_request" else None
        scheduled = False
        for intent in sure:
            kind, details = intent["type"], intent.get("details") or {}
            if kind in understanding.SCHEDULING:
                if scheduled:
                    plan.setdefault("unresolved", []).append({
                        "text": str((intent.get("evidence") or [kind])[0])[:300], "why": "second_scheduling_request"})
                    plan["decisions"].append({"decision": "none", "reason": "second_scheduling_request",
                                              "explanation": "A second scheduling request in the same "
                                                             "message was left for you."})
                    continue
                scheduled = True
                wanted = {"new_meeting": "new", "reschedule": "reschedule", "cancellation": "cancel"}[kind]
                doubt = self._time_in_doubt(intent, self.service.now(user))
                if doubt and kind != "cancellation":
                    # The reader named a time AND said the time is unclear, or
                    # quoted two days or two times for one meeting. Picking
                    # one is a guess; the sender is asked instead.
                    intent = {**intent, "details": {key: value for key, value in details.items()
                                                    if key not in ("requested_start", "requested_end")}}
                    plan.setdefault("missing", []).append("which time")
                    plan["decisions"].append({"decision": "hold", "reason": "time_ambiguous",
                                              "explanation": doubt})
                # The rules' reading is the floor: a change request stays one.
                if floor in ("reschedule", "cancel"):
                    wanted = floor
                self._plan_meeting(ctx, user, item, calendar, plan, intent=wanted,
                                   extracted=understanding.extracted_from(intent))
            elif kind == "task":
                self._plan_task(ctx, user, item, plan, title=details.get("title"), due_at=details.get("due_at"),
                                evidence=intent.get("evidence"), alone=len(sure) == 1)
            elif kind == "reminder":
                when = _moment(details.get("remind_at"))
                if details.get("title") and when is not None and when > self.service.now(user):
                    plan["proposals"].append({
                        "tool_name": "create_reminder", "purpose": "record_task",
                        "reason": "The message asks to be reminded.",
                        "tool_input": {"title": str(details["title"])[:160], "remind_at": when.isoformat()}})
                else:
                    plan.setdefault("unresolved", []).append({
                        "text": str((intent.get("evidence") or ["a reminder"])[0])[:300], "why": "details_missing"})
                    plan.setdefault("missing", []).append("reminder time")
                    plan["decisions"].append({"decision": "hold", "reason": "details_missing",
                                              "explanation": "A reminder was asked for with no time "
                                                             "that could be read; none is proposed."})
            elif kind in ("reply_needed", "information_request"):
                plan["decisions"].append({
                    "decision": "escalate", "reason": "reply_needs_author",
                    "explanation": "This needs a reply in your words. A draft can be prepared for "
                                   "you to review."})
            else:
                plan["decisions"].append({"decision": "none", "reason": kind,
                                          "explanation": "No action is needed for this part."})
        if triage.get("category") == "action_item" and not any(
                p.get("tool_name") in ("create_task", "create_reminder") for p in plan["proposals"]) \
                and (plan.get("held") or {}).get("reason") != "task_exists" \
                and not any(d.get("reason") in ("task_exists", "possibly_same_as_open_task")
                            for d in plan["decisions"]):
            # The rules' reading is the floor here too: a message they read as
            # something to do is recorded as a task even when the model saw
            # only a reply in it. A decision someone is waiting for is work.
            self._plan_task(ctx, user, item, plan)

    def _note_finished_work(self, ctx: Any, user: Any, item: Dict[str, Any], plan: Dict[str, Any],
                            found: Mapping[str, Any]) -> None:
        """A message may report that something the executive was tracking is
        finished. The Desk says WHICH open task only when exactly one matches
        the message's own words; it never picks between two."""
        text = f"{item.get('subject') or ''}\n{item.get('body') or item.get('snippet') or ''}"
        said_by_model = [i for i in found.get("intents") or [] if i.get("type") == "work_done"
                         and (i.get("confidence") or 0) >= understanding.MIN_CONFIDENCE]
        category = (item.get("triage") or {}).get("category")
        by_rule = category not in ("meeting_request", "automated") and planning.work_reported_done(text)
        if not said_by_model and not by_rule:
            return
        try:
            open_tasks = self.gateway.open_tasks(ctx, user, 100)
            plan["reads"].append({"tool": "task.list", "ok": True, "count": len(open_tasks)})
        except Exception:
            plan["reads"].append({"tool": "task.list", "ok": False, "error": "unavailable"})
            return
        # Matched against the MESSAGE only. A model's own words about which
        # task it is are not evidence: they could name a task the message
        # never mentions.
        match = planning.match_open_task(text, open_tasks)
        if match["status"] == "several":
            plan["decisions"].append({
                "decision": "none", "reason": "task_match_ambiguous",
                "explanation": "This reports finished work, and more than one open task could be "
                               "the one it means. None was marked done."})
            return
        if match["status"] != "one":
            return
        task = match["task"]
        plan.setdefault("task_updates", []).append({
            "op": "complete", "taskId": str(task.get("id")), "title": task.get("title"),
            "matched": match.get("matched"), "source": "model" if said_by_model else "rules"})
        plan.setdefault("facts", []).append(
            f"You have one open task this is about: \"{task.get('title')}\".")
        plan["decisions"].append({
            "decision": "complete_task", "reason": "work_reported_done",
            "explanation": f"The message reports \"{task.get('title')}\" as finished."})

    def _apply_task_updates(self, ctx: Any, user: Any, run: Dict[str, Any], plan: Mapping[str, Any]) -> None:
        policy = getattr(self.gateway, "auto_internal_writes", None)
        automatic = bool(callable(policy) and policy(user))
        for update in plan.get("task_updates") or []:
            self._record(user, run, "task", {**update, "state": "suggested"})
            if automatic:
                # The person's own records, and this Desk is set to keep them
                # without asking: the same fixed rule as for a new task.
                self._complete_task(ctx, user, run, str(update["taskId"]), by="policy")

    def _complete_task(self, ctx: Any, user: Any, run: Dict[str, Any], task_id: str, *, by: str) -> None:
        known = {u["taskId"]: u for u in lifecycle.task_updates(self.gateway.run_events(user, run))}
        update = known.get(task_id)
        if update is None:
            raise NotFound("This run suggests no change to that task.")
        if update.get("state") == "completed":
            return                                      # repeating it changes nothing
        try:
            self.gateway.complete_task(ctx, user, task_id)
        except Exception as exc:
            self._record(user, run, "task", {"taskId": task_id, "title": update.get("title"), "op": "complete",
                                             "state": "failed", "error": type(exc).__name__, "by": by})
            return
        # Verified by reading the tasks back: it is no longer among the open ones.
        try:
            still_open = any(str(t.get("id")) == task_id for t in self.gateway.open_tasks(ctx, user, 200))
            verified: Optional[bool] = not still_open
        except Exception:
            verified = None
        self._record(user, run, "task", {
            "taskId": task_id, "title": update.get("title"), "op": "complete",
            # Done only on evidence. When the tasks could not be read back the
            # call returned and nothing shows the result: that is not "completed".
            "state": "completed" if verified is True else ("failed" if verified is False else "unverified"),
            "verified": verified, "by": by,
            "error": None if verified is True else ("task_still_open" if verified is False else "task_not_read_back")})

    def apply_task_update(self, ctx: Any, user: Any, run_id: int, task_id: str,
                          *, dismiss: bool = False) -> Dict[str, Any]:
        """The person confirms (or dismisses) marking one of their tasks done."""
        run = self._run(user, run_id)
        with self._lock(run["meta"]["key"]):
            known = {u["taskId"]: u for u in lifecycle.task_updates(self.gateway.run_events(user, run))}
            if str(task_id) not in known:
                raise NotFound("This run suggests no change to that task.")
            if dismiss:
                if known[str(task_id)].get("state") == "suggested":
                    self._record(user, run, "task", {"taskId": str(task_id), "op": "complete",
                                                     "state": "dismissed", "by": user.email})
            else:
                self._complete_task(ctx, user, run, str(task_id), by=user.email)
        return self.view(ctx, user, run_id)

    def resolve_unresolved(self, ctx: Any, user: Any, run_id: int) -> Dict[str, Any]:
        """The person has seen the requests the Desk could not act on and
        takes them from here. Until then the run is not complete."""
        run = self._run(user, run_id)
        with self._lock(run["meta"]["key"]):
            open_ones = [entry for entry in lifecycle.unresolved_of(run["meta"], self.gateway.run_events(user, run))
                         if not entry["resolved"]]
            if open_ones:
                self._record(user, run, "human", {"action": "resolve_unresolved", "by": user.email,
                                                  "ids": [entry["id"] for entry in open_ones]})
        return self.view(ctx, user, run_id)

    # ── changing a workbook: always a copy, always asked for ────────────────
    def _run_file(self, user: Any, run: Dict[str, Any], file_id: str) -> Dict[str, Any]:
        """A file that belongs to THIS run: one that came with its message, or
        one the run generated. Anything else is not found."""
        events = self.gateway.run_events(user, run)
        own = {str((e.get("data") or {}).get("attachmentId")) for e in events
               if e.get("kind") == "read" and (e.get("data") or {}).get("tool") == "file.read_attachment"}
        own |= {str(((c.get("output") or {}).get("document") or {}).get("id")) for c in self.gateway.run_cards(user, run)}
        own |= {str(change.get("resultFileId")) for change in lifecycle.file_changes(events)}
        lookup = getattr(self.gateway, "stored_file", None)
        found = lookup(user, str(file_id)) if callable(lookup) and str(file_id) in own else None
        if not found:
            raise NotFound("That file is not part of this run.")
        return found

    def suggest_file_change(self, ctx: Any, user: Any, run_id: int, file_id: str, operations: Any) -> Dict[str, Any]:
        """Record a change to a workbook of this run as a suggestion. Nothing
        is changed: the person applies it or dismisses it."""
        run = self._run(user, run_id)
        with self._lock(run["meta"]["key"]):
            source = self._run_file(user, run, file_id)
            clean, problems = workbooks.validate(operations)
            if problems:
                raise InvalidRequest(" ".join(problems))
            info = files.inspect(source["filename"], source["content"])
            if not info["ok"] or info["kind"] != "xlsx":
                raise InvalidRequest("Only an .xlsx workbook can be changed.")
            known = lifecycle.file_changes(self.gateway.run_events(user, run))
            bound = workbooks.binding(source["sha256"], clean)
            if any(c.get("binding") == bound and c.get("state") in ("suggested", "applied") for c in known):
                return self.view(ctx, user, run_id)          # the same change, asked again: nothing new
            self._record(user, run, "file", {
                "changeId": f"fc-{run['id']}-{len(known) + 1}", "op": "change_workbook", "state": "suggested",
                "sourceFileId": str(source["id"]), "filename": source["filename"], "sourceSha256": source["sha256"],
                "operations": clean, "binding": bound, "by": user.email})
        return self.view(ctx, user, run_id)

    def apply_file_change(self, ctx: Any, user: Any, run_id: int, change_id: str,
                          *, dismiss: bool = False) -> Dict[str, Any]:
        """The person applies (or dismisses) a suggested change. Applying runs
        Scriba's Excel skills on a copy and keeps the result as a NEW file."""
        run = self._run(user, run_id)
        with self._lock(run["meta"]["key"]):
            known = {c["changeId"]: c for c in lifecycle.file_changes(self.gateway.run_events(user, run))}
            change = known.get(str(change_id))
            if change is None:
                raise NotFound("This run suggests no such change.")
            if change.get("state") == ("dismissed" if dismiss else "applied"):
                return self.view(ctx, user, run_id)          # repeating it changes nothing
            base = {"changeId": change["changeId"], "op": "change_workbook", "filename": change.get("filename")}
            if dismiss and change.get("state") in ("suggested", "failed", "unverified"):
                # Setting aside a change that failed or could not be verified is the person's
                # acknowledgement, not a success: what it was stays on the record.
                self._record(user, run, "file", {**base, "state": "dismissed", "dismissedFrom": change.get("state"),
                                                 "by": user.email})
                return self.view(ctx, user, run_id)
            if change.get("state") != "suggested":
                raise Conflict(f"This change is {change.get('state')}; it cannot be "
                               f"{'dismissed' if dismiss else 'applied'}."
                               + ("" if dismiss else " Suggest it again."))
            source = self._run_file(user, run, str(change.get("sourceFileId")))
            # Bound to the file and the operations that were shown.
            if workbooks.binding(source["sha256"], change.get("operations") or []) != change.get("binding"):
                self._record(user, run, "file", {**base, "state": "failed", "error": "change_no_longer_matches",
                                                 "by": user.email})
                return self.view(ctx, user, run_id)
            done = workbooks.apply(source["filename"], source["content"], change["operations"])
            if not done["ok"]:
                self._record(user, run, "file", {**base, "state": "failed", "error": done.get("code"),
                                                 "message": done.get("message"), "failedAt": done.get("failedAt"),
                                                 "steps": done.get("steps"), "by": user.email})
                return self.view(ctx, user, run_id)
            check = workbooks.verify(source["filename"], source["content"], done["content"], change["operations"],
                                     done["steps"])
            if not check["ok"]:
                # The skills said yes and the reopened result disagrees: it is not kept.
                self._record(user, run, "file", {**base, "state": "failed", "error": "result_not_verified",
                                                 "verification": check, "steps": done["steps"], "by": user.email})
                return self.view(ctx, user, run_id)
            keep = getattr(self.gateway, "keep_file", None)
            try:
                stored = keep(user, filename=workbooks.result_name(source["filename"]), content=done["content"],
                              mime_type=workbooks.XLSX_MIME, extension=".xlsx") if callable(keep) else None
            except Exception as exc:
                uncertain = bool(getattr(exc, "uncertain", False))
                self._record(user, run, "file", {**base, "state": "unverified" if uncertain else "failed",
                                                 "error": "file_store_did_not_confirm" if uncertain else "file_store_failed",
                                                 "steps": done["steps"], "by": user.email})
                return self.view(ctx, user, run_id)
            if not stored:
                self._record(user, run, "file", {**base, "state": "failed", "error": "no_file_store",
                                                 "message": "This backend keeps no files for the Desk.", "by": user.email})
                return self.view(ctx, user, run_id)
            # Read the kept file back: it must be the bytes that were verified.
            kept = self.gateway.stored_file(user, str(stored["id"]))
            same = bool(kept) and kept["sha256"] == done["sha256"]
            self._record(user, run, "file", {
                **base, "state": "applied" if same else "unverified", "resultFileId": str(stored["id"]),
                "resultFilename": stored.get("filename"), "resultSha256": done["sha256"],
                "sizeBytes": stored.get("size_bytes"), "steps": done["steps"],
                "verification": {**check, "method": "workbook_reopened", "verified": same},
                "error": None if same else "kept_file_differs", "by": user.email})
        return self.view(ctx, user, run_id)

    def _close_awaited(self, user: Any, item: Dict[str, Any], plan: Dict[str, Any]) -> None:
        """This message may be the answer someone was being waited on for."""
        waiting = getattr(self.gateway, "waiting_follow_ups", None)
        if not callable(waiting):
            return
        sender = sender_address(str(item.get("from_addr") or ""))
        for follow in waiting(user):
            awaited = follow.get("waitingOn") or {}
            address = str(awaited.get("email") if isinstance(awaited, dict) else awaited or "").lower()
            if str(follow.get("threadId") or "") == str(item.get("threadId") or "") and address == sender:
                if requests.is_holding_reply(item.get("body") or item.get("snippet")):
                    # They wrote, and what they wrote is that it is not there
                    # yet. The wait stays open.
                    plan.setdefault("kept_follow_ups", []).append({
                        "id": follow["id"], "state": "waiting", "external": True, "reason": "holding_reply",
                        "lastHoldingReplyId": item.get("id"), "lastHoldingReplyAt": item.get("timestamp"),
                        "waitingOn": address, "threadId": follow.get("threadId")})
                    plan["decisions"].append({
                        "decision": "keep_follow_up_open", "reason": "holding_reply",
                        "explanation": "This says the answer is still to come, so the follow-up stays open."})
                    continue
                if self.gateway.close_waiting_follow_up(user, follow["id"]):
                    plan.setdefault("closed_follow_ups", []).append({
                        "id": follow["id"], "state": "satisfied", "external": True,
                        "satisfiedBy": item.get("id"), "waitingOn": address,
                        "threadId": follow.get("threadId")})
                    plan["decisions"].append({
                        "decision": "close_follow_up", "reason": "answer_received",
                        "explanation": "This is the answer you were waiting for, so that "
                                       "follow-up was closed."})

    def _plan_task(self, ctx: Any, user: Any, item: Dict[str, Any], plan: Dict[str, Any],
                   title: Optional[str] = None, due_at: Optional[str] = None,
                   evidence: Optional[List[str]] = None, alone: bool = True) -> None:
        title = str(title or item.get("subject") or "Follow up on email").strip()[:160]
        try:
            open_tasks = self.gateway.open_tasks(ctx, user, 100)
            plan["reads"].append({"tool": "task.list", "ok": True, "count": len(open_tasks)})
        except Exception:
            open_tasks = None
            plan["reads"].append({"tool": "task.list", "ok": False, "error": "unavailable"})
        same = None
        if open_tasks and not any(_same_title(task.get("title"), title) for task in open_tasks):
            # Not the same title; is it the same work? An open task most of
            # whose title is in this request, when no other task comes close.
            match = planning.match_open_task(f"{title}\n{' '.join(str(q) for q in evidence or [])}", open_tasks)
            same = match["task"] if match["status"] == "one" else None
        if same is not None:
            wanted = _moment(due_at) if due_at else None
            theirs = _moment(same.get("due_at"))
            if wanted is None or theirs is None or abs((wanted - theirs).total_seconds()) < 3600:
                # Same work, same date (or none stated): it is already recorded.
                plan["held"] = plan["held"] or {
                    "reason": "task_exists", "slots": [], "calendars": [],
                    "target": {"taskId": str(same.get("id")), "title": same.get("title")},
                    "message": f"You already have an open task for this (\"{same.get('title')}\"), so no "
                               "second one is proposed."}
                plan["decisions"].append({"decision": "none", "reason": "task_exists",
                                          "explanation": "You already have this task."})
            else:
                # It looks like a task you have, with another date. Not a
                # second task, and not silently dropped either.
                plan.setdefault("unresolved", []).append({
                    "text": title[:300], "why": "possibly_same_as_open_task", "taskId": str(same.get("id"))})
                plan["decisions"].append({"decision": "none", "reason": "possibly_same_as_open_task",
                                          "explanation": f"This may be your open task \"{same.get('title')}\" "
                                                         "with a different date. It was left for you."})
            return
        if open_tasks and any(_same_title(task.get("title"), title) for task in open_tasks):
            # A second message about the same thing must not make a second task.
            plan["held"] = {"reason": "task_exists", "slots": [], "calendars": [],
                            "message": "An open task with this title already exists, so no second "
                                       "one is proposed."}
            plan["decisions"].append({"decision": "none", "reason": "task_exists",
                                      "explanation": "You already have this task."})
            return
        task: Dict[str, Any] = {
            "title": title,
            "description": (f"From {item.get('from_addr')}, received {item.get('timestamp')} "
                            f"({item.get('provider')}). {item.get('snippet') or ''}").strip(),
            "priority": item["triage"].get("priority") or "medium",
        }
        due = None
        try:
            zone_name, _, _, _ = self.service.working_context(user, None, None, None)
            local_now = self.service.now(user).astimezone(resolve_zone(zone_name))
            whole = f"{item.get('subject')}\n{item.get('body') or item.get('snippet') or ''}"
            if evidence:
                # One request among several: its deadline is in its own
                # sentence. Another request's date (the meeting's) is not it.
                due = planning.deadline_from(" ".join(str(quote) for quote in evidence), local_now)
                if due is None and alone:
                    due = planning.deadline_from(whole, local_now)
            else:
                due = planning.deadline_from(whole, local_now)
        except InvalidAvailabilityRequest:
            due = None
        if due_at and _moment(due_at) is not None:
            due = _moment(due_at)           # stated by the model, with its evidence checked
        if due is None:
            plan.setdefault("assumptions", []).append("No deadline is written in the message; the task has none.")
        if due is not None:
            task["due_at"] = due.isoformat()
        pressing = reading.urgency(f"{item.get('subject')} {item.get('body') or item.get('snippet') or ''}",
                                   due, self.service.now(user).astimezone(due.tzinfo) if due else
                                   self.service.now(user))
        if pressing:
            task["priority"] = "high"          # Scriba's task priorities stop at high
            plan["priority"] = pressing
        plan["proposals"].append({"tool_name": "create_task", "tool_input": task, "purpose": "record_task",
                                  "reason": "The message names something to do"
                                            + (f", due {due.isoformat()}." if due else
                                               "; no date could be read from it.")})
        plan["decisions"].append({"decision": "propose", "reason": "action_item",
                                  "explanation": "A task is proposed from this message."})

    def _offer(self, user: Any, item: Dict[str, Any], calendar: Optional[Dict[str, Any]],
               reason: str, purpose: str) -> Optional[Dict[str, Any]]:
        """A reply offering times verified free on EVERY calendar, or None
        when there is nothing verified to offer."""
        slots = (calendar or {}).get("slots") or []
        recipient = sender_address(str(item.get("from_addr") or ""))
        if not (calendar or {}).get("complete") or not slots or not recipient:
            return None
        offered = [{"start": slot["start"], "end": slot["end"]} for slot in slots[:3]]
        return {"tool_name": "send_email", "purpose": purpose, "proposedSlots": offered,
                "reason": "Only times verified free on every connected calendar are offered.",
                "tool_input": self._reply_input(item, planning.offer_times_reply(
                    slots=offered, timezone=str(calendar.get("timezone") or ""), reason=reason))}

    @staticmethod
    def _reply_input(item: Dict[str, Any], body: str) -> Dict[str, Any]:
        provider = str(item.get("provider") or "gmail")
        reply: Dict[str, Any] = {
            "provider": provider, "mode": "reply",
            "to": sender_address(str(item.get("from_addr") or "")),
            "subject": planning.reply_subject(str(item.get("subject") or "")),
            "body": body, "thread_id": item.get("threadId") or item.get("thread_id"),
            "provider_account_id": item.get("provider_account_id"),
        }
        # Name the message being answered in the field each provider uses.
        reply["email_id" if provider == "gmail" else "message_id"] = item.get("id") or item.get("email_id")
        return reply

    def _hold(self, plan: Dict[str, Any], user: Any, item: Dict[str, Any],
              calendar: Optional[Dict[str, Any]], reason: str, message: str,
              offer: Optional[str] = None, **extra: Any) -> None:
        plan["held"] = {"reason": reason, "slots": (calendar or {}).get("slots") or [],
                        "calendars": (calendar or {}).get("calendars") or [], "message": message, **extra}
        plan["decisions"].append({"decision": "hold", "reason": reason, "explanation": message})
        if offer:
            reply = self._offer(user, item, calendar, reason if reason != "change_time_busy" else "reschedule",
                                offer)
            if reply:
                plan["proposals"].append(reply)
                plan["decisions"].append({"decision": "propose", "reason": offer,
                                          "explanation": "A reply offering verified free times is proposed."})

    def _plan_meeting(self, ctx: Any, user: Any, item: Dict[str, Any],
                      calendar: Optional[Dict[str, Any]], plan: Dict[str, Any],
                      intent: Optional[str] = None, extracted: Optional[Dict[str, Any]] = None) -> None:
        pre_read = extracted is not None
        intent = intent or (item.get("triage") or {}).get("meeting_intent") or "new"
        subject, text = str(item.get("subject") or ""), str(item.get("body") or item.get("snippet") or "")
        # (An instruction that is taken back is stopped earlier, in ``_plan``,
        # before any reader is asked.)
        if intent == "new" and not pre_read and reading.refers_to_existing(subject, text) \
                and self._sender_has_meeting(user, item):
            # New or change is decided from the calendar, not from the verb:
            # the message speaks of an existing meeting and the sender is on
            # one. Booking a second event beside it would be the wrong action.
            # (Not when a model has read the message and reported a new
            # meeting: this wording test then moved a meeting nobody asked to
            # move. A model that reads a change says so, and that is honoured.)
            intent = "reschedule"
            plan["decisions"].append({"decision": "read_as_change", "reason": "refers_to_existing_meeting",
                                      "explanation": "The message refers to a meeting the sender is "
                                                     "already on, so it is read as a change to it."})
        try:
            zone_name, _, _, duration = self.service.working_context(user, None, None, None)
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "invalid_preferences",
                       "The time zone in your preferences is not valid.")
            return

        usage_scope = getattr(self.gateway, "model_usage", None)
        configured = getattr(self.gateway, "model_configured", None)
        has_model = bool(configured()) if callable(configured) else True
        model_failed = False
        if pre_read:
            pass                    # the model's understanding already read the request
        elif callable(usage_scope):
            with usage_scope() as calls:
                extracted = self.gateway.extract_meeting(user, item, zone_name)
            plan["usage"].extend(calls)
            # A call that did not complete (the provider is unreachable) is
            # not an answer. "The model read no time" and "the model could
            # not be asked" are different things.
            model_failed = not extracted and any(call.get("success") is False for call in calls)
        else:
            extracted = self.gateway.extract_meeting(user, item, zone_name)
        if not pre_read:
            plan["reads"].append({"tool": "model.extract_request", "ok": bool(extracted),
                                  "error": None if extracted else
                                  ("model_call_failed" if model_failed else
                                   "no_usable_answer" if has_model else "model_not_configured")})
        if not extracted and (not has_model or model_failed):
            # No model in this process, or it could not be reached. A time
            # that is written out in full is read by rule; anything less
            # exact is left unread, never guessed.
            written = reading.explicit_request(
                str(plan.get("meeting_text") or item.get("body") or item.get("snippet") or ""),
                self.service.now(user).astimezone(resolve_zone(zone_name)),
                change=intent in ("reschedule", "cancel"))
            now_local = self.service.now(user).astimezone(resolve_zone(zone_name))
            in_subject = reading.days_named(subject, now_local)
            in_body = reading.days_named(text, now_local)
            disagree = bool(in_subject and in_body and not set(in_subject) & set(in_body)
                            and intent == "new") or reading.weekday_contradicts_date(
                                f"{subject}\n{text}", now_local.date())
            plan["reads"].append({"tool": "rules.extract_time", "ok": bool(written) and not disagree,
                                  "error": "days_disagree" if disagree else
                                  (None if written else "no_single_written_time")})
            if disagree:
                self._hold(plan, user, item, calendar, "conflicting_instructions",
                           "The message names more than one day for the same thing (the subject and "
                           "the text disagree, or a weekday does not match its date), so no time is "
                           "picked. Ask which day is meant.")
                return
            if written:
                extracted = {**written, "calendar_action": "create" if intent == "new" else intent}
                plan["planner"] = "rules"
        elif extracted and not pre_read:
            plan["planner"] = "rules+model"
        if extracted and extracted.get("requested_start") and intent != "cancel" \
                and str(extracted.get("calendar_action") or "").lower() != "cancel" \
                and reading.weekday_contradicts_date(
                    f"{subject}\n{text}", self.service.now(user).astimezone(resolve_zone(zone_name)).date()):
            # "Wednesday 9 March", and the 9th is a Tuesday. Whoever read a
            # time out of that picked one of the two: a rule does not, and a
            # model may not either. The sender is asked which day is meant.
            plan["reads"].append({"tool": "rules.check_date", "ok": False, "error": "weekday_contradicts_date"})
            self._hold(plan, user, item, calendar, "conflicting_instructions",
                       "The message names a weekday that does not match its date, so no day is "
                       "picked. Ask which day is meant.")
            return
        if extracted and not extracted.get("requested_end") and not extracted.get("duration_minutes") \
                and intent == "new" and extracted.get("requested_start"):
            plan.setdefault("assumptions", []).append(
                f"The length was not stated; your default of {duration} minutes is used.")
        action = str((extracted or {}).get("calendar_action") or "").lower()
        if extracted and "cancel" not in (intent, action) and reading.stated_zone(
                str(item.get("body") or item.get("snippet") or ""))[1]:
            # The message names a zone that means more than one place ("IST",
            # "my time"). A model may still hand back a time with an offset:
            # that offset is its guess, and a guessed hour is not booked. The
            # rules refuse the same text; so does this.
            extracted = {key: value for key, value in extracted.items()
                         if key not in ("requested_start", "requested_end", "requester_timezone")}
            plan.setdefault("missing", []).append("time zone")
            plan["decisions"].append({
                "decision": "hold", "reason": "timezone_ambiguous",
                "explanation": "The message names a time zone that can mean more than one place, "
                               "so the time it gives was not used."})
        # The rule-based intent is the floor. The model may recognise a change
        # the rules missed; it may not turn a change request into a new booking.
        if intent == "new" and action in ("reschedule", "cancel"):
            intent = action
        if intent in ("reschedule", "cancel"):
            self._plan_change(ctx, user, item, calendar, plan, intent, extracted, zone_name)
            return

        start = str((extracted or {}).get("requested_start") or "").strip()
        if not extracted or action not in ("create", "") or not start:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "No specific time could be read from the message, so no event is proposed. "
                       "Offer the free times in a reply.", offer="clarify")
            return
        window = self._window(start, extracted, zone_name, duration)
        if window is None:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "The requested time could not be read.", offer="clarify")
            return
        try:
            check = self.service.slot_check(ctx, user, start=window[0], end=window[1], timezone=zone_name)
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "The requested time could not be read.", offer="clarify")
            return
        for entry in check["calendars"]:
            plan["reads"].append({"tool": "calendar.check_availability", "provider": entry.get("provider"),
                                  "account": entry.get("account"), "ok": bool(entry.get("ok")),
                                  "error": entry.get("error"), "timeMin": check["slot"]["start"],
                                  "timeMax": check["slot"]["end"]})
        if check["free"] is False and self._already_scheduled(user, item, check, plan):
            return
        if check["free"] is not True:
            conflict = check["free"] is False
            self._hold(
                plan, user, item, calendar,
                "calendar_conflict" if conflict else "availability_unknown",
                ("The requested time conflicts with an existing commitment. " if conflict else
                 "A calendar could not be read, so the requested time is not verified. ")
                + "No event is proposed. Offer verified free times in a reply.",
                offer="offer_times" if conflict else None,
                requested=check["slot"], conflicts=check["conflicts"], calendars=check["calendars"])
            return
        # Attendees: the sender, taken from the message's From header. Names or
        # addresses that appear only in the message text are not added.
        plan.setdefault("facts", []).append(
            f"The requested time is free on every connected calendar ({len(check['calendars'])} read).")
        if not check.get("within_working_hours"):
            # Free, but outside the hours the executive works. Still proposed:
            # the person decides, and is told.
            plan["flags"].append("outside_working_hours")
            plan["facts"].append("The requested time is outside your working hours.")
        sender = sender_address(str(item.get("from_addr") or ""))
        plan.setdefault("assumptions", []).append(
            "The only attendee is the sender; nobody named only in the text is invited.")
        event_input: Dict[str, Any] = {
            "title": str(extracted.get("summary") or item.get("subject") or "Meeting").strip()[:160],
            "start": check["slot"]["start"], "end": check["slot"]["end"], "timezone": zone_name,
            "attendees": [sender] if sender else [],
            "description": f"Requested by {item.get('from_addr')} by email.",
        }
        # The meeting goes on the calendar of the account the request reached:
        # the invitation then comes from the address the sender wrote to. It is
        # named on the card, never left for Scriba to choose between calendars.
        requester_zone = str(extracted.get("requester_timezone") or "").strip()
        if requester_zone and requester_zone != zone_name:
            plan["requester_timezone"] = requester_zone
        if str(item.get("provider")) == "outlook":
            event_input["calendar_provider"] = "outlook"
        else:
            event_input["calendar_provider"] = "google"
            if item.get("provider_account_id"):
                event_input["provider_account_id"] = item.get("provider_account_id")
        plan["proposals"].append({
            "tool_name": "create_calendar_event", "purpose": "book",
            "reason": "The requested time is free on every connected calendar."
                      + (" It is outside your working hours." if "outside_working_hours" in plan["flags"] else ""),
            "tool_input": event_input})
        plan["decisions"].append({"decision": "propose", "reason": "time_free",
                                  "explanation": "The requested time is free, so the meeting is "
                                                 "proposed for your approval."})

    def _sender_has_meeting(self, user: Any, item: Dict[str, Any]) -> bool:
        """The sender is on a meeting that is still ahead. A calendar that
        cannot be read says nothing: the request is then planned as written."""
        sender = sender_address(str(item.get("from_addr") or ""))
        now = self.service.now(user)
        if not sender:
            return False
        try:
            events = self.gateway.calendar_events(user, now, now + dt.timedelta(days=EVENT_SEARCH_DAYS))
        except Exception:
            return False
        found = planning.find_target_events(events, sender=sender, subject=str(item.get("subject") or ""), now=now,
                                            text=str(item.get("body") or item.get("snippet") or ""))
        return found["status"] in ("found", "ambiguous")

    def _already_scheduled(self, user: Any, item: Dict[str, Any], check: Dict[str, Any],
                           plan: Dict[str, Any]) -> bool:
        """The "conflict" is this very meeting: the sender is already on an
        event at exactly the requested time. A request that is sent again must
        not be answered with alternatives, and never booked twice."""
        sender = sender_address(str(item.get("from_addr") or ""))
        zone = resolve_zone(check["timezone"])
        try:
            start = parse_instant(check["slot"]["start"], zone)
            end = parse_instant(check["slot"]["end"], zone)
            events = self.gateway.calendar_events(user, start - dt.timedelta(minutes=1),
                                                  end + dt.timedelta(minutes=1))
        except Exception:
            return False
        for event in events:
            people = {str(a).lower() for a in (event.get("attendees") or [])}
            try:
                same = parse_instant(str(event.get("start")), zone) == start
            except InvalidAvailabilityRequest:
                same = False
            if sender and sender in people and same:
                plan["flags"].append("duplicate")
                plan["held"] = {
                    "reason": "already_scheduled", "slots": [], "calendars": check["calendars"],
                    "target": {key: event.get(key) for key in ("id", "title", "start", "end", "provider")},
                    "message": "This meeting is already on your calendar with this sender at that "
                               "time. Nothing more is proposed."}
                plan["decisions"].append({"decision": "none", "reason": "already_scheduled",
                                          "explanation": "The request repeats a meeting that is "
                                                         "already booked."})
                return True
        return False

    @staticmethod
    def _window(start: str, extracted: Dict[str, Any], zone_name: str, duration: int) -> Optional[tuple]:
        end = str(extracted.get("requested_end") or "").strip()
        if end:
            return start, end
        try:
            minutes = int(extracted.get("duration_minutes") or duration)
            return start, (parse_instant(start, resolve_zone(zone_name))
                           + dt.timedelta(minutes=max(15, min(minutes, 480)))).isoformat()
        except (InvalidAvailabilityRequest, TypeError, ValueError):
            return None

    def _plan_change(self, ctx: Any, user: Any, item: Dict[str, Any], calendar: Optional[Dict[str, Any]],
                     plan: Dict[str, Any], intent: str, extracted: Optional[Dict[str, Any]],
                     zone_name: str) -> None:
        """Move or cancel the ORIGINAL event. Never a second event."""
        sender = sender_address(str(item.get("from_addr") or ""))
        now = self.service.now(user)
        try:
            events = self.gateway.calendar_events(user, now - dt.timedelta(days=1),
                                                  now + dt.timedelta(days=EVENT_SEARCH_DAYS))
            plan["reads"].append({"tool": "calendar.list_events", "ok": True, "count": len(events),
                                  "timeMin": (now - dt.timedelta(days=1)).isoformat(),
                                  "timeMax": (now + dt.timedelta(days=EVENT_SEARCH_DAYS)).isoformat()})
        except Exception:
            plan["reads"].append({"tool": "calendar.list_events", "ok": False, "error": "unavailable"})
            self._hold(plan, user, item, calendar, "calendar_lookup_failed",
                       "Your calendar could not be searched for this meeting, so nothing is proposed.")
            return
        found = planning.find_target_events(
            events, sender=sender, subject=str(item.get("subject") or ""),
            hint=str((extracted or {}).get("target_event_hint") or ""), now=now,
            text=str(item.get("body") or item.get("snippet") or ""))
        if found["status"] == "named_not_found":
            self._hold(plan, user, item, calendar, "event_not_found",
                       "The message names a meeting (" + ", ".join(found["named"]) + ") and no meeting "
                       "with this sender carries that name, so nothing is changed. Their other "
                       "meetings are not touched.",
                       candidates=[{key: event.get(key) for key in ("id", "title", "start", "end", "provider")}
                                   for event in found["candidates"]][:5])
            return
        if found["status"] == "target_gone":
            # The meeting this is about was already cancelled or has taken
            # place. The sender's other meetings are not a substitute for it.
            plan["flags"].append("duplicate")
            self._hold(plan, user, item, calendar, "event_not_found",
                       "The meeting this seems to be about was already cancelled or has already taken "
                       "place, so there is nothing to change. No other meeting is touched.",
                       gone=[{key: event.get(key) for key in ("id", "title", "start", "end", "provider", "status")}
                             for event in found.get("gone") or []][:5])
            return
        candidates = [{key: event.get(key) for key in ("id", "title", "start", "end", "provider")}
                      for event in found["candidates"][:5]]
        if found["status"] == "sender_not_on_any_event":
            self._hold(plan, user, item, calendar, "event_not_found",
                       "No meeting with this sender was found in the next weeks, so there is nothing "
                       "to change. Check which meeting they mean.")
            return
        if found["status"] == "ambiguous":
            self._hold(plan, user, item, calendar, "event_ambiguous",
                       "Several meetings with this sender match. Choose which one they mean.",
                       candidates=candidates)
            return
        event = found["event"]
        target = {key: event.get(key) for key in ("id", "title", "start", "end", "provider",
                                                  "provider_account_id")}
        plan.setdefault("facts", []).append(
            f"The sender is on \"{event.get('title')}\", the only meeting this can be about.")
        if not event.get("is_organizer"):
            self._hold(plan, user, item, calendar, "not_organizer",
                       "You are not the organizer of this meeting, so it cannot be changed from "
                       "your calendar. Reply to the organizer instead.", target=target)
            return
        base = {"event_id": event.get("id"), "calendar_provider": event.get("provider"),
                "timezone": zone_name}
        if event.get("provider") == "google" and event.get("provider_account_id"):
            base["provider_account_id"] = event.get("provider_account_id")

        if intent == "cancel":
            plan["proposals"].append({
                "tool_name": "cancel_calendar_event", "purpose": "cancel", "tool_input": base,
                "reason": f"{sender} is on this meeting and asked to cancel it.", "target": target})
            plan["decisions"].append({"decision": "propose", "reason": "cancel_requested",
                                      "explanation": f"Cancelling \"{event.get('title')}\" is proposed "
                                                     "for your approval."})
            return

        start = str((extracted or {}).get("requested_start") or "").strip()
        zone = resolve_zone(zone_name)
        try:
            old_start = parse_instant(str(event.get("start")), zone)
            old_end = parse_instant(str(event.get("end")), zone)
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "calendar_lookup_failed",
                       "The meeting's current time could not be read.", target=target)
            return
        if not start:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "They ask to move this meeting but no new time could be read. Offer free "
                       "times in a reply.", offer="offer_times", target=target)
            return
        try:
            new_start = parse_instant(start, zone)
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "The new time could not be read.", offer="offer_times", target=target)
            return
        requested_end = str((extracted or {}).get("requested_end") or "").strip()
        try:
            new_end = parse_instant(requested_end, zone) if requested_end else new_start + (old_end - old_start)
        except InvalidAvailabilityRequest:
            new_end = new_start + (old_end - old_start)
        try:
            check = self.service.slot_check(ctx, user, start=new_start.isoformat(), end=new_end.isoformat(),
                                            timezone=zone_name, ignore=[(old_start, old_end)])
        except InvalidAvailabilityRequest:
            self._hold(plan, user, item, calendar, "time_not_understood",
                       "The new time could not be read.", offer="offer_times", target=target)
            return
        for entry in check["calendars"]:
            plan["reads"].append({"tool": "calendar.check_availability", "provider": entry.get("provider"),
                                  "account": entry.get("account"), "ok": bool(entry.get("ok")),
                                  "error": entry.get("error"), "timeMin": check["slot"]["start"],
                                  "timeMax": check["slot"]["end"]})
        if check["free"] is not True:
            conflict = check["free"] is False
            self._hold(plan, user, item, calendar,
                       "calendar_conflict" if conflict else "availability_unknown",
                       ("The new time conflicts with an existing commitment. " if conflict else
                        "A calendar could not be read, so the new time is not verified. ")
                       + "The meeting is not moved.",
                       offer="offer_times" if conflict else None, target=target,
                       requested=check["slot"], conflicts=check["conflicts"], calendars=check["calendars"])
            return
        plan["proposals"].append({
            "tool_name": "update_calendar_event", "purpose": "reschedule", "target": target,
            "reason": "The new time is free on every connected calendar. The existing event is moved.",
            "tool_input": {**base, "start": check["slot"]["start"], "end": check["slot"]["end"]}})
        plan["decisions"].append({"decision": "propose", "reason": "new_time_free",
                                  "explanation": f"Moving \"{event.get('title')}\" is proposed for "
                                                 "your approval."})

    # ── sweep ───────────────────────────────────────────────────────────────
    def sweep(self, ctx: Any, user: Any, *, provider: str = "all", limit: int = 25,
              max_new: int = SWEEP_MAX_NEW, mailbox: Optional[str] = None,
              trigger: str = "sweep") -> Dict[str, Any]:
        """Open a run for every recent message that needs one and has none.

        Bounded on purpose: at most ``max_new`` runs are opened per call,
        because each meeting request costs a model call and calendar reads.
        The rest are reported as ``deferred`` and picked up by the next call.
        One message failing does not stop the others. Like ``intake``, this
        proposes actions; it sends no mail and writes no calendar.
        """
        guard = self._lock(f"sweep|{int(user.id)}")
        if not guard.acquire(blocking=False):
            return {"account": user.email, "status": "already_running", "examined": 0,
                    "opened": [], "existing": 0, "skipped": 0, "deferred": [], "failed": [],
                    "sources": [], "complete": False}
        try:
            inbox = self.service.inbox(ctx, user, provider=provider, limit=limit, mailbox=mailbox)
            opened: List[Dict[str, Any]] = []
            deferred: List[Dict[str, Any]] = []
            failed: List[Dict[str, Any]] = []
            existing = skipped = 0
            for item in inbox["items"]:
                ref = {"provider": item.get("provider"), "id": item.get("id"),
                       "subject": item.get("subject"),
                       "category": (item.get("triage") or {}).get("category")}
                if ref["category"] not in SWEEP_CATEGORIES or not ref["id"] or not ref["provider"] \
                        or _not_inbound(item):
                    skipped += 1
                    continue
                key = run_key(user.id, ref["provider"], item.get("provider_account_id"), ref["id"],
                              self._namespace(user))
                if self.gateway.find_run(user, key) is not None:
                    existing += 1
                    continue
                if len(opened) + len(failed) >= max_new:
                    deferred.append(ref)
                    continue
                try:
                    run = self.intake(ctx, user, provider=ref["provider"], item_id=ref["id"],
                                      mailbox=mailbox, trigger=trigger)
                except IntakeBusy:
                    existing += 1             # a peer is opening it right now
                    continue
                except Exception as exc:  # one bad message must not stop the sweep
                    failed.append({**ref, "error": type(exc).__name__})
                    continue
                if run.get("duplicate"):
                    existing += 1
                else:
                    opened.append({**ref, "runId": run.get("runId"), "state": run.get("state")})
            return {"account": user.email, "status": "completed", "examined": len(inbox["items"]),
                    "opened": opened, "existing": existing, "skipped": skipped,
                    "deferred": deferred, "failed": failed,
                    "sources": inbox["sources"],
                    # False when a connected mailbox could not be read: mail may be missing.
                    "complete": bool(inbox["complete"])}
        finally:
            guard.release()

    # ── advancing after approval ────────────────────────────────────────────
    def advance(self, ctx: Any, user: Any, run_id: int) -> Dict[str, Any]:
        """Propose what may only follow an executed step, and look after the
        run's follow-ups. Safe to repeat.

        The plan decides: a deferred step is proposed when every step it
        depends on has taken effect, and is recorded as blocked, once, when
        one of them failed or was rejected. A blocked step is never proposed.
        """
        run = self._run(user, run_id)
        meta = run["meta"]
        with self._lock(meta["key"]):
            cards = self.gateway.run_cards(user, run)
            events = self.gateway.run_events(user, run)
            plan = _plan_of(events)
            if plan is None:
                self._advance_without_plan(user, run, cards, events)
            else:
                states = plans.step_states(plan, _cards_by_step(cards, events), _unverified(events))
                by_id = {step["id"]: step for step in states}
                blocked = {(e.get("data") or {}).get("stepId") for e in events
                           if e.get("kind") == "decision" and (e.get("data") or {}).get("decision") == "step_blocked"}
                for step in states:
                    if not step.get("deferred") or step.get("toolCallId") is not None:
                        continue
                    if step["state"] == "ready":
                        source = next((c for c in cards if c.get("id") == by_id[step["dependsOn"][0]]["toolCallId"]), None)
                        if source is None:
                            continue
                        if step.get("purpose") == "notify":
                            self.commands.propose_notification(user, run, source, step)
                        elif (step.get("pending") or {}).get("tool_name"):
                            self._propose(user, run, {**step["pending"], "stepId": step["id"]})
                        else:
                            self._propose_confirmation(user, run, source, step["id"])
                    elif step["state"] == "blocked" and step["id"] not in blocked:
                        self._record(user, run, "decision", {
                            "decision": "step_blocked", "stepId": step["id"], "tool": step["tool"],
                            "dependsOn": step["dependsOn"],
                            "explanation": "A step this one depends on did not take effect, or ran and could not be verified, so it "
                                           "is not proposed."})
            self._track_follow_ups(ctx, user, run)
        return self.view(ctx, user, run_id)

    def _advance_without_plan(self, user: Any, run: Dict[str, Any], cards: List[Dict[str, Any]],
                              events: List[Dict[str, Any]]) -> None:
        """Runs opened before plans were recorded."""
        purposes = self._purposes(user, run, events)
        if any(c["tool_name"] == "send_email" and purposes.get(c.get("id")) == "confirm" for c in cards):
            return
        changed = next((c for c in cards if c["tool_name"] in (
            "create_calendar_event", "update_calendar_event", "cancel_calendar_event")
            and c["status"] in _EFFECT), None)
        if changed is not None:
            self._propose_confirmation(user, run, changed, None)

    def _propose_confirmation(self, user: Any, run: Dict[str, Any], changed: Dict[str, Any],
                              step_id: Optional[str]) -> None:
        meta = run["meta"]
        if not sender_address(str(meta.get("from_addr") or "")):
            return
        # As approved: an edit the person made is what the sender is told.
        data, output = effective_input(changed), changed.get("output") or {}
        after = ((output.get("operation") or {}).get("after") or {})
        planned = data.get("planned_change") or {}
        title = str(data.get("title") or data.get("event_title") or after.get("title")
                    or meta.get("subject") or "the meeting")
        if changed["tool_name"] == "cancel_calendar_event":
            body = planning.cancellation_reply(title=title)
        else:
            body = planning.confirmation_reply(
                title=title, timezone=str(data.get("timezone") or ""),
                start=str(planned.get("start") or data.get("start")),
                end=str(planned.get("end") or data.get("end")),
                moved=changed["tool_name"] == "update_calendar_event",
                other_timezone=meta.get("requester_timezone"))
        item = {"provider": meta["provider"], "from_addr": meta.get("from_addr"),
                "subject": meta.get("subject"), "threadId": meta.get("thread_id"),
                "provider_account_id": meta.get("provider_account_id"), "id": meta.get("email_id")}
        self._propose(user, run, {
            "tool_name": "send_email", "purpose": "confirm", "stepId": step_id,
            "reason": "The calendar change has taken effect, so the sender is told.",
            "tool_input": self._reply_input(item, body)})

    def _purposes(self, user: Any, run: Dict[str, Any],
                  events: Optional[List[Dict[str, Any]]] = None) -> Dict[Any, Optional[str]]:
        events = events if events is not None else self.gateway.run_events(user, run)
        return {(e.get("data") or {}).get("toolCallId"): (e.get("data") or {}).get("purpose")
                for e in events if e.get("kind") == "proposal"}

    # ── follow-ups ──────────────────────────────────────────────────────────
    def _track_follow_ups(self, ctx: Any, user: Any, run: Dict[str, Any]) -> None:
        """Open a follow-up for each executed reply that awaits an answer;
        close it when the answer arrives; mark it overdue, and propose a
        reminder for approval, when it does not. Never sends anything."""
        meta = run["meta"]
        if meta.get("kind") == "command":
            return      # a reminder sent from an instruction belongs to the follow-up it chases
        events = self.gateway.run_events(user, run)
        cards = self.gateway.run_cards(user, run)
        purposes = self._purposes(user, run, events)
        known = {f["id"]: f for f in lifecycle.follow_ups(events)}
        now = self.service.now(user)
        executed_at = {(e.get("data") or {}).get("toolCallId"): e.get("at") for e in events
                       if e.get("kind") == "execution" and (e.get("data") or {}).get("status") == "executed"}

        for card in cards:
            purpose = purposes.get(card.get("id"))
            follow_id = f"fu-{run['id']}-{card.get('id')}"
            if (card["tool_name"] == "send_email" and card["status"] in _DONE
                    and purpose in REPLY_PURPOSES_AWAITING and follow_id not in known):
                data = card.get("input") or {}
                thread = data.get("thread_id") or meta.get("thread_id")
                person = sender_address(str(data.get("to") or meta.get("from_addr") or ""))
                if any(f.get("state") in ("waiting", "overdue", "escalated") and f.get("threadId") == thread
                       and f.get("waitingOn") == person for f in known.values()):
                    continue        # one wait per person and conversation, however many replies went out
                opened = {"id": follow_id, "state": "waiting", "kind": "reply", "toolCallId": card.get("id"),
                          "threadId": thread, "waitingOn": person,
                          "subject": meta.get("subject"),
                          # When the send executed, where that was recorded.
                          "sentAt": executed_at.get(card.get("id")) or now.isoformat(),
                          "dueAt": ((_moment(executed_at.get(card.get("id"))) or now)
                                    + dt.timedelta(days=FOLLOW_UP_DAYS)).isoformat()}
                self._record(user, run, "followup", opened)
                known[follow_id] = opened

        waiting = [f for f in known.values() if f.get("state") in ("waiting", "overdue")]
        if not waiting:
            return
        nudge_of = {(e.get("data") or {}).get("followUpId"): (e.get("data") or {}).get("toolCallId")
                    for e in events if e.get("kind") == "proposal" and (e.get("data") or {}).get("followUpId")}
        by_id = {card.get("id"): card for card in cards}
        try:
            sources, rows = self.service.read_mail(ctx, user, [meta["provider"]], 100, None)
        except Exception:
            return
        if not all(source.get("ok") for source in sources):
            return      # unknown is not "no reply": leave the follow-up as it is
        for follow in waiting:
            sent_at = _moment(follow.get("sentAt"))
            replies = [row for row in rows
                       if str(row.get("threadId") or "") == str(follow.get("threadId") or "")
                       and sender_address(str(row.get("from_addr") or "")) == follow.get("waitingOn")
                       and str(row.get("id")) != str(meta.get("email_id"))
                       and sent_at is not None and (_moment(row.get("timestamp")) or sent_at) > sent_at]
            # A reply that only says the answer is coming is not the answer.
            answer = next((row for row in replies
                           if not requests.is_holding_reply(row.get("body") or row.get("snippet"))), None)
            holding = replies[-1] if replies and answer is None else None
            if holding is not None and str(follow.get("lastHoldingReplyId")) != str(holding.get("id")):
                self._record(user, run, "followup", {
                    "id": follow["id"], "reason": "holding_reply", "lastHoldingReplyId": holding.get("id"),
                    "lastHoldingReplyAt": holding.get("timestamp")})
            if answer is not None:
                self._record(user, run, "followup", {
                    "id": follow["id"], "state": "satisfied", "satisfiedBy": answer.get("id"),
                    "satisfiedAt": answer.get("timestamp")})
                continue
            due = _moment(follow.get("dueAt"))
            nudge = by_id.get(nudge_of.get(follow["id"]))
            if follow.get("state") == "overdue" and nudge is not None and nudge["status"] in _DONE:
                # One reminder went out. If that brings no answer either, the
                # Desk does not write a third time: it is the person's now.
                # When it went out: the execution record; failing that, when
                # the wait was last recorded (it became overdue then).
                reminded = (_moment(executed_at.get(nudge.get("id"))) or _moment(follow.get("updatedAt"))
                            or now)
                if now > reminded + dt.timedelta(days=FOLLOW_UP_DAYS):
                    self._record(user, run, "followup", {
                        "id": follow["id"], "state": "escalated", "nudges": 1,
                        "lastNudgeAt": reminded.isoformat(),
                        "reason": "no_answer_after_reminder"})
                continue
            if follow.get("state") == "waiting" and due is not None and now > due:
                self._record(user, run, "followup", {"id": follow["id"], "state": "overdue"})
                item = {"provider": meta["provider"], "from_addr": meta.get("from_addr"),
                        "subject": meta.get("subject"), "threadId": follow.get("threadId"),
                        "provider_account_id": meta.get("provider_account_id"), "id": meta.get("email_id")}
                # A reminder is PROPOSED. Chasing someone is the person's call.
                self._propose(user, run, {
                    "tool_name": "send_email", "purpose": "nudge", "followUpId": follow["id"],
                    "reason": "No answer arrived by the follow-up date.",
                    "tool_input": self._reply_input(item, planning.nudge_reply(
                        subject=str(meta.get("subject") or "")))})

    def close_follow_up(self, ctx: Any, user: Any, run_id: int, follow_id: str) -> Dict[str, Any]:
        run = self._run(user, run_id)
        known = {f["id"]: f for f in lifecycle.follow_ups(self.gateway.run_events(user, run))}
        if follow_id not in known:
            raise NotFound("Follow-up not found.")
        if known[follow_id].get("state") in ("waiting", "overdue", "escalated"):
            self._record(user, run, "followup", {"id": follow_id, "state": "closed", "by": user.email})
        return self.view(ctx, user, run_id)

    def follow_ups(self, ctx: Any, user: Any, *, refresh: bool = True, limit: int = 50) -> Dict[str, Any]:
        """Everything the executive is waiting on, from records.

        - replies awaited on mail the Desk sent (kept on the run that sent it);
        - replies awaited that the Desk did not open (``source: "external"``:
          a world can be seeded with them);
        - the executive's own tasks whose date has passed (``overdueTasks``).

        Each follow-up says how many reminders went out for it (``nudges``)
        and whether one is waiting for approval (``nudgePending``), counted
        from the action cards of every run, so nothing is chased twice.
        """
        now = self.service.now(user)
        found: List[Dict[str, Any]] = []
        nudges: Dict[str, Dict[str, Any]] = {}
        for run in self.runs_in_scope(user, limit):
            if refresh:
                try:
                    with self._lock(run["meta"]["key"]):
                        self._track_follow_ups(ctx, user, run)
                except Exception:
                    pass
            events = self.gateway.run_events(user, run)
            cards = {card.get("id"): card for card in self.gateway.run_cards(user, run)}
            for item in events:
                data = item.get("data") or {}
                if item.get("kind") != "proposal" or not data.get("followUpId"):
                    continue
                card = cards.get(data.get("toolCallId")) or {}
                entry = nudges.setdefault(str(data["followUpId"]), {"sent": 0, "pending": False, "lastAt": None})
                if card.get("status") in _EFFECT:
                    entry["sent"] += 1
                    entry["lastAt"] = next((e.get("at") for e in reversed(events)
                                            if e.get("kind") == "execution"
                                            and (e.get("data") or {}).get("toolCallId") == card.get("id")), None)
                elif card.get("status") in _OPEN:
                    entry["pending"] = True
            for follow in lifecycle.follow_ups(events):
                found.append({"kind": "reply", **follow, "runId": run["id"], "source": "desk"})
        waiting = getattr(self.gateway, "waiting_follow_ups", None)
        for follow in (waiting(user) if callable(waiting) else []):
            awaited = follow.get("waitingOn") or {}
            due = _moment(follow.get("expectedBy"))
            found.append({
                "id": str(follow.get("id")), "kind": "reply", "source": "external", "runId": None,
                "state": "overdue" if due is not None and now > due else "waiting",
                "waitingOn": str(awaited.get("email") if isinstance(awaited, dict) else awaited or "").lower(),
                "waitingOnName": awaited.get("name") if isinstance(awaited, dict) else None,
                "threadId": follow.get("threadId"), "subject": follow.get("subject"),
                "sentAt": follow.get("sentAt"), "dueAt": follow.get("expectedBy")})
        for follow in found:
            sent = nudges.get(str(follow.get("id"))) or {}
            follow["nudges"] = int(sent.get("sent") or follow.get("nudges") or 0)
            follow["nudgePending"] = bool(sent.get("pending"))
            follow.setdefault("lastNudgeAt", sent.get("lastAt"))
            reminded = _moment(follow.get("lastNudgeAt")) or _moment(follow.get("updatedAt"))
            if follow["state"] == "overdue" and follow["nudges"] and reminded is not None:
                # Reminded once: it waits again, and after that it is the person's.
                follow["state"] = "escalated" if now > reminded + dt.timedelta(days=FOLLOW_UP_DAYS) else "waiting"
        counts = {state: sum(1 for f in found if f.get("state") == state)
                  for state in ("waiting", "overdue", "escalated", "satisfied", "closed")}
        overdue_tasks: List[Dict[str, Any]] = []
        try:
            for task in self.gateway.open_tasks(ctx, user, 200):
                due = _moment(task.get("due_at"))
                if due is not None and now > due:
                    overdue_tasks.append({"id": str(task.get("id")), "title": task.get("title"),
                                          "dueAt": due.isoformat()})
        except Exception:
            overdue_tasks = []                  # unknown: not reported as "none overdue" either
        return {"account": user.email, "followUps": found, "counts": counts, "overdueTasks": overdue_tasks}

    # ── reading a run ───────────────────────────────────────────────────────
    def _run(self, user: Any, run_id: int) -> Dict[str, Any]:
        run = self.gateway.get_run(user, int(run_id))
        if run is None:
            raise NotFound("Run not found.")
        return run

    def view(self, ctx: Any, user: Any, run_id: int, *, duplicate: bool = False,
             detail: bool = True) -> Dict[str, Any]:
        run = self._run(user, run_id)
        meta = run["meta"]
        cards = self.gateway.run_cards(user, run)
        events = self.gateway.run_events(user, run)
        actions = _action_views(cards, events, meta)
        statuses = [action["status"] for action in actions]
        done = [s for s in statuses if s in _DONE]
        partial = [s for s in statuses if s in _PARTIAL]
        failed = [s for s in statuses if s == "failed"]
        waiting = [s for s in statuses if s in _OPEN]

        if not actions:
            state = "no_action_proposed"
        elif waiting:
            state = "awaiting_approval" if any(s in ("awaiting_approval", "needs_info") for s in waiting) \
                else "executing"
        elif partial or (done and failed):
            state = "partial"
        elif failed:
            state = "failed"
        elif done:
            state = "completed"
        else:
            state = "cancelled"

        changed = next((a for a in actions if a["tool_name"] in (
            "create_calendar_event", "update_calendar_event", "cancel_calendar_event")), None)
        has_reply = any(a["tool_name"] == "send_email" for a in actions)
        has_confirmation = any(a["tool_name"] == "send_email" and a["purpose"] == "confirm" for a in actions)
        next_steps: List[str] = []
        plan = _plan_of(events)
        steps = plans.step_states(plan, _cards_by_step(cards, events), _unverified(events)) \
            if plan is not None else []
        if plan is not None:
            ready = any(step.get("deferred") and step["toolCallId"] is None and step["state"] == "ready"
                        for step in steps)
        else:
            ready = bool(changed and changed["status"] in _EFFECT and not has_confirmation)
        if ready:
            next_steps.append("advance")          # POST /desk/runs/{id}/advance
        if meta.get("draft_request") and not has_reply and not (changed and changed["status"] in _EFFECT):
            next_steps.append("draft_reply")      # POST the draft_request to Scriba
        stage = lifecycle.derive(meta, actions, events, pending_next="advance" in next_steps)
        follow = lifecycle.follow_ups(events)
        task_updates = lifecycle.task_updates(events)
        if any(update.get("state") == "suggested" for update in task_updates):
            next_steps.append("complete_task")    # POST /desk/runs/{id}/task-updates/{taskId}/apply
        unresolved = lifecycle.unresolved_of(meta, events)
        if any(not entry["resolved"] for entry in unresolved):
            next_steps.append("resolve_unresolved")   # POST /desk/runs/{id}/unresolved/resolve
        file_changes = lifecycle.file_changes(events)
        if any(change.get("state") == "suggested" for change in file_changes):
            next_steps.append("apply_file_change")    # POST /desk/runs/{id}/file-changes/{changeId}/apply
        counts: Dict[str, int] = {}
        for status in statuses:
            counts[status] = counts.get(status, 0) + 1
        view: Dict[str, Any] = {
            "runId": run["id"],
            "kind": meta.get("kind") or "email",
            "duplicate": duplicate,
            "state": state,
            "lifecycle": stage,
            "trigger": meta.get("trigger") or "manual",
            "simulated": bool(meta.get("sandbox")),
            "email": {key: meta.get(key) for key in (
                "provider", "email_id", "thread_id", "provider_account_id", "from_addr", "subject",
                "received_at")},
            "category": meta.get("category"),
            "outcome": meta.get("outcome"),
            "flags": meta.get("flags") or [],
            "createdAt": meta.get("created_at"),
            "updatedAt": events[-1].get("at") if events else meta.get("created_at"),
            "held": meta.get("held"),
            "draftRequest": meta.get("draft_request"),
            "actionCounts": counts,
            "next": next_steps,
            "followUps": follow,
            "taskUpdates": task_updates,
            "unresolved": unresolved,
            "fileChanges": [_file_change_view(change, bool(meta.get("sandbox")), run["id"]) for change in file_changes],
        }
        if detail:
            view["plan"] = {**plan, "steps": steps} if plan is not None else None
            view["actions"] = actions
            view["timeline"] = lifecycle.timeline(events)
            view["usage"] = lifecycle.usage_of(events)
            view["attachments"] = _attachment_views(events)
            view["files"] = _file_views(actions) + [
                {"id": c["resultFileId"], "filename": c.get("resultFilename"), "mimeType": workbooks.XLSX_MIME,
                 "sizeBytes": c.get("sizeBytes"), "toolCallId": None, "stepId": None, "changeId": c["changeId"],
                 "state": "VERIFIED" if c.get("state") == "applied" else "EXECUTED_UNVERIFIED",
                 "verified": c.get("state") == "applied", "simulated": bool(meta.get("sandbox")),
                 "download": {"method": "GET", "path": f"/desk/files/{c['resultFileId']}"}}
                for c in file_changes if c.get("resultFileId")]
            if meta.get("kind") == "command":
                view["command"] = {"text": meta.get("command"), "operations": meta.get("command_kinds") or []}
                view["assistantMessage"] = reply_text(view, str(meta.get("timezone") or "UTC"))
        return view

    def list_runs(self, ctx: Any, user: Any, limit: int = 50) -> List[Dict[str, Any]]:
        """The user's runs, newest first, each with where it stands."""
        rows = []
        for run in self.gateway.list_runs(user, limit):
            view = self.view(ctx, user, run["id"], detail=False)
            rows.append({
                "runId": run["id"],
                **{key: run["meta"].get(key) for key in (
                    "provider", "email_id", "subject", "from_addr", "category", "created_at")},
                "state": view["state"], "lifecycle": view["lifecycle"]["stage"],
                "next": view["next"], "trigger": view["trigger"], "simulated": view["simulated"],
                "held": {"reason": (view["held"] or {}).get("reason")} if view["held"] else None,
                "actionCounts": view["actionCounts"], "updatedAt": view["updatedAt"],
                "followUps": [{"id": f.get("id"), "state": f.get("state")} for f in view["followUps"]],
            })
        return rows

    def counts(self, ctx: Any, user: Any, limit: int = 200) -> Dict[str, int]:
        """Runs by lifecycle stage, for the worker status."""
        totals: Dict[str, int] = {}
        for run in self.gateway.list_runs(user, limit):
            stage = self.view(ctx, user, run["id"], detail=False)["lifecycle"]["stage"]
            totals[stage] = totals.get(stage, 0) + 1
        return totals


# The fields of an action that decide what happens in the world. An approval
# is bound to them: see ``execution.py``.
MATERIAL_FIELDS = ("to", "cc", "bcc", "attendees", "add_attendees", "remove_attendees", "subject", "body",
                   "text", "title", "summary", "start", "end", "start_time", "end_time", "event_id",
                   "thread_id", "remind_at", "due_at")
_ADDRESS_FIELDS = ("to", "cc", "bcc", "attendees", "add_attendees", "remove_attendees")


def _binding(tool_name: str, data: Any) -> str:
    """A digest of what an action will do: who it reaches, what it says,
    when, and which event or thread it touches."""
    import json

    from .safeguards import addresses_in

    data = data if isinstance(data, dict) else {}
    material: Dict[str, Any] = {"tool": tool_name}
    for key in MATERIAL_FIELDS:
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        if key in _ADDRESS_FIELDS:
            material[key] = sorted(addresses_in(value))
        elif key in ("start", "end", "start_time", "end_time", "remind_at", "due_at"):
            moment = _moment(value)
            material[key] = moment.astimezone(dt.timezone.utc).isoformat() if moment else str(value)
        else:
            material[key] = " ".join(str(value).split())
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:24]


# Fields an edit at approval may change that decide what the action does or says.
_EDITABLE_FIELDS = MATERIAL_FIELDS + ("timezone", "location", "description")


def approved_edits(card: Any) -> Dict[str, Any]:
    """The fields the person changed in the approve request, as Scriba keeps
    them (``output.approved_overrides``). Control flags of the Desk
    (``desk_confirmed_recipients`` and the like) are not edits of the action."""
    card = card if isinstance(card, dict) else {}
    output = card.get("output") if isinstance(card.get("output"), dict) else card.get("output_payload")
    approved = (output or {}).get("approved_overrides") if isinstance(output, dict) else None
    if not isinstance(approved, dict):
        return {}
    return {key: approved[key] for key in _EDITABLE_FIELDS if approved.get(key) not in (None, "", [], {})}


def effective_input(card: Any) -> Dict[str, Any]:
    """What the action does, or did: the stored input with the edit the
    person made when approving it.

    Scriba keeps a card's input as it was proposed and the person's edit
    beside it. Everything that speaks about the action AFTER the approval
    (the verification read-back, the search for its effect, the confirmation
    sent to the other person) has to speak about the edited action."""
    card = card if isinstance(card, dict) else {}
    stored = card.get("input") if isinstance(card.get("input"), dict) else card.get("input_payload")
    data = dict(stored) if isinstance(stored, dict) else {}
    edits = approved_edits(card)
    if not edits:
        return data
    data.update(edits)
    if isinstance(data.get("planned_change"), dict):
        # A move states its new time in ``planned_change``.
        data["planned_change"] = {**data["planned_change"],
                                  **{key: edits[key] for key in ("start", "end") if key in edits}}
    return data


def _plan_of(events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next((dict(e.get("data") or {}) for e in events if e.get("kind") == "plan"), None)


def _unverified(events: List[Dict[str, Any]]) -> set:
    """Cards whose latest verification failed: executed, and not shown by the
    state read back."""
    latest: Dict[Any, bool] = {}
    for item in events:
        data = item.get("data") or {}
        if item.get("kind") == "verification" and data.get("toolCallId") is not None:
            latest[data["toolCallId"]] = data.get("verified") is False
    return {card_id for card_id, failed in latest.items() if failed}


def _cards_by_step(cards: List[Dict[str, Any]], events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_id = {card.get("id"): card for card in cards}
    found: Dict[str, Dict[str, Any]] = {}
    for item in events:
        data = item.get("data") or {}
        if item.get("kind") == "proposal" and data.get("stepId") and data.get("toolCallId") in by_id:
            found[str(data["stepId"])] = by_id[data["toolCallId"]]
    return found


def _moment(value: Any) -> Optional[dt.datetime]:
    """An aware datetime from a stored timestamp (ISO text, or epoch milliseconds)."""
    from .sandbox import parse_time

    text = str(value or "").strip()
    if text.isdigit():
        return dt.datetime.fromtimestamp(int(text) / 1000, tz=dt.timezone.utc)
    return parse_time(text)


def _same_title(left: Any, right: Any) -> bool:
    clean = lambda value: re.sub(r"^(?:re|fwd?):\s*", "", " ".join(str(value or "").lower().split()))  # noqa: E731
    return bool(clean(left)) and clean(left) == clean(right)


def _not_inbound(item: Dict[str, Any]) -> bool:
    """Drafts, sent mail, spam and trash are not arrivals. Uses the labels or
    folder a row carries; a row with neither is taken as inbound, because the
    list it came from is already the inbox."""
    if item.get("is_sent") or item.get("is_draft"):
        return True
    labels = {str(label).upper() for label in (item.get("labels") or [])}
    if labels & {"DRAFT", "SPAM", "TRASH", "SENT"}:
        return True
    folder = str(item.get("mail_folder") or "").strip().lower().replace(" ", "")
    return folder in ("sent", "sentitems", "drafts", "junkemail", "deleteditems")


def _summary(meta: Dict[str, Any], proposals: List[Dict[str, Any]]) -> str:
    parts = [f"Incoming {meta['provider']} message from {meta.get('from_addr')}: "
             f"\"{meta.get('subject')}\". Classified as {meta['category']}."]
    if proposals:
        parts.append("Proposed for your approval: "
                     + ", ".join(p["tool_name"] for p in proposals) + ".")
    if meta.get("held"):
        parts.append(str(meta["held"].get("message") or ""))
    elif not proposals:
        parts.append("No action is proposed.")
    return " ".join(part for part in parts if part)


def _file_change_view(change: Mapping[str, Any], simulated: bool, run_id: Any) -> Dict[str, Any]:
    """A change to a workbook as the person sees it: what will be (or was)
    changed, on which file, and what shows that it worked."""
    state = str(change.get("state"))
    return {
        "id": change.get("changeId"), "state": state, "sourceFileId": change.get("sourceFileId"),
        "filename": change.get("filename"), "operations": change.get("operations") or [],
        "resultFileId": change.get("resultFileId"), "resultFilename": change.get("resultFilename"),
        # True only when the changed copy was reopened, compared with the original and read back from the store.
        "verified": state == "applied", "verification": change.get("verification"),
        "steps": change.get("steps") or [], "failedAt": change.get("failedAt"),
        "error": change.get("error") if state in ("failed", "unverified") else None,
        "message": change.get("message") if state == "failed" else None,
        "dismissedFrom": change.get("dismissedFrom") if state == "dismissed" else None,
        "by": change.get("by"), "updatedAt": change.get("updatedAt"), "simulated": simulated,
        "apply": {"method": "POST", "path": f"/desk/runs/{run_id}/file-changes/{change.get('changeId')}/apply"}
        if state == "suggested" else None,
    }


def _attachment_views(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The files that came with the message, as they were read. Facts about
    each file only: its text is never part of a run's record."""
    found = []
    for item in events:
        data = item.get("data") or {}
        if item.get("kind") == "read" and data.get("tool") == "file.read_attachment":
            found.append({"id": data.get("attachmentId"), "filename": data.get("filename"),
                          "kind": data.get("kind"), "sizeBytes": data.get("sizeBytes"), "sha256": data.get("sha256"),
                          "read": bool(data.get("ok")), "error": data.get("error"), "unit": data.get("unit"),
                          "unitCount": data.get("unitCount"), "truncated": bool(data.get("truncated")),
                          "unreadParts": data.get("unread") or 0, "untrustedFindings": data.get("findings") or 0,
                          "unusual": data.get("unusual") or 0, "readAt": item.get("at")})
    return found


def _file_views(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Files the Desk generated in this run. ``verified`` is true only after
    the file was reopened and showed what was approved."""
    found = []
    for action in actions:
        document = (action.get("output") or {}).get("document")
        if not isinstance(document, dict) or not document.get("id"):
            continue
        found.append({
            "id": str(document["id"]), "filename": document.get("filename"), "mimeType": document.get("mime_type"),
            "sizeBytes": document.get("size_bytes"), "toolCallId": action.get("toolCallId"),
            "stepId": action.get("stepId"), "state": action.get("lifecycle"), "verified": bool(action.get("verified")),
            "simulated": bool(action.get("simulated")),
            "download": {"method": "GET", "path": f"/desk/files/{document['id']}"}})
    return found


def _action_views(cards: List[Dict[str, Any]], events: List[Dict[str, Any]],
                  meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_card: Dict[Any, Dict[str, Any]] = {}
    for item in events:
        data = item.get("data") or {}
        card_id = data.get("toolCallId")
        if card_id is None:
            continue
        slot = by_card.setdefault(card_id, {})
        if item.get("kind") == "proposal":
            slot["proposal"] = {**data, "at": item.get("at")}
        elif item.get("kind") == "approval":
            slot.setdefault("decisions", []).append({**data, "at": item.get("at")})
        elif item.get("kind") == "execution":
            slot["execution"] = {**data, "at": item.get("at")}
            if data.get("status") != "held":
                slot["attempts"] = slot.get("attempts", 0) + 1
        elif item.get("kind") == "verification":
            slot["verification"] = {**data, "at": item.get("at")}
    return [_action_view(card, by_card.get(card.get("id"), {}), meta) for card in cards]


def _action_view(card: Dict[str, Any], evidence: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """One proposed action. ``verified`` is true only on evidence: a read-back
    of the provider state where one exists, otherwise Scriba's record of the
    executed action. It is never inferred from the status alone."""
    status = str(card.get("status") or "")
    output = card.get("output") or {}
    proposal = evidence.get("proposal") or {}
    verification = evidence.get("verification")
    if verification is not None:
        verified = bool(verification.get("verified")) and status in _DONE
    else:
        verified = bool(status in _DONE and card.get("assistant_action_id"))
    unknown = bool(output.get("outcome_unknown")) and status == "failed"
    held = bool(status == "needs_info" and output.get("blocked"))
    error_code = output.get("error_code") or (card.get("error") if status in ("needs_info", "failed") else None)
    attempts = int(evidence.get("attempts", 0))
    state = lifecycle.action_state(status, held=held, verified=verified, verification=verification,
                                   outcome_unknown=unknown, error_code=error_code)
    edits = approved_edits(card)
    return {
        "toolCallId": card.get("id"),
        "tool_name": card.get("tool_name"),
        "status": status,
        # The explicit state of this action (lifecycle.ACTION_STATES).
        "lifecycle": state,
        "final": state in lifecycle.ACTION_FINAL,
        # What a retry would do first, or null when there is nothing to retry.
        "retry": lifecycle.retry_of(state, simulated=bool(meta.get("sandbox")), attempts=attempts),
        "requiresApproval": True,
        "purpose": proposal.get("purpose"),
        "reason": proposal.get("reason"),
        "stepId": proposal.get("stepId"),
        # The existing event a calendar change is about, as it was when proposed.
        "target": proposal.get("target"),
        "followUpId": proposal.get("followUpId"),
        # Held by a guard: it cannot be approved as it stands.
        "held": held,
        # How many times execution was attempted (a retry is one more).
        "attempts": attempts,
        "proposedSlots": proposal.get("proposedSlots"),
        "input": card.get("input") or {},
        # The fields the person changed when approving, and the action as it
        # then ran: ``input`` stays as proposed, so an edit is never silent.
        "edited": sorted(edits),
        "effectiveInput": effective_input(card),
        "output": output,
        "message": output.get("message"),
        "error": card.get("error"),
        "errorCode": error_code,
        "availability": output.get("availability"),
        # One identity per real-world effect: a retry of this card reuses it.
        "idempotencyKey": f"desk:{meta.get('key')}:{card.get('id')}",
        # Scriba links an executed card to the action row its engine recorded.
        "assistantActionId": card.get("assistant_action_id"),
        "verified": verified,
        "verification": verification,
        "outcomeUnknown": unknown,
        "simulated": bool(meta.get("sandbox")),
        "proposedAt": proposal.get("at"),
        "decisions": evidence.get("decisions") or [],
        "execution": evidence.get("execution"),
        "approve": {"method": "POST", "path": f"/chat/tool-calls/{card.get('id')}/approve"}
        if status in ("awaiting_approval", "needs_info") else None,
    }
