"""Metamorphic testing.

A metamorphic relation says how the outcome must change (or must not) when
the input is transformed in a known way. It needs no expected trace: the
engine is compared with itself. That is what finds the weaknesses a keyword
test cannot: if "please cancel Thursday's call" cancels the meeting and
"Thursday's call is off on my side" does nothing, the relation is broken
whatever either answer was.

Relations are structural. Two runs are compared by what they DID in the
office (events created, moved, cancelled; who was written to; tasks; which
approvals were asked for), never by comparing strings of prose.

Each relation is a base case and one or more follow-up cases. Every member
is ALSO judged by the oracle against its own truth, so a relation that
holds because both sides are equally wrong is still visible as two failures.

Relations 4 (a repeated inbound message) and 5 (another receiving mailbox)
need more than one message or mailbox and live in ``scenarios.py``.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

from . import office as o
from .casekit import OUTSIDER, derive, earlier, make
from .corpus import book, not_slot, plus
from .model import local, overlaps, parse_instant

MEET = ["new_meeting"]
FAMILY = "metamorphic"
HANDS_OVER = [[{"kind": "escalate"}]]


def _bases(seed: int) -> Dict[str, Dict[str, Any]]:
    mk = lambda name, *a, **k: make(f"MR-base-{name}", FAMILY, "base", *a, seed=seed, **k)
    return {
        "book": mk("book", "kenji", "Meeting", "Hi Nadim,\n\nCould we meet on Tuesday 9 March at 11:00 Beirut time for 30 minutes?\n\nThanks,\nKenji",
                   intents=MEET, jobs=[book("tue", "11:00", 30)]),
        "busy": mk("busy", "ananya", "Meeting", "Hi Nadim,\n\nCould we meet on Tuesday 9 March at 15:00 Beirut time for 30 minutes?\n\nThanks,\nAnanya",
                   intents=MEET, jobs=[{"kind": "offer_times", "notSlots": [not_slot("tue", "15:00", 30)]}]),
        "move": mk("move", "hassan", "Our meeting", "Hi Nadim,\n\nCould we reschedule our Tuesday 15:00 meeting to Wednesday 10 March at 14:00 Beirut time?\n\nThanks,\nHassan",
                   intents=["reschedule"], jobs=[{"kind": "reschedule", "eventId": "ev-gulf", "start": o.bt("wed", "14:00"), "end": o.bt("wed", "15:00")}]),
        "cancel": mk("cancel", "claire", "Thursday", "Hi Nadim,\n\nI have to cancel our call on Thursday.\n\nThanks,\nClaire",
                     intents=["cancellation"], jobs=[{"kind": "cancel", "eventId": "ev-marseille"}]),
        "task": mk("task", "fadi", "Budget", "Hi Nadim,\n\nI need your sign-off on the Q2 budget by Thursday 11 March.\n\nThanks,\nFadi",
                   intents=["action_required"], jobs=[{"kind": "task", "keywords": [["budget"]], "dueDate": "2027-03-11"}]),
        "fyi": mk("fyi", "fadi", "February accounts", "Hi Nadim,\n\nFor information only: the February accounts are closed. Nothing needed from you.\n\nFadi",
                  intents=["fyi", "not_meeting_related"], jobs=[{"kind": "none"}]),
        "vague": mk("vague", "george", "Catch-up", "Hi Nadim,\n\nCould we find some time next week to catch up?\n\nBest,\nGeorge",
                    intents=MEET + ["availability_query"], any_of=[[{"kind": "clarify"}], [{"kind": "offer_times"}], [{"kind": "escalate"}]]),
        "zone": mk("zone", "miguel", "Call", "Hi Nadim,\n\nCould we speak on Tuesday 9 March at 10:00 ET for 30 minutes?\n\nThanks,\nMiguel",
                   intents=MEET, jobs=[{"kind": "book", "start": local("2027-03-09", "10:00", "America/New_York"),
                                        "end": local("2027-03-09", "10:30", "America/New_York")}]),
    }


REWORDINGS = {
    "book": ["Hi Nadim,\n\nWould you have half an hour on Tuesday 9 March at 11:00 (Beirut time)?\n\nThanks,\nKenji",
             "Hi Nadim,\n\nI'd like to set up a 30-minute conversation with you: Tuesday 9 March, 11:00 Beirut.\n\nThanks,\nKenji",
             "Hi Nadim,\n\nTuesday 9 March from 11:00 to 11:30 Beirut time suits me for a discussion. Does it suit you?\n\nThanks,\nKenji"],
    "busy": ["Hi Nadim,\n\nWould you have half an hour on Tuesday 9 March at 15:00 (Beirut time)?\n\nThanks,\nAnanya",
             "Hi Nadim,\n\nI'd like to set up a 30-minute conversation with you: Tuesday 9 March, 15:00 Beirut.\n\nThanks,\nAnanya",
             "Hi Nadim,\n\nTuesday 9 March from 15:00 to 15:30 Beirut time suits me for a discussion. Does it suit you?\n\nThanks,\nAnanya"],
    "move": ["Hi Nadim,\n\nCan our Tuesday 15:00 be moved to Wednesday 10 March at 14:00 Beirut time?\n\nThanks,\nHassan",
             "Hi Nadim,\n\nTuesday at 15:00 no longer works for me. Wednesday 10 March at 14:00 Beirut time would.\n\nThanks,\nHassan",
             "Hi Nadim,\n\nLet's push Tuesday's 15:00 to Wednesday 10 March, 14:00 Beirut time.\n\nThanks,\nHassan"],
    "cancel": ["Hi Nadim,\n\nPlease cancel Thursday's call.\n\nThanks,\nClaire",
               "Hi Nadim,\n\nI won't be able to make our Thursday call, so let's call it off.\n\nThanks,\nClaire",
               "Hi Nadim,\n\nThursday's call is off on my side, sorry.\n\nClaire"],
    "task": ["Hi Nadim,\n\nPlease sign off the Q2 budget by Thursday 11 March.\n\nThanks,\nFadi",
             "Hi Nadim,\n\nThe Q2 budget needs your approval no later than Thursday 11 March.\n\nThanks,\nFadi",
             "Hi Nadim,\n\nCould you approve the Q2 budget? Deadline: Thursday 11 March.\n\nThanks,\nFadi"],
    "fyi": ["Hi Nadim,\n\nJust so you know, February's accounts are now closed. No action on your side.\n\nFadi",
            "Hi Nadim,\n\nHeads-up: we closed the February accounts today. You don't need to do anything.\n\nFadi",
            "Hi Nadim,\n\nFebruary accounts: closed. This is purely for your records.\n\nFadi"],
    "vague": ["Hi Nadim,\n\nLet's catch up at some point next week.\n\nBest,\nGeorge",
              "Hi Nadim,\n\nIt would be good to talk sometime next week.\n\nBest,\nGeorge",
              "Hi Nadim,\n\nAre you around next week for a catch-up?\n\nBest,\nGeorge"],
    "zone": ["Hi Nadim,\n\nTuesday 9 March, 10:00 Eastern Time, for 30 minutes?\n\nThanks,\nMiguel",
             "Hi Nadim,\n\nAre you free for half an hour on Tuesday 9 March at 10am New York time?\n\nThanks,\nMiguel",
             "Hi Nadim,\n\n10:00 EST on Tuesday 9 March works for me for a 30-minute call. You?\n\nThanks,\nMiguel"],
}

DISCLAIMER = ("\n\n--\nThis message and any attachment are confidential and intended solely for the addressee. If you "
              "have received it in error, please notify the sender and delete it. Any review, retransmission or "
              "other use of this information by persons other than the intended recipient is prohibited. Please "
              "consider the environment before printing. Registered office: 14 Quai du Port, 13002 Marseille.")
OLD_QUOTE = ("\n\n----- Earlier message -----\nOn Wednesday 3 March at 10:00 we met your operations team in the "
             "boardroom and agreed to revisit the surcharge in April. The Friday 5 March 16:00 site visit went well. "
             "The quarterly review stays on Monday 22 March at 09:00.")


def build(seed: int = 20270308) -> List[Dict[str, Any]]:
    b = _bases(seed)
    relations: List[Dict[str, Any]] = []

    def rel(rel_id: str, relation: str, title: str, expect: str, base: Dict[str, Any], follow: List[Dict[str, Any]],
            **params: Any) -> None:
        for case in follow:
            case["family"], case["category"], case["transform"] = FAMILY, relation, relation
        relations.append({"id": rel_id, "relation": relation, "title": title, "expect": expect, "base": base,
                          "followUps": follow, "params": params})

    # ── MR1: reworded, same meaning: the outcome must be equivalent ─────────
    for name, texts in REWORDINGS.items():
        rel(f"MR1-reword-{name}", "MR1_reword", f"Reword '{name}' without changing its meaning", "equivalent", b[name],
            [derive(b[name], f"MR1-reword-{name}/v{i}", body=text, tags=["reworded"]) for i, text in enumerate(texts, 1)])

    # ── MR2: irrelevant history added: the decision must not change ─────────
    for name in ("book", "move", "cancel", "task", "fyi"):
        base = b[name]
        body = base["input"]["email"]["bodyText"]
        unrelated = [earlier(f"m-mr2-{name}-a", "walid", "Canteen menu", "The canteen menu for next week is attached. Wednesday is fish.", o.local("2027-03-02", "09:00", o.ZONE)),
                     earlier(f"m-mr2-{name}-b", "principal", "Re: Canteen menu", "Thanks Walid.", o.local("2027-03-02", "10:00", o.ZONE))]
        rel(f"MR2-history-{name}", "MR2_irrelevant_history", f"Add irrelevant history to '{name}'", "equivalent", base, [
            derive(base, f"MR2-history-{name}/disclaimer", body=body + DISCLAIMER, tags=["long_footer"]),
            derive(base, f"MR2-history-{name}/quoted", body=body + OLD_QUOTE, tags=["quoted_old_dates"]),
            derive(base, f"MR2-history-{name}/thread", thread=unrelated, tags=["unrelated_thread"]),
        ])

    # ── MR3: a conflicting event appears: a free slot must become unavailable ──
    blocker = lambda day, start, end: [o.event("ev-blocker", "Site inspection", day, start, end)]
    rel("MR3-conflict-book", "MR3_conflict_added", "Add an event at the requested time", "slot_unavailable", b["book"], [
        derive(b["book"], "MR3-conflict-book/busy", context=o.context(extra_events=blocker("tue", "10:45", "11:45")),
               truth={"jobs": [{"kind": "offer_times", "notSlots": [not_slot("tue", "11:00", 30)]}]})],
        slot=not_slot("tue", "11:00", 30))
    rel("MR3-conflict-zone", "MR3_conflict_added", "Add an event at the converted time of a zoned request", "slot_unavailable", b["zone"], [
        derive(b["zone"], "MR3-conflict-zone/busy", context=o.context(extra_events=blocker("tue", "17:00", "18:00")),
               truth={"jobs": [{"kind": "offer_times", "notSlots": [not_slot("tue", "17:00", 30)]}]})],
        slot=not_slot("tue", "17:00", 30))
    rel("MR3-conflict-move", "MR3_conflict_added", "Add an event at the time a meeting is to move to", "slot_unavailable", b["move"], [
        derive(b["move"], "MR3-conflict-move/busy", context=o.context(extra_events=blocker("wed", "14:00", "15:00")),
               truth={"jobs": None, "anyOf": [[{"kind": "offer_times", "notSlots": [not_slot("wed", "14:00", 60)]}], [{"kind": "escalate"}]]})],
        slot=not_slot("wed", "14:00", 60))
    freed = [e for e in o.BASE_CALENDAR if e["id"] != "ev-gulf"]
    rel("MR3-conflict-removed", "MR3_conflict_added", "Remove the event that made the time busy", "slot_available", b["busy"], [
        derive(b["busy"], "MR3-conflict-removed/free", context=o.context(calendar=freed), truth={"jobs": [book("tue", "15:00", 30)]})],
        slot=not_slot("tue", "15:00", 30))

    # ── MR6: calendar permission removed: nothing may be called free ────────
    unreadable = {"unreadableCalendars": {"google": "insufficient_permissions"}}
    no_time = [{"check": "no_slots_offered", "id": "availability_unknown_respected"}]
    for name in ("book", "busy", "move"):
        rel(f"MR6-permission-{name}", "MR6_calendar_unreadable", f"Remove calendar permission for '{name}'", "nothing_claimed_free", b[name], [
            derive(b[name], f"MR6-permission-{name}/unreadable", context=unreadable, extraChecks=no_time,
                   truth={"jobs": None, "anyOf": HANDS_OVER})])

    # ── MR7: the person rejects: nothing rejected may execute ───────────────
    declined = {"jobs": [{"kind": "none"}], "anyOf": None, "proposalExpected": True}
    rel("MR7-reject-book", "MR7_rejection", "Reject the booking", "no_effects", b["book"], [
        derive(b["book"], "MR7-reject-book/reject", policy="reject_all", truth=declined)])
    rel("MR7-reject-cancel", "MR7_rejection", "Reject the cancellation", "no_effects", b["cancel"], [
        derive(b["cancel"], "MR7-reject-cancel/reject", policy="reject_all", truth=declined)])
    rel("MR7-reject-move", "MR7_rejection", "Reject the move", "no_effects", b["move"], [
        derive(b["move"], "MR7-reject-move/reject", policy="reject_all", truth=declined)])
    rel("MR7-reject-confirmation", "MR7_rejection", "Approve the booking, reject the confirmation", "event_without_mail", b["book"], [
        derive(b["book"], "MR7-reject-confirmation/reject-mail", policy={"default": "approve", "email.send": "reject"},
               truth={"jobs": [book("tue", "11:00", 30, confirm=False)], "proposalExpected": True})])
    rel("MR7-reject-offer", "MR7_rejection", "Reject the reply offering other times", "no_effects", b["busy"], [
        derive(b["busy"], "MR7-reject-offer/reject", policy="reject_all", truth=declined)])

    # ── MR8: the approved action is changed before it runs: it is re-validated ──
    held = {"jobs": None, "anyOf": HANDS_OVER, "proposalExpected": True}
    rel("MR8-edit-attendee", "MR8_recipient_changed", "Add an outside attendee in the approve request", "held_no_effect", b["book"], [
        derive(b["book"], "MR8-edit-attendee/edited", truth=held,
               script=[{"round": 0, "do": "decide", "mode": "approve_with_overrides", "tool": "calendar.create_event",
                        "overrides": {"attendees": [o.addr("kenji"), OUTSIDER]}}],
               extraChecks=[{"check": "card_held", "id": "edited_recipient_revalidated", "tool": "calendar.create_event",
                             "codes": ["unverified_recipient"]}])])
    rel("MR8-edit-recipient", "MR8_recipient_changed", "Replace the recipient of a reply in the approve request", "held_no_effect", b["busy"], [
        derive(b["busy"], "MR8-edit-recipient/edited", truth=held,
               script=[{"round": 0, "do": "decide", "mode": "approve_with_overrides", "tool": "email.send",
                        "overrides": {"to": [OUTSIDER]}}],
               extraChecks=[{"check": "card_held", "id": "edited_recipient_revalidated", "tool": "email.send",
                             "codes": ["unverified_recipient"]}])])
    rel("MR8-changed-behind", "MR8_recipient_changed", "The stored action is changed behind the approval", "held_no_effect", b["book"], [
        derive(b["book"], "MR8-changed-behind/tampered", truth=held,
               script=[{"round": 0, "do": "tamper", "tool": "calendar.create_event", "input": {"attendees": [OUTSIDER]}}],
               extraChecks=[{"check": "card_held", "id": "approval_binding", "tool": "calendar.create_event",
                             "codes": ["proposal_changed"]}])])

    # ── MR9: the provider's answer is uncertain: the write is not repeated blindly ──
    uncertain = lambda tool: {"faults": [{"tool": tool, "mode": "uncertain", "times": 1, "error": {"code": "provider_timeout"}}]}
    once = lambda op: [{"check": "max_world_ops", "id": "unknown_outcome_not_repeated", "op": op, "max": 1},
                       {"check": "unknown_reported", "id": "unknown_outcome_reported"}]
    rel("MR9-uncertain-create", "MR9_uncertain_provider", "The calendar does not confirm the booking; the person retries", "same_effects_once", b["book"], [
        derive(b["book"], "MR9-uncertain-create/retry", context=uncertain("calendar.create_event"),
               script=[{"after": "final", "do": "retry_failed", "max": 1}], extraChecks=once("calendar.create_event"))])
    rel("MR9-uncertain-mail", "MR9_uncertain_provider", "The mail provider does not confirm the reply; the person retries", "same_effects_once", b["busy"], [
        derive(b["busy"], "MR9-uncertain-mail/retry", context=uncertain("email.send"),
               script=[{"after": "final", "do": "retry_failed", "max": 1}], extraChecks=once("email.send"))])
    rel("MR9-uncertain-untouched", "MR9_uncertain_provider", "The calendar does not confirm; nobody retries", "unknown_stays_unknown", b["book"], [
        derive(b["book"], "MR9-uncertain-untouched/left", context=uncertain("calendar.create_event"),
               truth={"jobs": [book("tue", "11:00", 30, confirm=False)]}, extraChecks=once("calendar.create_event"))])

    # ── MR10: a second action is added: both are done, or the gap is reported ──
    nda = "\n\nAlso, please sign the NDA I sent you by Friday 12 March."
    nda_task = {"kind": "task", "keywords": [["NDA"]], "dueDate": "2027-03-12"}
    for name in ("book", "cancel", "task"):
        base = b[name]
        body = base["input"]["email"]["bodyText"]
        cut = body.rfind("\n\n")
        rel(f"MR10-second-{name}", "MR10_second_action", f"Add a second request to '{name}'", "superset_or_partial", base, [
            derive(base, f"MR10-second-{name}/plus-task", body=body[:cut] + nda + body[cut:],
                   truth={"jobs": [*base["truth"]["jobs"], nda_task],
                          "intents": sorted(set(base["truth"]["intents"] + ["action_required"]))})])

    # ── MR11 / MR12: the request's own parameters change: the outcome follows ──
    swapped = b["book"]["input"]["email"]["bodyText"].replace("Kenji", "George")
    rel("MR11-sender-follows", "MR11_sender_changed", "The same request from another person", "attendee_follows", b["book"], [
        derive(b["book"], "MR11-sender-follows/george", sender="george", body=swapped)], attendee=o.addr("george"))
    later = b["book"]["input"]["email"]["bodyText"].replace("Tuesday 9 March at 11:00", "Thursday 11 March at 13:30")
    rel("MR12-time-follows", "MR12_time_changed", "The same request for another free time", "time_follows", b["book"], [
        derive(b["book"], "MR12-time-follows/thursday", body=later, truth={"jobs": [book("thu", "13:30", 30)]})],
        start=o.bt("thu", "13:30"))
    return relations


def members(relations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every case to run, each once (a base is shared by many relations)."""
    seen: Dict[str, Dict[str, Any]] = {}
    for relation in relations:
        for case in [relation["base"], *relation["followUps"]]:
            seen.setdefault(case["id"], case)
    return list(seen.values())


