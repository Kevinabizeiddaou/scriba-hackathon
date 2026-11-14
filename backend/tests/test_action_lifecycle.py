"""The explicit lifecycle of one action, what a retry does first, the action
as it was approved, and the rule that nothing follows an unverified step."""
from desk_overlay import lifecycle, plans
from desk_overlay.workflow import approved_edits, effective_input


def state(status, **kw):
    return lifecycle.action_state(status, **kw)


def test_every_card_status_maps_to_one_named_state():
    assert state("awaiting_approval") == "PROPOSED"
    assert state("needs_info") == "HELD"
    assert state("awaiting_approval", held=True) == "HELD"
    assert state("approved") == "APPROVED"
    assert state("executing") == "EXECUTING"
    assert state("partially_executed") == "PARTIALLY_EXECUTED"
    assert state("cancelled") == "REJECTED"
    assert state("failed") == "FAILED"
    assert state("unsupported") == "FAILED"
    for name in ("PROPOSED", "HELD", "APPROVED", "EXECUTING", "PARTIALLY_EXECUTED", "REJECTED", "FAILED"):
        assert name in lifecycle.ACTION_STATES


def test_executed_is_not_verified_without_evidence():
    assert state("executed") == "EXECUTED_UNVERIFIED"
    assert state("executed", verification={"verified": False, "reason": "start_differs"}) == "VERIFICATION_FAILED"
    assert state("executed", verified=True, verification={"verified": True}) == "VERIFIED"
    # The flag alone never upgrades another status.
    assert state("failed", verified=True) == "FAILED"
    assert state("awaiting_approval", verified=True) == "PROPOSED"


def test_a_failure_says_which_kind_it_is():
    assert state("failed", outcome_unknown=True) == "OUTCOME_UNKNOWN"
    assert state("failed", error_code="interrupted") == "INTERRUPTED"
    assert state("failed", error_code="provider_error") == "FAILED"
    # Unknown wins: an interrupted action whose outcome is not known is not "nothing happened".
    assert state("failed", outcome_unknown=True, error_code="interrupted") == "OUTCOME_UNKNOWN"


def test_only_a_verified_or_rejected_action_is_final():
    assert lifecycle.ACTION_FINAL == ("VERIFIED", "REJECTED")
    assert "EXECUTED_UNVERIFIED" not in lifecycle.ACTION_FINAL


def test_a_retry_says_what_it_does_first():
    assert lifecycle.retry_of("FAILED", simulated=True, attempts=1) == {"mode": "rerun", "attempts": 1, "sameEffect": True}
    assert lifecycle.retry_of("INTERRUPTED", simulated=True, attempts=1)["mode"] == "rerun"
    assert lifecycle.retry_of("OUTCOME_UNKNOWN", simulated=True, attempts=1)["mode"] == "readback_first"
    # On a real provider nothing can be read back: the person checks first.
    assert lifecycle.retry_of("OUTCOME_UNKNOWN", simulated=False, attempts=2) == {
        "mode": "confirm_first", "attempts": 2, "sameEffect": True}
    for name in ("PROPOSED", "HELD", "APPROVED", "EXECUTING", "VERIFIED", "EXECUTED_UNVERIFIED",
                 "VERIFICATION_FAILED", "PARTIALLY_EXECUTED", "REJECTED"):
        assert lifecycle.retry_of(name, simulated=True, attempts=1) is None, name


# ── the action as approved ──────────────────────────────────────────────────

CARD = {"input": {"title": "Intro call", "start": "2026-03-05T10:00:00+00:00", "end": "2026-03-05T10:30:00+00:00",
                  "attendees": ["sofia@client.example"]},
        "output": {"approved_overrides": {"start": "2026-03-05T10:30:00+00:00", "end": "2026-03-05T11:00:00+00:00",
                                          "desk_confirmed_recipients": True, "desk_availability_override": True,
                                          "title": ""}}}


def test_an_edit_at_approval_is_part_of_the_action_and_control_flags_are_not():
    assert approved_edits(CARD) == {"start": "2026-03-05T10:30:00+00:00", "end": "2026-03-05T11:00:00+00:00"}
    effective = effective_input(CARD)
    assert effective["start"] == "2026-03-05T10:30:00+00:00" and effective["end"] == "2026-03-05T11:00:00+00:00"
    assert effective["title"] == "Intro call"                      # an empty override changes nothing
    assert "desk_confirmed_recipients" not in effective
    assert CARD["input"]["start"] == "2026-03-05T10:00:00+00:00"   # the proposal is left as proposed


def test_an_unedited_card_is_its_input_and_a_stored_row_reads_the_same():
    assert effective_input({"input": {"title": "A"}, "output": {}}) == {"title": "A"}
    assert effective_input({"input": {"title": "A"}}) == {"title": "A"}
    assert effective_input({}) == {} and effective_input(None) == {}
    row = {"input_payload": dict(CARD["input"]), "output_payload": dict(CARD["output"])}
    assert effective_input(row)["start"] == "2026-03-05T10:30:00+00:00"


def test_an_edited_move_states_its_new_time_where_a_move_keeps_it():
    card = {"input": {"event_id": "e1", "planned_change": {"start": "2026-03-05T10:00:00+00:00",
                                                           "end": "2026-03-05T10:30:00+00:00"}},
            "output": {"approved_overrides": {"start": "2026-03-05T14:00:00+00:00"}}}
    assert effective_input(card)["planned_change"] == {"start": "2026-03-05T14:00:00+00:00",
                                                       "end": "2026-03-05T10:30:00+00:00"}


# ── nothing follows an unverified step ──────────────────────────────────────

PLAN = {"steps": [
    {"id": "s1", "tool": "create_calendar_event", "purpose": "book", "dependsOn": [], "deferred": False},
    {"id": "s2", "tool": "send_email", "purpose": "confirm", "dependsOn": ["s1"], "deferred": True}]}


def states(card, unverified=()):
    return [s["state"] for s in plans.step_states(PLAN, {"s1": card}, unverified)]


def test_a_dependent_step_is_ready_only_when_its_dependency_is_not_known_to_be_unverified():
    assert states({"id": 7, "status": "executed"}) == ["executed", "ready"]
    assert states({"id": 7, "status": "executed"}, {7}) == ["executed", "blocked"]
    assert states({"id": 7, "status": "partially_executed"}, {7}) == ["partially_executed", "blocked"]
    # Another card's failed verification does not block this one.
    assert states({"id": 7, "status": "executed"}, {8}) == ["executed", "ready"]
    assert states({"id": 7, "status": "awaiting_approval"}, {7}) == ["awaiting_approval", "waiting"]
    assert states({"id": 7, "status": "failed"}) == ["failed", "blocked"]


def test_a_later_verification_lifts_the_block():
    from desk_overlay.workflow import _unverified

    failed = {"kind": "verification", "data": {"toolCallId": 7, "verified": False}}
    passed = {"kind": "verification", "data": {"toolCallId": 7, "verified": True}}
    assert _unverified([failed]) == {7}
    assert _unverified([failed, passed]) == set()          # the latest evidence decides
    assert _unverified([passed, failed]) == {7}
    assert _unverified([{"kind": "execution", "data": {"toolCallId": 7, "verified": False}}]) == set()
