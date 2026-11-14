"""The isolated provider world: reads, writes, faults, verification, routing."""
import datetime as dt

import pytest

from desk_overlay.gateway import CalendarReadError, DeskUser
from desk_overlay.sandbox import (OP_CANCEL_EVENT, OP_CREATE_EVENT, OP_SEND_EMAIL, OP_UPDATE_EVENT,
                                  RoutedGateway, SandboxFault, SandboxWorld, WorldRegistry, active_world)

from .fakes import FakeGateway, email

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 16, 6, 0, tzinfo=UTC)
EXEC = "exec@example.test"


def world(**kwargs) -> SandboxWorld:
    return SandboxWorld("w1", owner_email=EXEC, principal_email="layla@desk.example", now=NOW,
                        gmail_accounts=["layla@desk.example"], outlook_account="layla@contoso.example",
                        **kwargs)


def create(start="2026-11-17T10:00:00+00:00", end="2026-11-17T10:30:00+00:00", title="Intro call",
           provider="google_calendar", attendees=("sofia@client.example",)):
    return {"action_type": "create_calendar_event", "provider": provider,
            "payload": {"action": {"type": "create", "event": {
                "summary": title, "start": start, "end": end, "attendees": list(attendees),
                "timezone": "UTC"}}}}


def test_a_delivered_message_is_listed_in_its_own_mailbox_only():
    w = world()
    w.deliver(provider="gmail", from_addr="Sofia <sofia@client.example>", subject="Hello", body="Hi there")
    w.deliver(provider="outlook", from_addr="Omar <omar@client.example>", subject="Report", body="Attached")
    gmail = w.list_emails("gmail", 10)["items"]
    assert [row["subject"] for row in gmail] == ["Hello"]
    assert gmail[0]["provider_account_id"] == "layla@desk.example" and gmail[0]["provider"] == "gmail"
    assert w.list_emails("outlook", 10)["items"][0]["provider_account_id"] == "layla@contoso.example"
    assert w.list_emails("gmail", 10, mailbox="someone@else.example")["items"] == []


def test_busy_time_keeps_its_calendar_and_ignores_cancelled_and_free_events():
    w = world()
    w.add_event(provider="google", title="Standup", start="2026-11-17T09:00:00+00:00",
                end="2026-11-17T09:30:00+00:00")
    gone = w.add_event(provider="google", title="Old", start="2026-11-17T11:00:00+00:00",
                       end="2026-11-17T12:00:00+00:00")
    w.events[gone["id"]]["status"] = "cancelled"
    w.add_event(provider="outlook", title="Focus", start="2026-11-17T13:00:00+00:00",
                end="2026-11-17T14:00:00+00:00", show_as="free")
    day = (dt.datetime(2026, 11, 17, tzinfo=UTC), dt.datetime(2026, 11, 18, tzinfo=UTC))
    google = w.busy("google", "layla@desk.example", *day)
    assert [(b.provider, b.account, b.title) for b in google] == [("google", "layla@desk.example", None)]
    assert w.busy("outlook", "layla@contoso.example", *day) == []


def test_an_unreadable_calendar_raises_and_is_never_empty():
    w = world()
    w.unreadable["outlook"] = "reconnect_required"
    with pytest.raises(CalendarReadError) as caught:
        w.busy("outlook", "layla@contoso.example", NOW, NOW + dt.timedelta(days=1))
    assert caught.value.code == "reconnect_required"


def test_creating_an_event_writes_the_world_and_is_logged_as_simulated():
    w = world()
    result = w.execute(create())
    assert result["status"] == "executed"
    event_id = result["result"]["event"]["id"]
    assert w.events[event_id]["attendees"] == ["sofia@client.example"]
    assert w.oplog == [{"seq": 1, "at": NOW.isoformat(), "op": OP_CREATE_EVENT, "status": "executed",
                        "object_id": event_id, "error": None, "simulated": True}]
    assert w.verify(OP_CREATE_EVENT, event_id, {"start": "2026-11-17T10:00:00+00:00"})["ok"] is True
    assert w.verify(OP_CREATE_EVENT, event_id, {"start": "2026-11-17T15:00:00+00:00"})["ok"] is False


def test_the_same_event_requested_twice_is_one_event():
    w = world()
    first = w.execute(create())
    second = w.execute(create())
    assert second["result"]["calendar_result"]["already_booked"] is True
    assert second["result"]["event"]["id"] == first["result"]["event"]["id"]
    assert len(w.events) == 1