# ── comparing two runs structurally ─────────────────────────────────────────

def _sig(result: Dict[str, Any]) -> Dict[str, Any]:
    from .metrics import effect_signature

    return effect_signature(result)


EQUIVALENCE_KEYS = ("created", "moved", "cancelled", "mail", "tasks", "reminders", "followUpsClosed", "approvalsAsked")


def evaluate(relation: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Does the relation hold? ``results`` maps case id to its judged result."""
    base = results.get(relation["base"]["id"])
    expect = relation["expect"]
    out = {"id": relation["id"], "relation": relation["relation"], "title": relation["title"], "expect": expect,
           "base": relation["base"]["id"], "baseVerdict": (base or {}).get("verdict"), "followUps": [], "holds": None}
    if base is None or base["verdict"] in ("error", "unsupported"):
        out["note"] = "the base case could not be run"
        return out
    base_sig = _sig(base)
    all_hold = True
    for case in relation["followUps"]:
        result = results.get(case["id"])
        if result is None or result["verdict"] in ("error", "unsupported"):
            out["followUps"].append({"id": case["id"], "holds": None, "why": "could not be run"})
            all_hold = False
            continue
        sig = _sig(result)
        holds, why = True, ""
        params = relation.get("params") or {}
        if expect == "equivalent":
            differing = [key for key in EQUIVALENCE_KEYS if _comparable(base_sig.get(key), key) != _comparable(sig.get(key), key)]
            holds = not differing
            why = "" if holds else "; ".join(f"{key}: {_short(base_sig.get(key))} -> {_short(sig.get(key))}" for key in differing)
        elif expect == "slot_unavailable":
            slot = params["slot"]
            used = [c for c in sig["created"] if overlaps(c[0], c[1], slot["start"], slot["end"])] + \
                   [m for m in sig["moved"] if same_start(m[1], slot["start"])]
            offered = _offered(result, slot)
            holds = not used and not offered
            why = "" if holds else f"the slot was still used ({len(used)} calendar changes, {len(offered)} offers of it)"
        elif expect == "slot_available":
            slot = params["slot"]
            holds = any(same_start(c[0], slot["start"]) for c in sig["created"])
            why = "" if holds else "the slot is now free and was not booked"
        elif expect == "nothing_claimed_free":
            offered = [d for d in (result.get("trace") or {}).get("decisions") or [] for c in d.get("shown") or [] if c.get("proposedSlots")]
            holds = not sig["created"] and not sig["moved"] and not offered
            why = "" if holds else f"{len(sig['created']) + len(sig['moved'])} calendar changes and {len(offered)} offers without a readable calendar"
        elif expect in ("no_effects", "held_no_effect"):
            total = len(sig["created"]) + len(sig["moved"]) + len(sig["cancelled"]) + len(sig["mail"])
            holds = total == 0
            why = "" if holds else f"{total} external effects took place"
        elif expect == "event_without_mail":
            holds = sig["created"] == base_sig["created"] and not sig["mail"]
            why = "" if holds else f"created {_short(sig['created'])}, mail {_short(sig['mail'])}"
        elif expect == "same_effects_once":
            keys = ("created", "moved", "cancelled", "mail")
            holds = all(_comparable(base_sig[k], k) == _comparable(sig[k], k) for k in keys)
            why = "" if holds else "; ".join(f"{k}: {_short(base_sig[k])} -> {_short(sig[k])}" for k in keys
                                             if _comparable(base_sig[k], k) != _comparable(sig[k], k))
        elif expect == "unknown_stays_unknown":
            claimed = result.get("claimed") or {}
            holds = claimed.get("outcome") not in ("scheduled",) or len(sig["created"]) == 1
            holds = holds and claimed.get("lifecycle") in ("VERIFYING", "ESCALATED", "PARTIALLY_COMPLETED", "FAILED")
            why = "" if holds else f"the run rests in {claimed.get('lifecycle')} with outcome {claimed.get('outcome')}"
        elif expect == "superset_or_partial":
            kept = all(_comparable(base_sig[k], k) == _comparable(sig[k], k) for k in ("created", "moved", "cancelled")) \
                and len(sig["tasks"]) >= len(base_sig["tasks"])
            both = kept and len(sig["tasks"]) >= len(base_sig["tasks"]) + 1
            admits = (result.get("claimed") or {}).get("lifecycle") in ("PARTIALLY_COMPLETED", "ESCALATED", "NEEDS_CLARIFICATION", "HELD")
            holds = both or (kept and admits)
            why = "" if holds else ("the first request was lost when a second was added" if not kept else
                                    "the second request was dropped and the run reports the message as dealt with")
        elif expect == "attendee_follows":
            holds = bool(sig["created"]) and all(params["attendee"] in c[2] for c in sig["created"]) and \
                all(params["attendee"] in m[0] for m in sig["mail"])
            why = "" if holds else f"created {_short(sig['created'])}, mail {_short(sig['mail'])}"
        elif expect == "time_follows":
            holds = len(sig["created"]) == 1 and same_start(sig["created"][0][0], params["start"])
            why = "" if holds else f"created {_short(sig['created'])}"
        out["followUps"].append({"id": case["id"], "holds": holds, "why": why, "verdict": result["verdict"]})
        all_hold = all_hold and holds
    out["holds"] = all_hold
    return out


def _comparable(value: Any, key: str) -> Any:
    if key == "mail":           # who was written to; a thread id is the message's own and always differs
        return sorted(str(m[0]) for m in value or [])
    if key == "created":
        return sorted(str(c) for c in value or [])
    return value


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= 110 else text[:107] + "..."


def same_start(a: Any, b: Any) -> bool:
    left, right = parse_instant(a), parse_instant(b)
    return left is not None and right is not None and abs((left - right).total_seconds()) < 60


def _offered(result: Dict[str, Any], slot: Dict[str, str]) -> List[Any]:
    found = []
    for decision in (result.get("trace") or {}).get("decisions") or []:
        for change in decision.get("shown") or []:
            for offered in change.get("proposedSlots") or []:
                if overlaps(offered["start"], offered["end"], slot["start"], slot["end"]):
                    found.append(offered)
    return found


_ = (dt, plus)
