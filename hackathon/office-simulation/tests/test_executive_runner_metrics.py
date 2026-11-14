"""The simulated executive, the runner against a stand-in backend, the
measurement and the report."""
import copy
import json

import pytest
from conftest import make_action, make_request, make_run

from officesim import metrics, oracle, report, scenarios as sc
from officesim.adapter import DeskApiError, DeskClient, SandboxServer
from officesim.executive import AGAINST_AUTONOMY, Executive, review
from officesim.fakes import FakeDesk
from officesim.office import address
from officesim.runner import Simulation, strip_volatile

START, END = "2026-11-18T14:00:00+01:00", "2026-11-18T14:30:00+01:00"


def event_card(spec, start=START, end=END, attendees=("mei",), provider="google", account=None, output=None):
    return make_action("create_calendar_event", "awaiting_approval", data={
        "start": start, "end": end, "attendees": [address(a) for a in attendees],
        "calendar_provider": provider,
        "provider_account_id": account or spec["accounts"]["gmail"][0]}, output=output)


def decide(mode, action, request, spec, clock, world, run=None):
    return Executive(mode).decide(action, request=request, run=run or make_run(1, "m1", [action]),
                                  state=world, spec=spec, clock=clock)


# ── the executive ───────────────────────────────────────────────────────────

def test_right_proposal_is_a_mandatory_approval(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("mei", "D+2 14:00", 30))
    decision = decide("attentive", event_card(spec), request, spec, clock, world)
    assert (decision["decision"], decision["category"], decision["countsAgainstAutonomy"]) == (
        "approve", "approval", False)


def test_wrong_time_is_rejected_and_counts_against_the_agent(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("mei", "D+2 14:00", 30))
    wrong = event_card(spec, start="2026-11-27T14:00:00+01:00", end="2026-11-27T14:30:00+01:00")
    decision = decide("attentive", wrong, request, spec, clock, world)
    assert decision["decision"] == "reject" and decision["category"] == "corrective_rejection"
    assert decision["countsAgainstAutonomy"] and decision["category"] in AGAINST_AUTONOMY


def test_wrong_calendar_is_rejected(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("hannah", "D+2 11:00", 45, calendar="outlook"),
                           sender="hannah", to="outlook")
    on_google = event_card(spec, start="2026-11-18T11:00:00+01:00", end="2026-11-18T11:45:00+01:00",
                           attendees=("hannah",))
    assert decide("attentive", on_google, request, spec, clock, world)["category"] == "corrective_rejection"


def test_a_missing_attendee_is_a_correction_through_the_approve_request(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("jonas", "D+3 16:00", 45, attendees=["jonas", "mei"]),
                           sender="jonas")
    card = event_card(spec, start="2026-11-19T16:00:00+01:00", end="2026-11-19T16:45:00+01:00", attendees=("jonas",))
    decision = decide("attentive", card, request, spec, clock, world)
    assert decision["category"] == "corrective_edit" and decision["countsAgainstAutonomy"]
    assert decision["overrides"]["desk_confirmed_recipients"] == [address("mei")]


def test_scripted_preference_is_not_an_agent_failure(spec, clock, world):
    request = make_request(spec, clock, world, sc.declined("create_calendar_event"))
    request["human"] = {"decision": "reject", "tool": "create_calendar_event", "why": "No cold intros."}
    decision = decide("attentive", event_card(spec), request, spec, clock, world)
    assert decision["category"] == "preference_rejection" and not decision["countsAgainstAutonomy"]
    request["human"] = {"decision": "edit", "tool": "create_calendar_event", "why": "Later.",
                        "overrides": {"start": "D+2 14:30", "end": "D+2 15:00"}}
    edit = decide("attentive", event_card(spec), request, spec, clock, world)
    assert edit["category"] == "preference_edit" and edit["overrides"]["start"] == "2026-11-18T14:30:00+01:00"


def test_trusting_executive_approves_unread_and_says_so(spec, clock, world):
    request = make_request(spec, clock, world, sc.nothing())
    decision = decide("trusting", event_card(spec), request, spec, clock, world)
    assert decision["decision"] == "approve" and decision["category"] == "unreviewed_approval"


