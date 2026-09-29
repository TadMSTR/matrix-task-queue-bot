# matrix-task-queue-bot

Matrix bot for task queue management on forge. Accepts text commands in a designated Matrix
room, handles custom widget events from the task queue dashboard widget, and maintains a set
of pinned, self-updating per-agent status boards plus a single daily morning brief.

## What it does

Runs as a PM2 always-on service (`matrix-task-queue-bot`) using the `matrix-nio` client. It
reads and writes the queue only through task-queue-mcp's HTTP API, under its own client token
(`TASK_QUEUE_TOKEN_FILE`, sent as `X-Task-Queue-Token`). It parses no queue YAML; the watchdog
watcher is a change trigger that causes an API read. The Task Queue room is a **passive status surface**: boards edit in place
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
  task_client.py   task-queue-mcp HTTP API client (reads + control-API writes), token file
tests/             pytest: task_client (token file, headers, truncation, prefix ids), formatter
pyproject.toml
```

## Invariants

- **No queue YAML is parsed here.** Reads go through `GET /tasks` / `GET /tasks/{id}`;
  writes through the control API. A new read is an API call, never a `yaml.safe_load`.
- **A failed read raises, never returns `[]`.** `list_page` raises `TaskQueueError`; a board
  refresh that fails leaves every board as it was. An empty list would repaint every board
  as "no open tasks".
- **`truncated` is rendered.** Boards and the digest carry the notice. If the queue ever
  needs more than one 1000-record page, report the number and the use; do not page silently
  or ask for the server cap to be raised.
- **The token is in a file; the env holds only its path.** Never send it as
  `Authorization`, and never log it.
- **An ambiguous id prefix resolves to nothing.** Acting on an arbitrary one of two tasks is
  worse than asking for a longer id.

## Configuration

Key env vars: `MATRIX_HOMESERVER`, `MATRIX_USER`, `MATRIX_PASSWORD`,
`MATRIX_ROOM_TASK_QUEUE`, `AUTHORIZED_MXIDS`, `DIGEST_HOUR`. See `README.md` for the full list.

## Known gaps

- **No test suite** and **not packaged** (no `[build-system]`) — CI is lint-only. Test
  coverage and packaging are tracked in Vikunja.

## Git workflow

Branch before editing — do not commit directly to `main`.
