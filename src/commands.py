"""Text command handlers for the task queue bot."""

from __future__ import annotations

import logging
from typing import Any

from .task_client import TaskQueueClient
from .formatter import format_task_table, format_task_detail
from .session import launch_headless

logger = logging.getLogger(__name__)

HELP_TEXT = """\
!queue — List all non-terminal tasks
!queue <agent> — List tasks for a specific agent
!task <id> — Show task detail
!task start <id> — Start task (review mode)
!task run <id> — Start task (auto mode)
!task approve <id> — Approve a pending task
!help — Show this help"""

HELP_HTML = HELP_TEXT.replace("\n", "<br/>").replace("!", "<code>!")
HELP_HTML = HELP_HTML.replace("</code>", "</code>", 1)  # fix first
# Actually just do it cleanly:
HELP_HTML = "<br/>".join(
    f"<code>{line.split(' — ')[0]}</code> — {line.split(' — ')[1]}"
    if " — " in line
    else line
    for line in HELP_TEXT.strip().split("\n")
)


async def handle_command(
    body: str,
    task_client: TaskQueueClient,
) -> tuple[str, str] | None:
    """Parse and handle a command. Returns (plain, html) or None if not a command."""
    body = body.strip()
    if not body.startswith("!"):
        return None

    parts = body.split()
    cmd = parts[0].lower()

    if cmd == "!help":
        return HELP_TEXT, HELP_HTML

    if cmd == "!queue":
        return await _cmd_queue(parts[1:], task_client)

    if cmd == "!task":
        return await _cmd_task(parts[1:], task_client)

    return None


async def _cmd_queue(
    args: list[str], client: TaskQueueClient
) -> tuple[str, str]:
    """!queue [agent] — list non-terminal tasks."""
    agent = args[0] if args else None

    tasks = await client.list_tasks(target_agent=agent)
    # Filter out terminal statuses
    active = [t for t in tasks if t.get("status") not in ("completed", "failed")]
    return format_task_table(active)


async def _cmd_task(
    args: list[str], client: TaskQueueClient
) -> tuple[str, str]:
    """!task <subcommand> <id>"""
    if not args:
        return "Usage: !task <id> | !task start <id> | !task run <id> | !task approve <id>", \
               "Usage: <code>!task &lt;id&gt;</code> | <code>!task start &lt;id&gt;</code> | <code>!task run &lt;id&gt;</code> | <code>!task approve &lt;id&gt;</code>"

    subcmd = args[0].lower()

    # !task <id> — show detail
    if subcmd not in ("start", "run", "approve"):
        task_id = _resolve_id(subcmd, client)
        if not task_id:
            return f"Invalid task ID: {subcmd}", f"Invalid task ID: <code>{subcmd}</code>"
        task = await client.get_task(task_id)
        if not task:
            return f"Task not found: {task_id}", f"Task not found: <code>{task_id}</code>"
        return format_task_detail(task)

    # Subcommands need an ID
    if len(args) < 2:
        return f"Usage: !task {subcmd} <id>", f"Usage: <code>!task {subcmd} &lt;id&gt;</code>"

    task_id = _resolve_id(args[1], client)
    if not task_id:
        return f"Invalid task ID: {args[1]}", f"Invalid task ID: <code>{args[1]}</code>"

    if subcmd == "start":
        return await _start_task(task_id, "review", client)
    elif subcmd == "run":
        return await _start_task(task_id, "auto", client)
    elif subcmd == "approve":
        return await _approve_task(task_id, client)

    return f"Unknown subcommand: {subcmd}", f"Unknown subcommand: <code>{subcmd}</code>"


def _resolve_id(short_or_full: str, client: TaskQueueClient) -> str | None:
    """Accept full UUID or short prefix (8+ chars)."""
    cleaned = short_or_full.strip().lower()
    if not cleaned:
        return None
    # If it looks like a UUID, use as-is
    if len(cleaned) >= 36:
        return cleaned
    # Short prefix — we'll pass it and let the MCP resolve it
    # (MCP requires full ID, so we need to search)
    return cleaned if len(cleaned) >= 8 else None


async def _start_task(
    task_id: str, mode: str, client: TaskQueueClient
) -> tuple[str, str]:
    """Launch an agent session for a task."""
    # Get task to find target agent
    task = await client.get_task(task_id)
    if not task:
        return f"Task not found: {task_id}", f"Task not found: <code>{task_id}</code>"

    target_agent = task.get("target_agent", "")
    result = launch_headless(task_id, target_agent, mode)

    if result.get("ok") == "true":
        mode_label = "review" if mode == "review" else "auto"
        plain = f"Session launched for {target_agent} ({mode_label} mode) — task {task_id[:8]}"
        html = f"Session launched for <strong>{target_agent}</strong> ({mode_label} mode) — task <code>{task_id[:8]}</code>"
        return plain, html
    else:
        logger.error("Failed to launch session for task %s", task_id[:8])
        return "Failed to launch session — check bot logs.", "Failed to launch session — check bot logs."


async def _approve_task(
    task_id: str, client: TaskQueueClient
) -> tuple[str, str]:
    """Approve a pending task."""
    try:
        await client.update_task(task_id, "approved", "operator", "Approved via Matrix bot")
        return (
            f"Task {task_id[:8]} approved.",
            f"Task <code>{task_id[:8]}</code> approved.",
        )
    except Exception:
        logger.exception("Failed to approve task %s", task_id[:8])
        return "Failed to approve — check bot logs.", "Failed to approve — check bot logs."
