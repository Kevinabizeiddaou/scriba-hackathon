"""The Desk workflow through Scriba's real machinery.

Real: Scriba's application and routes, session guard, card creation
(``_handle_tool_call`` and the validation gate), the approve route with its
atomic claim, and the execution engine for tasks. In memory: the chat and
action storage (Scriba's own contract-test stores). Scripted: mail, calendars
and the model's meeting extraction; the calendar provider write is a
recording stand-in.

So these prove the workflow's control flow end to end. They are NOT a live
agent run: no model, mailbox or calendar was involved.
"""
import datetime as dt
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest

from desk_overlay import chat_scope
from desk_overlay.availability import Busy
from desk_overlay.gateway import ScribaGateway
from desk_overlay.routes import build_router

from ..fakes import FakeGateway, email

UTC = dt.timezone.utc
ALICE = "alice@example.com"
BOB = "bob@example.com"
NOW = dt.datetime(2027, 3, 1, 8, 0, tzinfo=UTC)
ORIGIN = {"Origin": "http://localhost:5173"}
PLAN = {"calendar_action": "create", "summary": "Intro call",
        "requested_start": "2027-03-04T10:00:00+00:00", "requested_end": "2027-03-04T10:30:00+00:00"}


_WORLDS: list = []


class HybridGateway(ScribaGateway):
    """Scriba's real identity, run and card methods; scripted provider data."""

    def __init__(self, data: FakeGateway) -> None:
        self.data = data

    def _world_user(self, user):
        return self.data.world(user.email)["user"]

    def provider_status(self, request):
        return self.data.users[self.data.acting_as]["status"]

    def preferences(self, user):
        return self.data.preferences(self._world_user(user))

    def list_emails(self, request, user, **kwargs):
        return self.data.list_emails(request, self._world_user(user), **kwargs)

    def google_busy(self, user, account, start, end, timezone):
        return self.data.google_busy(self._world_user(user), account, start, end, timezone)

    def outlook_busy(self, user, account, start, end):
        return self.data.outlook_busy(self._world_user(user), account, start, end)

    def extract_meeting(self, user, item, timezone):
        return self.data.extract_meeting(self._world_user(user), item, timezone)


@contextmanager
def desk_world(*, scope: bool = False):
    from test_contract_chat_tool_lifecycle import InMemoryToolCalls, _engine_record_patches, create_task_db
    from contract_harness import auth_app, login_as, recording

    import app.chat_repository as chat_repo
    from app import chat_service

    class Store(InMemoryToolCalls):
        def __init__(self):
            super().__init__()
            self.conversations, self.messages = {}, []

        def create_conversation(self, *, user_id, title=None, metadata=None, project_id=None):
            row = {"id": len(self.conversations) + 1, "user_id": int(user_id), "title": title,
                   "metadata": metadata or {}, "status": "active"}
            self.conversations[row["id"]] = row
            return dict(row)

        def get_conversation(self, conversation_id, *, user_id):
            row = self.conversations.get(int(conversation_id))
            return dict(row) if row and row["user_id"] == int(user_id) else None

        def list_conversations(self, user_id, *, limit=50):
            return [dict(r) for r in self.conversations.values() if r["user_id"] == int(user_id)][:limit]

        def create_message(self, *, conversation_id, user_id, role, content, **_):
            row = {"id": len(self.messages) + 1, "conversation_id": conversation_id,
                   "user_id": int(user_id), "role": role, "content": content}
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

        def list_tool_calls_for_conversation(self, conversation_id, *, user_id):
            return [dict(r) for r in self.rows.values()
                    if r["conversation_id"] == conversation_id and r["user_id"] == int(user_id)]

    store, data = Store(), FakeGateway()
    created, bundle = create_task_db()
    db_patches = {**_engine_record_patches(), **bundle}
    gateway = HybridGateway(data)
    calendar_write = recording({
        "status": "executed", "action": {"id": 900, "source_item_id": None},
        "result": {"event": {"id": "gevt-1"}, "calendar_result": {"event": {"id": "gevt-1"}}}})

    with ExitStack() as stack:
        for name in ("get_tool_call", "claim_tool_call_for_approval", "update_tool_call",
                     "cancel_tool_call_if_cancellable", "create_conversation", "get_conversation",
                     "list_conversations", "create_message", "list_messages", "create_tool_call",
                     "list_tool_calls_for_conversation"):
            stack.enter_context(patch.object(chat_repo, name, getattr(store, name)))
        stack.enter_context(patch.object(chat_repo, "list_recent_executed_tool_calls",
                                         lambda **kwargs: []))
        client, users = stack.enter_context(auth_app(**db_patches))
        # Scriba's app object is shared by every test in the process, so each
        # world mounts its own router (own gateway and clock) under its own prefix.
        _WORLDS.append(None)
        prefix = f"/t{len(_WORLDS)}"
        client.app.include_router(build_router(gateway, now=lambda: NOW), prefix=prefix)
        if scope:
            chat_scope.enable(app=client.app, gateway=gateway, clock=lambda: NOW)
            stack.callback(chat_scope.disable)

        def sign_in(address, **connections):
            user = login_as(client, users, address)
            data.add_user(user["id"], address, **connections)
            data.acting_as = address
            return user

        yield {"client": client, "data": data, "store": store, "created": created, "prefix": prefix,
               "sign_in": sign_in, "calendar_write": calendar_write, "chat_service": chat_service}


