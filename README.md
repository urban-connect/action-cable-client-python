# action-cable-client-python

ActionCable client for Python. It implements the [ActionCable](https://guides.rubyonrails.org/action_cable_overview.html) protocol, so a Python program can subscribe to the channels of a Rails (or AnyCable) application, receive broadcasts and call channel actions.

The package has three parts:

- `action_cable_client.protocol` builds the frames a client sends and turns server frames into typed events. It does no I/O.
- `action_cable_client.aio` is the asyncio transport.
- `action_cable_client.sync` is the blocking transport for threaded programs.

Both transports are built on [websockets](https://websockets.readthedocs.io/), speak the same protocol and expose the same operations: `subscribe`, `unsubscribe`, `perform` and `receive`. Reconnecting is left to the caller: open a new connection and subscribe again.

## Installation

Requires Python 3.10 or newer. Install it from git, pinned to a tag:

```toml
dependencies = [
    "action-cable-client @ git+https://github.com/urban-connect/action-cable-client-python.git@v0.1.0",
]
```

## Usage

With asyncio:

```python
from action_cable_client import ConfirmSubscription, Identifier, Message, Welcome, aio

room = Identifier("ChatChannel", room_id=1)

async with aio.connect("wss://example.com/cable") as connection:
  async for event in connection:
    match event:
      case Welcome():
        await connection.subscribe(room)
      case ConfirmSubscription():
        await connection.perform(room, "speak", {"text": "Hello"})
      case Message(identifier, payload):
        print(identifier, payload)
```

With threads:

```python
from action_cable_client import Identifier, Message, Welcome, sync

room = Identifier("ChatChannel", room_id=1)

with sync.connect("wss://example.com/cable") as connection:
  while not quit.is_set():
    event = connection.receive(timeout=1.0)  # None when nothing arrived in time

    match event:
      case Welcome():
        connection.subscribe(room)
      case Message(identifier, payload):
        print(identifier, payload)
```

An `Identifier` is a channel name plus the params of the subscription. `perform(identifier, action, data)` calls the channel method `action` with `data` as its argument.

## Authentication

How a connection is authenticated is up to the server. Two common ways are supported:

- `connect(url, token="...")` appends the token to the URL as the `token` query parameter.
- Any other keyword argument is passed to the underlying `websockets` connect call, so headers go in as `additional_headers={"Authorization": "Bearer ..."}`.

## Events

`receive` returns one of:

| Event | Meaning |
|---|---|
| `Welcome(sid)` | The connection is accepted. Subscribe now. |
| `Ping(timestamp)` | Server heartbeat. |
| `ConfirmSubscription(identifier)` | The subscription is active. |
| `RejectSubscription(identifier)` | The channel refused the subscription. |
| `Disconnect(reason, reconnect)` | The server is about to close the connection. |
| `Message(identifier, payload)` | A broadcast on a subscribed channel. |
| `Unknown(raw)` | A frame that is not valid ActionCable. Log it and carry on. |

Identifiers compare by content, so the identifier of an incoming `Message` can be compared with, or used as a dictionary key next to, the one used to subscribe.

## Liveness

The server pings every few seconds. `receive` raises `PingTimeout` (a `TimeoutError`) when no ping has arrived for `ping_deadline` seconds, 60 by default. Pass `ping_deadline=None` to `connect` to turn this off. A closed socket raises the `websockets` exception as is.

## Testing

`action_cable_client.testing.FakeCable` is a small ActionCable server for tests. It welcomes clients, confirms or rejects subscriptions, records what the client sends and can broadcast, ping and disconnect.

```python
from action_cable_client.testing import FakeCable

with FakeCable() as cable:
  ...  # connect to cable.url
  cable.broadcast(room, {"text": "Hello"})
  frame = cable.received.get(timeout=5)
```

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format .
```
