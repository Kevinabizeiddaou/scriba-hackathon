"""The stateful simulation runner: one office, one clock, one day at a time.

For each step of a day profile the runner:

1. moves the sandbox world's clock to the step's time;
2. does what the outside world does (a message arrives, a provider fails);
3. lets the Desk's own intake worker take the work in (``/sim/worker/tick``
   runs one real pass of it);
4. shows every proposal to the simulated executive, who approves, rejects or
   edits it through Scriba's own approve route;
5. lets the Desk execute, verify and propose what follows;
6. checks the safety invariants against the world's real state.

Later steps see the world the earlier ones left behind: a meeting booked at
08:30 is a conflict at 15:00. At the end every message gets one verdict from
the oracle, read from the world's state.

The runner never writes a run, a card or an outcome.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import time
from typing import Any, Callable, Dict, List, Mapping, Optional

from . import oracle
from .adapter import DeskApiError, DeskClient
from .executive import Executive
from .office import OfficeClock, address, fingerprint, from_header, person

MAX_TICKS = 6
MAX_ROUNDS = 8
# Never part of the replay fingerprint: they are measured on the real clock.
VOLATILE_KEYS = ("durationMs", "wallMs", "lastTickMs", "lastTickAt", "lastAt", "tickMs")


def strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_volatile(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [strip_volatile(v) for v in value]
    return value


class Simulation:
    def __init__(self, client: DeskClient, spec: Mapping[str, Any], profile: Mapping[str, Any], *,
                 seed: int, executive: Optional[Executive] = None,
                 narrate: Optional[Callable[[str], None]] = None,
                 observe: Optional[Callable[[str, Mapping[str, Any]], None]] = None) -> None:
        self.client, self.spec, self.profile, self.seed = client, spec, profile, int(seed)
        self.executive = executive or Executive()
        self.narrate = narrate or (lambda line: None)
        # Called with ("proposed", step record) once the Desk has taken the
        # step's work in and before the executive decides, and with
        # ("done", step record) when the step is over. For a demonstration.
        self.observe = observe or (lambda stage, record: None)
        self.clock = OfficeClock(spec["day"], spec["timezone"])
        self.rng = random.Random(f"{self.seed}:{profile['id']}")
        self.now: Optional[dt.datetime] = None
        self.replay: List[Dict[str, Any]] = []
        self.steps: List[Dict[str, Any]] = []
        self.requests: Dict[str, Dict[str, Any]] = {}
        self.decisions: List[Dict[str, Any]] = []
        self.checks: List[Dict[str, Any]] = []
        self.violations: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.briefings: List[Dict[str, Any]] = []
        self.decided: set = set()
        self.interrupted: set = set()
        self.overridden_events: set = set()
        self.duplicates_prevented: List[Dict[str, Any]] = []
        self.run_views: Dict[int, Dict[str, Any]] = {}
        self.initial: Dict[str, Any] = {}
        self.meta: Dict[str, Any] = {}
        self.health: Dict[str, Any] = {}
        self.tick_ms: List[int] = []
        self.started = time.monotonic()

    # ── logging ─────────────────────────────────────────────────────────────
    def log(self, kind: str, **data: Any) -> Dict[str, Any]:
        entry = {"seq": len(self.replay) + 1, "t": self.now.isoformat() if self.now else None,
                 "type": kind, **strip_volatile(data)}
        self.replay.append(entry)
        return entry

    def say(self, line: str) -> None:
        stamp = self.now.astimezone(self.clock.zone).strftime("%a %H:%M") if self.now else "--:--"
        self.narrate(f"[{stamp}] {line}")

    def state(self) -> Dict[str, Any]:
        return self.client.sim_state()["world"]

    # ── the day ─────────────────────────────────────────────────────────────
    def run(self) -> Dict[str, Any]:
        self.client.sign_in(self.spec["scribaUser"])
        self.meta = self.client.sim_meta()
        self.health = self.client.health()
        self.initial = self.state()
        self.now = oracle.parse(self.initial["now"])
        self.log("office", specFingerprint=self.spec["fingerprint"], worldFingerprint=fingerprint(
            {k: self.initial[k] for k in ("events", "tasks", "reminders", "followUps", "sent", "accounts")}),
            profile=self.profile["id"], seed=self.seed, executive=self.executive.mode,
            engine={"overlay": self.health.get("version"), "deskBackend": self.meta.get("deskBackend"),
                    "executionMode": self.health.get("executionMode"),
                    "externalWrites": (self.health.get("externalWrites") or {}).get("enabled"),
                    "modelConfigured": (self.health.get("model") or {}).get("configured")})
        self.say(f"Office ready: {self.spec['executive']['name']}, {self.spec['organization']['name']}. "
                 f"{len(self.initial['events'])} meetings, {len(self.initial['tasks'])} tasks, "
                 f"{len(self.initial['followUps'])} replies awaited. Execution mode: "
                 f"{self.health.get('executionMode')} (simulated).")
        for step in self.profile["steps"]:
            started = time.monotonic()
            record = {"id": step["id"], "at": step["at"], "title": step["title"], "kind": step["kind"],
                      "job": step["job"], "requests": [], "notes": [], "checks": []}
            self.steps.append(record)
            try:
                self.play(step, record)
            except DeskApiError as exc:
                # An unexpected answer from the backend stops this step, is
                # recorded, and the day goes on.
                record["error"] = str(exc)
                self.errors.append({"step": step["id"], "error": str(exc)})
                self.log("backend_error", step=step["id"], status=exc.status, path=exc.path)
                self.say(f"BACKEND ERROR in {step['id']}: {exc}")
            record["wallMs"] = int((time.monotonic() - started) * 1000)
            self.observe("done", record)
        return self.finish()

    def play(self, step: Mapping[str, Any], record: Dict[str, Any]) -> None:
        params = step["params"]
        # Nothing arrives on the stroke of the minute: a seeded number of
        # seconds is added, so no result depends on an exact boundary.
        moment = oracle.ref_time(self.clock, step["at"]) + dt.timedelta(seconds=self.rng.randint(5, 55))
        self.client.sim_clock(moment.isoformat())
        self.now = moment
        self.log("clock", step=step["id"], title=step["title"])
        self.say(f"== {step['title']}")
        before = self.state()
        kind = step["kind"]

        if params.get("when") and not self._holds(params["when"], before):
            for email in step["emails"]:
                self.requests[email["id"]] = {"id": email["id"], "stepId": step["id"], "status": "not_sent",
                                              "subject": email["subject"], "sender": email["sender"],
                                              "why": "The earlier work this message answers never happened."}
                record["requests"].append(email["id"])
            record["notes"].append("precondition not met: the message was never sent")
            self.log("not_sent", step=step["id"], when=params["when"])
            self.say("   (not sent: what it answers never happened)")
            return

        if params.get("fault"):
            fault = params["fault"]
            self.client.sim_fault(fault["tool"], fault.get("mode", "fail_times"), int(fault.get("times", 1)),
                                  fault.get("error", "provider_error"))
            self.log("fault", **fault)
            self.say(f"   provider fault armed: {fault['tool']} {fault.get('mode')}")

        emails = list(step["emails"])
        if kind == "counterpart_reply":
            built = self._counterpart_reply(step, before)
            if built is None:
                record["notes"].append("precondition not met: no offered time is still open in this thread")
                self.log("not_sent", step=step["id"], thread=params["thread"])
                self.say("   (not sent: the Desk offered no time in this thread that is still ahead)")
                return
            emails = [built]
        elif kind == "unreadable":
            self.client.sim_unreadable(params["key"], params.get("code"))
            self.log("unreadable", key=params["key"], code=params.get("code"))
            self.say(f"   {params['key']} is now {'UNREADABLE' if params.get('code') else 'readable'}")
        elif kind == "restart":
            self._restart(record)
        elif kind == "retry_failed":
            if params.get("clear_faults"):
                self.client.sim_clear_faults()
                self.log("faults_cleared")
        elif kind == "invalid_approvals":
            self._invalid_approvals(record)

        for email in emails:
            self._deliver(step, email, before, record)
        if params.get("duplicate_notification"):
            for email in emails:
                again = self.client.sim_deliver(self._wire(email))
                prevented = bool(again.get("duplicateNotification"))
                self.log("duplicate_notification", id=email["id"], ignoredByMailbox=prevented)
                self.say("   the provider notifies a second time about the same message")

        self._intake(record)
        if params.get("duplicate_notification"):
            # A second notification means a second look at the same message.
            for email in emails:
                wire = self._wire(email)
                again = self.client.intake(wire["provider"], email["id"])
                same = bool(again.get("duplicate"))
                self._check(record, "duplicate_notification_one_run", same,
                            f"second intake of {email['id']} returned run {again.get('runId')} "
                            f"(duplicate={again.get('duplicate')})")
                if same:
                    self.duplicates_prevented.append({"what": "second notification for one message",
                                                      "message": email["id"], "runId": again.get("runId")})
        record["runsOpened"] = sorted(view["runId"] for view in self.run_views.values()
                                      if (view.get("email") or {}).get("email_id") in record["requests"])
        self.observe("proposed", record)
        self._approvals(record, retry_failed=(kind == "retry_failed"))

        if kind == "briefing":
            self._briefing(record)
        if params.get("check"):
            self._scenario_check(step, record, params["check"])
        self._invariants(record)

    # ── the outside world ───────────────────────────────────────────────────
    def _wire(self, email: Mapping[str, Any]) -> Dict[str, Any]:
        provider, account = oracle.mailbox_of(self.spec, email["to"])
        received = (oracle.ref_time(self.clock, email["received"]) if email.get("received") else self.now)
        return {"provider": provider, "account": account, "message_id": email["id"],
                "from_addr": from_header(email["sender"]), "subject": email["subject"],
                "body": email["body"], "thread_id": email["thread"],
                "received_at": received.isoformat(), "labels": email.get("labels"), "to": [account]}

    def _deliver(self, step: Mapping[str, Any], email: Mapping[str, Any], before: Mapping[str, Any],
                 record: Dict[str, Any]) -> None:
        wire = self._wire(email)
        resolved = oracle.resolve(email["expect"], spec=self.spec, clock=self.clock, state=before,
                                  mailbox=email["to"])
        self.client.sim_deliver(wire)
        who = person(email["sender"])
        self.requests[email["id"]] = {
            "id": email["id"], "stepId": step["id"], "status": "delivered", "sender": email["sender"],
            "senderName": who["name"], "senderEmail": who["email"].lower(), "senderKind": who["kind"],
            "provider": wire["provider"], "account": wire["account"], "thread": email["thread"],
            "subject": email["subject"], "body": email["body"], "expect": email["expect"],
            "resolved": resolved, "arrivedAt": self.now.isoformat(), "receivedAt": wire["received_at"],
            "stateAtArrival": before, "human": email.get("human"), "interrupt": email.get("interrupt"),
            "job": step["job"], "needsWork": oracle.needs_work(resolved)}
        record["requests"].append(email["id"])
        self.log("deliver", id=email["id"], provider=wire["provider"], account=wire["account"],
                 sender=who["email"], subject=email["subject"], thread=email["thread"],
                 receivedAt=wire["received_at"], body=fingerprint(email["body"]))
        self.say(f"   mail in {wire['provider']} ({wire['account'].split('@')[1]}) from {who['name']}: "
                 f"\"{email['subject']}\"")

    def _holds(self, when: Mapping[str, Any], state: Mapping[str, Any]) -> bool:
        if "event_with" in when:
            start = oracle.ref_time(self.clock, when["start"])
            return any(address(when["event_with"]) in event["attendees"]
                       and oracle.same_moment(event["start"], start) for event in oracle.active_events(state))
        return True

    def _counterpart_reply(self, step: Mapping[str, Any], state: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """The person who was offered times picks one and writes back."""
        params = step["params"]
        thread = params["thread"]
        original = next((r for r in self.requests.values() if r.get("thread") == thread
                         and r.get("status") == "delivered"), None)
        if original is None:
            return None
        offers = []
        for run in self._views_for(original["id"]):
            for action in run.get("actions") or []:
                if action["tool_name"] == "send_email" and action["status"] == "executed" \
                        and action.get("purpose") in ("offer_times", "clarify") and action.get("proposedSlots"):
                    offers.append(action)
        if not offers:
            return None
        # Nobody accepts a time that has already passed, or is minutes away.
        slots = [s for s in offers[-1]["proposedSlots"]
                 if oracle.parse(s["start"]) >= self.now + dt.timedelta(minutes=10)]
        if not slots:
            return None
        slot = slots[self.rng.randrange(len(slots))]
        start, end = oracle.parse(slot["start"]), oracle.parse(slot["end"])
        local = start.astimezone(self.clock.zone)
        when = (f"{local.strftime('%A')} {local.day} {local.strftime('%B')} from {local.strftime('%H:%M')} "
                f"to {end.astimezone(self.clock.zone).strftime('%H:%M')}")
        who = person(params["sender"])
        to = {"gmail": "work", "outlook": "outlook"}[original["provider"]]
        if original["account"] == self.spec["accounts"]["gmail"][1]:
            to = "advisory"
        minutes = int((end - start).total_seconds() // 60)
        offset = (local.date() - self.clock.day).days
        email = {
            "slug": params["slug"], "id": f"{self.profile['id']}-{params['slug']}", "sender": params["sender"],
            "to": to, "subject": f"Re: {original['subject']}", "thread": thread, "received": None,
            "labels": None, "human": None, "interrupt": None,
            "body": f"Thank you, Layla. {when} works for us. Could we confirm that slot?",
            "expect": {"outcome": "schedule", "with": params["sender"],
                       "start": f"D{offset:+d} {local.strftime('%H:%M')}", "minutes": minutes,
                       "calendar": to, "if_busy": "offer_times", "confirm": True,
                       "attendees": [params["sender"]]},
        }
        self.log("counterpart_picks", thread=thread, sender=who["email"], slot=slot,
                 offered=len(slots))
        return email

    # ── autonomous intake ───────────────────────────────────────────────────
    def _intake(self, record: Dict[str, Any]) -> None:
        opened_total = 0
        for _ in range(MAX_TICKS):
            started = time.monotonic()
            result = self.client.sim_worker_tick()
            self.tick_ms.append(int((time.monotonic() - started) * 1000))
            users = (result.get("tick") or {}).get("users") or []
            mine = users[0] if users else {}
            opened = int(mine.get("opened") or 0)
            opened_total += opened
            self.log("worker_tick", status=mine.get("status"), opened=opened,
                     error=mine.get("error"))
            if mine.get("status") not in ("ok",):
                record["notes"].append(f"worker: {mine.get('status')}")
                self.say(f"   intake worker: {mine.get('status')}")
            if opened == 0:
                break
        record["opened"] = opened_total
        for row in self.client.runs():
            if row["runId"] not in self.run_views:
                view = self._refresh(row["runId"])
                self.log("run_opened", **self._run_summary(view))
                self.say(f"   Desk run {view['runId']}: {view['category']} -> "
                         f"{view['lifecycle']['stage']}"
                         + (f" (held: {view['held']['reason']})" if view.get("held") else "")
                         + (f"; proposes {', '.join(a['tool_name'] for a in view['actions'])}"
                            if view.get("actions") else ""))

    def _refresh(self, run_id: int) -> Dict[str, Any]:
        view = self.client.run(run_id)
        self.run_views[run_id] = view
        return view

    def _views_for(self, message_id: str) -> List[Dict[str, Any]]:
        return [view for view in self.run_views.values()
                if (view.get("email") or {}).get("email_id") == message_id]

    @staticmethod
    def _run_summary(view: Mapping[str, Any]) -> Dict[str, Any]:
        return {"runId": view["runId"], "message": (view.get("email") or {}).get("email_id"),
                "trigger": view.get("trigger"), "category": view.get("category"),
                "stage": (view.get("lifecycle") or {}).get("stage"),
                "reason": (view.get("lifecycle") or {}).get("reason"),
                "held": (view.get("held") or {}).get("reason"), "flags": view.get("flags"),
                "planner": (view.get("plan") or {}).get("planner"),
                "steps": [{"id": s["id"], "tool": s["tool"], "dependsOn": s["dependsOn"], "state": s["state"]}
                          for s in (view.get("plan") or {}).get("steps") or []],
                "actions": [{"toolCallId": a["toolCallId"], "tool": a["tool_name"], "status": a["status"],
                             "purpose": a.get("purpose")} for a in view.get("actions") or []]}

    # ── the executive ───────────────────────────────────────────────────────
    def _approvals(self, record: Dict[str, Any], *, retry_failed: bool = False) -> None:
        retried: set = set()
        for _ in range(MAX_ROUNDS):
            acted = False
            for row in sorted(self.client.runs(), key=lambda r: r["runId"]):
                counts = row.get("actionCounts") or {}
                if not (counts.get("awaiting_approval") or counts.get("failed") or counts.get("needs_info")):
                    continue
                view = self._refresh(row["runId"])
                request = self.requests.get((view.get("email") or {}).get("email_id")) or self._stranger(view)
                for action in view.get("actions") or []:
                    card = action["toolCallId"]
                    if action["status"] == "awaiting_approval" and not action.get("held") and card not in self.decided:
                        self._decide(action, view, request, record)
                        acted = True
                    elif action["status"] == "needs_info" and not action.get("held") and card not in self.decided:
                        # Incomplete, not held by a guard: the executive may fill it in.
                        self.decided.add(card)
                        decision = self.executive.complete(action, request=request, run=view, state=self.state(),
                                                           spec=self.spec, clock=self.clock)
                        if decision is not None:
                            self.decided.discard(card)
                            self._decide(action, view, request, record, decision=decision)
                            acted = True
                    elif action["status"] == "failed" and card not in retried and (
                            retry_failed or card in self.decided):
                        if not retry_failed and self._retries(card) >= 1:
                            continue
                        retried.add(card)
                        self._retry(action, view, request, record)
                        acted = True
            if not acted:
                break
            # The worker's next pass: follow-ups, and anything left to propose.
            self._intake(record)
        for row in self.client.runs():
            self._refresh(row["runId"])

    def _retries(self, card: Any) -> int:
        return sum(1 for d in self.decisions if d["toolCallId"] == card and d["decision"] == "retry")

    def _stranger(self, view: Mapping[str, Any]) -> Dict[str, Any]:
        """A run for a message the scenario did not send (should not happen)."""
        email = view.get("email") or {}
        return {"id": email.get("email_id"), "status": "unknown", "thread": email.get("thread_id"),
                "senderEmail": "", "resolved": {"outcome": "none"}, "human": None, "interrupt": None}

    def _decide(self, action: Mapping[str, Any], view: Mapping[str, Any], request: Mapping[str, Any],
                record: Dict[str, Any], decision: Optional[Dict[str, Any]] = None) -> None:
        card = action["toolCallId"]
        state = self.state()
        decision = decision or self.executive.decide(action, request=request, run=view, state=state,
                                                     spec=self.spec, clock=self.clock)
        decision.update(stepId=record["id"], at=self.now.isoformat(), result=None, error=None)
        self.decided.add(card)
        if decision["decision"] == "approve" and request.get("interrupt") == action["tool_name"] \
                and card not in self.interrupted:
            # The executive approved; the process stops before the action runs.
            self.interrupted.add(card)
            self.client.sim_interrupt(card)
            decision.update(result="interrupted", interrupted=True)
            self.decisions.append(decision)
            self.log("decision", **self._public(decision))
            self.say(f"   EXECUTIVE approves {action['tool_name']}; the process stops mid-action")
            return
        try:
            if decision["decision"] == "approve":
                answer = self.client.approve(card, idempotency_key=f"sim:{self.profile['id']}:{card}:1",
                                             payload_overrides=decision.get("overrides"))
            else:
                answer = self.client.reject(card)
            after = (answer or {}).get("tool_call") or {}
            decision["result"] = after.get("status")
            decision["errorCode"] = (after.get("output") or {}).get("error_code")
            if decision.get("overrides", {}).get("desk_availability_override"):
                self.overridden_events.add(card)
        except DeskApiError as exc:
            decision.update(result="error", error=str(exc))
        self.decisions.append(decision)
        self.log("decision", **self._public(decision))
        verb = {"approval": "approves", "unreviewed_approval": "approves (unread)",
                "preference_rejection": "declines", "preference_edit": "edits and approves",
                "corrective_edit": "CORRECTS and approves", "corrective_rejection": "REJECTS (wrong)",
                "missing_information": "FILLS IN what is missing and approves"}[
            decision["category"]]
        self.say(f"   EXECUTIVE {verb} {action['tool_name']}"
                 + (f" [{action.get('purpose')}]" if action.get("purpose") else "")
                 + f" -> {decision['result']}" + (f" ({decision['errorCode']})" if decision.get("errorCode") else "")
                 + f". {decision['why']}")

    def _retry(self, action: Mapping[str, Any], view: Mapping[str, Any], request: Mapping[str, Any],
               record: Dict[str, Any]) -> None:
        reason = ("the outcome was unknown" if action.get("outcomeUnknown")
                  else f"it failed ({action.get('errorCode') or action.get('error')})")
        decision = Executive.retry(action, request=request, run=view, reason=reason)
        decision.update(stepId=record["id"], at=self.now.isoformat(), result=None, error=None)
        try:
            answer = self.client.retry(action["toolCallId"])
            after = (answer or {}).get("tool_call") or {}
            decision["result"] = after.get("status")
            decision["reconciled"] = bool((after.get("output") or {}).get("reconciled")
                                          or (answer or {}).get("reconciled"))
            decision["errorCode"] = (after.get("output") or {}).get("error_code")
        except DeskApiError as exc:
            decision.update(result="error", error=str(exc))
        self.decisions.append(decision)
        self.log("decision", **self._public(decision))
        self.say(f"   EXECUTIVE retries {action['tool_name']} because {reason} -> {decision['result']}"
                 + (" (already done: not run twice)" if decision.get("reconciled") else ""))

    @staticmethod
    def _public(decision: Mapping[str, Any]) -> Dict[str, Any]:
        return {key: decision.get(key) for key in (
            "stepId", "requestId", "runId", "toolCallId", "tool", "purpose", "decision", "category",
            "overrides", "why", "result", "errorCode", "reconciled", "interrupted",
            "countsAgainstAutonomy", "error")}

    # ── special steps ───────────────────────────────────────────────────────
    def _restart(self, record: Dict[str, Any]) -> None:
        before = {row["runId"] for row in self.client.runs()}
        answer = self.client.sim_worker_restart()
        self.log("worker_restart", claims=answer.get("claims"))
        self.say(f"   the worker restarts (claims: {answer.get('claims')})")
        result = self.client.sim_worker_tick()
        opened = int((((result.get("tick") or {}).get("users") or [{}])[0]).get("opened") or 0)
        after = {row["runId"] for row in self.client.runs()}
        ok = opened == 0 and after == before
        self._check(record, "restart_opens_no_duplicate_runs", ok,
                    f"{len(before)} runs before the restart, {len(after)} after; the first pass opened {opened}")
        if ok:
            self.duplicates_prevented.append({"what": "no message taken in twice after a restart",
                                              "runs": len(before)})

    def _invalid_approvals(self, record: Dict[str, Any]) -> None:
        """Approvals that must change nothing."""
        before = self.state()
        digest = fingerprint({k: before[k] for k in ("events", "sent", "tasks", "reminders", "operations")})
        attempts: List[Dict[str, Any]] = []

        def attempt(label: str, call: Callable[[], Any]) -> None:
            try:
                answer = call()
                card = (answer or {}).get("tool_call") or {}
                attempts.append({"case": label, "http": 200, "status": card.get("status"),
                                 "replay": bool((answer or {}).get("idempotent_replay")
                                                or (card.get("output") or {}).get("idempotent_replay"))})
            except DeskApiError as exc:
                attempts.append({"case": label, "http": exc.status, "status": None})

        executed = [(view, a) for view in self.run_views.values() for a in view.get("actions") or []
                    if a["status"] == "executed"]
        cancelled = [(view, a) for view in self.run_views.values() for a in view.get("actions") or []
                     if a["status"] == "cancelled"]
        if executed:
            card = executed[0][1]["toolCallId"]
            attempt("approve an action that already executed, same key",
                    lambda: self.client.approve(card, idempotency_key=f"sim:{self.profile['id']}:{card}:1"))
            attempt("approve an action that already executed, new key",
                    lambda: self.client.approve(card, idempotency_key=f"sim:{self.profile['id']}:{card}:again"))
            attempt("reject an action that already executed", lambda: self.client.reject(card))
        if cancelled:
            card = cancelled[0][1]["toolCallId"]
            attempt("approve an action the executive rejected",
                    lambda: self.client.approve(card, idempotency_key=f"sim:{self.profile['id']}:{card}:late"))
        attempt("approve an action that does not exist",
                lambda: self.client.approve(987654, idempotency_key="sim:none"))
        after = self.state()
        same = digest == fingerprint({k: after[k] for k in ("events", "sent", "tasks", "reminders", "operations")})
        self.log("invalid_approvals", attempts=attempts, worldUnchanged=same)
        self._check(record, "invalid_approvals_change_nothing", same,
                    "; ".join(f"{a['case']}: HTTP {a['http']}, card {a['status']}" for a in attempts))

    def _briefing(self, record: Dict[str, Any]) -> None:
        brief = self.client.briefing()
        state = self.state()
        follow = self.client.follow_ups(refresh=False)
        zone = self.clock.zone
        today = self.now.astimezone(zone).date()
        meetings_today = [e for e in oracle.active_events(state)
                          if oracle.parse(e["start"]).astimezone(zone).date() == today]
        open_tasks = [t for t in state["tasks"] if t.get("status") == "open"]
        counts = brief.get("counts") or {}
        self.briefings.append({"stepId": record["id"], "at": self.now.isoformat(), "briefing": brief,
                               "followUps": follow.get("counts")})
        self.log("briefing", headline=brief.get("headline"), counts=counts,
                 unavailable=brief.get("unavailable"), followUps=follow.get("counts"))
        self.say(f"   Desk briefing: {brief.get('headline')}")
        self._check(record, "briefing_meetings_today_match_calendar",
                    counts.get("meetings_today") == len(meetings_today),
                    f"briefing says {counts.get('meetings_today')}, the calendars hold {len(meetings_today)}")
        self._check(record, "briefing_open_tasks_match_task_list",
                    counts.get("open_tasks") == len(open_tasks),
                    f"briefing says {counts.get('open_tasks')}, the task list holds {len(open_tasks)}")
        self._check(record, "briefing_built_on_complete_inbox", bool(brief.get("inbox_complete")),
                    f"inbox_complete={brief.get('inbox_complete')}, unavailable={brief.get('unavailable')}")
        text = json.dumps(brief).lower()
        handled = sum(1 for view in self.run_views.values()
                      if any(a["status"] == "executed" for a in view.get("actions") or []))
        self._check(record, "briefing_reports_handled_work",
                    any(key in brief for key in ("handled", "completed", "done")),
                    f"{handled} runs executed something today; the briefing has no section for work "
                    "that was done" if not any(key in brief for key in ("handled", "completed", "done"))
                    else "the briefing lists handled work")
        waiting = [f for f in state["followUps"] if f.get("status") == "waiting"]
        run_waiting = (follow.get("counts") or {}).get("waiting", 0) + (follow.get("counts") or {}).get("overdue", 0)
        self._check(record, "briefing_reports_awaited_replies",
                    "follow" in text or "await" in text or (not waiting and not run_waiting),
                    f"{len(waiting) + run_waiting} replies are awaited; the briefing "
                    + ("mentions them" if "follow" in text or "await" in text else "does not mention them"))

    def _scenario_check(self, step: Mapping[str, Any], record: Dict[str, Any], check: Mapping[str, Any]) -> None:
        state = self.state()
        follow = self.client.follow_ups(refresh=False)
        runs = list(self.run_views.values())

        def nudges(thread: str) -> List[Dict[str, Any]]:
            return [a for view in runs for a in view.get("actions") or []
                    if a["tool_name"] == "send_email" and a.get("purpose") == "nudge"
                    and (a.get("input") or {}).get("thread_id") == thread]

        if "overdue_surfaced" in check:
            wanted = next((f for f in state["followUps"] if f["id"] == check["overdue_surfaced"]), {})
            who = address(check["person"])
            surfaced = any(str(f.get("waitingOn")) == who and f.get("state") == "overdue"
                           for f in follow.get("followUps") or []) or any(
                who in oracle.addresses((a.get("input") or {}).get("to")) and a.get("purpose") == "nudge"
                for view in runs for a in view.get("actions") or [])
            self._check(record, "overdue_awaited_reply_is_surfaced", surfaced,
                        f"the reply from {who} was expected by {wanted.get('expectedBy')} and is still "
                        f"{wanted.get('status')}; the Desk "
                        + ("flags it as overdue" if surfaced else "neither flags it nor proposes a reminder"))
        if "nudge" in check:
            found = nudges(check["nudge"])
            sent = [a for a in found if a["status"] == "executed"]
            helped = [d for d in self.decisions if d["category"] == "missing_information"
                      and d["toolCallId"] in {a["toolCallId"] for a in found}]
            self._check(record, "overdue_follow_up_is_chased", len(sent) == 1,
                        f"{len(found)} reminder(s) proposed in {check['nudge']} "
                        f"({', '.join(a['status'] + (': ' + str(a.get('message')) if a.get('message') else '') for a in found) or 'none'}), "
                        f"{len(sent)} sent"
                        + ("; the proposal had no recipient until the executive typed it in" if helped else ""))
        if "no_second_nudge" in check:
            found = nudges(check["no_second_nudge"])
            self._check(record, "reminder_is_not_repeated", len(found) <= 1,
                        f"{len(found)} reminder(s) exist in {check['no_second_nudge']}")
            if len(found) == 1:
                self.duplicates_prevented.append({"what": "a second reminder was not proposed",
                                                  "thread": check["no_second_nudge"]})
        if "follow_up_satisfied" in check:
            mine = [f for f in follow.get("followUps") or [] if f.get("threadId") == check["follow_up_satisfied"]]
            self._check(record, "answer_satisfies_follow_up",
                        bool(mine) and all(f.get("state") == "satisfied" for f in mine),
                        f"follow-ups in {check['follow_up_satisfied']}: "
                        + (", ".join(f"{f.get('id')}={f.get('state')}" for f in mine) or "none"))
        if "overdue_task" in check:
            brief = self.client.briefing()
            task = next((t for t in state["tasks"] if t["id"] == check["overdue_task"]), {})
            text = json.dumps(brief).lower()
            self._check(record, "overdue_task_is_reported", "overdue" in text,
                        f"\"{task.get('title')}\" was due {task.get('due_at')} and is still open; the "
                        "briefing " + ("marks overdue work" if "overdue" in text else "has no overdue section"))
        if check.get("dependent_steps"):
            for request_id in record["requests"]:
                for view in self._views_for(request_id):
                    kinds = [(e["kind"], (e.get("data") or {}).get("tool"), (e.get("data") or {}).get("purpose"))
                             for e in view.get("timeline") or []]
                    booked = next((i for i, k in enumerate(kinds) if k[0] == "execution"
                                   and k[1] == "create_calendar_event"), None)
                    confirm = next((i for i, k in enumerate(kinds) if k[0] == "proposal" and k[2] == "confirm"), None)
                    steps = (view.get("plan") or {}).get("steps") or []
                    declared = len(steps) == 2 and steps[1]["dependsOn"] == [steps[0]["id"]]
                    self._check(record, "confirmation_only_after_the_booking_took_effect",
                                booked is not None and confirm is not None and confirm > booked and declared,
                                f"plan declares the dependency: {declared}; booking executed at timeline "
                                f"position {booked}, confirmation proposed at {confirm}")
        if check.get("blocked_step"):
            def blocked_in(view: Mapping[str, Any]) -> bool:
                return any(e["kind"] == "decision" and (e.get("data") or {}).get("decision") == "step_blocked"
                           for e in view.get("timeline") or [])

            for request_id in record["requests"]:
                for view in self._views_for(request_id):
                    emails = [a for a in view.get("actions") or [] if a["tool_name"] == "send_email"]
                    self._check(record, "dependent_step_not_proposed_after_rejection", not emails,
                                f"emails proposed after the booking was rejected: {len(emails)}")
                    unprompted = blocked_in(view)
                    after = self._refresh(self.client.advance(view["runId"])["runId"])
                    self._check(record, "blocked_step_is_recorded", blocked_in(after),
                                f"recorded by the Desk on its own: {unprompted}; after a client called "
                                f"POST /desk/runs/(id)/advance: {blocked_in(after)}")
        if check.get("partial_reported"):
            for request_id in record["requests"]:
                for view in self._views_for(request_id):
                    stage = (view.get("lifecycle") or {}).get("stage")
                    self._check(record, "partial_success_reported_as_partial",
                                stage == "PARTIALLY_COMPLETED" and view.get("state") == "partial",
                                f"the event exists and the confirmation failed; the Desk reports the run as "
                                f"{stage} / {view.get('state')}, compensation "
                                f"{((view.get('lifecycle') or {}).get('compensation') or {}).get('policy')}")
        if "unknown_then_reconciled" in check:
            tool = check["unknown_then_reconciled"]
            op = {"send_email": "email.send", "create_calendar_event": "calendar.create_event"}[tool]
            for request_id in record["requests"]:
                for view in self._views_for(request_id):
                    kinds = [(e["kind"], (e.get("data") or {}).get("tool"), (e.get("data") or {}).get("status"),
                              bool((e.get("data") or {}).get("reconciled"))) for e in view.get("timeline") or []]
                    unknown = any(k[0] == "execution" and k[1] == tool and k[2] == "unknown" for k in kinds)
                    reconciled = any(k[0] == "verification" and k[1] == tool and k[3] for k in kinds)
                    mine = [a for a in view.get("actions") or [] if a["tool_name"] == tool]
                    attempts = sum(int(a.get("attempts") or 0) for a in mine)
                    self._check(record, "unknown_outcome_is_read_back_not_repeated",
                                unknown and reconciled and all(a["status"] == "executed" for a in mine),
                                f"recorded as unknown: {unknown}; settled by a read-back, not a second "
                                f"write: {reconciled}; execution attempts recorded: {attempts}")
        if "interrupted_then_recovered" in check:
            tool = check["interrupted_then_recovered"]
            for request_id in record["requests"]:
                for view in self._views_for(request_id):
                    recovered = any(e["kind"] == "execution" and (e.get("data") or {}).get("recovered")
                                    for e in view.get("timeline") or [])
                    action = next((a for a in view.get("actions") or [] if a["tool_name"] == tool), {})
                    request = self.requests.get(request_id) or {}
                    effects = [e for e in oracle.active_events(state)
                               if request.get("senderEmail") in e["attendees"]
                               and oracle.same_moment(e["start"], oracle.action_start(action))] if action else []
                    self._check(record, "interrupted_action_is_settled_then_takes_effect_once",
                                recovered and action.get("status") == "executed" and len(effects) == 1,
                                f"the Desk's recovery settled the stuck action without running it: "
                                f"{recovered}; after the executive's retry it is {action.get('status')}; "
                                f"the meeting is on the calendar {len(effects)} time(s); the run's evidence "
                                f"counts {action.get('attempts')} execution records for it")
        if "flag" in check:
            for request_id in record["requests"]:
                flags = [flag for view in self._views_for(request_id) for flag in view.get("flags") or []]
                self._check(record, f"run_flagged_{check['flag']}", check["flag"] in flags, f"flags: {flags}")

    def _check(self, record: Dict[str, Any], name: str, passed: bool, detail: str) -> None:
        entry = {"stepId": record["id"], "check": name, "passed": bool(passed), "detail": detail}
        record["checks"].append(entry)
        self.checks.append(entry)
        self.log("check", check=name, passed=bool(passed), detail=detail)
        self.say(f"   CHECK {'pass' if passed else 'FAIL'}: {name}. {detail}")

    def _invariants(self, record: Dict[str, Any]) -> None:
        found = oracle.invariants(spec=self.spec, state=self.state(), initial=self.initial,
                                  runs=list(self.run_views.values()), overrides=self.overridden_events,
                                  interrupted=self.interrupted)
        for problem in found:
            entry = {"stepId": record["id"], **problem}
            if not any(v["invariant"] == entry["invariant"] and v["detail"] == entry["detail"]
                       for v in self.violations):
                self.violations.append(entry)
                self.log("invariant_violated", **entry)
                self.say(f"   INVARIANT VIOLATED: {problem['invariant']}: {problem['detail']}")

    # ── the end of the day ──────────────────────────────────────────────────
    def finish(self) -> Dict[str, Any]:
        for row in self.client.runs():
            self._refresh(row["runId"])
        final = self.state()
        follow = self.client.follow_ups(refresh=False)
        gate = self.client.sim_state().get("gate") or {}
        verdicts: Dict[str, Dict[str, Any]] = {}
        for request in self.requests.values():
            if request["status"] != "delivered":
                continue
            verdict = oracle.judge(spec=self.spec, clock=self.clock, request=request,
                                   runs=self._views_for(request["id"]), state=final, initial=self.initial,
                                   decisions=self.decisions)
            verdicts[request["id"]] = verdict
            self.log("verdict", request=request["id"], verdict=verdict["verdict"], notes=verdict["notes"],
                     runs=verdict["runIds"], stages=verdict["stages"])
        # Seeded "duplicate" expectations: repeated requests the Desk held.
        for request in self.requests.values():
            verdict = verdicts.get(request["id"])
            if verdict and verdict["verdict"] == "correct_escalation":
                reasons = [(run.get("held") or {}).get("reason") for run in self._views_for(request["id"])]
                if any(r in ("already_scheduled", "task_exists") for r in reasons):
                    self.duplicates_prevented.append({"what": f"repeated request held ({reasons[0]})",
                                                      "message": request["id"]})
        return {
            "profile": {k: self.profile[k] for k in ("id", "name", "description")},
            "seed": self.seed, "executive": self.executive.mode, "meta": self.meta, "health": self.health,
            "spec": self.spec, "steps": self.steps,
            "requests": {rid: {k: v for k, v in request.items() if k != "stateAtArrival"}
                         for rid, request in self.requests.items()},
            "verdicts": verdicts, "decisions": self.decisions, "checks": self.checks,
            "violations": self.violations, "errors": self.errors, "briefings": self.briefings,
            "duplicatesPrevented": self.duplicates_prevented, "runs": self.run_views,
            "followUps": follow, "initialState": self.initial, "finalState": final, "gate": gate,
            "replay": self.replay, "replayFingerprint": fingerprint(self.replay),
            "tickMs": self.tick_ms, "wallSeconds": round(time.monotonic() - self.started, 2),
            "apiCalls": self.client.calls,
        }
