# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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

- Standard CI workflow (`ci.yml`) — ruff lint + format check (pinned `ruff==0.16.0`).
  Lint-only: the bot has no test suite and is not packaged (no `[build-system]`).
- Release workflow (`release.yml`) — a `vX.Y.Z` tag cuts a source-only GitHub Release.
- Explicit ruff config (`select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]`) to pin
  the enforced ruleset against ruff's widening defaults.
- Standard repo docs: `CHANGELOG.md`, `AGENTS.md`, `SECURITY.md`.

## [0.1.0]

### Added

- Initial release: Matrix bot for task queue management — text commands, custom widget
  event handling, self-updating per-agent status boards, and a daily morning brief.
