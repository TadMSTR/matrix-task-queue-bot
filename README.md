# matrix-task-queue-bot

Matrix bot for task queue management on forge. Accepts text commands in a designated Matrix room, handles custom widget events from the task queue dashboard widget, and keeps a set of pinned, self-updating status boards — one per agent — plus a single daily morning brief.

## Overview

The bot runs as a PM2 always-on service (`matrix-task-queue-bot`) using the `matrix-nio` Python client. Every queue read and write goes through task-queue-mcp's HTTP API (`GET /tasks`, `GET /tasks/{id}`, and the `POST` control routes), under the bot's own client token. It needs task-queue-mcp v0.11.0 or later. The bot parses no queue YAML: the queue's TTL, dead-letter and status rules are applied by the queue's owner, not re-implemented here.

Four subsystems run concurrently:

- **Text command handler** — responds to `!` commands in the task queue room
- **Widget event handler** — processes custom `com.helmforge.task.*` room events from the Matrix widget
- **File watcher** (watchdog) — monitors `~/.claude/task-queue/*.yml` and, on any change, coalesces a single refresh of the live boards
- **Daily digest scheduler** — posts one dated "morning brief" per day at `DIGEST_HOUR` (local time)

The Task Queue room is a **passive status surface**: the boards edit in place silently (via `m.replace`) and do not notify. The only notifying message is the once-a-day morning brief.

## Text commands

All commands must be sent to the configured task queue room (`MATRIX_ROOM_TASK_QUEUE`).

| Command | Description |
|---------|-------------|
| `!queue` | List all non-terminal tasks (excludes `completed` / `failed`) |
| `!queue <agent>` | List tasks for a specific agent |
| `!task <id>` | Show task detail (accepts full UUID or 8-char prefix) |
| `!task start <id>` | Launch agent session in **review mode** (plan permissions, agent summarizes then waits) |
| `!task run <id>` | Launch agent session in **auto mode** (agent claims and executes) |
| `!task approve <id>` | Set task status to `approved` (actor: `operator`) |
| `!help` | Show command reference |

Task IDs accept either full UUIDs or 8-character prefixes. Short IDs must be at least 8 characters.

## Widget events

The bot handles custom Matrix room events sent by the task queue widget (`matrix-task-queue-widget`). Read-only events are open to all room members; mutating actions require the sender to be in `AUTHORIZED_MXIDS`.

| Event type | Auth required | Action |
|------------|--------------|--------|
| `com.helmforge.task.list` | No | Returns filtered task list via `com.helmforge.task.data` |
| `com.helmforge.task.detail` | No | Returns single task via `com.helmforge.task.response` |
| `com.helmforge.task.start` | Yes | Launches headless agent session |
| `com.helmforge.task.approve` | Yes | Sets task status to `approved` |

Responses are sent as custom room events (`com.helmforge.task.response` / `com.helmforge.task.data`). The widget correlates responses via `request_id` in the event content.

## Live status boards

The file watcher (watchdog, non-recursive) monitors `~/.claude/task-queue/` for any change — creation, modification, deletion, or move (archival). It is **a change trigger only**: an event causes an API read, never a file parse. All events are collapsed by a single coalesce timer (`BOARD_COALESCE_SEC`, default 2s) into one refresh pass.

Each refresh rebuilds one board **per agent** in `BOARD_AGENTS` (plus any other agent seen in the queue, appended lazily) from one `GET /tasks?limit=1000`:

- If the API reports `truncated` (more than 1000 records matched), every board and the morning brief say so: `⚠ queue read truncated: N records matched, not all shown`. It is logged too. It is never hidden, because an agent's board could otherwise read "no open tasks" while it has some past the cut.
- If the read fails (API down, token refused), the refresh is abandoned and logged, and **every board keeps its last content**. An empty result is never painted as an empty queue.

- Each board lists that agent's **non-terminal** tasks (`submitted`, `approved`, `pending-approval`, `in-progress`; `completed` / `failed` / `cancelled` are excluded), sorted by priority → status → age.
- Columns: **ID · Priority · Status · Type · Summary · Age**. Header shows `AGENT (n)`; an agent with no open tasks shows `AGENT (0) — ✔️ no open tasks`.
- The board message is **edited in place** via an `m.replace` relation, so updates are silent (no notification) and the message keeps a stable event ID. Boards whose meaningful content is unchanged are skipped to avoid churn (the `updated HH:MM` footer is a wall-clock stamp of the last real change, not a live clock).
- All boards are pinned in one `m.room.pinned_events` state event so they read top-to-bottom in `BOARD_AGENTS` order. Pinning requires the bot to hold a state-event power level (PL 50) in the room; if it can't, pinning degrades to a logged no-op and the boards still work unpinned.

Board message event IDs are persisted to `${STATE_DIR}/boards.json` (an `agent → event_id` map) so the bot re-edits the same messages across restarts. Delete `boards.json` to force a clean re-post.

## Daily morning brief

