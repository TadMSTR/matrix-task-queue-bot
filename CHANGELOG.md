# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
