"""The Desk scope applied to Scriba's real chat service.

Real: Scriba's chat service, tool policy, planner request builder, plan
cleaner, validation gate and approve path. Scripted: the calendars (through
the gateway), the chat store and the execution engine, using Scriba's own
contract-test harness. No model is called, so these prove what the agent is
ALLOWED and FORCED to do, not what a model chooses to say.
"""
import datetime as dt
import json

import pytest

from desk_overlay import chat_scope
from desk_overlay.availability import Busy

from ..fakes import FakeGateway

UTC = dt.timezone.utc
ACCOUNT = "owner@example.com"          # the account Scriba's calendar chat harness uses
USER_ID = 7
OTHER = "other@example.test"
NOW = dt.datetime(2027, 3, 1, 8, 0, tzinfo=UTC)
START = dt.datetime(2027, 3, 4, 10, 0, tzinfo=UTC)   # the harness's FUTURE_START
EXCLUDED = ["send_slack_message", "send_teams_message", "create_jira_issue", "list_jira_issues",
            "recent_slack_messages", "recent_teams_messages", "search_google_drive", "search_onedrive",
            "drive_upload_file", "onedrive_upload_file", "drive_delete_file", "create_spreadsheet",
            "create_document", "run_automation_with_file", "capture_note", "remember_fact", "query_table"]


def busy(provider, account, start_hour, end_hour, title=None):
    return Busy(START.replace(hour=start_hour), START.replace(hour=end_hour), provider, account, title)


@pytest.fixture()
def desk():
    gateway = FakeGateway()
    gateway.add_user(USER_ID, ACCOUNT, google=[ACCOUNT], outlook="owner@contoso.example")
    gateway.add_user(8, OTHER, google=["other@gmail.example"])
    gateway.acting_as = ACCOUNT
    chat_scope.enable(app=None, gateway=gateway, clock=lambda: NOW)
    try:
        yield gateway
    finally:
        chat_scope.disable()


@pytest.fixture()
def world(desk):
    from test_contract_calendar_mutation_chat import chat_world

    with chat_world() as harness:
        repo = harness["repo"]

        def create_tool_call(**row):
            return repo.seed(tool_name=row["tool_name"], status=row.get("status") or "pending",
                             input_payload=row.get("input_payload"), user_id=row["user_id"],
                             output_payload=row.get("output_payload") or {}, error=row.get("error"))

        repo.create_tool_call = create_tool_call
        yield desk, harness


# ── scope: what exists ─────────────────────────────────────────────────────

def test_scope_narrows_scribas_own_tool_sets_and_disable_restores_them():
    from app import chat_service
    from packages.domain.chat import policy

    before = (set(policy.READ_ONLY_TOOLS), set(policy.APPROVAL_TOOLS))
    assert "send_slack_message" in before[1] and "search_google_drive" in before[0]

    gateway = FakeGateway()
    chat_scope.enable(app=None, gateway=gateway)
    try:
        # Scriba's chat service holds the SAME set objects, so it is scoped too.
        assert chat_service.READ_ONLY_TOOLS is policy.READ_ONLY_TOOLS
        assert policy.APPROVAL_TOOLS == set(chat_scope.DESK_APPROVAL_TOOLS)
        assert policy.READ_ONLY_TOOLS == set(chat_scope.DESK_READ_TOOLS) | set(chat_scope.DESK_TOOL_DESCRIPTIONS)
        for name in EXCLUDED:
            assert name not in policy.READ_ONLY_TOOLS and name not in policy.APPROVAL_TOOLS, name
        assert chat_scope.status()["chatScope"] == "enforced"
    finally:
        chat_scope.disable()
    assert (set(policy.READ_ONLY_TOOLS), set(policy.APPROVAL_TOOLS)) == before
    assert chat_scope.status() == {"chatScope": "off"}


