# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An ActionCable client for Python, built on the `websockets` library. It lets a Python program subscribe to the channels of a Rails or AnyCable application, receive broadcasts and call channel actions.

This repository is public. Keep everything in it generic: no private hostnames, internal project names, real channel or action names, tokens or other details of the systems that use the library, in code, tests, documentation, commit messages or pull requests. Examples use `ChatChannel` and `example.com`.

## Installing Dependencies

```bash
uv sync --group dev
```

## Testing and Linting

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

CI (GitHub Actions) runs Ruff and pytest on every PR, and both checks are required to merge.

## Architecture

The package lives in `src/action_cable_client/`:

- `protocol.py` — the wire protocol without any I/O: `Identifier`, the functions that build client frames (`subscribe`, `unsubscribe`, `perform`), `decode`, which turns a server frame into a typed event, and the two handshake helpers `authenticated_url` and `check_subprotocol`. `decode` never raises; a frame it cannot parse comes back as `Unknown`.
- `aio.py` — the asyncio transport.
- `sync.py` — the blocking transport for threaded programs.
- `testing.py` — `FakeCable`, a small ActionCable server that consumers and this repository's own tests connect to.

Both transports wrap one websocket and expose the same operations (`subscribe`, `unsubscribe`, `perform`, `receive`). Anything about the protocol belongs in `protocol.py`, so the two transports cannot drift apart; a transport only moves frames and enforces the ping deadline. Reconnecting is the caller's job and is not implemented here.

## Git & PRs

- Try to keep branch names short but readable
- Do not add Claude as a co-author to commit messages and PR descriptions
- Provide short description for the PR, do not add test cases there
- Always assign the PR to its author when creating it
- Never force push (`git push --force` / `git push -f`) branches to GitHub
- To resolve conflicts with main, use `git pull origin main` instead of `git rebase` (rebase requires force push)
- Always ask before using `--admin` flag when merging PRs — it bypasses branch protection checks

## Releases

Consumers install the package from git, pinned to a tag. A release is one pull request that bumps the version in `pyproject.toml`, runs `uv lock` (the lock records the package's own version and CI installs with `--locked`) and updates the tag in the README install example. Once it is merged to `main`, tag that commit `vX.Y.Z`. Never move or delete a published tag.

## Key Conventions

- Python 3.10+ (uses `match`/`case` and `X | Y` type unions)
- Two-space indentation, enforced by Ruff
- `websockets` is the only runtime dependency; do not add others without a strong reason
- Every change to the protocol or a transport comes with a test; transport tests run against a real local server: `FakeCable`, or a plain `websockets` server when the test needs a server that misbehaves
- Whatever one transport gains, the other gains too