def post(world, path, **kwargs):
    return world["client"].post(f"{world['prefix']}/desk{path}", headers=ORIGIN, **kwargs)


def get(world, path):
    return world["client"].get(f"{world['prefix']}/desk{path}")


# ── case 2: actionable email -> approved, executed, verified task ───────────

def test_actionable_email_to_a_verified_task_through_scribas_approve_route_and_engine():
    with desk_world() as world:
        world["sign_in"](ALICE, google=["alice@gmail.example"], gmail_mail=True)
        world["data"].world(ALICE)["emails"]["gmail"] = [
            email("a1", "Board pack", "Please note the deadline is Friday.",
                  from_addr="Omar <omar@client.example>", account="alice@gmail.example")]

        run = post(world, "/intake", json={"provider": "gmail", "id": "a1"}).json()
        assert run["state"] == "awaiting_approval", run
        action = run["actions"][0]
        assert action["tool_name"] == "create_task" and action["status"] == "awaiting_approval"
        assert world["created"].calls == []                     # nothing happens before approval

        approved = world["client"].post(action["approve"]["path"], json={}, headers=ORIGIN)
        assert approved.status_code == 200, approved.text
        assert approved.json()["tool_call"]["status"] == "executed"
        assert len(world["created"].calls) == 1
        assert world["created"].calls[0]["kwargs"]["title"] == "Board pack"

        after = get(world, f"/runs/{run['runId']}").json()
        assert after["state"] == "completed"
        assert after["actions"][0]["verified"] is True and after["actions"][0]["assistantActionId"]

        # Approving again, and taking the same message in again, repeat nothing.
        world["client"].post(action["approve"]["path"], json={}, headers=ORIGIN)
        again = post(world, "/intake", json={"provider": "gmail", "id": "a1"}).json()
        assert again["duplicate"] is True and again["runId"] == run["runId"]
        assert len(world["created"].calls) == 1 and len(world["store"].rows) == 1


def test_a_rejected_task_proposal_executes_nothing():
    with desk_world() as world:
        world["sign_in"](ALICE, google=["alice@gmail.example"], gmail_mail=True)
        world["data"].world(ALICE)["emails"]["gmail"] = [
            email("a1", "Board pack", "The deadline is Friday.", account="alice@gmail.example")]
        run = post(world, "/intake", json={"provider": "gmail", "id": "a1"}).json()
        card_id = run["actions"][0]["toolCallId"]
        cancelled = world["client"].post(f"/chat/tool-calls/{card_id}/cancel", headers=ORIGIN)
        assert cancelled.status_code == 200, cancelled.text
        late = world["client"].post(f"/chat/tool-calls/{card_id}/approve", json={}, headers=ORIGIN)
        assert late.status_code == 400                          # a cancelled card cannot be approved
        assert world["created"].calls == []
        assert get(world, f"/runs/{run['runId']}").json()["state"] == "cancelled"


