"""Approval, execution and verification through Scriba's REAL machinery, on
an isolated provider world.

Real: Scriba's application and routes, session guard, card creation and the
validation gate (including its calendar-edit validation, which re-reads the
event live), the approve, retry and cancel routes with their atomic claim,
and the Desk's chat scope and execution gate installed on them. In memory:
the chat storage. Isolated: every provider read and write goes to a
``SandboxWorld``; Scriba's execution engine and every real provider client
are replaced by tripwires that fail the test if they are reached.

Scripted: the model's reading of a meeting time (``extract_email_plan``).
No model, mailbox or calendar was involved, so these prove control flow,
ordering, isolation and idempotency, not model quality.
"""
import datetime as dt
import threading
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest

from desk_overlay import chat_scope
from desk_overlay.claims import MemoryClaims
from desk_overlay.execution import ExecutionGate
from desk_overlay.gateway import ScribaGateway
from desk_overlay.routes import build_router
from desk_overlay.sandbox import (OP_CREATE_EVENT, OP_SEND_EMAIL, RoutedGateway, SandboxIsolationError,
                                  SandboxWorld, WorldRegistry)
from desk_overlay.service import AppContext
from desk_overlay.worker import IntakeWorker

UTC = dt.timezone.utc
ALICE, BOB = "alice@example.com", "bob@example.com"
NOW = dt.datetime(2026, 3, 2, 8, 0, tzinfo=UTC)       # in the PAST on purpose: the world's clock rules
ORIGIN = {"Origin": "http://localhost:5173"}
SOFIA = "Sofia Marchetti <sofia@client.example>"
THU10 = ("2026-03-05T10:00:00+00:00", "2026-03-05T10:30:00+00:00")
_PREFIX = [0]


