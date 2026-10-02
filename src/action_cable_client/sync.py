import time
from collections.abc import Iterator
from contextlib import contextmanager

from websockets.sync.client import connect as websocket_connect

from action_cable_client import protocol
from action_cable_client.protocol import Event, Identifier, Ping

# Blocking transport for threaded programs. One Connection wraps one
# websocket; reconnecting is the caller's job (open a new connection and
# subscribe again).


class PingTimeout(TimeoutError):
  pass


class Connection:
  def __init__(
    self,
    websocket,
    ping_deadline: float | None = protocol.PING_DEADLINE_SECONDS,
  ):
    self.websocket = websocket
    self.ping_deadline = ping_deadline
    self.last_ping_at = time.monotonic()

  def subscribe(self, identifier: Identifier) -> None:
    self.websocket.send(protocol.subscribe(identifier))

  def unsubscribe(self, identifier: Identifier) -> None:
    self.websocket.send(protocol.unsubscribe(identifier))

  def perform(
    self, identifier: Identifier, action: str, data: dict | None = None
  ) -> None:
    self.websocket.send(protocol.perform(identifier, action, data))

  def receive(self, timeout: float | None = None) -> Event | None:
    """Wait for the next event, at most `timeout` seconds.

    Returns None when nothing arrived in time, so a caller can poll its own
    stop flag between calls. Raises PingTimeout when the server has been
    silent for longer than `ping_deadline`, and whatever the websocket raises
    when it is closed.
    """
    wait = timeout

    if self.ping_deadline is not None:
      remaining = self.ping_deadline - (time.monotonic() - self.last_ping_at)

      if remaining <= 0:
        raise PingTimeout(f"no ping from server for {int(self.ping_deadline)} seconds")

      wait = remaining if timeout is None else min(timeout, remaining)

    try:
      raw = self.websocket.recv(timeout=wait)
    except TimeoutError:
      if timeout is None or wait < timeout:
        raise PingTimeout(
          f"no ping from server for {int(self.ping_deadline or 0)} seconds"
        ) from None

      return None

    event = protocol.decode(raw)

    if isinstance(event, Ping):
      self.last_ping_at = time.monotonic()

    return event


@contextmanager
def connect(
  url: str,
  token: str | None = None,
  ping_deadline: float | None = protocol.PING_DEADLINE_SECONDS,
  **kwargs,
) -> Iterator[Connection]:
  """Open a connection. Extra keyword arguments go to `websockets.sync.client.connect`."""
  with websocket_connect(protocol.authenticated_url(url, token), **kwargs) as websocket:
    yield Connection(websocket, ping_deadline=ping_deadline)
