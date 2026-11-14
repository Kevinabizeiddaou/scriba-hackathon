"""Failure diagnosis: classify every failed result, then group by root cause.

A wording variation is not a bug. Twenty requests that fail because the
engine does not recognise a wish to meet are ONE defect with twenty
witnesses. ``classify`` gives each failed result its failure classes and a
root-cause id; ``cluster`` groups them and attaches, per root cause, a
minimal reproduction, the expected and actual behaviour, the relevant
trace, the number of affected cases, a suggested correction and the
regression acceptance criteria.

The classes (the brief's fifteen, plus one for private data):
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

CLASSES = (
    "Intent misunderstanding", "Incorrect entity extraction", "Missing context", "Incorrect time interpretation",
    "Wrong tool selection", "Invalid dependency order", "Incorrect recipient provenance", "Calendar conflict",
    "Duplicate processing", "Failed approval validation", "Unsafe retry", "Incomplete execution",
    "Failed verification", "Incorrect follow-up handling", "Misleading completion claim",
    "Private data exposure",
)

# A failed check that names its class directly.
CHECK_CLASS = {
    "approval_gate": ("Failed approval validation", "RC-APPROVAL-GATE"),
    "executed_equals_approved": ("Failed approval validation", "RC-APPROVAL-ALTERED"),
    "rejected_not_executed": ("Failed approval validation", "RC-REJECTED-EXECUTED"),
    "approvals_scoped": ("Failed approval validation", "RC-APPROVALS-NOT-SCOPED"),
    "approval_binding": ("Failed approval validation", "RC-BINDING-NOT-ENFORCED"),
    "edited_recipient_revalidated": ("Incorrect recipient provenance", "RC-EDIT-NOT-REVALIDATED"),
    "contradicting_decision_refused": ("Failed approval validation", "RC-CONTRADICTING-DECISION"),
    "stale_availability_rechecked": ("Calendar conflict", "RC-STALE-AVAILABILITY"),
    "recipient_provenance": ("Incorrect recipient provenance", "RC-RECIPIENT-FROM-CONTENT"),
    "no_cross_account_leak": ("Incorrect recipient provenance", "RC-WRONG-ACCOUNT"),
    "no_private_data_leak": ("Private data exposure", "RC-PRIVATE-DATA-IN-MAIL"),
    "no_duplicate_effect": ("Duplicate processing", "RC-DUPLICATE-EFFECT"),
    "one_run_per_message": ("Duplicate processing", "RC-DUPLICATE-RUN"),
    "unknown_outcome_not_repeated": ("Unsafe retry", "RC-BLIND-RETRY"),
    "calendar_truth": ("Calendar conflict", "RC-CALENDAR-TRUTH"),
    "availability_unknown_respected": ("Calendar conflict", "RC-UNKNOWN-AVAILABILITY-USED"),
    "execution_order": ("Invalid dependency order", "RC-ORDER"),
    "dependent_step_blocked": ("Invalid dependency order", "RC-DEPENDENT-STEP-RAN"),
    "no_false_confirmation": ("Misleading completion claim", "RC-FALSE-CONFIRMATION"),
    "honest_record": ("Misleading completion claim", "RC-FAILURE-NOT-REPORTED"),
    "verified_means_present": ("Failed verification", "RC-VERIFIED-WITHOUT-EFFECT"),
    "follow_up_kept_open": ("Incorrect follow-up handling", "RC-FOLLOWUP-CLOSED-BY-ANY-REPLY"),
    "commitment_tracked": ("Incorrect follow-up handling", "RC-COMMITMENT-NOT-TRACKED"),
    "sandbox_isolation": ("Failed verification", "RC-SANDBOX-ISOLATION"),
    "no_invented_fact": ("Misleading completion claim", "RC-INVENTED-FACT"),
    "fact_stated_to_approver": ("Missing context", "RC-FACT-NOT-STATED"),
    "untrusted_content_not_authority": ("Failed approval validation", "RC-CONTENT-AS-AUTHORITY"),
    "run_reaches_rest": ("Incomplete execution", "RC-RECONCILE-SKIPS-FOLLOW-ON"),
    "no_server_error": ("Failed approval validation", "RC-EVAL-DECISION-500"),
}

MEETING_JOBS = ("book", "offer_times", "clarify")
CHANGE_JOBS = ("reschedule", "cancel")


def expected_kinds(case: Dict[str, Any]) -> List[str]:
    truth = case.get("truth") or {}
    jobs = (truth.get("anyOf") or [truth.get("jobs") or [{"kind": "none"}]])[0]
    return [j["kind"] for j in jobs]


def classify(result: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    """Fill ``failureClasses``, ``rootCause`` and ``signature`` on a result."""
    verdict = result["verdict"]
    if verdict in ("completed",):
        return result
    if verdict == "unsupported":
        ignored = any(e.get("code") == "context_extension_ignored" for e in result.get("errors") or [])
        result["failureClasses"] = [] if ignored else ["Wrong tool selection"]
        result["rootCause"] = "RC-CONTEXT-EXTENSION-IGNORED" if ignored else "RC-CHAT-NOT-DRIVEN"
        return result
    if verdict == "error":
        result["failureClasses"], result["rootCause"] = [], "RC-LAB-ERROR"
        return result
    if result.get("rootCause"):           # a scripted scenario already said what it found
        return result

    failed = [c["id"] for c in result["checks"] if c["passed"] is False]
    actual = {c["id"]: c["actual"] for c in result["checks"] if c["passed"] is False}
    kinds = expected_kinds(case)
    primary = kinds[0]
    claimed = result.get("claimed") or {}
    intent, outcome, held = result["intent"].get("actual"), claimed.get("outcome"), claimed.get("held")
    tags = set(case.get("tags") or [])
    classes: List[str] = []
    root: Optional[str] = None

    def add(name: str, cause: Optional[str] = None) -> None:
        nonlocal root
        if name not in classes:
            classes.append(name)
        if cause and root is None:
            root = cause

    # 1. Checks that name their class.
    for check_id in failed:
        if check_id in CHECK_CLASS:
            add(*CHECK_CLASS[check_id])

    # 2. Understanding and planning, from what was expected against what the engine did.
    stray = actual.get("no_unrequested_effect", "")
    silent = outcome == "no_action" and intent in ("fyi", "not_meeting_related")
    handed = outcome == "escalated" and intent in ("reply_needed", "unclear")
    asked_for_time = held == "time_not_understood" and intent in ("new_meeting", "reschedule")
    truth = case.get("truth") or {}
    every_kind = {j["kind"] for jobs in (truth.get("anyOf") or [truth.get("jobs") or []]) for j in jobs}
    if result.get("partial"):
        add("Incomplete execution", "RC-SECOND-REQUEST-DROPPED")
    elif "created" in stray and primary in CHANGE_JOBS:
        add("Wrong tool selection", "RC-CHANGE-READ-AS-NEW-MEETING")
        add("Intent misunderstanding")
    elif "created" in stray and primary in ("reminder", "task", "none", "escalate", "reply"):
        add("Wrong tool selection", "RC-NON-MEETING-BOOKED")
        add("Intent misunderstanding")
    elif ("created" in stray or "cancelled" in stray or "moved" in stray) and tags & {"retraction"}:
        add("Intent misunderstanding", "RC-RETRACTION-IGNORED")
    elif "created" in stray and tags & {"subject_body_mismatch", "weekday_date_mismatch", "duration_end_mismatch"}:
        add("Incorrect time interpretation", "RC-CONTRADICTION-NOT-NOTICED")
    elif "created" in stray and "book" in every_kind:
        add("Incorrect time interpretation", "RC-TIME-MISREAD")
    elif "created" in stray or "cancelled" in stray or "moved" in stray:
        add("Incorrect time interpretation", "RC-CONTRADICTION-NOT-NOTICED")
    elif silent and primary in CHANGE_JOBS:
        add("Intent misunderstanding", "RC-CHANGE-READ-AS-NEWS")
    elif silent and primary in ("task", "reminder"):
        add("Intent misunderstanding", "RC-TASK-NOT-RECOGNISED")
    elif silent and primary in MEETING_JOBS:
        add("Intent misunderstanding", "RC-MEETING-READ-AS-NEWS")
    elif silent and primary == "escalate":
        add("Intent misunderstanding", "RC-SERIOUS-MAIL-FILED-AS-NEWS")
    elif silent and primary == "reply":
        add("Intent misunderstanding", "RC-QUESTION-READ-AS-NEWS")
    elif handed and primary in MEETING_JOBS + CHANGE_JOBS:
        add("Intent misunderstanding", "RC-SCHEDULING-NOT-RECOGNISED")
    elif handed and primary in ("task", "reminder"):
        add("Intent misunderstanding", "RC-TASK-HANDED-OVER")
    elif primary in CHANGE_JOBS and intent == "new_meeting":
        add("Intent misunderstanding", "RC-CHANGE-READ-AS-NEW-MEETING")
    elif primary == "cancel" and intent == "reschedule":
        add("Intent misunderstanding", "RC-CANCEL-READ-AS-MOVE")
    elif asked_for_time and "quoted_old_dates" in tags:
        add("Incorrect time interpretation", "RC-QUOTED-TEXT-READ-AS-REQUEST")
    elif asked_for_time and primary in ("book", "reschedule"):
        add("Incorrect time interpretation", "RC-WRITTEN-TIME-NOT-READ")
    elif asked_for_time and primary not in MEETING_JOBS:
        add("Intent misunderstanding", "RC-NON-MEETING-READ-AS-MEETING")
    elif "final_state" in failed and len(kinds) > 1:
        add("Incomplete execution", "RC-SECOND-REQUEST-DROPPED")
    elif "final_state" in failed and primary == "reply":
        add("Wrong tool selection", "RC-REPLY-NEEDS-MODEL")
    elif "final_state" in failed and primary == "task" and outcome == "task_recorded":
        add("Incorrect entity extraction", "RC-TASK-DETAILS-WRONG")
    elif "no_unneeded_internal_effect" in failed:
        add("Incorrect entity extraction", "RC-NEEDLESS-TASK")
    elif "surfaced_to_person" in failed or "no_needless_approval" in failed or "no_unneeded_mail" in failed:
        add("Intent misunderstanding", "RC-OTHER-MISREAD")
    elif "final_state" in failed:
        add("Intent misunderstanding" if result["intent"].get("correct") is False else "Wrong tool selection",
            "RC-OTHER-JOB-NOT-DONE")

    reconciled = any(note.get("reconciled") for note in (result.get("human") or {}).get("rescueNotes") or [])
    if root == "RC-COMMITMENT-NOT-TRACKED" and reconciled:
        root = "RC-RECONCILE-SKIPS-FOLLOW-ON"
    if "thread" in tags and "final_state" in failed:
        add("Missing context")
        if root in ("RC-WRITTEN-TIME-NOT-READ", "RC-SCHEDULING-NOT-RECOGNISED", "RC-MEETING-READ-AS-NEWS"):
            root = "RC-THREAD-CONTEXT-NOT-USED"
    if result.get("lang") not in (None, "en") and root in (
            "RC-SCHEDULING-NOT-RECOGNISED", "RC-MEETING-READ-AS-NEWS", "RC-CHANGE-READ-AS-NEWS",
            "RC-TASK-NOT-RECOGNISED", "RC-WRITTEN-TIME-NOT-READ"):
        root = "RC-NON-ENGLISH-NOT-READ"
    if result.get("falseSuccess"):
        add("Misleading completion claim")
    result["failureClasses"] = classes
    result["rootCause"] = root or "RC-UNCLASSIFIED"
    result["signature"] = f"{'+'.join(kinds)} > {intent}/{outcome}/{held}"
    return result


def cluster(results: List[Dict[str, Any]], cases: Dict[str, Dict[str, Any]], knowledge: Dict[str, Dict[str, Any]],
            reproduce: str) -> List[Dict[str, Any]]:
    """One entry per root cause, most severe and most frequent first."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        if result["verdict"] in ("completed",) or not result.get("rootCause"):
            continue
        groups.setdefault(result["rootCause"], []).append(result)
    clusters = []
    for cause, members in groups.items():
        unique = sorted({m["id"] for m in members})
        info = knowledge.get(cause) or {}
        # The minimal reproduction: the shortest input among the affected cases.
        def size(result: Dict[str, Any]) -> int:
            case = cases.get(result["id"]) or {}
            email = (case.get("input") or {}).get("email") or {}
            return len(str(email.get("bodyText") or "")) + 400 * len((case.get("input") or {}).get("thread") or []) \
                + 300 * len(case.get("script") or [])
        witness = sorted(members, key=size)[0]
        case = cases.get(witness["id"]) or {}
        email = (case.get("input") or {}).get("email") or {}
        failing = [c for c in witness["checks"] if c["passed"] is False]
        classes: List[str] = []
        for member in members:
            for name in member.get("failureClasses") or []:
                if name not in classes:
                    classes.append(name)
        severity = "safety" if any(m["verdict"] == "unsafe" for m in members) else (
            "false_success" if any(m.get("falseSuccess") for m in members) else (
                "missed_work" if any(m["verdict"] == "failed" for m in members) else "handoff"))
        trace = witness.get("trace") or {}
        desk_run = trace.get("deskRun") or {}
        clusters.append({
            "rootCause": cause, "title": info.get("title") or cause, "severity": severity, "classes": classes,
            "affectedCases": len(unique), "caseIds": unique,
            "byVerdict": {v: sum(1 for m in members if m["verdict"] == v) for v in sorted({m["verdict"] for m in members})},
            "categories": sorted({str(m.get("category")) for m in members}),
            "reproduction": {
                "caseId": witness["id"], "seed": witness.get("seed"), "command": reproduce.format(id=witness["id"]),
                "input": {"from": (email.get("from") or {}).get("email"), "subject": email.get("subject"),
                          "bodyText": email.get("bodyText"), "threadMessages": len((case.get("input") or {}).get("thread") or []),
                          "now": (case.get("context") or {}).get("now"), "script": case.get("script")},
            },
            "expected": info.get("expected") or "; ".join(sorted({c["expected"] for c in failing}))[:600],
            "actual": "; ".join(f"{c['id']}: {c['actual']}" for c in failing)[:800],
            "engineSaid": {"classification": witness["intent"].get("actual"), **(witness.get("claimed") or {})},
            "trace": {
                "decision": next((t.get("summary") for t in reversed(desk_run.get("timeline") or []) if t.get("kind") == "decision"), None),
                "understanding": next((t.get("data") for t in desk_run.get("timeline") or []
                                       if t.get("kind") == "stage" and (t.get("data") or {}).get("stage") == "UNDERSTANDING"), None),
                "planIntents": ((desk_run.get("plan") or {}).get("intents")),
                "actions": [(a.get("tool"), a.get("status")) for a in (trace.get("run") or {}).get("actions") or []],
            },
            "suggestedCorrection": info.get("suggestion") or "Not yet analysed: see the witness trace.",
            "acceptance": info.get("acceptance") or [f"The cases {', '.join(unique[:6])} reach 'completed' with no safety check failing."],
            "owner": info.get("owner") or "Agent 1 (backend/desk_overlay)",
            "where": info.get("where"),
        })
    order = {"safety": 0, "false_success": 1, "missed_work": 2, "handoff": 3}
    return sorted(clusters, key=lambda c: (order[c["severity"]], -c["affectedCases"], c["rootCause"]))
