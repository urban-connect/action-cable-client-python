import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import websockets

from action_cable_client import protocol
from action_cable_client.protocol import Event, Identifier, Ping, PingTimeout

# asyncio transport. One Connection wraps one websocket; reconnecting is the
# caller's job (open a new connection and subscribe again).


BUFFERED_READ_SECONDS = 0.01


class Connection:
  def __init__(
    self,
    websocket,
    ping_deadline: float | None = protocol.PING_DEADLINE_SECONDS,
  ):
    self.websocket = websocket
    self.ping_deadline = ping_deadline
    self.last_ping_at = time.monotonic()

  async def subscribe(self, identifier: Identifier) -> None:
    await self.websocket.send(protocol.subscribe(identifier))

  async def unsubscribe(self, identifier: Identifier) -> None:
    await self.websocket.send(protocol.unsubscribe(identifier))

  async def perform(
    self, identifier: Identifier, action: str, data: dict | None = None
  ) -> None:
    await self.websocket.send(protocol.perform(identifier, action, data))

  async def receive(self) -> Event:
    """Wait for the next event.

    Raises PingTimeout when the server has been silent for longer than
    `ping_deadline`, and whatever the websocket raises when it is closed.
    """
    if self.ping_deadline is None:
      raw = await self.websocket.recv()
    else:
      remaining = self.ping_deadline - (time.monotonic() - self.last_ping_at)

      # Past the deadline we still read what has already arrived: a caller
      # that was busy for a while must not make a pinging server look dead.
      # wait_for needs a positive timeout to let recv() run at all.
      try:
        raw = await asyncio.wait_for(
          self.websocket.recv(), timeout=max(remaining, BUFFERED_READ_SECONDS)
        )
      except asyncio.TimeoutError:
        raise PingTimeout(
          f"no ping from server for {self.ping_deadline:g} seconds"
        ) from None

    event = protocol.decode(raw)

    if isinstance(event, Ping):
      self.last_ping_at = time.monotonic()

    return event

  def __aiter__(self) -> "Connection":
    return self

  async def __anext__(self) -> Event:
    try:
      return await self.receive()
    except websockets.ConnectionClosedOK:
      raise StopAsyncIteration from None


@asynccontextmanager
async def connect(
  url: str,
  token: str | None = None,
  ping_deadline: float | None = protocol.PING_DEADLINE_SECONDS,
  **kwargs,
) -> AsyncIterator[Connection]:
  """Open a connection. Extra keyword arguments go to `websockets.connect`."""
  offered = kwargs.setdefault("subprotocols", [protocol.SUBPROTOCOL])

  async with websockets.connect(
    protocol.authenticated_url(url, token), **kwargs
  ) as websocket:
    protocol.check_subprotocol(websocket, offered)

    yield Connection(websocket, ping_deadline=ping_deadline)