class Bomb:
    """Stands where a real provider client or Scriba's engine would be."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("a real provider path was reached from the sandbox")


@contextmanager
def sandbox_desk(*, env=None):
    from test_contract_chat_tool_lifecycle import InMemoryToolCalls, _engine_record_patches
    from contract_harness import auth_app, login_as, recording

    import app.chat_repository as chat_repo
    from app import calendar_client, chat_service, gmail_client, llm_client, outlook_client

    class Store(InMemoryToolCalls):
        def __init__(self):
            super().__init__()
            self.conversations, self.messages = {}, []
            self._guard = threading.Lock()

        def create_conversation(self, *, user_id, title=None, metadata=None, project_id=None):
            row = {"id": len(self.conversations) + 1, "user_id": int(user_id), "title": title,
                   "metadata": metadata or {}, "status": "active"}
            self.conversations[row["id"]] = row
            return dict(row)

        def get_conversation(self, conversation_id, *, user_id):
            row = self.conversations.get(int(conversation_id))
            return dict(row) if row and row["user_id"] == int(user_id) else None

        def list_conversations(self, user_id, *, limit=50):
            rows = [dict(r) for r in self.conversations.values() if r["user_id"] == int(user_id)]
            return sorted(rows, key=lambda r: r["id"], reverse=True)[:limit]

        def create_message(self, *, conversation_id, user_id, role, content, metadata=None, **_):
            row = {"id": len(self.messages) + 1, "conversation_id": conversation_id,
                   "user_id": int(user_id), "role": role, "content": content,
                   "metadata": dict(metadata or {})}
            self.messages.append(row)
            return dict(row)

        def list_messages(self, conversation_id, *, user_id, limit=200):
            return [dict(m) for m in self.messages
                    if m["conversation_id"] == conversation_id and m["user_id"] == int(user_id)]

        def create_tool_call(self, *, message_id, conversation_id, user_id, tool_name, status,
                             input_payload=None, output_payload=None, error=None,
                             idempotency_key=None, **_):
            if idempotency_key:
                for row in self.rows.values():
                    if row.get("idempotency_key") == idempotency_key and row["user_id"] == int(user_id):
                        return dict(row)
            row = self.add(tool_call_id=len(self.rows) + 1, user_id=int(user_id), tool_name=tool_name,
                           payload=input_payload or {}, status=status)
            row.update(message_id=message_id, conversation_id=conversation_id,
                       output_payload=dict(output_payload or {}), error=error,
                       idempotency_key=idempotency_key)
            return dict(row)

        def claim_tool_call_for_approval(self, tool_call_id, *, user_id, expected_statuses=()):
            with self._guard:      # the database's claim is atomic; so is this one
                return super().claim_tool_call_for_approval(
                    tool_call_id, user_id=user_id, expected_statuses=expected_statuses)

        def list_tool_calls_for_conversation(self, conversation_id, *, user_id):
            return [dict(r) for r in self.rows.values()
                    if r["conversation_id"] == conversation_id and r["user_id"] == int(user_id)]

    store, registry = Store(), WorldRegistry()
    routed = RoutedGateway(ScribaGateway(), registry)
    # A model is "configured" in these tests and its answer is scripted below
    # (``extract``). The hermetic environment itself has only a placeholder key.
    routed.inner.model_configured = lambda: model["on"]
    model = {"on": True}
    engine = Bomb()
    providers = {name: Bomb() for name in ("calendar_service", "gmail_service", "send_message_once",
                                           "get_access_token", "graph_get", "send_email")}
    plan = {"value": None, "calls": 0}

    def extract(**kwargs):
        plan["calls"] += 1
        return dict(plan["value"]) if plan["value"] else {"calendar_action": "none"}

    with ExitStack() as stack:
        for name in ("get_tool_call", "claim_tool_call_for_approval", "update_tool_call",
                     "cancel_tool_call_if_cancellable", "create_conversation", "get_conversation",
                     "list_conversations", "create_message", "list_messages", "create_tool_call",
                     "list_tool_calls_for_conversation"):
            stack.enter_context(patch.object(chat_repo, name, getattr(store, name)))
        stack.enter_context(patch.object(chat_repo, "list_recent_executed_tool_calls", lambda **kwargs: []))
        # Scriba's engine and the provider clients: reaching any of them fails the test.
        stack.enter_context(patch.object(chat_service, "execute_action", engine))
        stack.enter_context(patch.object(chat_service, "retry_action", engine))
        stack.enter_context(patch.object(calendar_client, "calendar_service", providers["calendar_service"]))
        stack.enter_context(patch.object(gmail_client, "gmail_service", providers["gmail_service"]))
        stack.enter_context(patch.object(gmail_client, "send_message_once", providers["send_message_once"]))
        stack.enter_context(patch.object(outlook_client, "get_access_token", providers["get_access_token"]))
        stack.enter_context(patch.object(outlook_client, "graph_get", providers["graph_get"]))
        stack.enter_context(patch.object(outlook_client, "send_email", providers["send_email"]))
        stack.enter_context(patch.object(llm_client, "extract_email_plan", extract))
        # Scriba's own audit line and feedback row for an approval: recorded
        # here instead of written to a database.
        audit = recording(None)
        stack.enter_context(patch.object(chat_service, "log_action_execution", audit))
        stack.enter_context(patch.object(chat_service, "_record_chat_feedback", recording(None)))
        client, users = stack.enter_context(auth_app(**_engine_record_patches()))

        gate = ExecutionGate(routed, registry, scope_enforced=chat_scope.is_enabled, env=env or {}).install()
        stack.callback(gate.uninstall)
        chat_scope.enable(app=client.app, gateway=routed)
        stack.callback(chat_scope.disable)
        _PREFIX[0] += 1
        prefix = f"/x{_PREFIX[0]}"
        router = build_router(routed, registry=registry, claims=MemoryClaims(), env=env or {})
        router.desk["gate"] = gate
        workflow = router.desk["workflow"]
        gate.on_settled = lambda user, run: workflow.advance(AppContext(client.app), user, run["id"])
        client.app.include_router(router, prefix=prefix)

        def sign_in(address, *, world=True):
            user = login_as(client, users, address)
            if world:
                registry.add(SandboxWorld(
                    f"w-{address.split('@')[0]}", owner_email=address, now=NOW,
                    gmail_accounts=[f"{address.split('@')[0]}@gmail.example"],
                    outlook_account=f"{address.split('@')[0]}@contoso.example"), default=True)
            return user

        desk = {"client": client, "store": store, "registry": registry, "gate": gate, "prefix": prefix,
                "engine": engine, "providers": providers, "plan": plan, "sign_in": sign_in,
                "workflow": workflow, "routed": routed, "users": users, "audit": audit, "model": model,
                "router_desk": router.desk,
                "world": lambda address=ALICE: registry.default_for(address)}
        yield desk
        # Whatever the test did, no real provider path may have been reached.
        assert engine.calls == [], "Scriba's execution engine was called"
        assert all(bomb.calls == [] for bomb in providers.values()), "a provider client was called"
        assert gate.stats["isolationViolations"] == 0


def post(desk, path, **kwargs):
    return desk["client"].post(f"{desk['prefix']}/desk{path}", headers=ORIGIN, **kwargs)


def get(desk, path):
    return desk["client"].get(f"{desk['prefix']}/desk{path}")


def approve(desk, action, **body):
    response = desk["client"].post(f"/chat/tool-calls/{action['toolCallId']}/approve", json=body,
                                   headers=ORIGIN)
    assert response.status_code == 200, response.text
    return response.json()["tool_call"]


def meeting(desk, body="Could we meet on Thursday at 10:00 for 30 minutes?", message_id="m1",
            start=THU10[0], end=THU10[1]):
    desk["world"]().deliver(message_id=message_id, from_addr=SOFIA, subject="Intro call?", body=body,
                            thread_id=f"T-{message_id}")
    desk["plan"]["value"] = {"calendar_action": "create", "summary": "Intro call",
                             "requested_start": start, "requested_end": end}
    run = post(desk, "/intake", json={"provider": "gmail", "id": message_id})
    assert run.status_code == 200, run.text
    return run.json()


# ── the whole job, in order ─────────────────────────────────────────────────

def test_a_meeting_is_booked_then_confirmed_in_that_order_and_verified():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        run = meeting(desk)
        [event] = run["actions"]
        assert event["tool_name"] == "create_calendar_event" and event["status"] == "awaiting_approval", event
        assert event["availability"]["free"] is True and event["simulated"] is True
        assert world.events == {} and world.sent == []            # nothing before approval

        card = approve(desk, event)
        assert card["status"] == "executed", card
        [booked] = world.events.values()
        assert booked["title"] == "Intro call" and booked["attendees"] == ["sofia@client.example"]
        assert booked["start"] == dt.datetime(2026, 3, 5, 10, 0, tzinfo=UTC)
        assert booked["account"] == "alice@gmail.example"

        # The confirmation reply was proposed by the Desk as soon as the event existed.
        after = get(desk, f"/runs/{run['runId']}").json()
        booking, reply = after["actions"]
        assert booking["verified"] is True and booking["verification"]["method"] == "sandbox_readback"
        assert reply["tool_name"] == "send_email" and reply["purpose"] == "confirm"
        assert reply["status"] == "awaiting_approval", reply
        assert world.sent == []                                   # proposed, not sent

        assert approve(desk, reply)["status"] == "executed"
        [sent] = world.sent
        assert sent["to"] == ["sofia@client.example"] and sent["thread_id"] == "T-m1"
        assert sent["in_reply_to"] == "m1" and sent["provider_account_id"] == "alice@gmail.example"
        assert [entry["op"] for entry in world.oplog] == [OP_CREATE_EVENT, OP_SEND_EMAIL]   # event first

        done = get(desk, f"/runs/{run['runId']}").json()
        assert done["lifecycle"]["stage"] == "COMPLETED" and done["state"] == "completed"
        assert all(action["verified"] for action in done["actions"])
        kinds = [item["kind"] for item in done["timeline"]]
        # Decision, proposal, approval, execution and verification are separate records.
        for kind in ("decision", "proposal", "approval", "execution", "verification"):
            assert kind in kinds
        decisions = [i["data"] for i in done["timeline"] if i["kind"] == "approval"]
        assert [d["decision"] for d in decisions] == ["approve", "approve"]
        assert all(d["by"] == ALICE and d["simulated"] is True for d in decisions)
        assert done["usage"] is None                              # scripted: no model call was made
        # Scriba's own audit lines say these executions were simulated.
        audited = [call["kwargs"] for call in desk["audit"].calls]
        assert [a["action_name"] for a in audited] == ["sandbox_chat_create_calendar_event",
                                                      "sandbox_chat_send_email"]
        assert all(a["details"]["simulated"] is True and a["details"]["sandbox_world"] == "w-alice"
                   for a in audited)


def test_approving_twice_books_one_event():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run = meeting(desk)
        approve(desk, run["actions"][0])
        again = approve(desk, run["actions"][0])
        assert again["status"] == "executed" and len(desk["world"]().events) == 1
        assert len([e for e in desk["world"]().oplog if e["op"] == OP_CREATE_EVENT]) == 1


def test_concurrent_approvals_of_one_card_book_one_event():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run = meeting(desk)
        from app import chat_service

        results, barrier = [], threading.Barrier(6)

        def click():
            barrier.wait()
            try:
                results.append(chat_service.approve_tool_call(
                    account_email=ALICE, tool_call_id=run["actions"][0]["toolCallId"])["tool_call"]["status"])
            except ValueError as exc:
                results.append(str(exc))

        threads = [threading.Thread(target=click) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(desk["world"]().events) == 1, results
        assert len([e for e in desk["world"]().oplog if e["op"] == OP_CREATE_EVENT]) == 1


def test_a_rejected_proposal_executes_nothing_and_is_recorded():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run = meeting(desk)
        card_id = run["actions"][0]["toolCallId"]
        assert desk["client"].post(f"/chat/tool-calls/{card_id}/cancel", headers=ORIGIN).status_code == 200
        view = get(desk, f"/runs/{run['runId']}").json()
        assert view["lifecycle"]["stage"] == "CANCELLED" and desk["world"]().events == {}
        assert view["actions"][0]["decisions"][0]["decision"] == "reject"
        late = desk["client"].post(f"/chat/tool-calls/{card_id}/approve", json={}, headers=ORIGIN)
        assert late.status_code == 400 and desk["world"]().events == {}


def test_the_calendars_are_read_again_at_approval():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run = meeting(desk)
        # Free when proposed; the Outlook calendar fills up before the approval.
        desk["world"]().add_event(provider="outlook", title="Board call", start=THU10[0],
                                  end="2026-03-05T11:00:00+00:00")
        held = approve(desk, run["actions"][0])
        assert held["status"] == "needs_info" and held["output"]["error_code"] == "calendar_conflict"
        assert len(desk["world"]().events) == 1                   # only the conflicting one


def test_another_user_cannot_approve_or_see_a_sandbox_run():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run = meeting(desk)
        desk["sign_in"](BOB)
        assert get(desk, f"/runs/{run['runId']}").status_code == 404
        refused = desk["client"].post(f"/chat/tool-calls/{run['actions'][0]['toolCallId']}/approve",
                                      json={}, headers=ORIGIN)
        assert refused.status_code == 400
        assert desk["world"](ALICE).events == {} and desk["world"](BOB).events == {}


# ── external writes are held in the server ──────────────────────────────────

def test_without_a_sandbox_an_approved_calendar_write_is_held_and_nothing_runs():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE, world=False)
        from app import chat_repository, chat_service

        conversation = chat_repository.create_conversation(user_id=1, title="Desk: test",
                                                           metadata={"desk_run": {"key": "k1"}})
        message = chat_repository.create_message(conversation_id=conversation["id"], user_id=1,
                                                 role="assistant", content="x")
        card = chat_repository.create_tool_call(
            message_id=message["id"], conversation_id=conversation["id"], user_id=1,
            tool_name="create_calendar_event", status="awaiting_approval",
            input_payload={"title": "Intro", "start": THU10[0], "end": THU10[1], "timezone": "UTC"})
        held = chat_service.approve_tool_call(account_email=ALICE, tool_call_id=card["id"])["tool_call"]
        assert held["status"] == "needs_info" and held["output"]["error_code"] == "external_writes_disabled"
        assert held["output"]["blocked"] is True and desk["gate"].stats["held"] == 1
        health = get(desk, "/health").json()
        assert health["externalWrites"]["enabled"] is False and health["executionMode"] == "held"
        assert health["externalWrites"]["capable"] is True


def test_no_environment_setting_lets_a_real_write_through():
    env = {"DESK_EXTERNAL_WRITES": "on", "DESK_EXTERNAL_WRITES_AUTHORIZED_BY": "someone",
           "DESK_ISOLATED_PROVIDER_TEST_REPORT": "a-report"}
    with sandbox_desk(env=env) as desk:
        desk["sign_in"](ALICE, world=False)
        from app import chat_repository, chat_service

        conversation = chat_repository.create_conversation(user_id=1, title="Desk: test",
                                                           metadata={"desk_run": {"key": "k1"}})
        message = chat_repository.create_message(conversation_id=conversation["id"], user_id=1,
                                                 role="assistant", content="x")
        card = chat_repository.create_tool_call(
            message_id=message["id"], conversation_id=conversation["id"], user_id=1,
            tool_name="send_email", status="awaiting_approval",
            input_payload={"to": "sofia@client.example", "subject": "Hi", "body": "Hello"})
        held = chat_service.approve_tool_call(account_email=ALICE, tool_call_id=card["id"])["tool_call"]
        assert held["output"]["error_code"] == "external_writes_disabled"


def test_a_run_whose_sandbox_is_gone_cannot_fall_through_to_a_real_provider():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run = meeting(desk)
        desk["registry"].remove("w-alice")                        # the process restarted
        held = approve(desk, run["actions"][0])
        assert held["status"] == "needs_info" and held["output"]["error_code"] == "sandbox_world_gone"


# ── isolation ───────────────────────────────────────────────────────────────

def test_a_real_provider_client_called_inside_a_sandbox_raises():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        from app import calendar_client, outlook_client

        world = desk["world"]()
        with desk["registry"].using(world):
            with pytest.raises(SandboxIsolationError):
                calendar_client.calendar_service(ALICE)
            with pytest.raises(SandboxIsolationError):
                outlook_client.graph_get("/me/calendarView", "token")
        assert world.violations == ["app.calendar_client.calendar_service", "app.outlook_client.graph_get"]
        assert desk["gate"].stats["isolationViolations"] == 2
        desk["gate"].stats["isolationViolations"] = 0             # counted on purpose in this test
        assert all(bomb.calls == [] for bomb in desk["providers"].values())   # the tripwire fired first


def test_a_whole_run_opens_no_socket_to_another_host():
    """Every connection made through Python's socket layer during a full run
    is recorded. The test client's own loopback pipes are the only ones
    allowed. (A database driver that connects in C is outside this check;
    the sandbox reaches no database either, see the tripwires above.)"""
    import socket

    attempts = []
    real_connect = socket.socket.connect

    def watched(sock, address):
        if not (isinstance(address, tuple) and str(address[0]) in ("127.0.0.1", "::1", "localhost")):
            attempts.append(address)
        return real_connect(sock, address)

    with sandbox_desk() as desk, patch.object(socket.socket, "connect", watched):
        desk["sign_in"](ALICE)
        run = meeting(desk)
        approve(desk, run["actions"][0])
        reply = get(desk, f"/runs/{run['runId']}").json()["actions"][1]
        approve(desk, reply)
        assert len(desk["world"]().sent) == 1
    assert attempts == [], attempts


# ── failures, unknown outcomes, partial success ─────────────────────────────

def test_a_failure_between_the_booking_and_the_confirmation_is_partial_and_escalated():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        world.add_fault(OP_SEND_EMAIL, mode="fail_always")
        run = meeting(desk)
        approve(desk, run["actions"][0])
        reply = get(desk, f"/runs/{run['runId']}").json()["actions"][1]
        failed = desk["client"].post(f"/chat/tool-calls/{reply['toolCallId']}/approve", json={},
                                     headers=ORIGIN)
        assert failed.status_code == 200 and failed.json()["tool_call"]["status"] == "failed"
        view = get(desk, f"/runs/{run['runId']}").json()
        assert view["state"] == "partial" and view["lifecycle"]["stage"] == "PARTIALLY_COMPLETED"
        assert view["lifecycle"]["compensation"]["policy"] == "escalate"
        # The meeting stays booked: the Desk does not undo an executed action by itself.
        assert len(world.events) == 1 and list(world.events.values())[0]["status"] == "confirmed"
        assert world.sent == []


def test_a_failed_send_can_be_retried_once_the_provider_recovers():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        world.add_fault(OP_SEND_EMAIL, mode="fail_times", times=1)
        run = meeting(desk)
        approve(desk, run["actions"][0])
        reply = get(desk, f"/runs/{run['runId']}").json()["actions"][1]
        assert approve(desk, reply)["status"] == "failed"
        retried = desk["client"].post(f"/chat/tool-calls/{reply['toolCallId']}/retry", headers=ORIGIN)
        assert retried.status_code == 200 and retried.json()["tool_call"]["status"] == "executed"
        assert len(world.sent) == 1
        assert get(desk, f"/runs/{run['runId']}").json()["lifecycle"]["stage"] == "COMPLETED"


def test_an_unconfirmed_write_is_unknown_and_a_retry_does_not_repeat_it():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        world.add_fault(OP_CREATE_EVENT, mode="uncertain", times=1, error="timeout")
        run = meeting(desk)
        card = approve(desk, run["actions"][0])
        assert card["status"] == "failed" and card["output"]["outcome_unknown"] is True
        assert card["output"]["error_code"] == "outcome_unknown"
        view = get(desk, f"/runs/{run['runId']}").json()
        assert view["actions"][0]["outcomeUnknown"] is True and view["actions"][0]["verified"] is False
        assert view["lifecycle"] == {"stage": "VERIFYING", "reason": "outcome_unknown", "final": False,
                                     "outcomeUnknown": True, "compensation": None}
        assert len(world.events) == 1                             # it did happen; the Desk was not told

        # Retrying reads the provider state first, finds the event, and does not create a second.
        retried = desk["client"].post(f"/chat/tool-calls/{card['id']}/retry", headers=ORIGIN).json()
        assert retried["reconciled"] is True and retried["tool_call"]["status"] == "executed"
        assert len(world.events) == 1
        assert len([e for e in world.oplog if e["op"] == OP_CREATE_EVENT]) == 1
        settled = get(desk, f"/runs/{run['runId']}").json()
        assert settled["actions"][0]["verified"] is True
        assert settled["actions"][0]["verification"]["reconciled"] is True


def test_an_unknown_outcome_that_did_not_happen_is_run_again_after_the_check():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        world.add_fault(OP_CREATE_EVENT, mode="uncertain", times=1, error="timeout")
        run = meeting(desk)
        card = approve(desk, run["actions"][0])
        world.events.clear()                                      # in this telling, it never landed
        retried = desk["client"].post(f"/chat/tool-calls/{card['id']}/retry", headers=ORIGIN).json()
        assert "reconciled" not in retried and retried["tool_call"]["status"] == "executed"
        assert len(world.events) == 1


# ── rescheduling and cancelling the ORIGINAL event ──────────────────────────

def change(desk, body, plan, message_id="r1"):
    desk["world"]().deliver(message_id=message_id, from_addr=SOFIA, subject="Budget review", body=body,
                            thread_id=f"T-{message_id}")
    desk["plan"]["value"] = plan
    run = post(desk, "/intake", json={"provider": "gmail", "id": message_id})
    assert run.status_code == 200, run.text
    return run.json()


@pytest.mark.parametrize("provider", ["google", "outlook"])
def test_a_reschedule_patches_the_original_event_through_scribas_own_validation(provider):
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        original = world.add_event(provider=provider, title="Budget review", start="2026-03-04T10:00:00+00:00",
                                   end="2026-03-04T11:00:00+00:00", attendees=["sofia@client.example"])
        run = change(desk, "Could we reschedule our budget review to Friday at 14:00?",
                     {"calendar_action": "reschedule", "requested_start": "2026-03-06T14:00:00+00:00"})
        [card] = run["actions"]
        assert card["tool_name"] == "update_calendar_event" and card["status"] == "awaiting_approval", card
        # Scriba's validation re-read the event and computed the change from it.
        assert card["output"]["operation"]["before"]["title"] == "Budget review"
        assert card["input"]["planned_change"]["start"].startswith("2026-03-06T14:00")

        executed = approve(desk, card)
        assert executed["status"] == "executed", executed
        assert list(world.events) == [original["id"]]            # the SAME event; no second one
        moved = world.events[original["id"]]
        assert moved["start"] == dt.datetime(2026, 3, 6, 14, 0, tzinfo=UTC)
        assert moved["end"] == dt.datetime(2026, 3, 6, 15, 0, tzinfo=UTC)
        after = get(desk, f"/runs/{run['runId']}").json()
        assert after["actions"][0]["verified"] is True
        assert after["actions"][1]["purpose"] == "confirm" and "moved" in after["actions"][1]["input"]["body"]


def test_a_move_is_stopped_at_approval_when_the_new_time_has_filled_up():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        original = world.add_event(provider="google", title="Budget review", start="2026-03-04T10:00:00+00:00",
                                   end="2026-03-04T11:00:00+00:00", attendees=["sofia@client.example"])
        run = change(desk, "Could we reschedule our budget review to Friday at 14:00?",
                     {"calendar_action": "reschedule", "requested_start": "2026-03-06T14:00:00+00:00"})
        world.add_event(provider="outlook", title="Offsite", start="2026-03-06T13:00:00+00:00",
                        end="2026-03-06T16:00:00+00:00")
        held = approve(desk, run["actions"][0])
        assert held["status"] == "needs_info" and held["output"]["error_code"] == "calendar_conflict"
        assert world.events[original["id"]]["start"] == dt.datetime(2026, 3, 4, 10, 0, tzinfo=UTC)


def test_a_cancellation_cancels_that_event_and_is_verified():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        original = world.add_event(provider="google", title="Budget review", start="2026-03-04T10:00:00+00:00",
                                   end="2026-03-04T11:00:00+00:00", attendees=["sofia@client.example"])
        other = world.add_event(provider="google", title="Board call", start="2026-03-04T15:00:00+00:00",
                                end="2026-03-04T16:00:00+00:00", attendees=["omar@client.example"])
        run = change(desk, "I need to cancel our budget review meeting, apologies.", None, message_id="c1")
        [card] = run["actions"]
        assert card["tool_name"] == "cancel_calendar_event" and card["status"] == "awaiting_approval", card
        assert approve(desk, card)["status"] == "executed"
        assert world.events[original["id"]]["status"] == "cancelled"
        assert world.events[other["id"]]["status"] == "confirmed"        # only the one asked about
        assert get(desk, f"/runs/{run['runId']}").json()["actions"][0]["verified"] is True


def test_a_meeting_the_user_does_not_organize_is_refused_by_scriba_too():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        theirs = world.add_event(provider="google", title="Budget review", start="2026-03-04T10:00:00+00:00",
                                 end="2026-03-04T11:00:00+00:00", attendees=["alice@gmail.example"],
                                 organizer="sofia@client.example")
        from app import chat_service

        # Even a card made directly, without the Desk's own check, cannot be approved.
        run = change(desk, "Hello", None, message_id="h1")
        conversation_id = run["runId"]
        from app import chat_repository

        message = chat_repository.create_message(conversation_id=conversation_id, user_id=1,
                                                 role="assistant", content="x")
        with desk["registry"].using(world):
            card = chat_service._handle_tool_call(
                account_email=ALICE, user_id=1, conversation_id=conversation_id, message_id=message["id"],
                tool_name="cancel_calendar_event", tool_input={"event_id": theirs["id"], "calendar_provider": "google"},
                provider_status=world.provider_status(), email_id=None, thread_id=None, provider=None,
                user_message="")
        assert card["status"] == "needs_info", card
        assert world.events[theirs["id"]]["status"] == "confirmed"


# ── tasks, and the worker, on the real application ──────────────────────────

def test_a_task_in_a_sandbox_is_written_to_the_sandbox_only():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        desk["world"]().deliver(message_id="a1", from_addr="Omar <omar@client.example>", subject="Board pack",
                                body="Please note the deadline is Friday.")
        run = post(desk, "/intake", json={"provider": "gmail", "id": "a1"}).json()
        [task] = run["actions"]
        assert task["tool_name"] == "create_task" and task["input"]["due_at"].startswith("2026-03-06T17:00")
        assert approve(desk, task)["status"] == "executed"
        assert [t["title"] for t in desk["world"]().tasks] == ["Board pack"]
        done = get(desk, f"/runs/{run['runId']}").json()
        assert done["lifecycle"]["stage"] == "COMPLETED" and done["actions"][0]["verified"] is True


def test_a_synthetic_email_becomes_a_run_and_finishes_with_no_intake_call():
    """The completion target: mail arrives, nobody calls intake, and the run
    goes from received to verified with a person approving twice."""
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        desk["plan"]["value"] = {"calendar_action": "create", "summary": "Intro call",
                                 "requested_start": THU10[0], "requested_end": THU10[1]}
        delivered = post(desk, "/sandbox/deliver", json={
            "from_addr": SOFIA, "subject": "Intro call?", "body": "Could we meet on Thursday at 10:00?"})
        assert delivered.status_code == 200 and get(desk, "/runs").json()["runs"] == []

        worker = IntakeWorker(desk["client"].app, desk["routed"], desk["workflow"],
                              registry=desk["registry"], env={"DESK_INTAKE_WORKER": "on"})
        tick = worker.tick()                                       # no session, no request, no intake call
        assert tick["users"] == [{"user": ALICE, "status": "ok", "opened": 1}], tick

        [row] = get(desk, "/runs").json()["runs"]
        assert row["trigger"] == "worker" and row["lifecycle"] == "AWAITING_APPROVAL"
        run = get(desk, f"/runs/{row['runId']}").json()
        approve(desk, run["actions"][0])
        reply = get(desk, f"/runs/{row['runId']}").json()["actions"][1]
        approve(desk, reply)
        worker.tick()

        done = get(desk, f"/runs/{row['runId']}").json()
        assert done["lifecycle"]["stage"] == "COMPLETED"
        assert [entry["op"] for entry in world.oplog] == [OP_CREATE_EVENT, OP_SEND_EMAIL]
        assert len(world.events) == 1 and len(world.sent) == 1
        assert len(get(desk, "/runs").json()["runs"]) == 1         # the later ticks opened nothing more
        snapshot = get(desk, "/sandbox").json()["world"]
        assert snapshot["isolationViolations"] == [] and len(snapshot["operations"]) == 2


def test_the_worker_reads_status_without_a_session_and_only_for_its_user():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        desk["sign_in"](BOB)
        desk["client"].post("/auth/logout", headers=ORIGIN)       # nobody is signed in
        desk["world"](ALICE).deliver(message_id="a1", from_addr=SOFIA, subject="Board pack",
                                     body="Please note the deadline is Friday.")
        worker = IntakeWorker(desk["client"].app, desk["routed"], desk["workflow"],
                              registry=desk["registry"], env={"DESK_INTAKE_WORKER": "on"})
        served = {entry["user"]: entry["opened"] for entry in worker.tick()["users"]}
        assert served == {ALICE: 1, BOB: 0}
        assert desk["world"](BOB).mail == {"gmail": [], "outlook": []}
        runs = desk["store"].conversations
        assert [row["user_id"] for row in runs.values()] == [1]


def test_with_the_model_switched_off_no_model_call_is_attempted():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        desk["model"]["on"] = False
        run = meeting(desk)                    # the body names one day and one time in full
        assert desk["plan"]["calls"] == 0      # Scriba's extraction was never called
        [event] = run["actions"]
        assert event["tool_name"] == "create_calendar_event" and event["input"]["start"] == THU10[0]
        reads = {i["data"]["tool"]: i["data"] for i in run["timeline"] if i["kind"] == "read"}
        assert reads["model.extract_request"]["error"] == "model_not_configured"
        assert reads["rules.extract_time"]["ok"] is True


def test_a_placeholder_key_is_never_treated_as_a_model(monkeypatch):
    gateway = ScribaGateway()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("DESK_MODEL", raising=False)
    assert gateway.model_configured() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-looks-real-but-is-not")
    monkeypatch.setenv("DESK_MODEL", "off")
    assert gateway.model_configured() is False
    assert gateway.extract_meeting(None, {"subject": "x", "body": "y"}, "UTC") is None
