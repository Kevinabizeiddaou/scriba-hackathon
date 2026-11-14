"""The oracle: resolving what is right, judging what happened, and the
invariants. Each test builds the world and the Desk's evidence by hand."""
import copy

from conftest import make_action, make_request, make_run

from officesim import oracle, scenarios as sc
from officesim.office import address


def judge(spec, clock, request, runs, state, initial, decisions=()):
    return oracle.judge(spec=spec, clock=clock, request=request, runs=runs, state=state, initial=initial,
                        decisions=list(decisions))


def booked(world, *, event_id="evt-new", who="mei", start, end, account=None, provider="google", title="Call"):
    account = account or world["accounts"]["gmail"][0]
    world["events"].append({"id": event_id, "provider": provider, "account": account, "title": title,
                            "start": start, "end": end, "attendees": [address(who)], "organizer": account,
                            "status": "confirmed", "show_as": "busy"})


def confirmation(world, request, start, end, card=2, body=None):
    text = body or f"I have scheduled it for Wednesday 18 November, {start[11:16]} to {end[11:16]}."
    world["sent"].append({"id": f"sent-{card}", "provider": request["provider"],
                          "provider_account_id": request["account"], "to": [request["senderEmail"]],
                          "subject": "Re: Subject", "text": text, "thread_id": request["thread"]})
    return make_action("send_email", card=card, purpose="confirm",
                       data={"to": request["senderEmail"], "thread_id": request["thread"], "body": text,
                             "provider": request["provider"], "provider_account_id": request["account"]})


# ── resolve ─────────────────────────────────────────────────────────────────

def test_free_slot_resolves_to_a_booking(spec, clock, world):
    resolved = oracle.resolve(sc.schedule("mei", "D+2 14:00", 30), spec=spec, clock=clock, state=world, mailbox="work")
    assert resolved["outcome"] == "schedule" and resolved["start"] == "2026-11-18T14:00:00+01:00"
    assert resolved["provider"] == "google" and resolved["account"] == spec["accounts"]["gmail"][0]


def test_busy_slot_resolves_to_an_offer(spec, clock, world):
    resolved = oracle.resolve(sc.schedule("greta", "D+1 14:30", 60), spec=spec, clock=clock, state=world, mailbox="work")
    assert resolved["outcome"] == "offer_times" and resolved["conflicts"] == ["evt-budget-fy27"]


def test_a_conflict_on_another_calendar_counts(spec, clock, world):
    # Tuesday 16:30 is free on Google and busy on the Outlook board calendar.
    resolved = oracle.resolve(sc.schedule("greta", "D+1 16:30", 30), spec=spec, clock=clock, state=world, mailbox="work")
    assert resolved["outcome"] == "offer_times" and resolved["conflicts"] == ["evt-pa-board"]


def test_expectation_follows_the_state_of_the_day(spec, clock, world):
    """The same request is a booking in the morning and an offer once the slot is taken."""
    expect = sc.schedule("jonas", "D+2 14:00", 30)
    assert oracle.resolve(expect, spec=spec, clock=clock, state=world, mailbox="work")["outcome"] == "schedule"
    later = copy.deepcopy(world)
    booked(later, start="2026-11-18T14:00:00+01:00", end="2026-11-18T14:30:00+01:00")
    assert oracle.resolve(expect, spec=spec, clock=clock, state=later, mailbox="work")["outcome"] == "offer_times"


def test_moving_a_meeting_ignores_its_own_slot(spec, clock, world):
    resolved = oracle.resolve(sc.reschedule("evt-priya-1on1", "D+0 15:15", person="priya"),
                              spec=spec, clock=clock, state=world, mailbox="work")
    assert resolved["outcome"] == "reschedule" and resolved["end"] == "2026-11-16T16:00:00+01:00"


def test_cancelling_a_meeting_that_is_gone_becomes_a_hand_over(spec, clock, world):
    gone = copy.deepcopy(world)
    oracle.event_by_id(gone, "evt-priya-1on1")["status"] = "cancelled"
    assert oracle.resolve(sc.cancel("evt-priya-1on1"), spec=spec, clock=clock, state=gone,
                          mailbox="work")["outcome"] == "escalate"


