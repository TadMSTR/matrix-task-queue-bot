# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.2.0] - 2026-09-29

Own client token, and every queue read through task-queue-mcp's API. Build
`operator-panel-2026-09-p2-queue-read-api`; vikunja#396. **Requires task-queue-mcp v0.11.0
or later, and `TASK_QUEUE_TOKEN_FILE`.**

### Changed

- **The bot authenticates with its own client token**, read from the file named by
  `TASK_QUEUE_TOKEN_FILE` and sent as `X-Task-Queue-Token`. The bot refuses to start if the
  variable is unset or the file is missing or empty. Its writes are recorded with
  `channel: matrix-bot`.
- **Every read goes through the API.** `list_tasks` calls `GET /tasks` and `get_task` calls
  `GET /tasks/{id}`. The queue's TTL, dead-letter and status rules now come from the queue's
  owner. An 8+ character id prefix is resolved against the listing, and an ambiguous prefix
  now resolves to nothing, where it used to pick whichever file came first.
- **A failed read raises** instead of returning an empty list, so a board refresh that
  cannot read the queue leaves the boards as they were rather than painting them empty.
- **Truncation is shown.** Boards and the morning brief carry a notice when the API
  truncated the read, and it is logged.
- The watchdog watcher is now a change trigger only.
- **`TASK_QUEUE_API` must be `https://`, or `http://` to a loopback host.** The token
  (read + operator-write) goes on every request, so the bot refuses to start rather than
  send it in cleartext to another host. The deployed default, `http://127.0.0.1:8485`, passes.
  For an `http://` base, environment proxies (`HTTP_PROXY` etc.) are ignored, so the token
  cannot reach a proxy host in cleartext either.
- **Launched sessions no longer inherit the bot's credentials.** `launch_headless` spawned
  `claude` with the bot's whole environment, so every session started from Matrix held
  `MATRIX_ACCESS_TOKEN` and `TASK_QUEUE_API_SECRET`. The child environment now has the
  bot's credentials removed (`session.child_env`).
- **A Start launches only live, unfinished work.** A full id now also resolves archived and
  dead-lettered records, which the old file scan never saw. `!task start` / `!task run` and
  the widget's start event refuse any task outside the live queue or in a terminal status,
  and say why, so the launch surface is no wider than before.

### Removed

- `TASK_QUEUE_API_SECRET` and the `X-Task-Queue-Secret` header.
- The `pyyaml` dependency; nothing parses YAML any more.


### Fixed

- **Status boards no longer render a gated task as though it had been launched.**
  task-queue-mcp v0.9.0 adds `manual-then-auto`, which waits for an operator Start exactly
  like `semi-auto`. `format_status_update` tested `workflow_mode == "semi-auto"` to decide
  whether to say *awaiting operator pickup*, so the new mode fell to the `else` branch and
  read as already running — the most misleading thing that line could say about a task that
  is in fact sitting and waiting for the operator reading the board.

  Now the **inverse of the dispatcher's launch rule** rather than a list of modes:
  `task-dispatcher.py` launches on `workflow_mode == "auto"` and sends everything else to
  operator pickup, so `!= "auto"` states the same rule once and cannot drift as modes are
  added. Enumerating them is what caused this. `manual-then-auto` additionally notes that the
  rest of the chain runs itself, which is the whole reason an operator would pick it.

  Also refreshes the stale `SECURITY[accepted]` note, which cited the mode set as
  `{"semi-auto", "auto"}`. The mitigation is unchanged — it rests on there being validation at
  submission time, not on the specific values. (Build `task-queue-headless-chain-2026-08`,
  vikunja#533.)

### Added

- The first test suite (`tests/`), and a pytest job in CI.
- Standard CI workflow (`ci.yml`) — ruff lint + format check (pinned `ruff==0.16.0`).
  The bot is not packaged (no `[build-system]`).
- Release workflow (`release.yml`) — a `vX.Y.Z` tag cuts a source-only GitHub Release.
- Explicit ruff config (`select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]`) to pin
  the enforced ruleset against ruff's widening defaults.
- Standard repo docs: `CHANGELOG.md`, `AGENTS.md`, `SECURITY.md`.

## [0.1.0]

### Added

- Initial release: Matrix bot for task queue management — text commands, custom widget
  event handling, self-updating per-agent status boards, and a daily morning brief.