def test_another_user_cannot_see_approve_or_advance_the_run():
    with desk_world() as world:
        world["sign_in"](ALICE, google=["alice@gmail.example"], gmail_mail=True)
        world["data"].world(ALICE)["emails"]["gmail"] = [
            email("a1", "Board pack", "The deadline is Friday.", account="alice@gmail.example")]
        run = post(world, "/intake", json={"provider": "gmail", "id": "a1"}).json()
        card_id = run["actions"][0]["toolCallId"]

        world["sign_in"](BOB)
        assert get(world, f"/runs/{run['runId']}").status_code == 404
        assert post(world, f"/runs/{run['runId']}/advance").status_code == 404
        assert world["client"].post(f"/chat/tool-calls/{card_id}/approve", json={},
                                    headers=ORIGIN).status_code == 400
        assert world["created"].calls == []
        assert get(world, "/runs").json()["runs"] == []


def test_intake_from_another_site_is_blocked_by_scribas_guard():
    with desk_world() as world:
        world["sign_in"](ALICE, google=["alice@gmail.example"], gmail_mail=True)
        blocked = world["client"].post(f"{world['prefix']}/desk/intake", json={"provider": "gmail", "id": "a1"},
                                       headers={"Origin": "https://elsewhere.example.test"})
        assert blocked.status_code == 403 and blocked.json()["errorCode"] == "cross_site_blocked"


# ── case 1: meeting request -> event, then the reply ───────────────────────

MEETING = email("m1", "Intro call next week?", "Could we meet on 4 March at 10:00 for 30 minutes?",
                from_addr="Sofia Marchetti <sofia@client.example>", thread="T-m1",
                account="alice@gmail.example")
CONNECTED = {"providers": {
    "gmail": {"connected": True, "available": True, "configured": True, "email": "alice@gmail.example"},
    "google_calendar": {"connected": True, "available": True, "configured": True,
                        "email": "alice@gmail.example"}},
    "emailAccounts": [{"provider": "gmail", "email": "alice@gmail.example", "label": "Gmail",
                       "providerAccountId": "alice@gmail.example", "isPrimary": True}]}


@contextmanager
def meeting_world(**busy):
    with desk_world(scope=True) as world:
        world["sign_in"](ALICE, google=["alice@gmail.example"], outlook="alice@contoso.example",
                         gmail_mail=True)
        data = world["data"].world(ALICE)
        data["emails"]["gmail"] = [MEETING]
        data["meeting_plan"] = PLAN
        data.update(busy)
        service = world["chat_service"]
        with patch.object(service, "_safe_provider_status", lambda account_email: CONNECTED), \
                patch.object(service, "execute_action", world["calendar_write"]):
            yield world


def test_meeting_request_event_is_created_before_any_reply_is_proposed():
    with meeting_world() as world:
        run = post(world, "/intake", json={"provider": "gmail", "id": "m1"}).json()
        assert [a["tool_name"] for a in run["actions"]] == ["create_calendar_event"], run
        event = run["actions"][0]
        assert event["status"] == "awaiting_approval", event
        assert event["input"]["attendees"] == ["sofia@client.example"]
        assert event["availability"]["free"] is True            # Scriba's gate, with the Desk check
        assert world["calendar_write"].calls == []

        # No reply can be proposed before the event exists.
        assert post(world, f"/runs/{run['runId']}/advance").json()["actions"][0]["tool_name"] == \
            "create_calendar_event"
        assert len(world["store"].rows) == 1

        approved = world["client"].post(event["approve"]["path"], json={}, headers=ORIGIN)
        assert approved.status_code == 200, approved.text
        assert approved.json()["tool_call"]["status"] == "executed"
        assert len(world["calendar_write"].calls) == 1
        sent = world["calendar_write"].calls[0]["kwargs"]["action"]
        assert sent["action_type"] == "create_calendar_event"

        after = post(world, f"/runs/{run['runId']}/advance").json()
        reply = next(a for a in after["actions"] if a["tool_name"] == "send_email")
        assert reply["input"]["to"] == "sofia@client.example"
        assert reply["input"]["thread_id"] == "T-m1" and reply["input"]["email_id"] == "m1"
        assert reply["status"] in ("awaiting_approval", "needs_info"), reply
        assert len(world["calendar_write"].calls) == 1          # proposing a reply sends nothing