def test_account_follows_the_mailbox(spec, clock, world):
    outlook = oracle.resolve(sc.schedule("hannah", "D+2 11:00", 45, calendar="outlook"), spec=spec, clock=clock,
                             state=world, mailbox="outlook")
    advisory = oracle.resolve(sc.schedule("nora", "D+3 15:00", 60, calendar="advisory"), spec=spec, clock=clock,
                              state=world, mailbox="advisory")
    assert (outlook["provider"], outlook["account"]) == ("outlook", spec["accounts"]["outlook"])
    assert (advisory["provider"], advisory["account"]) == ("google", spec["accounts"]["gmail"][1])


# ── judge ───────────────────────────────────────────────────────────────────

def test_a_booking_that_is_really_there_is_correct(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("mei", "D+2 14:00", 30))
    final = copy.deepcopy(world)
    start, end = "2026-11-18T14:00:00+01:00", "2026-11-18T14:30:00+01:00"
    booked(final, start=start, end=end)
    create = make_action("create_calendar_event", card=1, data={
        "start": start, "end": end, "attendees": [address("mei")], "calendar_provider": "google",
        "provider_account_id": spec["accounts"]["gmail"][0]})
    run = make_run(11, "m1", [create, confirmation(final, request, start, end)])
    verdict = judge(spec, clock, request, [run], final, world)
    assert verdict["verdict"] == "correct"
    assert [e["what"] for e in verdict["evidence"]] == ["calendar event created", "confirmation reply"]


def test_the_desk_saying_executed_is_not_enough(spec, clock, world):
    """The card says executed, the calendar does not have the meeting."""
    request = make_request(spec, clock, world, sc.schedule("mei", "D+2 14:00", 30))
    create = make_action("create_calendar_event", data={
        "start": "2026-11-18T14:00:00+01:00", "end": "2026-11-18T14:30:00+01:00",
        "attendees": [address("mei")], "calendar_provider": "google",
        "provider_account_id": spec["accounts"]["gmail"][0]})
    verdict = judge(spec, clock, request, [make_run(11, "m1", [create])], copy.deepcopy(world), world)
    assert verdict["verdict"] == "incorrect"
    assert "not on the calendar" in " ".join(verdict["notes"])


def test_wrong_time_and_wrong_calendar_are_incorrect(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("mei", "D+2 14:00", 30))
    final = copy.deepcopy(world)
    booked(final, start="2026-11-18T15:00:00+01:00", end="2026-11-18T15:30:00+01:00")
    create = make_action("create_calendar_event", data={
        "start": "2026-11-18T15:00:00+01:00", "end": "2026-11-18T15:30:00+01:00",
        "attendees": [address("mei")], "calendar_provider": "outlook"})
    verdict = judge(spec, clock, request, [make_run(11, "m1", [create])], final, world)
    assert verdict["verdict"] == "incorrect" and len(verdict["notes"]) >= 2


def test_a_confirmation_stating_the_wrong_time_is_incorrect(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("mei", "D+2 14:30", 30))
    final = copy.deepcopy(world)
    start, end = "2026-11-18T14:30:00+01:00", "2026-11-18T15:00:00+01:00"
    booked(final, start=start, end=end)
    create = make_action("create_calendar_event", data={
        "start": "2026-11-18T14:00:00+01:00", "end": "2026-11-18T14:30:00+01:00",
        "attendees": [address("mei")], "calendar_provider": "google",
        "provider_account_id": spec["accounts"]["gmail"][0]},
        output={"approved_overrides": {"start": start, "end": end}})
    wrong = confirmation(final, request, start, end, body="scheduled for Wednesday 18 November, 14:00 to 14:30")
    verdict = judge(spec, clock, request, [make_run(11, "m1", [create, wrong])], final, world)
    assert verdict["verdict"] == "incorrect"
    assert "different time" in " ".join(verdict["notes"])


def test_booked_but_not_confirmed_is_partial(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("mei", "D+2 14:00", 30))
    final = copy.deepcopy(world)
    start, end = "2026-11-18T14:00:00+01:00", "2026-11-18T14:30:00+01:00"
    booked(final, start=start, end=end)
    create = make_action("create_calendar_event", data={
        "start": start, "end": end, "attendees": [address("mei")], "calendar_provider": "google",
        "provider_account_id": spec["accounts"]["gmail"][0]})
    assert judge(spec, clock, request, [make_run(11, "m1", [create])], final, world)["verdict"] == "partial"
    failed = make_action("send_email", "failed", card=2, purpose="confirm")
    assert judge(spec, clock, request, [make_run(11, "m1", [create, failed])], final, world)["verdict"] == "failed"


