"""Matrix task queue bot — text commands, widget events, file watcher."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from nio import AsyncClient, MatrixRoom, RoomMessageText, Event
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from .task_client import TaskQueueClient
from .commands import handle_command
from .formatter import format_status_update
from .widget_events import (
    handle_widget_event,
    EVENT_TASK_LIST,
    EVENT_TASK_DETAIL,
    EVENT_TASK_START,
    EVENT_TASK_APPROVE,
)

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────

ENV_FILE = os.environ.get("ENV_FILE", os.path.expanduser("~/.secrets/matrix-task-queue-bot.env"))
if os.path.isfile(ENV_FILE):
    load_dotenv(ENV_FILE)

REQUIRED_VARS = ["MATRIX_HOMESERVER_URL", "MATRIX_ACCESS_TOKEN", "MATRIX_ROOM_TASK_QUEUE"]
for var in REQUIRED_VARS:
    if not os.environ.get(var):
        print(f"ERROR: Missing required env var: {var}", file=sys.stderr)
        sys.exit(1)

HOMESERVER = os.environ["MATRIX_HOMESERVER_URL"]
ACCESS_TOKEN = os.environ["MATRIX_ACCESS_TOKEN"]
BOT_USER_ID = os.environ.get("MATRIX_BOT_USER_ID", "@forge-task-queue:helmforge.me")
ROOM_ID = os.environ["MATRIX_ROOM_TASK_QUEUE"]
MCP_URL = os.environ.get("TASK_QUEUE_MCP_URL", "http://localhost:8485/mcp")
TASK_QUEUE_DIR = os.environ.get("TASK_QUEUE_DIR", os.path.expanduser("~/.claude/task-queue"))
# Mutations route through the MCP control API (shared-secret gated). Reads stay direct.
TASK_QUEUE_API = os.environ.get("TASK_QUEUE_API", "http://127.0.0.1:8485")
TASK_QUEUE_API_SECRET = os.environ.get("TASK_QUEUE_API_SECRET", "")
AUTHORIZED_SENDERS = set(
    s.strip() for s in os.environ.get("AUTHORIZED_MXIDS", "@ted:helmforge.me").split(",") if s.strip()
)

# ── Task file watcher ──────────────────────────────────────────────────

class TaskFileHandler(FileSystemEventHandler):
    """Watches task queue YAML files for status changes."""

    def __init__(self, loop: asyncio.AbstractEventLoop, callback):
        self._loop = loop
        self._callback = callback
        self._debounce: dict[str, asyncio.TimerHandle] = {}
        self._known_statuses: dict[str, str] = {}
        # Seed known statuses
        self._scan_initial()

    def _scan_initial(self) -> None:
        task_dir = Path(TASK_QUEUE_DIR)
        if not task_dir.is_dir():
            return
        for f in task_dir.glob("*.yml"):
            if f.name.endswith(".tmp"):
                continue
            try:
                data = yaml.safe_load(f.read_text())
                if isinstance(data, dict) and "id" in data:
                    self._known_statuses[data["id"]] = data.get("status", "")
            except Exception:
                pass

    def _handle(self, path: str) -> None:
        if not path.endswith(".yml") or path.endswith(".tmp"):
            return
        # Debounce per file (1s)
        key = path
        if key in self._debounce:
            self._debounce[key].cancel()
        self._debounce[key] = self._loop.call_later(1.0, self._process, path)

    def _process(self, path: str) -> None:
        try:
            data = yaml.safe_load(Path(path).read_text())
            if not isinstance(data, dict) or "id" not in data:
                return
            task_id = data["id"]
            new_status = data.get("status", "")
            old_status = self._known_statuses.get(task_id)

            if old_status is not None and old_status != new_status:
                # Status changed — notify
                asyncio.run_coroutine_threadsafe(
                    self._callback(data, old_status), self._loop
                )
            self._known_statuses[task_id] = new_status
        except Exception as e:
            logger.warning("Error processing task file %s: %s", path, e)

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent):
            self._handle(event.src_path)

    def on_created(self, event):
        if isinstance(event, FileCreatedEvent):
            self._handle(event.src_path)


# ── Bot ────────────────────────────────────────────────────────────────

class TaskQueueBot:
    def __init__(self) -> None:
        self.client = AsyncClient(HOMESERVER, BOT_USER_ID)
        self.client.access_token = ACCESS_TOKEN
        self.client.user_id = BOT_USER_ID
        self.task_client = TaskQueueClient(
            TASK_QUEUE_DIR,
            api_base=TASK_QUEUE_API,
            api_secret=TASK_QUEUE_API_SECRET,
        )
        self._observer: Observer | None = None

    async def _send_html(self, room_id: str, plain: str, html: str) -> None:
        await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": plain,
                "format": "org.matrix.custom.html",
                "formatted_body": html,
            },
        )

    async def _handle_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        # Skip own messages
        if event.sender == BOT_USER_ID:
            return
        # Only respond in the task queue room
        if room.room_id != ROOM_ID:
            return

        body = event.body.strip()
        if not body.startswith("!"):
            return

        try:
            result = await handle_command(body, self.task_client)
            if result:
                plain, html = result
                await self._send_html(room.room_id, plain, html)
        except Exception as e:
            logger.exception("Command handler error: %s", e)
            await self._send_html(
                room.room_id,
                "Error: an internal error occurred. Check bot logs for details.",
                "<strong>Error:</strong> an internal error occurred. Check bot logs for details.",
            )

    async def _handle_custom_event(self, room: MatrixRoom, event: Event) -> None:
        """Handle custom widget events."""
        if room.room_id != ROOM_ID:
            return
        if event.sender == BOT_USER_ID:
            return

        event_type = getattr(event, "type", "") or ""
        content = getattr(event, "source", {}).get("content", {})

        # Mutating actions require authorized sender; read-only queries are open to room members
        if event_type in (EVENT_TASK_START, EVENT_TASK_APPROVE):
            if event.sender not in AUTHORIZED_SENDERS:
                logger.warning("Unauthorized widget action from %s: %s", event.sender, event_type)
                return

        if event_type in (EVENT_TASK_LIST, EVENT_TASK_DETAIL, EVENT_TASK_START, EVENT_TASK_APPROVE):
            await handle_widget_event(
                self.client, room.room_id, event_type, content, self.task_client
            )

    async def _on_status_change(self, task_data: dict, old_status: str) -> None:
        """Called by file watcher when a task status changes."""
        plain, html = format_status_update(task_data, old_status)
        await self._send_html(ROOM_ID, plain, html)

    def _start_file_watcher(self) -> None:
        loop = asyncio.get_event_loop()
        handler = TaskFileHandler(loop, self._on_status_change)
        self._observer = Observer()
        self._observer.schedule(handler, TASK_QUEUE_DIR, recursive=False)
        self._observer.daemon = True
        self._observer.start()
        logger.info("File watcher started on %s", TASK_QUEUE_DIR)

    async def run(self) -> None:
        logger.info("Starting task queue bot — homeserver=%s room=%s", HOMESERVER, ROOM_ID)

        # Register callbacks
        self.client.add_event_callback(self._handle_message, RoomMessageText)
        self.client.add_event_callback(self._handle_custom_event, Event)

        # Start file watcher
        Path(TASK_QUEUE_DIR).mkdir(parents=True, exist_ok=True)
        self._start_file_watcher()

        try:
            await self.client.sync_forever(timeout=30000, full_state=True)
        finally:
            if self._observer:
                self._observer.stop()
                self._observer.join(timeout=5)
            await self.task_client.close()
            await self.client.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot = TaskQueueBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
