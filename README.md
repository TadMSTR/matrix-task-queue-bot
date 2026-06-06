# matrix-task-queue-bot

Matrix bot for task queue management on forge. Accepts text commands in a designated Matrix room, handles custom widget events from the task queue dashboard widget, and posts notifications when task status changes.

## Overview

The bot runs as a PM2 always-on service (`matrix-task-queue-bot`) using the `matrix-nio` Python client. It reads task YAML files directly from `~/.claude/task-queue/` — no HTTP dependency on task-queue-mcp for queries.

Three subsystems run concurrently:

- **Text command handler** — responds to `!` commands in the task queue room
- **Widget event handler** — processes custom `com.helmforge.task.*` room events from the Matrix widget
- **File watcher** (watchdog) — monitors `~/.claude/task-queue/*.yml` for status changes and posts notifications to the room

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

## Status notifications

The file watcher (watchdog, non-recursive, 1s debounce per file) monitors `~/.claude/task-queue/` for YAML file creation and modification. When a task's `status` field changes, the bot posts a formatted notification to the room.

Only actual status transitions are notified — the watcher seeds its known-status map at startup to avoid spurious notifications on restart.

## Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `MATRIX_HOMESERVER_URL` | Yes | — | Matrix homeserver (e.g. `http://localhost:8008`) |
| `MATRIX_ACCESS_TOKEN` | Yes | — | Bot access token |
| `MATRIX_ROOM_TASK_QUEUE` | Yes | — | Room ID for task queue commands (e.g. `!task-queue:helmforge.me`) |
| `MATRIX_BOT_USER_ID` | No | `@forge-task-queue:helmforge.me` | Bot's Matrix user ID |
| `TASK_QUEUE_MCP_URL` | No | `http://localhost:8485/mcp` | Unused at runtime (reads files directly) |
| `TASK_QUEUE_DIR` | No | `~/.claude/task-queue` | Task YAML directory |
| `AUTHORIZED_MXIDS` | No | `@ted:helmforge.me` | Comma-separated MXIDs allowed to run mutating commands |
| `ENV_FILE` | No | `~/.secrets/matrix-task-queue-bot.env` | Path to dotenv file |

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
| `httpx` | HTTP client (trigger-proxy support) |
| `watchdog` | File system watcher |
| `pyyaml` | Task YAML parsing |
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
