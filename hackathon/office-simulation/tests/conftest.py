"""Tests of the simulator itself. No Scriba, no Desk backend, no network
beyond 127.0.0.1 (the stand-in backend in ``officesim.fakes``), except the
tests marked ``live``, which start the real sandbox backend when it is
configured and are skipped when it is not."""
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from officesim import oracle  # noqa: E402
from officesim.fakes import empty_world  # noqa: E402
from officesim.office import OfficeClock, build_office  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "live: starts the real sandbox backend (skipped when not configured)")


@pytest.fixture(autouse=True)
def no_outbound_connections(monkeypatch):
    """A test that reaches another host fails."""
    real_connect = socket.socket.connect
    attempts = []

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if str(host) not in ("127.0.0.1", "::1", "localhost"):
            attempts.append(address)
            raise OSError(f"outbound connection blocked in tests: {address!r}")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield
    assert attempts == [], f"this test tried to reach another host: {attempts}"


@pytest.fixture(autouse=True)
def stand_in_password(request, monkeypatch):
    """The stand-in backend accepts anything; the real sandbox (``live``
    tests) needs the seeded user's own password, read from the Scriba checkout."""
    if request.node.get_closest_marker("live"):
        monkeypatch.delenv("OFFICESIM_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("OFFICESIM_PASSWORD", "stand-in-backend-accepts-anything")


@pytest.fixture
def spec():
    return build_office()


@pytest.fixture
def clock(spec):
    return OfficeClock(spec["day"], spec["timezone"])


@pytest.fixture
def world(spec):
    """The office at 08:00, in the shape of the sandbox world's state."""
    return empty_world(spec)


def make_action(tool, status="executed", *, card=1, purpose=None, data=None, verified=True, output=None,
                slots=None, approved=True):
    return {"toolCallId": card, "tool_name": tool, "status": status, "purpose": purpose, "input": data or {},
            "output": output or {}, "verified": verified and status == "executed",
            "verification": {"method": "sandbox_readback", "verified": verified} if status == "executed" else None,
            "attempts": 1 if status in ("executed", "failed") else 0, "proposedSlots": slots, "held": False,
            "outcomeUnknown": False, "errorCode": None, "error": None,
            "decisions": [{"decision": "approve", "by": "alice@example.com"}] if approved and status != "awaiting_approval" else []}


def make_run(run_id, message_id, actions, *, stage="COMPLETED", state="completed", held=None, draft=None):
    return {"runId": run_id, "email": {"provider": "gmail", "email_id": message_id}, "actions": actions,
            "lifecycle": {"stage": stage}, "state": state, "held": held, "draftRequest": draft,
            "simulated": True, "followUps": [], "flags": [], "timeline": []}


def make_request(spec, clock, world, expect, *, message_id="m1", sender="mei", to="work", thread="thread-m1",
                 arrived="D+0 08:30"):
    from officesim.office import person

    provider, account = oracle.mailbox_of(spec, to)
    who = person(sender)
    return {"id": message_id, "status": "delivered", "sender": sender, "senderName": who["name"],
            "senderEmail": who["email"].lower(), "provider": provider, "account": account, "thread": thread,
            "subject": "Subject", "expect": expect,
            "resolved": oracle.resolve(expect, spec=spec, clock=clock, state=world, mailbox=to),
            "arrivedAt": oracle.ref_time(clock, arrived).isoformat(), "stateAtArrival": world,
            "human": None, "interrupt": None, "needsWork": True}
