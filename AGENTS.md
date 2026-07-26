# matrix-task-queue-bot

Matrix bot for task queue management on forge. Accepts text commands in a designated Matrix
room, handles custom widget events from the task queue dashboard widget, and maintains a set
of pinned, self-updating per-agent status boards plus a single daily morning brief.

## What it does

Runs as a PM2 always-on service (`matrix-task-queue-bot`) using the `matrix-nio` client. It
reads task YAML directly from `~/.claude/task-queue/` — no HTTP dependency on task-queue-mcp
for queries. The Task Queue room is a **passive status surface**: boards edit in place
silently (`m.replace`); the only notifying message is the once-a-day morning brief.

Four subsystems run concurrently: text command handler, widget event handler, a watchdog
file watcher that coalesces board refreshes, and a daily digest scheduler.

## Text commands

Sent to the configured task queue room (`MATRIX_ROOM_TASK_QUEUE`):

- `!queue` / `!queue <agent>` — list non-terminal tasks (optionally per agent).
- `!task <id>` — show task detail (full UUID or 8-char prefix).
- `!task start <id>` — launch agent session in **review mode**.
- `!task run <id>` — launch agent session in **auto mode**.
- `!task approve <id>` — set task status to `approved` (actor: `operator`).
- `!help` — command reference.

## Widget events

Custom `com.helmforge.task.*` room events. Read-only events (`list`, `detail`) are open to
room members; mutating events (`start`, `approve`) require the sender to be in
`AUTHORIZED_MXIDS`. Responses correlate via `request_id`.

## Structure

```
src/
  __init__.py
  bot.py           Bot wiring, board pinning, event dispatch, auth gate
  commands.py      ! text command handlers
  widget_events.py com.helmforge.task.* event handlers
  formatter.py     Plain/HTML rendering for boards, detail, digest
  session.py       Agent session launch prompts
  task_client.py   Reads task YAML from ~/.claude/task-queue/
tests/             (none yet — see CHANGELOG / tracker)
pyproject.toml
```

## Configuration

Key env vars: `MATRIX_HOMESERVER`, `MATRIX_USER`, `MATRIX_PASSWORD`,
`MATRIX_ROOM_TASK_QUEUE`, `AUTHORIZED_MXIDS`, `DIGEST_HOUR`. See `README.md` for the full list.

## Known gaps

- **No test suite** and **not packaged** (no `[build-system]`) — CI is lint-only. Test
  coverage and packaging are tracked in Vikunja.

## Git workflow

Branch before editing — do not commit directly to `main`.
