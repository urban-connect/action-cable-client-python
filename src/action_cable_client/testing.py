import json
import threading
from queue import Queue

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from action_cable_client.protocol import SUBPROTOCOL, Identifier

# A tiny ActionCable server for tests. It welcomes every client, confirms (or
# rejects) subscriptions and records every frame the client sends. It runs in
# a thread, so it serves the asyncio and the blocking transport alike.


class FakeCable:
  def __init__(self, reject: list[Identifier] | None = None):
    self.reject = reject or []
    self.received: Queue = Queue()
    self.requests: Queue = Queue()
    self.subprotocols: Queue = Queue()
    self.subscribed = threading.Event()
    self._clients: list = []
    self._server = serve(self._session, "127.0.0.1", 0, subprotocols=[SUBPROTOCOL])
    self.port = self._server.socket.getsockname()[1]
    self.url = f"ws://127.0.0.1:{self.port}/cable"

    threading.Thread(target=self._server.serve_forever, daemon=True).start()

  def _session(self, websocket) -> None:
    self._clients.append(websocket)
    self.requests.put(websocket.request.path)
    self.subprotocols.put(websocket.subprotocol)

    websocket.send(json.dumps({"type": "welcome", "sid": "fake"}))

    for raw in websocket:
      data = json.loads(raw)
      self.received.put(data)

      if data.get("command") == "subscribe":
        identifier = Identifier.decode(data["identifier"])
        kind = (
          "reject_subscription" if identifier in self.reject else "confirm_subscription"
        )

        websocket.send(json.dumps({"type": kind, "identifier": data["identifier"]}))
        self.subscribed.set()

  def _send_all(self, frame: dict) -> None:
    for websocket in list(self._clients):
      try:
        websocket.send(json.dumps(frame))
      except ConnectionClosed:
        self._clients.remove(websocket)

  def broadcast(self, identifier: Identifier, message) -> None:
    """Send a channel message to every connected client."""
    self._send_all({"identifier": identifier.encode(), "message": message})

  def ping(self, timestamp: int = 0) -> None:
    self._send_all({"type": "ping", "message": timestamp})

  def disconnect(self, reason: str = "server_restart", reconnect: bool = True) -> None:
    self._send_all({"type": "disconnect", "reason": reason, "reconnect": reconnect})

  def stop(self) -> None:
    self._server.shutdown()

  def __enter__(self):
    return self

  def __exit__(self, *exc) -> None:
    self.stop()
