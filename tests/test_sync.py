import json
import threading
import time

import pytest
from websockets.exceptions import ConnectionClosedOK
from websockets.sync.server import serve

from action_cable_client import sync
from action_cable_client.protocol import (
  ConfirmSubscription,
  Disconnect,
  Identifier,
  Message,
  Ping,
  ProtocolError,
  RejectSubscription,
  Welcome,
)
from action_cable_client.testing import FakeCable

ROOM = Identifier("ChatChannel", room_id=1)
OTHER = Identifier("ChatChannel", room_id=2)


@pytest.fixture
def cable():
  with FakeCable(reject=[OTHER]) as cable:
    yield cable


def test_connects_with_token(cable):
  with sync.connect(cable.url, token="secret") as connection:
    assert connection.receive(timeout=5) == Welcome(sid="fake")

  assert cable.requests.get(timeout=5) == "/cable?token=secret"


def test_offers_the_action_cable_subprotocol(cable):
  with sync.connect(cable.url) as connection:
    connection.receive(timeout=5)

    assert connection.websocket.subprotocol == "actioncable-v1-json"

  assert cable.subprotocols.get(timeout=5) == "actioncable-v1-json"


def test_subscription_is_confirmed(cable):
  with sync.connect(cable.url) as connection:
    connection.receive(timeout=5)
    connection.subscribe(ROOM)

    assert connection.receive(timeout=5) == ConfirmSubscription(ROOM)


def test_subscription_is_rejected(cable):
  with sync.connect(cable.url) as connection:
    connection.receive(timeout=5)
    connection.subscribe(OTHER)

    assert connection.receive(timeout=5) == RejectSubscription(OTHER)


def test_receives_broadcast_and_performs_action(cable):
  with sync.connect(cable.url) as connection:
    connection.receive(timeout=5)
    connection.subscribe(ROOM)
    connection.receive(timeout=5)

    cable.broadcast(ROOM, {"kind": "message.created", "data": {"id": 7}})

    event = connection.receive(timeout=5)
    assert event == Message(ROOM, {"kind": "message.created", "data": {"id": 7}})

    connection.perform(event.identifier, "mark_as_read", {"id": 7})

    assert cable.received.get(timeout=5)["command"] == "subscribe"
    frame = cable.received.get(timeout=5)
    assert frame["command"] == "message"
    assert json.loads(frame["data"]) == {"action": "mark_as_read", "id": 7}


def test_receive_returns_none_on_timeout(cable):
  with sync.connect(cable.url) as connection:
    connection.receive(timeout=5)

    assert connection.receive(timeout=0.05) is None


def test_disconnect_is_surfaced(cable):
  with sync.connect(cable.url) as connection:
    connection.receive(timeout=5)
    cable.disconnect(reason="server_restart", reconnect=True)

    assert connection.receive(timeout=5) == Disconnect("server_restart", True)


def test_ping_timeout_when_server_is_silent(cable):
  with sync.connect(cable.url, ping_deadline=0.2) as connection:
    connection.receive(timeout=5)

    with pytest.raises(sync.PingTimeout):
      while True:
        connection.receive(timeout=0.05)


def test_ping_timeout_without_receive_timeout(cable):
  with sync.connect(cable.url, ping_deadline=0.2) as connection:
    connection.receive()

    with pytest.raises(sync.PingTimeout):
      connection.receive()


def test_buffered_pings_count_after_a_slow_caller(cable):
  with sync.connect(cable.url, ping_deadline=0.5) as connection:
    connection.receive(timeout=5)

    for _ in range(3):
      time.sleep(0.25)
      cable.ping()

    time.sleep(0.1)

    assert isinstance(connection.receive(timeout=1), Ping)
    assert isinstance(connection.receive(timeout=1), Ping)


def test_refuses_a_server_without_the_subprotocol():
  def session(websocket):
    websocket.send('{"type": "welcome"}')

  with serve(session, "127.0.0.1", 0) as server:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"ws://127.0.0.1:{server.socket.getsockname()[1]}/cable"

    with pytest.raises(ProtocolError), sync.connect(url):
      pass

    with sync.connect(url, subprotocols=None) as connection:
      assert connection.receive(timeout=5) == Welcome()

    server.shutdown()


def test_clean_close_raises(cable):
  with sync.connect(cable.url) as connection:
    connection.receive(timeout=5)
    cable.close_clients()

    with pytest.raises(ConnectionClosedOK):
      connection.receive(timeout=5)


def test_ping_pushes_the_deadline(cable):
  with sync.connect(cable.url, ping_deadline=0.5) as connection:
    connection.receive(timeout=5)

    for _ in range(4):
      assert connection.receive(timeout=0.2) is None
      cable.ping()
      assert isinstance(connection.receive(timeout=5), Ping)