def test_a_conflict_found_at_approval_stops_the_booking():
    with meeting_world() as world:
        run = post(world, "/intake", json={"provider": "gmail", "id": "m1"}).json()
        event = run["actions"][0]
        # Free when proposed; the Outlook calendar fills up before the user approves.
        world["data"].world(ALICE)["outlook_busy"] = [Busy(
            dt.datetime(2027, 3, 4, 10, 0, tzinfo=UTC), dt.datetime(2027, 3, 4, 11, 0, tzinfo=UTC),
            "outlook", "alice@contoso.example", "Board call")]
        held = world["client"].post(event["approve"]["path"], json={}, headers=ORIGIN).json()["tool_call"]
        assert held["status"] == "needs_info" and held["output"]["error_code"] == "calendar_conflict"
        assert world["calendar_write"].calls == []
        view = get(world, f"/runs/{run['runId']}").json()
        assert view["state"] == "awaiting_approval" and "advance" not in view["next"]


def test_a_conflict_at_intake_proposes_no_event_at_all():
    conflict = [Busy(dt.datetime(2027, 3, 4, 9, 30, tzinfo=UTC), dt.datetime(2027, 3, 4, 10, 30, tzinfo=UTC),
                     "outlook", "alice@contoso.example", "Board call")]
    with meeting_world(outlook_busy=conflict) as world:
        run = post(world, "/intake", json={"provider": "gmail", "id": "m1"}).json()
        assert run["actions"] == [] and run["held"]["reason"] == "calendar_conflict"
        assert world["store"].rows == {} and world["calendar_write"].calls == []


def test_an_unreadable_calendar_at_intake_proposes_no_event():
    with meeting_world(outlook_error="reconnect_required") as world:
        run = post(world, "/intake", json={"provider": "gmail", "id": "m1"}).json()
        assert run["actions"] == [] and run["held"]["reason"] == "availability_unknown"
        assert world["store"].rows == {}


# ── sweep on Scriba's real app ─────────────────────────────────────────────

def test_a_sweep_opens_runs_whose_cards_execute_once_through_scribas_engine():
    with desk_world() as world:
        world["sign_in"](ALICE, google=["alice@gmail.example"], gmail_mail=True)
        world["data"].world(ALICE)["emails"]["gmail"] = [
            email("a1", "Board pack", "Please note the deadline is Friday.",
                  from_addr="Omar <omar@client.example>", account="alice@gmail.example"),
            email("n1", "Weekly digest", "Unsubscribe here.",
                  from_addr="News <no-reply@news.example>", account="alice@gmail.example")]

        swept = post(world, "/intake/sweep", json={}).json()
        assert swept["status"] == "completed" and [r["id"] for r in swept["opened"]] == ["a1"], swept
        assert world["created"].calls == []                     # a sweep proposes, it does not act

        run = get(world, f"/runs/{swept['opened'][0]['runId']}").json()
        action = run["actions"][0]
        assert action["tool_name"] == "create_task" and action["status"] == "awaiting_approval"
        approved = world["client"].post(action["approve"]["path"], json={}, headers=ORIGIN)
        assert approved.status_code == 200, approved.text
        assert len(world["created"].calls) == 1

        again = post(world, "/intake/sweep", json={}).json()
        assert again["opened"] == [] and again["existing"] == 1
        assert len(world["created"].calls) == 1 and len(world["store"].rows) == 1


def test_a_sweep_from_another_site_is_blocked_by_scribas_guard():
    with desk_world() as world:
        world["sign_in"](ALICE, google=["alice@gmail.example"], gmail_mail=True)
        blocked = world["client"].post(f"{world['prefix']}/desk/intake/sweep", json={},
                                       headers={"Origin": "https://elsewhere.example.test"})
        assert blocked.status_code == 403 and blocked.json()["errorCode"] == "cross_site_blocked"
