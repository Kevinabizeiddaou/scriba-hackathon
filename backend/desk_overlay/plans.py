"""The typed execution plan of a run. Pure.

A plan is written once, when the run is opened, and stored as evidence. It
says what was understood, what that rests on, and what will be done in what
order:

    message      which message, in which mailbox
    intents      what it asks for, each with confidence and evidence
    facts        what the Desk verified by reading (a calendar, the thread)
    assumptions  what it filled in because the message did not say
    missing      what is needed and absent (leads to a question, not a guess)
    tools        the reads that were made
    steps        the actions, each with what it depends on
    approvals    how many of them a person must approve
    escalation   the conditions under which the Desk stops and hands over

A step is ``deferred`` when its content depends on the result of another
(the confirmation of a booking needs the booking). A deferred step is
proposed only after every step it depends on has taken effect, and never if
one of them failed, was rejected or is held: ``step_states`` decides that
from the cards, and the workflow obeys it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .readiness import EXTERNAL_WRITE_TOOLS

EFFECT = ("executed", "partially_executed")
DEAD = ("failed", "cancelled", "unsupported")
EXPECTED = {
    "book": "The meeting exists on the named calendar at the proposed time.",
    "reschedule": "The original event is at the new time; no second event exists.",
    "cancel": "The original event is cancelled.",
    "confirm": "The sender has a reply in the original thread stating what was done.",
    "offer_times": "The sender has a reply offering only times verified free.",
    "clarify": "The sender has been asked for the missing detail.",
    "nudge": "The awaited person has one reminder in the original thread.",
    "reply": "The sender has the reply the executive approved.",
    "record_task": "The task or reminder exists in the executive's own records.",
}
ESCALATION = [
    "A calendar cannot be read: availability is unknown and nothing is booked.",
    "A provider does not confirm a write: the outcome is unknown and is not retried blindly.",
    "A step fails or is rejected: the steps that depend on it are not proposed.",
    "An executed action cannot be verified: the run is handed to the person.",
]


def build(*, meta: Mapping[str, Any], understanding: Mapping[str, Any], plan: Mapping[str, Any]) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    for index, proposal in enumerate(plan.get("proposals") or [], start=1):
        proposal["stepId"] = f"s{index}"
        steps.append(_step(proposal["stepId"], proposal["tool_name"], proposal.get("purpose"),
                           proposal.get("depends_on") or [], deferred=False))
    # What may only follow a calendar change: telling the sender.
    for step in list(steps):
        if step["purpose"] in ("book", "reschedule", "cancel"):
            steps.append(_step(f"s{len(steps) + 1}", "send_email", "confirm", [step["id"]], deferred=True))
    return {
        "version": 1,
        "message": {key: meta.get(key) for key in ("provider", "provider_account_id", "email_id", "thread_id")},
        "planner": plan.get("planner"),
        "intents": [{key: intent.get(key) for key in ("type", "confidence", "evidence", "missing", "source")}
                    for intent in understanding.get("intents") or []],
        "unsupported": list(understanding.get("dropped") or []),
        "facts": list(plan.get("facts") or []),
        "assumptions": list(plan.get("assumptions") or []),
        "missing": sorted({m for intent in understanding.get("intents") or [] for m in intent.get("missing") or []}
                          | set(plan.get("missing") or [])),
        "tools": sorted({str(read.get("tool")) for read in plan.get("reads") or [] if read.get("tool")}),
        "steps": steps,
        "approvals": sum(1 for step in steps if step["requiresApproval"]),
        "escalation": ESCALATION,
    }


def _step(step_id: str, tool: str, purpose: Optional[str], depends_on: List[str], *, deferred: bool) -> Dict[str, Any]:
    return {"id": step_id, "tool": tool, "purpose": purpose, "dependsOn": list(depends_on),
            "requiresApproval": True, "external": tool in EXTERNAL_WRITE_TOOLS, "deferred": deferred,
            "expected": EXPECTED.get(str(purpose), "The action takes effect and is verified."),
            "onFailure": "Dependent steps are not proposed; the run is handed to the person."}


def step_states(plan: Optional[Mapping[str, Any]], cards_by_step: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Each step with where it stands.

    ``proposed`` steps take their card's status. A step with no card is
    ``ready`` when every step it depends on has taken effect, ``blocked``
    when one of them is dead (failed, rejected) and ``waiting`` otherwise.
    """
    states: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for step in (plan or {}).get("steps") or []:
        card = cards_by_step.get(step["id"])
        if card is not None:
            state = str(card.get("status") or "proposed")
        else:
            needs = [by_id.get(dep, {}).get("state") for dep in step.get("dependsOn") or []]
            if any(s in DEAD or s == "blocked" for s in needs):
                state = "blocked"
            elif needs and all(s in EFFECT for s in needs):
                state = "ready"
            elif not needs:
                state = "ready"
            else:
                state = "waiting"
        entry = {**step, "state": state, "toolCallId": (card or {}).get("id")}
        by_id[step["id"]] = entry
        states.append(entry)
    return states