def test_a_reschedule_moves_the_original_event_and_never_adds_one():
    w = world()
    event = w.add_event(provider="google", title="Review", start="2026-11-17T10:00:00+00:00",
                        end="2026-11-17T11:00:00+00:00", attendees=["sofia@client.example"])
    result = w.execute({"action_type": "create_calendar_event", "provider": "google", "payload": {
        "action": {"type": "reschedule", "target_event_id": event["id"],
                   "event": {"start": "2026-11-18T14:00:00+00:00", "timezone": "UTC"}}}})
    assert result["status"] == "executed" and len(w.events) == 1
    moved = w.events[event["id"]]
    assert moved["start"] == dt.datetime(2026, 11, 18, 14, 0, tzinfo=UTC)
    assert moved["end"] - moved["start"] == dt.timedelta(hours=1)        # the length is kept
    assert w.verify(OP_UPDATE_EVENT, event["id"], {"start": "2026-11-18T14:00:00+00:00"})["ok"] is True


def test_a_cancellation_marks_the_event_cancelled_and_frees_the_time():
    w = world()
    event = w.add_event(provider="outlook", title="Review", start="2026-11-17T10:00:00+00:00",
                        end="2026-11-17T11:00:00+00:00")
    w.execute({"action_type": "create_calendar_event", "provider": "outlook", "payload": {
        "action": {"type": "cancel", "target_event_id": event["id"], "event": {}}}})
    assert w.events[event["id"]]["status"] == "cancelled"
    assert w.verify(OP_CANCEL_EVENT, event["id"], {})["ok"] is True
    assert w.busy("outlook", "layla@contoso.example", NOW, NOW + dt.timedelta(days=3)) == []


def test_only_the_organizer_can_change_or_cancel_a_meeting():
    w = world()
    event = w.add_event(provider="google", title="Their meeting", start="2026-11-17T10:00:00+00:00",
                        end="2026-11-17T11:00:00+00:00", organizer="sofia@client.example")
    result = w.execute({"action_type": "create_calendar_event", "provider": "google", "payload": {
        "action": {"type": "cancel", "target_event_id": event["id"], "event": {}}}})
    assert result["status"] == "failed" and w.events[event["id"]]["status"] == "confirmed"


def test_changing_an_event_that_does_not_exist_fails_and_changes_nothing():
    w = world()
    result = w.execute({"action_type": "create_calendar_event", "provider": "google", "payload": {
        "action": {"type": "reschedule", "target_event_id": "nope", "event": {"start": "2026-11-18T14:00Z"}}}})
    assert result["status"] == "failed" and result["error_code"] == "calendar_event_not_found"
    assert w.events == {}


def test_sending_mail_lands_in_sent_with_its_thread_and_never_in_an_inbox():
    w = world()
    result = w.execute({"action_type": "send_email", "provider": "gmail", "payload": {
        "provider": "gmail", "mode": "reply", "to": "sofia@client.example", "subject": "Re: Hi",
        "text": "Tuesday works.", "thread_id": "T-1", "email_id": "m1",
        "provider_account_id": "layla@desk.example"}})
    assert result["status"] == "executed"
    [sent] = w.sent
    assert sent["to"] == ["sofia@client.example"] and sent["thread_id"] == "T-1" and sent["in_reply_to"] == "m1"
    assert w.mail == {"gmail": [], "outlook": []}
    assert w.verify(OP_SEND_EMAIL, sent["id"], {"thread_id": "T-1"})["ok"] is True
    assert w.verify(OP_SEND_EMAIL, sent["id"], {"thread_id": "T-other"})["ok"] is False


def test_an_email_with_no_recipient_or_no_text_is_refused():
    w = world()
    for payload in ({"to": "", "text": "x"}, {"to": "a@b.example", "text": "  "}):
        result = w.execute({"action_type": "send_email", "provider": "gmail", "payload": payload})
        assert result["status"] == "failed"
    assert w.sent == []


def test_tasks_and_reminders_are_simulated_too():
    w = world()
    task = w.execute({"action_type": "create_task", "payload": {"title": "Board pack", "due_at": None}})
    reminder = w.execute({"action_type": "create_reminder", "payload": {
        "title": "Call Omar", "remind_at": "2026-11-17T09:00:00+00:00"}})
    assert task["status"] == reminder["status"] == "executed"
    assert [t["title"] for t in w.tasks] == ["Board pack"] and len(w.reminders) == 1
    assert all(entry["simulated"] for entry in w.oplog)


def test_an_unknown_action_is_refused_not_guessed():
    w = world()
    assert w.execute({"action_type": "send_slack_message", "payload": {}})["status"] == "failed"
    assert w.sent == [] and w.events == {}


