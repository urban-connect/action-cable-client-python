import asyncio
import json
import threading
from unittest.mock import AsyncMock

import pytest
from websockets.sync.server import serve

from action_cable_client import aio
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


async def test_connects_with_token(cable):
  async with aio.connect(cable.url, token="secret") as connection:
    assert await connection.receive() == Welcome(sid="fake")

  assert cable.requests.get(timeout=5) == "/cable?token=secret"


async def test_offers_the_action_cable_subprotocol(cable):
  async with aio.connect(cable.url) as connection:
    await connection.receive()

    assert connection.websocket.subprotocol == "actioncable-v1-json"

  assert cable.subprotocols.get(timeout=5) == "actioncable-v1-json"


async def test_subscription_is_confirmed(cable):
  async with aio.connect(cable.url) as connection:
    await connection.receive()
    await connection.subscribe(ROOM)

    assert await connection.receive() == ConfirmSubscription(ROOM)


async def test_subscription_is_rejected(cable):
  async with aio.connect(cable.url) as connection:
    await connection.receive()
    await connection.subscribe(OTHER)

    assert await connection.receive() == RejectSubscription(OTHER)


async def test_receives_broadcast_and_performs_action(cable):
  async with aio.connect(cable.url) as connection:
    await connection.receive()
    await connection.subscribe(ROOM)
    await connection.receive()

    cable.broadcast(ROOM, {"kind": "message.created", "data": {"id": 7}})

    event = await connection.receive()
    assert event == Message(ROOM, {"kind": "message.created", "data": {"id": 7}})

    await connection.perform(event.identifier, "mark_as_read", {"id": 7})

    loop = asyncio.get_running_loop()
    frame = await loop.run_in_executor(None, cable.received.get, True, 5)
    assert frame["command"] == "subscribe"
    frame = await loop.run_in_executor(None, cable.received.get, True, 5)
    assert frame["command"] == "message"
    assert json.loads(frame["data"]) == {"action": "mark_as_read", "id": 7}


async def test_iterates_over_events(cable):
  events = []

  async with aio.connect(cable.url) as connection:
    async for event in connection:
      events.append(event)

      if isinstance(event, Welcome):
        cable.disconnect(reason="server_restart", reconnect=True)
      else:
        break

  assert events == [Welcome(sid="fake"), Disconnect("server_restart", True)]


async def test_ping_timeout_when_server_is_silent(cable):
  async with aio.connect(cable.url, ping_deadline=0.2) as connection:
    await connection.receive()

    with pytest.raises(aio.PingTimeout):
      await connection.receive()


async def test_buffered_pings_count_after_a_slow_caller(cable):
  async with aio.connect(cable.url, ping_deadline=0.5) as connection:
    await connection.receive()

    for _ in range(3):
      await asyncio.sleep(0.25)
      cable.ping()

    await asyncio.sleep(0.1)

    assert isinstance(await connection.receive(), Ping)
    assert isinstance(await connection.receive(), Ping)


async def test_refuses_a_server_without_the_subprotocol():
  def session(websocket):
    websocket.send('{"type": "welcome"}')

  with serve(session, "127.0.0.1", 0) as server:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"ws://127.0.0.1:{server.socket.getsockname()[1]}/cable"

    with pytest.raises(ProtocolError):
      async with aio.connect(url):
        pass

    server.shutdown()


async def test_iteration_ends_on_a_clean_close(cable):
  events = []

  async with aio.connect(cable.url) as connection:
    async for event in connection:
      events.append(event)

      # Off the event loop: closing waits for this client to answer.
      await asyncio.get_running_loop().run_in_executor(None, cable.close_clients)

  assert events == [Welcome(sid="fake")]


async def test_ping_pushes_the_deadline(cable):
  async with aio.connect(cable.url, ping_deadline=0.5) as connection:
    await connection.receive()

    for _ in range(4):
      await asyncio.sleep(0.2)
      cable.ping()
      assert isinstance(await connection.receive(), Ping)


async def test_wraps_an_existing_websocket():
  websocket = AsyncMock()
  connection = aio.Connection(websocket)

  await connection.perform(ROOM, "appear")

  frame = json.loads(websocket.send.call_args[0][0])
  assert frame["command"] == "message"
  assert json.loads(frame["data"]) == {"action": "appear"}