def test_confirmation_must_state_the_time_that_is_on_the_calendar(spec, clock, world):
    request = make_request(spec, clock, world, sc.schedule("mei", "D+2 14:30", 30))
    state = copy.deepcopy(world)
    state["events"].append({"id": "evt-new", "provider": "google", "account": spec["accounts"]["gmail"][0],
                            "title": "Call", "start": "2026-11-18T14:30:00+01:00", "end": "2026-11-18T15:00:00+01:00",
                            "attendees": [address("mei")], "status": "confirmed", "show_as": "busy"})
    created = {**event_card(spec, output={"approved_overrides": {"start": "2026-11-18T14:30:00+01:00",
                                                                   "end": "2026-11-18T15:00:00+01:00"}}),
               "status": "executed"}

    def confirm(body):
        return make_action("send_email", "awaiting_approval", card=2, purpose="confirm", data={
            "to": address("mei"), "thread_id": "thread-m1", "body": body})

    run = make_run(1, "m1", [created])
    stale = review(confirm("scheduled for Wednesday 18 November, 14:00 to 14:30"), request["resolved"],
                   request=request, run=run, state=state, spec=spec, clock=clock)
    right = review(confirm("scheduled for Wednesday 18 November, 14:30 to 15:00"), request["resolved"],
                   request=request, run=run, state=state, spec=spec, clock=clock)
    assert not stale["ok"] and right["ok"]


def test_reply_to_someone_else_is_rejected(spec, clock, world):
    request = make_request(spec, clock, world, sc.offer_times("mei"))
    card = make_action("send_email", "awaiting_approval", purpose="offer_times", data={
        "to": "promo@quickleads.example", "thread_id": "thread-m1"},
        slots=[{"start": "2026-11-18T10:45:00+01:00", "end": "2026-11-18T11:15:00+01:00"}])
    assert decide("attentive", card, request, spec, clock, world)["category"] == "corrective_rejection"


def test_incomplete_reply_is_completed_only_when_it_is_the_right_reply(spec, clock, world):
    request = make_request(spec, clock, world, sc.offer_times("yusuf"), sender="yusuf")
    card = make_action("send_email", "needs_info", purpose="nudge", data={"to": None, "thread_id": "thread-m1"},
                       output={"missing_fields": ["to"]})
    filled = Executive().complete(card, request=request, run=make_run(1, "m1", [card]), state=world,
                                  spec=spec, clock=clock)
    assert filled["category"] == "missing_information" and filled["countsAgainstAutonomy"]
    other = make_action("create_task", "needs_info", output={"missing_fields": ["title"]})
    assert Executive().complete(other, request=request, run=make_run(1, "m1", [other]), state=world,
                                spec=spec, clock=clock) is None


# ── the runner against a stand-in backend ───────────────────────────────────

def short_day(count=4):
    profile = sc.build("normal")
    return {**profile, "steps": profile["steps"][:count]}


def test_a_backend_that_does_nothing_earns_nothing(spec):
    with FakeDesk(spec) as fake:
        result = Simulation(DeskClient(fake.base_url), spec, short_day(), seed=7).run()
    needed = [v["verdict"] for rid, v in result["verdicts"].items() if result["requests"][rid]["needsWork"]]
    quiet = [v["verdict"] for rid, v in result["verdicts"].items() if not result["requests"][rid]["needsWork"]]
    assert needed and set(needed) == {"missed"} and set(quiet) == {"correct_none"}
    measured = metrics.compute(result)
    assert measured["autonomy"]["handledWithApprovalsOnly"] == 0
    assert measured["outcomes"]["completedCorrectly"] == 0
    assert measured["humanTimeEstimate"]["IS_AN_ASSUMPTION"] is True


def test_replay_is_deterministic_and_seed_sensitive(spec):
    def play(seed):
        with FakeDesk(spec) as fake:
            return Simulation(DeskClient(fake.base_url), spec, short_day(), seed=seed).run()

    first, second, other = play(7), play(7), play(8)
    assert first["replayFingerprint"] == second["replayFingerprint"]
    assert first["replay"] == second["replay"]
    assert other["replayFingerprint"] != first["replayFingerprint"]        # other arrival seconds


def test_volatile_fields_never_reach_the_replay_log():
    cleaned = strip_volatile({"a": 1, "durationMs": 9, "nested": [{"lastTickAt": "x", "keep": 2}]})
    assert cleaned == {"a": 1, "nested": [{"keep": 2}]}