def test_a_fault_that_fails_n_times_then_lets_the_action_through():
    w = world()
    w.add_fault(OP_CREATE_EVENT, mode="fail_times", times=2, error="provider_error")
    assert [w.execute(create())["status"] for _ in range(3)] == ["failed", "failed", "executed"]
    assert len(w.events) == 1


def test_a_permanent_fault_never_takes_effect():
    w = world()
    w.add_fault(OP_SEND_EMAIL, mode="fail_always")
    send = {"action_type": "send_email", "provider": "gmail",
            "payload": {"to": "a@b.example", "text": "hello"}}
    assert [w.execute(send)["status"] for _ in range(3)] == ["failed"] * 3 and w.sent == []


def test_an_uncertain_fault_takes_effect_and_then_reports_a_timeout():
    w = world()
    w.add_fault(OP_CREATE_EVENT, mode="uncertain", times=1, error="timeout")
    with pytest.raises(SandboxFault) as caught:
        w.execute(create())
    assert caught.value.uncertain is True
    assert len(w.events) == 1                    # it happened, and the caller was not told
    assert w.oplog[-1]["status"] == "unknown"


def test_two_worlds_never_share_state():
    a = SandboxWorld("a", owner_email=EXEC, now=NOW)
    b = SandboxWorld("b", owner_email="other@example.test", now=NOW)
    a.execute(create())
    a.deliver(from_addr="x@y.example", subject="s", body="b")
    assert b.events == {} and b.mail["gmail"] == [] and b.oplog == []


# ── routing: which world, if any, answers ───────────────────────────────────

def routed():
    inner = FakeGateway()
    inner.add_user(1, EXEC, google=["exec@gmail.example"], gmail_mail=True)
    inner.add_user(2, "other@example.test", google=["other@gmail.example"], gmail_mail=True)
    inner.world(EXEC)["emails"]["gmail"] = [email("real-1", "Real mail", "From the fake provider")]
    registry = WorldRegistry()
    return inner, registry, RoutedGateway(inner, registry)


def test_with_no_world_the_inner_gateway_answers():
    inner, _, gateway = routed()
    user = inner.world(EXEC)["user"]
    assert gateway.list_emails(None, user, provider="gmail", limit=5)["items"][0]["id"] == "real-1"
    assert gateway.world_for(user) is None and gateway.key_namespace(user) == ""
    assert gateway.verify_effect(user, OP_CREATE_EVENT, "x", {}) is None


def test_a_default_world_answers_for_its_owner_and_nobody_else():
    inner, registry, gateway = routed()
    user, other = inner.world(EXEC)["user"], inner.world("other@example.test")["user"]
    w = registry.add(world(), default=True)
    w.deliver(from_addr="Sofia <sofia@client.example>", subject="Synthetic", body="Hello")
    assert [r["subject"] for r in gateway.list_emails(None, user, provider="gmail", limit=5)["items"]] == ["Synthetic"]
    assert gateway.provider_status_for(user)["sandbox"]["id"] == "w1"
    assert gateway.clock_for(user) == NOW
    # The other user has no world: their reads go to their own provider data.
    assert gateway.list_emails(None, other, provider="gmail", limit=5)["items"] == []
    assert gateway.clock_for(other) is None
    assert ("list_emails", "other@example.test", "gmail", None) in inner.calls
    assert ("list_emails", EXEC, "gmail", None) not in inner.calls      # the real mailbox was not read


def test_a_world_set_for_the_context_wins_and_ends_with_the_block():
    inner, registry, gateway = routed()
    user = inner.world(EXEC)["user"]
    case = registry.add(SandboxWorld("case-9", owner_email=EXEC, now=NOW, evaluation=True))
    assert active_world() is None
    with registry.using(case):
        assert gateway.world_for(user) is case
        assert gateway.key_namespace(user) == "sandbox:case-9"
    assert active_world() is None and gateway.world_for(user) is None


def test_removing_a_world_stops_it_answering():
    inner, registry, gateway = routed()
    user = inner.world(EXEC)["user"]
    registry.add(world(), default=True)
    registry.remove("w1")
    assert gateway.world_for(user) is None and registry.get("w1") is None


def test_the_status_of_a_world_names_only_the_four_desk_accounts():
    status = world().provider_status()
    assert set(status["providers"]) == {"gmail", "google_calendar", "outlook", "outlook_calendar"}
    assert all(row["connected"] for row in status["providers"].values())
    assert DeskUser(id=1, email=EXEC).email == status["email"]
