import json
from dataclasses import dataclass, field
from typing import Any

# The ActionCable wire protocol, without any I/O.
#
# Everything here turns Python values into the text frames a client sends and
# server frames into typed events. The transports (`aio`, `sync`) only move
# those frames over a websocket, so both speak exactly the same protocol:
#
#   connect -> Welcome -> subscribe -> ConfirmSubscription -> Message / perform
#
# The server pings every few seconds; a client that stops seeing pings should
# treat the connection as dead (see PING_DEADLINE_SECONDS).

PING_DEADLINE_SECONDS = 60.0


class Identifier:
  """Names one channel subscription: the channel class plus its params.

  The server echoes the identifier back on every frame of the subscription,
  so identifiers are compared by content, not by their JSON spelling.
  """

  def __init__(self, channel: str, **params: Any):
    self.channel = channel
    self.params = params

  def encode(self) -> str:
    return json.dumps({"channel": self.channel, **self.params})

  @classmethod
  def decode(cls, raw: str) -> "Identifier":
    data = json.loads(raw)
    channel = data.pop("channel")

    return cls(channel, **data)

  def _key(self) -> str:
    return json.dumps({"channel": self.channel, **self.params}, sort_keys=True)

  def __eq__(self, other: object) -> bool:
    if not isinstance(other, Identifier):
      return NotImplemented

    return self._key() == other._key()

  def __hash__(self) -> int:
    return hash(self._key())

  def __repr__(self) -> str:
    params = "".join(f", {key}={value!r}" for key, value in self.params.items())

    return f"Identifier({self.channel!r}{params})"


@dataclass(frozen=True)
class Welcome:
  sid: str | None = None


@dataclass(frozen=True)
class Ping:
  timestamp: int | None = None


@dataclass(frozen=True)
class ConfirmSubscription:
  identifier: Identifier


@dataclass(frozen=True)
class RejectSubscription:
  identifier: Identifier


@dataclass(frozen=True)
class Disconnect:
  reason: str | None = None
  reconnect: bool = True


@dataclass(frozen=True)
class Message:
  identifier: Identifier
  payload: Any = field(hash=False)


@dataclass(frozen=True)
class Unknown:
  """A frame that is not valid ActionCable. Carries the raw text for logging."""

  raw: str = field(hash=False)


Event = (
  Welcome
  | Ping
  | ConfirmSubscription
  | RejectSubscription
  | Disconnect
  | Message
  | Unknown
)


def subscribe(identifier: Identifier) -> str:
  return json.dumps({"command": "subscribe", "identifier": identifier.encode()})


def unsubscribe(identifier: Identifier) -> str:
  return json.dumps({"command": "unsubscribe", "identifier": identifier.encode()})


def perform(identifier: Identifier, action: str, data: dict | None = None) -> str:
  """Call a channel action. `data` becomes the action's argument."""
  return json.dumps(
    {
      "command": "message",
      "identifier": identifier.encode(),
      "data": json.dumps((data or {}) | {"action": action}),
    }
  )


def decode(raw: str | bytes) -> Event:
  """Turn one server frame into an event.

  Never raises: a frame we cannot make sense of comes back as `Unknown`, since
  one bad frame is not worth dropping the connection for.
  """
  text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw

  try:
    data = json.loads(text)

    if not isinstance(data, dict):
      return Unknown(text)

    match data.get("type"):
      case "welcome":
        return Welcome(sid=data.get("sid"))
      case "ping":
        return Ping(timestamp=data.get("message"))
      case "confirm_subscription":
        return ConfirmSubscription(Identifier.decode(data["identifier"]))
      case "reject_subscription":
        return RejectSubscription(Identifier.decode(data["identifier"]))
      case "disconnect":
        return Disconnect(
          reason=data.get("reason"), reconnect=bool(data.get("reconnect", True))
        )
      case None if "identifier" in data and "message" in data:
        return Message(Identifier.decode(data["identifier"]), data["message"])
      case _:
        return Unknown(text)
  except (ValueError, KeyError, TypeError, AttributeError):
    return Unknown(text)


def authenticated_url(url: str, token: str | None) -> str:
  """Append an access token to the URL as the `token` query parameter."""
  if not token:
    return url

  separator = "&" if "?" in url else "?"

  return f"{url}{separator}token={token}"
