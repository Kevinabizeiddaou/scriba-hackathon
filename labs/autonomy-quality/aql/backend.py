"""Backend adapters.

``DeskBackend`` speaks three interfaces of one running Desk backend:

* the versioned evaluation contract, ``/desk/eval/v1`` (contract 1.1.0);
* the Desk's product routes (``/desk/*`` and Scriba's ``/chat/tool-calls``),
  used for the things a person does in the product: approve with an edit,
  retry, take a message in twice;
* the lab probe, ``/lab/v1`` (``server/lab_server.py``), for reading the
  synthetic office back and for changing the outside world.

``connect`` asks the backend what it has before anything is sent. Whatever is
absent is listed in ``missing`` with what it is needed for; the lab then runs
what it can and says so, instead of failing or inventing an endpoint.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from . import CONTRACT_VERSION
from .transport import Session, TransportError, error_code

EVAL = "/desk/eval/v1"
LAB = "/lab/v1"
SEEDED_USERS = {"alice": ("alice@example.com", "e2e-password-123"), "bob": ("bob@example.com", "e2e-password-456")}


class BackendError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DeskBackend:
    def __init__(self, api_root: str, *, user: str = "alice", timeout: float = 60.0) -> None:
        self.api_root = api_root.rstrip("/")
        self.user = user
        self.session = Session(self.api_root, timeout=timeout)
        self.meta: Dict[str, Any] = {}
        self.health: Dict[str, Any] = {}
        self.lab: Dict[str, Any] = {}
        self.missing: List[Dict[str, str]] = []
        self.caps: Dict[str, bool] = {}

    # ── handshake ───────────────────────────────────────────────────────────
    def connect(self) -> "DeskBackend":
        email = os.environ.get("AQL_EMAIL") or SEEDED_USERS[self.user][0]
        password = os.environ.get("AQL_PASSWORD") or SEEDED_USERS[self.user][1]
        self.session.sign_in(email, password)

        def need(ok: bool, endpoint: str, needed_for: str) -> bool:
            if not ok:
                self.missing.append({"endpoint": endpoint, "neededFor": needed_for})
            return ok

        status, health = self.session.get("/desk/health")
        self.health = health if status == 200 and isinstance(health, dict) else {}
        self.caps["overlay"] = need(status == 200, "GET /desk/health", "any Desk run at all")

        status, meta = self.session.get(f"{EVAL}/meta")
        self.meta = meta if status == 200 and isinstance(meta, dict) else {}
        self.caps["eval"] = need(status == 200 and bool(self.meta.get("capabilities", {}).get("evaluation")),
                                 f"GET {EVAL}/meta, POST {EVAL}/evaluation/runs",
                                 "starting a synthetic case in an isolated world")
        if self.caps["eval"]:
            major = str(self.meta.get("contractVersion") or "").split(".")[0]
            if major != CONTRACT_VERSION.split(".")[0]:
                raise BackendError("unsupported_contract_version",
                                   f"The backend implements contract {self.meta.get('contractVersion')}; "
                                   f"this runner speaks {CONTRACT_VERSION}.")
            if self.meta.get("sandbox") is not True:
                raise BackendError("not_a_sandbox", "The backend does not report sandbox: true. The lab never "
                                                    "runs synthetic cases against a real mailbox or calendar.")
        capabilities = self.meta.get("capabilities") or {}
        self.caps["faults"] = need(bool(capabilities.get("faultInjection")) or not self.caps["eval"],
                                   "capabilities.faultInjection", "provider failure and unknown-outcome cases")
        self.caps["chat"] = need(bool(capabilities.get("chat")) or not self.caps["eval"],
                                 f"{EVAL}: input.kind = conversation",
                                 "cases that start from a chat turn instead of an email")

        status, lab = self.session.get(f"{LAB}/info")
        self.lab = lab if status == 200 and isinstance(lab, dict) else {}
        features = self.lab.get("features") or {}
        self.caps["world"] = need(bool(features.get("evalWorldProbe")),
                                  f"GET {EVAL}/runs/{{id}}/world (served today only by the lab probe, {LAB})",
                                  "reading the synthetic office back: without it every state check rests on "
                                  "the engine's own claims and no case can be scored 'completed'")
        self.caps["office"] = need(bool(features.get("office")), f"POST {LAB}/office",
                                   "multi-mailbox, duplicate-delivery and product-route scenarios")
        self.caps["instrumented"] = bool(features.get("storedStateFaults"))
        if not self.caps["instrumented"]:
            self.missing.append({"endpoint": f"POST {LAB}/cards/{{id}}/tamper|interrupt",
                                 "neededFor": "changed-behind-approval and interrupted-process scenarios"})
        return self

    # ── identity of what is being measured ──────────────────────────────────
    def execution_mode(self) -> Dict[str, Any]:
        """Which of the five evidence classes this target belongs to."""
        desk = self.meta.get("desk") or {}
        model = bool((desk.get("model") or {}).get("configured")) or self.meta.get("agent") == "real"
        env = (self.lab.get("env") or {})
        if model:
            planner, model_name = "real_model", env.get("DESK_MODEL_NAME") or "configured (name not reported)"
        else:
            planner, model_name = "rules_only", None
        return {
            "planner": planner,                               # rules_only | scripted_model | real_model
            "provider": "isolated_sandbox" if self.meta.get("sandbox") is True else "unknown",
            "model": model_name,
            "understanding": env.get("DESK_UNDERSTANDING") or "off",
            "agentStep": env.get("DESK_AGENT") or "off",
            "internalWrites": desk.get("internalWrites"),
            "label": f"{planner}+isolated_sandbox" if self.meta.get("sandbox") is True else planner,
        }

    def identity(self) -> Dict[str, Any]:
        return {
            "apiRoot": self.api_root, "service": self.meta.get("service"),
            "contractVersion": self.meta.get("contractVersion"), "overlayVersion": self.health.get("version"),
            "backendCommit": self.lab.get("backendCommit"), "backendDirty": self.lab.get("backendDirty"),
            "scribaCommit": self.lab.get("scribaCommit"), "agentReported": self.meta.get("agent"),
            "executionMode": self.execution_mode(), "capabilities": dict(self.caps), "missing": list(self.missing),
        }

    # ── the evaluation contract ─────────────────────────────────────────────
    def start_case(self, case: Dict[str, Any]) -> Dict[str, Any]:
        status, run = self.session.post(f"{EVAL}/evaluation/runs", {
            "caseId": case["id"], "input": case["input"], "context": case["context"], "mode": "sandbox"})
        if status not in (200, 202) or not isinstance(run, dict) or not run.get("id"):
            raise BackendError(error_code(run) or f"http_{status}", f"The case could not be started (HTTP {status}).")
        return run

    def run(self, run_id: str) -> Dict[str, Any]:
        status, run = self.session.get(f"{EVAL}/runs/{run_id}")
        if status != 200 or not isinstance(run, dict):
            raise BackendError(error_code(run) or f"http_{status}", f"GET run failed (HTTP {status}).")
        return run

    def approvals(self, run_id: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        query = f"?runId={run_id}" + (f"&status={status_filter}" if status_filter else "")
        status, found = self.session.get(f"{EVAL}/approvals{query}")
        if status != 200 or not isinstance(found, list):
            raise BackendError(error_code(found) or f"http_{status}", f"GET approvals failed (HTTP {status}).")
        return found

    def decide(self, approval_id: str, decision: str, note: Optional[str] = None) -> Tuple[int, Any]:
        return self.session.post(f"{EVAL}/approvals/{approval_id}/decision",
                                 {"decision": decision, "decidedBy": "Autonomy Quality Lab", "note": note})

    # ── the product's own routes ────────────────────────────────────────────
    def desk_run(self, desk_run_id: Any) -> Optional[Dict[str, Any]]:
        status, run = self.session.get(f"/desk/runs/{desk_run_id}")
        return run if status == 200 and isinstance(run, dict) else None

    def card(self, card_id: Any) -> Tuple[int, Any]:
        return self.session.get(f"/chat/tool-calls/{card_id}")

    def approve_card(self, card_id: Any, overrides: Optional[Dict[str, Any]] = None,
                     idempotency_key: Optional[str] = None) -> Tuple[int, Any]:
        body: Dict[str, Any] = {}
        if overrides:
            body["payload_overrides"] = overrides
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self.session.post(f"/chat/tool-calls/{card_id}/approve", body)

    def cancel_card(self, card_id: Any) -> Tuple[int, Any]:
        return self.session.post(f"/chat/tool-calls/{card_id}/cancel", {})

    def retry_card(self, card_id: Any) -> Tuple[int, Any]:
        return self.session.post(f"/chat/tool-calls/{card_id}/retry", {})

    def intake(self, provider: str, message_id: str, mailbox: Optional[str] = None) -> Tuple[int, Any]:
        body = {"provider": provider, "id": message_id}
        if mailbox:
            body["mailbox"] = mailbox
        return self.session.post("/desk/intake", body)

    def sweep(self, **body: Any) -> Tuple[int, Any]:
        return self.session.post("/desk/intake/sweep", body)

    def advance(self, desk_run_id: Any) -> Tuple[int, Any]:
        return self.session.post(f"/desk/runs/{desk_run_id}/advance", {})

    # ── the lab probe ───────────────────────────────────────────────────────
    def eval_world(self, run_id: str) -> Optional[Dict[str, Any]]:
        """{"deskRunId", "world"} for an evaluation run, or None without the probe."""
        if not self.caps.get("world"):
            return None
        status, found = self.session.get(f"{LAB}/eval-runs/{run_id}/world")
        return found if status == 200 and isinstance(found, dict) else None

    def change_eval_world(self, run_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        status, found = self.session.post(f"{LAB}/eval-runs/{run_id}/world/changes", changes)
        if status != 200:
            raise BackendError(error_code(found) or f"http_{status}", "The world change could not be applied.")
        return found.get("applied") or {}

    def new_office(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        status, found = self.session.post(f"{LAB}/office", spec)
        if status != 200:
            raise BackendError(error_code(found) or f"http_{status}", f"The lab office could not be built (HTTP {status}).")
        return found

    def office_world(self) -> Dict[str, Any]:
        status, found = self.session.get(f"{LAB}/office/world")
        if status != 200:
            raise BackendError(error_code(found) or f"http_{status}", "The lab office could not be read.")
        return found["world"]

    def change_office(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        status, found = self.session.post(f"{LAB}/office/changes", changes)
        if status != 200:
            raise BackendError(error_code(found) or f"http_{status}", "The office change could not be applied.")
        return found.get("applied") or {}

    def tamper_card(self, card_id: Any, fields: Dict[str, Any]) -> Tuple[int, Any]:
        return self.session.post(f"{LAB}/cards/{card_id}/tamper", {"input": fields})

    def interrupt_card(self, card_id: Any, effect_applied: bool) -> Tuple[int, Any]:
        return self.session.post(f"{LAB}/cards/{card_id}/interrupt", {"effectApplied": effect_applied})

    def recover_run(self, desk_run_id: Any) -> Tuple[int, Any]:
        return self.session.post(f"{LAB}/runs/{desk_run_id}/recover", {})


def connect(api_root: str, *, user: str = "alice") -> DeskBackend:
    try:
        return DeskBackend(api_root, user=user).connect()
    except TransportError as exc:
        raise BackendError(exc.code, str(exc)) from None