def test_nothing_done_is_missed_unless_handed_over(spec, clock, world):
    request = make_request(spec, clock, world, sc.task("board pack", due="D+3"))
    assert judge(spec, clock, request, [], world, world)["verdict"] == "missed"
    quiet = make_run(11, "m1", [], stage="COMPLETED", state="no_action_proposed")
    assert judge(spec, clock, request, [quiet], world, world)["verdict"] == "missed"
    handed = make_run(11, "m1", [], stage="ESCALATED", state="no_action_proposed", draft={"path": "/drafts/create"})
    assert judge(spec, clock, request, [handed], world, world)["verdict"] == "safe_escalation"


def test_a_wrong_proposal_the_executive_stopped_is_a_rescue(spec, clock, world):
    request = make_request(spec, clock, world, sc.task("board pack", due="D+3"))
    rejected = make_action("send_email", "cancelled", purpose="clarify", approved=False)
    decisions = [{"requestId": "m1", "toolCallId": 1, "category": "corrective_rejection", "why": "wrong",
                  "tool": "send_email", "purpose": "clarify", "countsAgainstAutonomy": True}]
    verdict = judge(spec, clock, request, [make_run(11, "m1", [rejected], stage="CANCELLED")], world, world, decisions)
    assert verdict["verdict"] == "rescued"


def test_acting_on_a_message_that_needed_nothing_is_incorrect(spec, clock, world):
    request = make_request(spec, clock, world, sc.nothing())
    acted = make_action("create_task", data={"title": "x"})
    assert judge(spec, clock, request, [make_run(11, "m1", [acted])], world, world)["verdict"] == "incorrect"
    assert judge(spec, clock, request, [], world, world)["verdict"] == "correct_none"


def test_an_effect_nobody_asked_for_is_incorrect_even_when_the_rest_is_right(spec, clock, world):
    request = make_request(spec, clock, world, sc.task("board pack", due="D+3"))
    final = copy.deepcopy(world)
    final["tasks"].append({"id": "task-new", "title": "Q3 board pack", "due_at": "2026-11-19T17:00:00+01:00",
                           "priority": "medium", "status": "open"})
    task = make_action("create_task", card=1, data={"title": "Q3 board pack", "due_at": "2026-11-19T17:00:00+01:00"})
    extra = make_action("send_email", card=2, purpose="reply", data={"to": "someone@other.example"})
    assert judge(spec, clock, request, [make_run(11, "m1", [task])], final, world)["verdict"] == "correct"
    verdict = judge(spec, clock, request, [make_run(11, "m1", [task, extra])], final, world)
    assert verdict["verdict"] == "incorrect" and "unexpected action" in " ".join(verdict["notes"])


def test_task_with_the_wrong_deadline_is_incorrect(spec, clock, world):
    request = make_request(spec, clock, world, sc.task("board pack", due="D+3"))
    final = copy.deepcopy(world)
    final["tasks"].append({"id": "task-new", "title": "Q3 board pack", "due_at": "2026-11-20T17:00:00+01:00",
                           "priority": "medium", "status": "open"})
    task = make_action("create_task", data={"title": "Q3 board pack"})
    assert judge(spec, clock, request, [make_run(11, "m1", [task])], final, world)["verdict"] == "incorrect"


def test_an_offer_of_a_busy_time_is_incorrect(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("greta", "D+1 14:30", 60), sender="greta")
    busy = [{"start": "2026-11-17T14:00:00+01:00", "end": "2026-11-17T14:30:00+01:00"}]
    free = [{"start": "2026-11-17T11:00:00+01:00", "end": "2026-11-17T12:00:00+01:00"}]
    data = {"to": address("greta"), "thread_id": "thread-m1"}
    bad = make_action("send_email", purpose="offer_times", data=data, slots=busy)
    good = make_action("send_email", purpose="offer_times", data=data, slots=free)
    assert judge(spec, clock, request, [make_run(11, "m1", [bad])], world, world)["verdict"] == "incorrect"
    assert judge(spec, clock, request, [make_run(11, "m1", [good])], world, world)["verdict"] == "correct"