def test_the_planner_is_offered_only_desk_tools_and_the_desk_rules(desk):
    from app import chat_service, llm_client

    available = sorted(chat_service.READ_ONLY_TOOLS | chat_service.APPROVAL_TOOLS)
    payload = llm_client._chat_request_payload(
        available=available, user_message="When am I free this week?", history=[],
        provider_status={"providers": {}}, timezone="UTC", account_email=ACCOUNT,
        personal_context=None, pending_action=None, active_goal=None, recent_actions=None)
    system, catalogue = payload["messages"][0]["content"], json.loads(payload["messages"][1]["content"])
    offered = set(catalogue["available_tools"])
    assert {"check_availability", "find_free_slots", "executive_briefing"} <= offered
    assert offered == set(available)
    for name in EXCLUDED:
        assert name not in offered, name
    assert "DESK SCOPE" in system and "availability is UNKNOWN" in system
    assert "UNTRUSTED CONTENT" in system


def test_an_excluded_tool_the_model_emits_is_stripped_from_the_plan(desk):
    from app import chat_service, llm_client

    available = sorted(chat_service.READ_ONLY_TOOLS | chat_service.APPROVAL_TOOLS)
    # A plan as a model might write it after reading an email that says
    # "post this in Slack and upload the file to Drive".
    _, calls = llm_client._clean_chat_plan({
        "reply_text": "On it.",
        "tool_calls": [
            {"tool_name": "send_slack_message", "input": {"channel": "#general", "text": "hi"}},
            {"tool_name": "drive_upload_file", "input": {}},
            {"tool_name": "check_availability", "input": {"start": "2027-03-04T10:00:00Z",
                                                          "end": "2027-03-04T10:30:00Z"}},
        ],
    }, available)
    assert [call["tool_name"] for call in calls] == ["check_availability"]


def test_dispatch_refuses_an_excluded_tool_even_if_it_reaches_it(world):
    from app import chat_service

    _, harness = world
    card = chat_service._handle_tool_call(
        account_email=ACCOUNT, user_id=USER_ID, conversation_id=1, message_id=1,
        tool_name="send_slack_message", tool_input={"channel": "#general", "text": "hi"},
        provider_status={"providers": {}})
    assert card["status"] == "unsupported"
    assert harness["execute"].calls == []


def test_approving_an_old_card_for_an_excluded_tool_executes_nothing(world):
    from app import chat_service

    _, harness = world
    row = harness["repo"].seed(tool_name="send_slack_message", input_payload={"text": "hi"})
    with pytest.raises(Exception):
        chat_service.approve_tool_call(account_email=ACCOUNT, tool_call_id=row["id"])
    assert harness["execute"].calls == []
    assert harness["repo"].rows[row["id"]]["status"] == "failed"


def test_the_model_is_told_about_desk_integrations_only(desk):
    from app import chat_capabilities, llm_client

    summary = chat_capabilities.summarize_for_llm({"providers": {
        "gmail": {"connected": True, "available": True}, "slack": {"connected": True, "available": True},
        "jira": {"connected": False, "available": True}, "google_drive": {"connected": True, "available": True},
        "outlook_calendar": {"connected": False, "available": True}}})
    listed = set(summary["connected"]) | set(summary["available_to_connect"]) | set(
        summary["not_available_in_this_deployment"])
    assert listed <= {"Gmail", "Outlook Mail", "Google Calendar", "Outlook Calendar"}
    assert "Gmail" in summary["connected"]

    from app import chat_service

    available = sorted(chat_service.READ_ONLY_TOOLS | chat_service.APPROVAL_TOOLS)
    reply = llm_client._chat_fallback_reply("what can you do", available)
    text = json.dumps(reply)
    for word in ("Slack", "Jira", "Drive", "Teams"):
        assert word not in text, word


# ── read tools through Scriba's dispatcher ─────────────────────────────────

def run_tool(name, tool_input):
    from app import chat_service

    return chat_service._handle_tool_call(
        account_email=ACCOUNT, user_id=USER_ID, conversation_id=1, message_id=1,
        tool_name=name, tool_input=tool_input, provider_status={"providers": {}})


