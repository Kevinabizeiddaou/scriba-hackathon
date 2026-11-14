"""Make ``desk_overlay`` importable when pytest runs from ``backend/``, and
keep every test in this suite off the network."""
import socket
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_LOOPBACK = ("127.0.0.1", "::1", "localhost")


@pytest.fixture(autouse=True)
def no_outbound_connections(monkeypatch):
    """A test that opens a socket to another host fails.

    These tests are meant to reach no provider, no model and no other
    service. Connections made through Python's socket layer are checked
    here; loopback is allowed (the test client uses it). The test then fails
    with the address it tried, instead of quietly depending on the network.
    """
    attempts = []
    real_connect = socket.socket.connect

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if str(host) not in _LOOPBACK:
            attempts.append(address)
            raise OSError(f"outbound connection blocked in tests: {address!r}")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield
    assert attempts == [], f"this test tried to reach another host: {attempts}"