Once a day at `DIGEST_HOUR` (local time, default 05:00) the bot posts a **fresh** message (not an edit) — the one message in the room that notifies. It is a dated digest of all non-completed tasks grouped by agent (`Morning brief — YYYY-MM-DD · N non-completed across M agents`).

A stamp file `${STATE_DIR}/digest-stamp` records the last-sent date to guard against a double-send on restart. On startup the scheduler arms for the next occurrence of `DIGEST_HOUR`; it does not send a catch-up brief for a hour already passed.

## Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `MATRIX_HOMESERVER_URL` | Yes | — | Matrix homeserver (e.g. `http://localhost:8008`) |
| `MATRIX_ACCESS_TOKEN` | Yes | — | Bot access token |
| `MATRIX_ROOM_TASK_QUEUE` | Yes | — | Room ID for task queue commands (e.g. `!task-queue:helmforge.me`) |
| `MATRIX_BOT_USER_ID` | No | `@forge-task-queue:helmforge.me` | Bot's Matrix user ID |
| `TASK_QUEUE_TOKEN_FILE` | Yes | — | Path to a file holding the bot's task-queue-mcp client token (and nothing else). The bot refuses to start if it is unset, missing or empty. See [Client token](#client-token). |
| `TASK_QUEUE_API` | No | `http://127.0.0.1:8485` | Base URL of task-queue-mcp's HTTP API |
| `TASK_QUEUE_MCP_URL` | No | `http://localhost:8485/mcp` | Unused at runtime |
| `TASK_QUEUE_DIR` | No | `~/.claude/task-queue` | Watched for changes only; the bot never reads the files |
| `AUTHORIZED_MXIDS` | No | `@ted:helmforge.me` | Comma-separated MXIDs allowed to run mutating commands |
| `STATE_DIR` | No | `~/.local/state/matrix-task-queue-bot` | Holds `boards.json` (agent→event_id) and `digest-stamp` |
| `DIGEST_HOUR` | No | `5` | Local-time hour (0–23) for the daily morning brief |
| `BOARD_COALESCE_SEC` | No | `2` | Debounce window collapsing a burst of queue writes into one board refresh |
| `BOARD_AGENTS` | No | `developer,sysadmin,research,writer,security` | Ordered set of agents to always keep a (possibly empty) board for |
| `MAX_BOARD_AGENTS` | No | `25` | Hard cap on total boards; extra agents beyond it are logged and dropped (floored to `BOARD_AGENTS` size) |
| `ENV_FILE` | No | `~/.secrets/matrix-task-queue-bot.env` | Path to dotenv file |

### Client token

The bot authenticates to task-queue-mcp with its own client token, sent as `X-Task-Queue-Token` (never `Authorization`). The server holds only the token's `sha256:` digest, registered as client `matrix-bot` with `read,operator-write` scopes, and records the bot's writes with `channel: matrix-bot`. See task-queue-mcp's README for minting a token and its digest.

The environment carries the file's **path**, never the token. Keep the file `0600`. Sessions the bot launches (`!task start` / `!task run`, widget start) get the bot's environment **minus its credentials**: `MATRIX_ACCESS_TOKEN`, `TASK_QUEUE_API_SECRET`, `TASK_QUEUE_TOKEN_FILE`, and any `TASK_QUEUE_TOKEN_*` / `TASK_QUEUE_CLIENT_*` are removed (`session.child_env`). Before v0.2.0 every launched session inherited all of them. This is containment only: a launched session runs as the same OS user and can still read the token file. Before v0.2.0 the bot sent a shared secret, `TASK_QUEUE_API_SECRET`, as `X-Task-Queue-Secret`; that variable is no longer read.

## Installation

Requires Python 3.12+.

```bash
cd ~/repos/personal/matrix-task-queue-bot
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `matrix-nio[e2e]` | Matrix client |
| `httpx` | HTTP client: task-queue-mcp API and trigger-proxy |
| `watchdog` | File system watcher (change trigger for board refreshes) |
| `python-dotenv` | Env file loading |

## Deployment (PM2)

```javascript
// ecosystem.config.js excerpt
{
  name: "matrix-task-queue-bot",
  script: "venv/bin/matrix-task-queue-bot",
  cwd: "/home/ted/repos/personal/matrix-task-queue-bot",
  env: { ENV_FILE: "/home/ted/.secrets/matrix-task-queue-bot.env" },
  restart_delay: 5000,
  autorestart: true,
}
```

```bash
pm2 start ecosystem.config.js
pm2 save
```

## Session launch behavior

| Mode | Permission mode | Agent behavior |
|------|----------------|---------------|
| `review` | `plan` | Reads task, presents summary, waits for operator approval |
| `auto` | `default` | Reads task, claims it (in-progress), executes |

Sessions are launched as detached `claude` subprocesses pointing at the agent's project directory. The task `target_agent` field determines which project directory is used.

## Forge deployment

- PM2 service: `matrix-task-queue-bot` (always-on)
- Env file: `~/.secrets/matrix-task-queue-bot.env`
- Matrix room: `#task-queue:helmforge.me`
- Repo: `~/repos/personal/matrix-task-queue-bot/`
