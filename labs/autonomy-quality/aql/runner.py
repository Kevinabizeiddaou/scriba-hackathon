"""Drive one synthetic case through the real Desk workflow and record what
actually happened.

The runner plays the person, and only the person: it starts the case, waits,
looks at what is proposed, decides each approval according to the case's
policy, and waits again. It never completes a step for the engine. Anything
it does beyond deciding an approval (a retry, an ``advance``) is recorded as
a human rescue.

It records three independent things, which the oracle keeps apart:

* ``decisions``: what the lab itself decided, and exactly what it was shown
  when it decided (the approval's ``changes``);
* ``run`` / ``approvals`` / ``deskRun``: what the engine reports;
* ``world``: the synthetic office afterwards, read back through the probe.

No tool trace is hardcoded anywhere: a case carries an input, a context and a
decision policy, and nothing else reaches the backend.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from .backend import BackendError, DeskBackend
from .transport import TransportError, error_code

FINAL = ("completed", "failed", "cancelled")
SIDE_EFFECT_TOOLS = ("email.send", "calendar.create_event", "calendar.update_event", "calendar.cancel_event")


def _tool_of(approval: Dict[str, Any]) -> str:
    changes = approval.get("changes") or []
    return str(changes[0].get("tool")) if changes else ""


def _card_id(approval_id: str) -> Optional[int]:
    try:
        return int(str(approval_id).rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return None


def decision_for(policy: Any, approval: Dict[str, Any], ordinal: int) -> str:
    """The person's decision. ``policy`` is "approve_all", "reject_all", or
    {"default": "approve", "<tool>": "reject", "nth": {"2": "reject"}}."""
    if policy in (None, "approve_all"):
        return "approve"
    if policy == "reject_all":
        return "reject"
    if isinstance(policy, dict):
        nth = policy.get("nth") or {}
        if str(ordinal) in nth:
            return str(nth[str(ordinal)])
        return str(policy.get(_tool_of(approval)) or policy.get("default") or "approve")
    return "approve"


class CaseRunner:
    def __init__(self, backend: DeskBackend, *, timeout: float = 30.0, poll: float = 0.15, stall: float = 2.5) -> None:
        self.backend = backend
        self.timeout = timeout
        self.poll = poll
        self.stall = stall

    def run(self, case: Dict[str, Any]) -> Dict[str, Any]:
        obs: Dict[str, Any] = {
            "runId": None, "error": None, "log": [], "stops": [], "run": None, "approvals": [], "decisions": [],
            "world": None, "deskRunId": None, "deskRun": None, "labEvents": [], "labSent": [],
            "rescues": [], "instrumented": [], "foreignApprovals": 0,
            "timing": {"wallMs": None, "toFirstStopMs": None},
        }
        started = time.monotonic()

        def log(kind: str, **data: Any) -> None:
            obs["log"].append({"seq": len(obs["log"]) + 1, "ms": int((time.monotonic() - started) * 1000),
                               "type": kind, **data})

        script = list(case.get("script") or [])
        backend = self.backend
        try:
            run = backend.start_case(case)
            obs["runId"] = run["id"]
            log("start", runId=run["id"])
            rounds = ordinal = retries = 0
            while True:
                run = self._wait(obs["runId"], obs, log)
                if obs["timing"]["toFirstStopMs"] is None:
                    obs["timing"]["toFirstStopMs"] = int((time.monotonic() - started) * 1000)
                obs["stops"].append({"status": run.get("status"), "outcome": run.get("outcome"),
                                     "lifecycle": run.get("lifecycle"),
                                     "errorCodes": [(a.get("error") or {}).get("code") for a in run.get("actions") or []
                                                    if a.get("error")],
                                     "actions": [(a.get("tool"), a.get("status")) for a in run.get("actions") or []]})
                log("observe", status=run.get("status"), outcome=run.get("outcome"))
                if obs.get("stalled"):
                    break
                if run.get("status") == "awaiting_approval":
                    listed = backend.approvals(obs["runId"])
                    obs["foreignApprovals"] += sum(1 for a in listed if a.get("runId") != obs["runId"])
                    pending = [a for a in listed if a.get("runId") == obs["runId"] and a.get("status") == "pending"]
                    if not pending:
                        log("stuck", reason="awaiting_approval with nothing pending")
                        break
                    for step in [s for s in script if s.get("round") == rounds and s.get("do") != "decide"]:
                        self._intervene(case, step, pending, obs, log)
                    mode = next((s for s in script if s.get("round") == rounds and s.get("do") == "decide"), None)
                    for approval in sorted(pending, key=lambda a: str(a.get("createdAt")) + str(a.get("id"))):
                        ordinal += 1
                        if any(s.get("round") == rounds and s.get("do") == "interrupt" for s in script):
                            continue        # the interruption stood in for the decision
                        self._decide(case, approval, ordinal, rounds, mode, obs, log)
                    rounds += 1
                    if rounds > 12:
                        log("stuck", reason="more than 12 approval rounds")
                        break
                    continue
                # A final status. The person may retry a failed action, if the case says they do.
                retry = next((s for s in script if s.get("after") == "final" and s.get("do") == "retry_failed"), None)
                if retry and retries < int(retry.get("max") or 1) and self._retry_failed(run, obs, log):
                    retries += 1
                    continue
                break
            obs["run"] = run
            for step in [s for s in script if s.get("after") == "final" and s.get("do") not in ("retry_failed",)]:
                self._intervene(case, step, [], obs, log)
            if any(s.get("after") == "final" for s in script):
                obs["run"] = backend.run(obs["runId"])
            obs["approvals"] = [a for a in backend.approvals(obs["runId"]) if a.get("runId") == obs["runId"]]
        except (BackendError, TransportError) as exc:
            obs["error"] = {"code": getattr(exc, "code", "error"), "message": str(exc)}
            log("error", code=obs["error"]["code"])
        obs["timing"]["wallMs"] = int((time.monotonic() - started) * 1000)
        self._read_back(obs)
        return obs

    # ── waiting ─────────────────────────────────────────────────────────────
    def _wait(self, run_id: str, obs: Dict[str, Any], log: Any) -> Dict[str, Any]:
        began = time.monotonic()
        deadline = began + self.timeout
        nudged = False
        while True:
            run = self.backend.run(run_id)
            if run.get("status") in FINAL or run.get("status") == "awaiting_approval":
                return run
            if not nudged and time.monotonic() - began > self.stall:
                # The run rests in "running". If the Desk itself says a step is ready
                # and is waiting for a client to ask for it (next: ["advance"]), it
                # will rest there for ever: the evaluation contract has no such call,
                # and the product route would run outside this case's world. The lab
                # does not push it. It records the stall and judges what is there.
                nudged = True
                probe = self.backend.eval_world(run_id) or {}
                view = self.backend.desk_run(probe.get("deskRunId")) if probe.get("deskRunId") is not None else None
                if view and "advance" in (view.get("next") or []):
                    obs["stalled"] = {"status": run.get("status"), "stage": (view.get("lifecycle") or {}).get("stage"),
                                      "next": view.get("next"), "afterMs": int((time.monotonic() - began) * 1000)}
                    log("stalled", **obs["stalled"])
                    return run
            if time.monotonic() > deadline:
                raise BackendError("case_timeout", f"The run was still {run.get('status')} after {self.timeout:.0f}s.")
            time.sleep(self.poll)

    # ── the person decides ──────────────────────────────────────────────────
    def _decide(self, case: Dict[str, Any], approval: Dict[str, Any], ordinal: int, rounds: int,
                mode: Optional[Dict[str, Any]], obs: Dict[str, Any], log: Any) -> None:
        backend = self.backend
        decision = decision_for(case.get("policy"), approval, ordinal)
        how = (mode or {}).get("mode") or "single"
        if mode and mode.get("tool") and mode["tool"] != _tool_of(approval):
            how = "single"
        record = {"approvalId": approval["id"], "tool": _tool_of(approval), "decision": decision, "round": rounds,
                  "ordinal": ordinal, "mode": how, "shown": approval.get("changes"), "responses": [],
                  "seq": len(obs["log"]) + 1}
        obs["decisions"].append(record)

        def send(what: str) -> None:
            status, body = backend.decide(approval["id"], what)
            record["responses"].append({"decision": what, "http": status, "code": error_code(body) if status >= 400 else None,
                                        "status": body.get("status") if isinstance(body, dict) else None})

        if how == "single":
            send(decision)
        elif how == "double_approve":            # the same click twice
            send("approve")
            send("approve")
        elif how == "approve_then_reject":       # a contradicting decision after the fact
            send("approve")
            send("reject")
            record["decision"] = "approve"
        elif how == "reject_then_approve":
            send("reject")
            send("approve")
            record["decision"] = "reject"
        elif how == "concurrent_approve":        # several approvers, or a client retrying in parallel
            workers = [threading.Thread(target=send, args=("approve",)) for _ in range(int(mode.get("n") or 5))]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            record["decision"] = "approve"
        elif how == "approve_with_overrides":    # the person edits the action as they approve it
            card = _card_id(approval["id"])
            status, body = backend.approve_card(card, overrides=dict(mode.get("overrides") or {}),
                                                idempotency_key=f"aql:{approval['id']}")
            card_view = (body or {}).get("tool_call") if isinstance(body, dict) else None
            record["responses"].append({"decision": "approve", "http": status,
                                        "cardStatus": (card_view or {}).get("status"),
                                        "errorCode": ((card_view or {}).get("output") or {}).get("error_code")})
            record["decision"], record["overrides"] = "approve", dict(mode.get("overrides") or {})
        log("decision", approvalId=approval["id"], tool=record["tool"], decision=record["decision"], mode=how,
            http=[r["http"] for r in record["responses"]])

    # ── the outside world changes, or stored state is damaged ───────────────
    def _intervene(self, case: Dict[str, Any], step: Dict[str, Any], pending: List[Dict[str, Any]],
                   obs: Dict[str, Any], log: Any) -> None:
        backend, what = self.backend, step.get("do")
        if what == "world_changes":
            applied = backend.change_eval_world(obs["runId"], step["changes"])
            obs["labEvents"].extend(applied.get("addedEvents") or [])
            obs["labSent"].extend(applied.get("sentSeeded") or [])
            log("world_changes", applied=applied)
        elif what in ("tamper", "interrupt"):
            target = next((a for a in pending if not step.get("tool") or _tool_of(a) == step["tool"]), None)
            if target is None:
                log("intervention_skipped", do=what, reason="no matching pending approval")
                return
            card = _card_id(target["id"])
            if what == "tamper":
                status, body = backend.tamper_card(card, dict(step.get("input") or {}))
                obs["instrumented"].append("stored_action_changed_behind_approval")
            else:
                status, body = backend.interrupt_card(card, bool(step.get("effectApplied")))
                obs["instrumented"].append("process_stopped_mid_action")
                # An action is only ever "executing" after the person approved it.
                obs["decisions"].append({"approvalId": target["id"], "tool": _tool_of(target), "decision": "approve",
                                         "round": step.get("round"), "ordinal": len(obs["decisions"]) + 1,
                                         "mode": "approved_then_process_died", "shown": target.get("changes"),
                                         "responses": [{"decision": "approve", "http": 200, "instrumented": True}],
                                         "seq": len(obs["log"]) + 1})
                obs["providerApplied"] = (body or {}).get("effectApplied") if status == 200 else None
                world = backend.eval_world(obs["runId"]) or {}
                if world.get("deskRunId") is not None:
                    recovered = backend.recover_run(world["deskRunId"])
                    log("recover", http=recovered[0], body=recovered[1])
            log(what, card=card, http=status, body=body if status != 200 else None)
        elif what == "redeliver_decision":
            for record in obs["decisions"]:
                status, body = backend.decide(record["approvalId"], step.get("decision") or record["decision"])
                record["responses"].append({"decision": step.get("decision") or record["decision"], "http": status,
                                            "code": error_code(body) if status >= 400 else None, "late": True,
                                            "status": body.get("status") if isinstance(body, dict) else None})
            log("redeliver_decision")

    def _retry_failed(self, run: Dict[str, Any], obs: Dict[str, Any], log: Any) -> bool:
        failed = [a for a in run.get("actions") or [] if a.get("status") == "failed" and a.get("approvalId")]
        if not failed:
            return False
        card = _card_id(failed[0]["approvalId"])
        status, body = self.backend.retry_card(card)
        card_view = (body or {}).get("tool_call") if isinstance(body, dict) else None
        obs["rescues"].append({"kind": "retry", "tool": failed[0].get("tool"), "card": card, "http": status,
                               "cardStatus": (card_view or {}).get("status"),
                               "reconciled": bool(((card_view or {}).get("output") or {}).get("reconciled"))})
        log("retry", card=card, http=status, cardStatus=(card_view or {}).get("status"))
        return status == 200

    # ── afterwards: read the office back ────────────────────────────────────
    def _read_back(self, obs: Dict[str, Any]) -> None:
        if not obs.get("runId"):
            return
        try:
            probe = self.backend.eval_world(obs["runId"])
            if probe:
                obs["world"], obs["deskRunId"] = probe.get("world"), probe.get("deskRunId")
                if obs["deskRunId"] is not None:
                    obs["deskRun"] = self.backend.desk_run(obs["deskRunId"])
        except (BackendError, TransportError) as exc:
            obs["log"].append({"seq": len(obs["log"]) + 1, "type": "probe_error", "code": getattr(exc, "code", "error")})