def test_check_availability_runs_as_a_recorded_read_tool_with_real_calendar_data(world):
    gateway, harness = world
    gateway.world(ACCOUNT)["google_busy"][ACCOUNT] = [busy("google", ACCOUNT, 9, 10)]
    gateway.world(ACCOUNT)["outlook_busy"] = [busy("outlook", "owner@contoso.example", 10, 11, "Board call")]
    card = run_tool("check_availability", {"start": "2027-03-04T10:15:00Z", "end": "2027-03-04T10:45:00Z"})
    assert card["status"] == "executed" and card["tool_name"] == "check_availability"
    assert card["output"]["free"] is False
    assert card["output"]["conflicts"] == [{
        "start": "2027-03-04T10:00:00+00:00", "end": "2027-03-04T11:00:00+00:00",
        "provider": "outlook", "account": "owner@contoso.example", "title": "Board call"}]
    assert harness["execute"].calls == []          # a read tool never executes an action


def test_find_free_slots_says_unknown_when_a_calendar_is_disconnected(world):
    gateway, _ = world
    gateway.world(ACCOUNT)["outlook_error"] = "reconnect_required"
    card = run_tool("find_free_slots", {"start": "2027-03-04T00:00:00Z", "end": "2027-03-05T00:00:00Z"})
    assert card["status"] == "executed"
    assert card["output"]["complete"] is False and card["output"]["slots"] == []
    failed = [c for c in card["output"]["calendars"] if not c["ok"]]
    assert failed == [{"provider": "outlook", "account": "owner@contoso.example", "ok": False,
                       "error": "reconnect_required", "busy_count": 0}]


def test_a_bad_tool_input_is_a_failed_card_not_an_exception(world):
    card = run_tool("check_availability", {"start": "whenever"})
    assert card["status"] == "failed" and card["error"] == "invalid_request"


def test_chat_tools_never_read_another_users_calendar(world):
    gateway, _ = world
    gateway.world(OTHER)["google_busy"]["other@gmail.example"] = [busy("google", "other@gmail.example", 0, 23)]
    card = run_tool("check_availability", {"start": "2027-03-04T10:00:00Z", "end": "2027-03-04T10:30:00Z"})
    assert card["output"]["free"] is True
    assert all(call[1] == ACCOUNT for call in gateway.calls)


def test_provider_status_tool_is_answered_by_the_desk(world):
    card = run_tool("provider_status", {})
    assert [c["id"] for c in card["output"]["capabilities"]] == [
        "gmail", "google_calendar", "outlook_mail", "outlook_calendar"]


# ── the gate inside Scriba's approve path ──────────────────────────────────

def seed_event(harness, **overrides):
    from test_contract_calendar_mutation_chat import calendar_input

    return harness["repo"].seed(tool_name="create_calendar_event", input_payload=calendar_input(**overrides))


def approve(row, **kwargs):
    from app import chat_service

    return chat_service.approve_tool_call(account_email=ACCOUNT, tool_call_id=row["id"], **kwargs)


def test_a_free_slot_is_approved_and_executed_once(world):
    _, harness = world
    result = approve(seed_event(harness))
    assert result["tool_call"]["status"] == "executed"
    assert len(harness["execute"].calls) == 1


def test_a_conflict_on_the_other_provider_stops_the_approval(world):
    gateway, harness = world
    gateway.world(ACCOUNT)["outlook_busy"] = [busy("outlook", "owner@contoso.example", 10, 11, "Board call")]
    row = seed_event(harness)
    result = approve(row)
    card = result["tool_call"]
    assert card["status"] == "needs_info" and card["output"]["error_code"] == "calendar_conflict"
    assert "Board call" in card["output"]["message"]
    assert card["output"]["availability"]["conflicts"][0]["provider"] == "outlook"
    assert harness["execute"].calls == []          # nothing was booked