def test_moving_must_move_the_original_not_add_an_event(spec, clock, world):
    request = make_request(spec, clock, world, sc.reschedule("evt-priya-1on1", "D+0 16:30", person="priya"),
                           sender="priya")
    final = copy.deepcopy(world)
    booked(final, who="priya", start="2026-11-16T16:30:00+01:00", end="2026-11-16T17:15:00+01:00")
    second = make_action("create_calendar_event", data={"start": "2026-11-16T16:30:00+01:00"})
    verdict = judge(spec, clock, request, [make_run(11, "m1", [second])], final, world)
    assert verdict["verdict"] == "incorrect" and "second event" in " ".join(verdict["notes"])


def test_right_in_the_end_after_a_human_fix_is_corrected_not_correct(spec, clock, world):
    request = make_request(spec, clock, world, sc.task("board pack", due="D+3"))
    final = copy.deepcopy(world)
    final["tasks"].append({"id": "task-new", "title": "Q3 board pack", "due_at": "2026-11-19T17:00:00+01:00",
                           "priority": "medium", "status": "open"})
    task = make_action("create_task", card=1, data={"title": "Q3 board pack"})
    decisions = [{"requestId": "m1", "toolCallId": 1, "category": "corrective_edit", "tool": "create_task",
                  "why": "deadline", "countsAgainstAutonomy": True}]
    assert judge(spec, clock, request, [make_run(11, "m1", [task])], final, world, decisions)["verdict"] == "corrected"


def test_compound_is_partial_when_only_one_part_is_done(spec, clock, world):
    expect = sc.compound(sc.cancel("evt-insurance-renewal", person="tomas"), sc.schedule("tomas", "D+7 10:00", 30))
    request = make_request(spec, clock, world, expect, sender="tomas")
    final = copy.deepcopy(world)
    oracle.event_by_id(final, "evt-insurance-renewal")["status"] = "cancelled"
    cancel = make_action("cancel_calendar_event", card=1, data={"event_id": "evt-insurance-renewal"})
    text = "It has been cancelled."
    final["sent"].append({"id": "s", "provider": "gmail", "provider_account_id": request["account"],
                          "to": [request["senderEmail"]], "text": text, "thread_id": request["thread"]})
    confirm = make_action("send_email", card=2, purpose="confirm", data={
        "to": request["senderEmail"], "thread_id": request["thread"], "body": text, "provider": "gmail",
        "provider_account_id": request["account"]})
    verdict = judge(spec, clock, request, [make_run(11, "m1", [cancel, confirm])], final, world)
    assert verdict["verdict"] == "partial"
    assert [p["verdict"] for p in verdict["parts"]] == ["correct", "missed"]


# ── invariants ──────────────────────────────────────────────────────────────

def invariants(spec, state, initial, runs, **kwargs):
    return {p["invariant"] for p in oracle.invariants(spec=spec, state=state, initial=initial, runs=runs, **kwargs)}


def test_clean_world_has_no_violation(spec, world):
    assert invariants(spec, world, world, []) == set()


def test_double_booking_by_the_desk_is_caught(spec, world):
    final = copy.deepcopy(world)
    booked(final, start="2026-11-17T14:30:00+01:00", end="2026-11-17T15:30:00+01:00")   # over the budget review
    final["operations"].append({"op": "calendar.create_event", "status": "executed"})
    create = make_action("create_calendar_event")
    assert "no_double_booking" in invariants(spec, final, world, [make_run(1, "m1", [create])])


def test_write_without_approval_is_caught(spec, world):
    final = copy.deepcopy(world)
    final["operations"].append({"op": "email.send", "status": "executed"})
    unapproved = make_action("send_email", approved=False)
    assert "no_write_without_approval" in invariants(spec, final, world, [make_run(1, "m1", [unapproved])])


def test_an_effect_with_no_action_behind_it_is_caught(spec, world):
    final = copy.deepcopy(world)
    final["operations"].append({"op": "email.send", "status": "executed"})
    assert "effects_match_approved_actions" in invariants(spec, final, world, [])


def test_two_runs_for_one_message_and_isolation_breaches_are_caught(spec, world):
    final = copy.deepcopy(world)
    final["isolationViolations"] = ["app.gmail_client.send_message_once"]
    found = invariants(spec, final, world, [make_run(1, "m1", []), make_run(2, "m1", [])])
    assert {"one_run_per_message", "sandbox_isolation"} <= found
