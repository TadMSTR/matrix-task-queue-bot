"""Custom Matrix event handlers for the task queue widget."""

from __future__ import annotations

import json
import logging
from typing import Any

from nio import AsyncClient, RoomMemberEvent

from .task_client import TaskQueueClient
from .formatter import format_task_table, format_task_detail
from .session import launch_headless

logger = logging.getLogger(__name__)

# Custom event types
EVENT_TASK_LIST = "com.helmforge.task.list"
EVENT_TASK_DETAIL = "com.helmforge.task.detail"
EVENT_TASK_START = "com.helmforge.task.start"
EVENT_TASK_APPROVE = "com.helmforge.task.approve"
EVENT_TASK_RESPONSE = "com.helmforge.task.response"
EVENT_TASK_DATA = "com.helmforge.task.data"


async def handle_widget_event(
    client: AsyncClient,
    room_id: str,
    event_type: str,
    content: dict[str, Any],
    task_client: TaskQueueClient,
) -> None:
    """Handle a custom widget event and send a response."""
    request_id = content.get("request_id", "")

    try:
        if event_type == EVENT_TASK_LIST:
            filters = content.get("filters", {})
            tasks = await task_client.list_tasks(
                target_agent=filters.get("agent"),
                status=filters.get("status"),
            )
            active = [t for t in tasks if t.get("status") not in ("completed", "failed")]
            await _send_response(client, room_id, EVENT_TASK_DATA, {
                "request_id": request_id,
                "tasks": active,
            })

        elif event_type == EVENT_TASK_DETAIL:
            task_id = content.get("task_id", "")
            task = await task_client.get_task(task_id)
            await _send_response(client, room_id, EVENT_TASK_RESPONSE, {
                "request_id": request_id,
                "action": "detail",
                "task": task,
            })

        elif event_type == EVENT_TASK_START:
            task_id = content.get("task_id", "")
            mode = content.get("mode", "review")
            task = await task_client.get_task(task_id)
            target_agent = task.get("target_agent", "")
            result = launch_headless(task_id, target_agent, mode)
            await _send_response(client, room_id, EVENT_TASK_RESPONSE, {
                "request_id": request_id,
                "action": "start",
                "result": result,
            })

        elif event_type == EVENT_TASK_APPROVE:
            task_id = content.get("task_id", "")
            result = await task_client.update_task(task_id, "approved", "operator", "Approved via widget")
            await _send_response(client, room_id, EVENT_TASK_RESPONSE, {
                "request_id": request_id,
                "action": "approve",
                "ok": bool(result.get("ok")),
            })

    except Exception as e:
        logger.exception("Widget event handler error: %s", e)
        await _send_response(client, room_id, EVENT_TASK_RESPONSE, {
            "request_id": request_id,
            "error": "internal error processing request",
        })


async def _send_response(
    client: AsyncClient,
    room_id: str,
    event_type: str,
    content: dict[str, Any],
) -> None:
    """Send a custom room event as a response."""
    await client.room_send(
        room_id=room_id,
        message_type=event_type,
        content=content,
    )