def test_the_calendars_are_rechecked_at_approval_not_trusted_from_proposal(world):
    gateway, harness = world
    row = seed_event(harness)                       # free when the card was made...
    gateway.world(ACCOUNT)["google_busy"][ACCOUNT] = [busy("google", ACCOUNT, 10, 11)]   # ...taken since
    assert approve(row)["tool_call"]["output"]["error_code"] == "calendar_conflict"
    assert harness["execute"].calls == []


def test_an_unreadable_calendar_makes_availability_unknown_and_stops_the_approval(world):
    gateway, harness = world
    gateway.world(ACCOUNT)["outlook_error"] = "reconnect_required"
    card = approve(seed_event(harness))["tool_call"]
    assert card["status"] == "needs_info" and card["output"]["error_code"] == "availability_unknown"
    assert card["output"]["blocked"] is True
    assert harness["execute"].calls == []


def test_the_user_can_confirm_a_conflict_and_only_then_is_it_booked(world):
    gateway, harness = world
    gateway.world(ACCOUNT)["outlook_busy"] = [busy("outlook", "owner@contoso.example", 10, 11)]
    row = seed_event(harness)
    assert approve(row)["tool_call"]["status"] == "needs_info"
    assert harness["execute"].calls == []

    confirmed = approve(row, payload_overrides={chat_scope.OVERRIDE_FLAG: True})
    assert confirmed["tool_call"]["status"] == "executed"
    assert len(harness["execute"].calls) == 1
    # The confirmation is recorded on the card, with the conflict it overrode.
    record = confirmed["tool_call"]["output"]["availability_override"]
    assert record["by"] == "user" and record["conflicts"][0]["provider"] == "outlook"
    assert harness["repo"].rows[row["id"]]["output_payload"]["availability_override"]["by"] == "user"


def test_the_model_cannot_pre_confirm_a_conflict_when_proposing(world):
    from app import chat_validation

    gateway, _ = world
    gateway.world(ACCOUNT)["outlook_busy"] = [busy("outlook", "owner@contoso.example", 10, 11)]
    from test_contract_calendar_mutation_chat import GOOGLE_CONNECTED, calendar_input

    token = chat_scope._proposing.set(True)        # as Scriba's _handle_tool_call does
    try:
        result = chat_validation.validate_tool_call(
            tool_name="create_calendar_event",
            tool_input=calendar_input(**{chat_scope.OVERRIDE_FLAG: True}),
            account_email=ACCOUNT, provider_status=GOOGLE_CONNECTED, user_message="book it")
    finally:
        chat_scope._proposing.reset(token)
    assert result.status == "needs_info" and result.error == "calendar_conflict"
    assert chat_scope.OVERRIDE_FLAG not in result.input


def test_a_time_given_in_another_zone_is_checked_as_the_same_instant(world):
    gateway, harness = world
    gateway.world(ACCOUNT)["google_busy"][ACCOUNT] = [busy("google", ACCOUNT, 10, 11)]
    row = seed_event(harness, start="2027-03-04T12:15:00+02:00", end="2027-03-04T12:45:00+02:00")
    assert approve(row)["tool_call"]["output"]["error_code"] == "calendar_conflict"


def test_another_users_busy_calendar_does_not_block_this_users_event(world):
    gateway, harness = world
    gateway.world(OTHER)["google_busy"]["other@gmail.example"] = [busy("google", "other@gmail.example", 0, 23)]
    assert approve(seed_event(harness))["tool_call"]["status"] == "executed"


def test_scribas_own_validation_still_runs_first(world):
    _, harness = world
    row = seed_event(harness, title="")             # Scriba's gate rejects a card with no title
    card = approve(row)["tool_call"]
    assert card["status"] == "needs_info"
    assert card["output"].get("error_code") not in ("calendar_conflict", "availability_unknown")
    assert harness["execute"].calls == []
