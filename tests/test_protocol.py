import json

from action_cable_client import protocol
from action_cable_client.protocol import (
  ConfirmSubscription,
  Disconnect,
  Identifier,
  Message,
  Ping,
  RejectSubscription,
  Unknown,
  Welcome,
)

ROOM = Identifier("ChatChannel", room_id=1)


class TestIdentifier:
  def test_encode(self):
    assert json.loads(ROOM.encode()) == {
      "channel": "ChatChannel",
      "room_id": 1,
    }

  def test_decode_round_trip(self):
    assert Identifier.decode(ROOM.encode()) == ROOM

  def test_equality_ignores_json_spelling(self):
    raw = '{"room_id": 1,   "channel": "ChatChannel"}'

    assert Identifier.decode(raw) == ROOM
    assert hash(Identifier.decode(raw)) == hash(ROOM)

  def test_different_params_are_different_identifiers(self):
    assert Identifier("ChatChannel", room_id=2) != ROOM

  def test_params_may_shadow_argument_names(self):
    raw = '{"channel": "ChatChannel", "self": 1, "cls": 2}'

    assert Identifier.decode(raw).params == {"self": 1, "cls": 2}

  def test_usable_as_dict_key(self):
    handlers = {ROOM: "room 1"}

    assert handlers[Identifier("ChatChannel", room_id=1)] == "room 1"


class TestCommands:
  def test_subscribe(self):
    frame = json.loads(protocol.subscribe(ROOM))

    assert frame["command"] == "subscribe"
    assert Identifier.decode(frame["identifier"]) == ROOM

  def test_unsubscribe(self):
    frame = json.loads(protocol.unsubscribe(ROOM))

    assert frame["command"] == "unsubscribe"
    assert Identifier.decode(frame["identifier"]) == ROOM

  def test_perform(self):
    frame = json.loads(protocol.perform(ROOM, "appear"))

    assert frame["command"] == "message"
    assert Identifier.decode(frame["identifier"]) == ROOM
    assert json.loads(frame["data"]) == {"action": "appear"}

  def test_perform_with_data(self):
    frame = json.loads(protocol.perform(ROOM, "mark_as_read", {"id": 7}))

    assert json.loads(frame["data"]) == {"action": "mark_as_read", "id": 7}


class TestDecode:
  def test_welcome(self):
    assert protocol.decode('{"type": "welcome", "sid": "abc"}') == Welcome(sid="abc")

  def test_ping(self):
    assert protocol.decode('{"type": "ping", "message": 1234}') == Ping(timestamp=1234)

  def test_confirm_subscription(self):
    frame = json.dumps({"type": "confirm_subscription", "identifier": ROOM.encode()})

    assert protocol.decode(frame) == ConfirmSubscription(ROOM)

  def test_reject_subscription(self):
    frame = json.dumps({"type": "reject_subscription", "identifier": ROOM.encode()})

    assert protocol.decode(frame) == RejectSubscription(ROOM)

  def test_disconnect(self):
    frame = '{"type": "disconnect", "reason": "unauthorized", "reconnect": false}'

    assert protocol.decode(frame) == Disconnect(reason="unauthorized", reconnect=False)

  def test_message(self):
    payload = {"kind": "message.created", "data": {"id": 7}}
    frame = json.dumps({"identifier": ROOM.encode(), "message": payload})

    assert protocol.decode(frame) == Message(ROOM, payload)

  def test_bytes(self):
    assert protocol.decode(b'{"type": "welcome", "sid": "abc"}') == Welcome(sid="abc")

  def test_invalid_json_is_unknown(self):
    assert protocol.decode("not json") == Unknown("not json")

  def test_unexpected_shape_is_unknown(self):
    assert isinstance(protocol.decode('{"unexpected": "shape"}'), Unknown)
    assert isinstance(protocol.decode("[1, 2]"), Unknown)

  def test_unknown_type_is_unknown(self):
    assert isinstance(protocol.decode('{"type": "mystery"}'), Unknown)

  def test_absurdly_nested_frame_is_unknown(self):
    assert isinstance(protocol.decode("[" * 200000), Unknown)

    frame = '{"identifier": "{}", "message": ' + "[" * 200000 + "}"
    assert isinstance(protocol.decode(frame), Unknown)

  def test_broken_identifier_is_unknown(self):
    frame = '{"type": "confirm_subscription", "identifier": "not json"}'

    assert isinstance(protocol.decode(frame), Unknown)


class TestAuthenticatedUrl:
  def test_appends_token(self):
    url = protocol.authenticated_url("wss://ws.example.com/cable", "secret")

    assert url == "wss://ws.example.com/cable?token=secret"

  def test_keeps_existing_query(self):
    url = protocol.authenticated_url("wss://ws.example.com/cable?a=1", "secret")

    assert url == "wss://ws.example.com/cable?a=1&token=secret"

  def test_escapes_the_token(self):
    url = protocol.authenticated_url("wss://ws.example.com/cable", "a&b=c#d e+f")

    assert url == "wss://ws.example.com/cable?token=a%26b%3Dc%23d%20e%2Bf"

  def test_without_token(self):
    url = protocol.authenticated_url("wss://ws.example.com/cable", None)

    assert url == "wss://ws.example.com/cable"
