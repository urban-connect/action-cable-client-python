import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from websockets.exceptions import InvalidURI
from websockets.uri import parse_uri

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

# Offered during the websocket handshake, the same way the official client does.
SUBPROTOCOL = "actioncable-v1-json"


class PingTimeout(TimeoutError):
  """The server has not pinged for longer than the ping deadline."""


class ProtocolError(Exception):
  """The server on the other end does not speak ActionCable."""


class Identifier:
  """Names one channel subscription: the channel class plus its params.

  The server echoes the identifier back on every frame of the subscription,
  so identifiers are compared by content, not by their JSON spelling.
  """

  def __init__(self, channel: str, /, **params: Any):
    if "channel" in params:
      raise ValueError("`channel` is the first argument and cannot also be a param")

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
  except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
    # RecursionError: json.loads gives up on absurdly nested input.
    return Unknown(text)


def check_subprotocol(websocket, offered: list[str]) -> None:
  """Refuse a server that did not pick the ActionCable subprotocol.

  Only applies when the default was offered; a caller who passes their own
  `subprotocols` has taken the negotiation over.
  """
  if offered == [SUBPROTOCOL] and websocket.subprotocol != SUBPROTOCOL:
    raise ProtocolError(f"server did not accept the {SUBPROTOCOL} subprotocol")


def authenticated_url(url: str, token: str | None) -> str:
  """Append an access token to the URL as the `token` query parameter.

  The token ends up in the request line, so it shows in the access logs of the
  server and of every proxy on the way. Prefer a header where the server
  accepts one, and never use this over plain `ws://` outside of tests.
  """
  if not token:
    return url

  separator = "&" if "?" in url else "?"
  authenticated = f"{url}{separator}token={quote(token, safe='')}"

  # Checked on the finished URL, with the same parser the connection uses,
  # because websockets quotes the whole URL in its own error. Raised outside
  # the handler so that error, which carries the token, is not kept as context.
  try:
    parse_uri(authenticated)
  except InvalidURI as error:
    reason = error.msg
  else:
    return authenticated

  raise ValueError(f"{url!r} isn't a valid URI: {reason}")