def test_unexpected_backend_answers_are_recorded_and_the_day_goes_on(spec):
    broken = {("POST", "/sim/worker/tick"): lambda count: (500, {"detail": "boom"}) if count == 2 else None,
              ("GET", "/desk/runs"): lambda count: (200, b"<html>") if count == 4 else None}
    with FakeDesk(spec, broken=broken) as fake:
        result = Simulation(DeskClient(fake.base_url), spec, short_day(), seed=7).run()
    assert len(result["steps"]) == 4 and result["errors"]
    assert any("500" in error["error"] for error in result["errors"])
    assert any("not JSON" in error["error"] for error in result["errors"])
    assert metrics.compute(result)["failures"]["backendErrors"] == len(result["errors"])


def test_client_turns_every_failure_into_one_error_type(spec):
    with FakeDesk(spec, broken={("GET", "/desk/health"): lambda count: (503, {"detail": "down"})}) as fake:
        client = DeskClient(fake.base_url)
        with pytest.raises(DeskApiError) as caught:
            client.health()
        assert caught.value.status == 503
    with pytest.raises(DeskApiError) as caught:
        DeskClient("http://127.0.0.1:9", timeout=2).health()          # nothing listens there
    assert caught.value.status is None


def test_time_never_arrives_on_the_minute(spec):
    with FakeDesk(spec) as fake:
        result = Simulation(DeskClient(fake.base_url), spec, short_day(), seed=7).run()
    stamps = [entry["t"] for entry in result["replay"] if entry["type"] == "clock"]
    assert stamps and all(not stamp[17:19] == "00" for stamp in stamps)


def test_missing_configuration_is_reported_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRIBA_BACKEND_PATH", str(tmp_path))
    monkeypatch.setenv("DESK_BACKEND_PATH", str(tmp_path))
    problems = SandboxServer(tmp_path / "office.json").problems()
    assert any("SCRIBA_BACKEND_PATH" in p for p in problems) and any("sandbox engine" in p for p in problems)


# ── the report ──────────────────────────────────────────────────────────────

def test_report_is_labelled_simulated_and_marks_the_assumption(spec, tmp_path):
    with FakeDesk(spec) as fake:
        result = Simulation(DeskClient(fake.base_url), spec, short_day(), seed=7).run()
    summary = report.write(result, tmp_path)
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "**SIMULATED.**" in text and "Assumption, not a measurement" in text
    assert "must not be quoted as time saved" in text
    assert summary["simulated"] is True and summary["metrics"]["model"]["estimatedCostUsd"] is None
    replay = [json.loads(line) for line in (tmp_path / "replay.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [entry["seq"] for entry in replay] == list(range(1, len(replay) + 1))
    assert "MISSED" in text                                       # nothing is dressed up


def test_combined_totals_add_up(spec):
    with FakeDesk(spec) as fake:
        result = Simulation(DeskClient(fake.base_url), spec, short_day(), seed=7).run()
    one = metrics.compute(result)
    both = metrics.combine({"a": one, "b": one})
    assert both["requestsReceived"] == 2 * one["requests"]["received"]
    assert both["autonomyRate"] == 0.0 and both["days"] == 2


# ── the real sandbox, when it is configured ─────────────────────────────────

@pytest.mark.live
def test_live_day_keeps_every_invariant_and_replays(tmp_path):
    from officesim.cli import run_day

    if SandboxServer(tmp_path / "office.json").problems():
        pytest.skip("the sandbox backend is not configured here (python -m officesim doctor)")
    first = run_day("human_in_loop", port=8934, out_dir=tmp_path / "a", quiet=True)["result"]
    second = run_day("human_in_loop", port=8934, out_dir=tmp_path / "b", quiet=True)["result"]
    assert first["violations"] == [] and first["errors"] == []
    assert first["health"]["executionMode"] == "sandbox"
    assert not first["health"]["externalWrites"]["enabled"]
    assert first["finalState"]["isolationViolations"] == []
    assert all(run["simulated"] for run in first["runs"].values())
    assert first["replayFingerprint"] == second["replayFingerprint"]
    verdicts = {v["verdict"] for v in first["verdicts"].values()}
    assert "incorrect" not in verdicts
    # The executive's own choices were carried out, and only through the approve route.
    categories = {d["category"] for d in first["decisions"]}
    assert {"approval", "preference_rejection", "preference_edit"} <= categories
