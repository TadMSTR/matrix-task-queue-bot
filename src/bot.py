"""Matrix task queue bot — text commands, widget events, live boards, daily digest.

The Task Queue room is a passive status surface: one pinned, self-editing board per
agent (silently edited in place on every task event via ``m.replace``), plus a single
dated "morning brief" posted once a day at ``DIGEST_HOUR`` — the only notifying message.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from nio import (
    AsyncClient,
    Event,
    MatrixRoom,
    RoomMessageText,
    RoomPutStateError,
    RoomSendResponse,
)
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .task_client import TaskQueueClient
from .commands import handle_command
from .formatter import board_signature, board_tasks, format_agent_board, format_digest
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

# Live-board / digest configuration
STATE_DIR = os.path.expanduser(
    os.environ.get("STATE_DIR", "~/.local/state/matrix-task-queue-bot")
)
try:
    DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "5"))
except ValueError:
    DIGEST_HOUR = 5
if not 0 <= DIGEST_HOUR <= 23:
    DIGEST_HOUR = 5
try:
    BOARD_COALESCE_SEC = float(os.environ.get("BOARD_COALESCE_SEC", "2"))
except ValueError:
    BOARD_COALESCE_SEC = 2.0
BOARD_AGENTS = [
    a.strip()
    for a in os.environ.get(
        "BOARD_AGENTS", "developer,sysadmin,research,writer,security"
    ).split(",")
    if a.strip()
]

# ── Task file watcher ──────────────────────────────────────────────────

class TaskFileHandler(FileSystemEventHandler):
    """Coalesces any queue-file change into a single board refresh.

    Watchdog callbacks fire on the observer thread; all event-loop interaction is
    marshalled back via ``call_soon_threadsafe``. A single debounce timer collapses a
    burst of writes (atomic .tmp→.yml renames, multi-file updates) into one refresh.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, refresh_coro, coalesce_sec: float = 2.0):
        self._loop = loop
        self._refresh_coro = refresh_coro
        self._coalesce = max(0.2, coalesce_sec)
        self._timer: asyncio.TimerHandle | None = None

    def _schedule(self) -> None:  # runs on the event-loop thread
        if self._timer is not None:
            self._timer.cancel()
        self._timer = self._loop.call_later(self._coalesce, self._fire)

    def _fire(self) -> None:  # event-loop thread
        self._timer = None
        asyncio.ensure_future(self._refresh_coro())

    def _maybe(self, path: str) -> None:
        p = str(path or "")
        if p.endswith(".yml") and not p.endswith(".tmp"):
            self._loop.call_soon_threadsafe(self._schedule)

    def on_created(self, event):
        self._maybe(getattr(event, "src_path", ""))

    def on_modified(self, event):
        self._maybe(getattr(event, "src_path", ""))

    def on_deleted(self, event):
        # A task file removed from the watch dir (archival) must drop off its board.
        self._maybe(getattr(event, "src_path", ""))

    def on_moved(self, event):
        # Atomic writes (.tmp→.yml) and archival moves both surface here.
        self._maybe(getattr(event, "src_path", ""))
        self._maybe(getattr(event, "dest_path", ""))


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
        # agent → Matrix event_id of its pinned board (persisted to boards.json)
        self._board_events: dict[str, str] = {}
        # agent → last-rendered signature (in-memory; drives no-op edit skipping)
        self._board_sigs: dict[str, str] = {}
        self._pinned_ids: list[str] | None = None
        self._refresh_lock = asyncio.Lock()
        self._boards_file = os.path.join(STATE_DIR, "boards.json")
        self._digest_stamp = os.path.join(STATE_DIR, "digest-stamp")

    # ── Matrix send helpers ────────────────────────────────────────────

    async def _send_html(self, room_id: str, plain: str, html: str) -> RoomSendResponse | None:
        resp = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": plain,
                "format": "org.matrix.custom.html",
                "formatted_body": html,
            },
        )
        if isinstance(resp, RoomSendResponse):
            return resp
        logger.warning("room_send failed in %s: %s", room_id, resp)
        return None

    async def _edit_html(self, room_id: str, event_id: str, plain: str, html: str) -> None:
        """Edit an existing message in place via an ``m.replace`` relation (silent, no ping)."""
        content = {
            "msgtype": "m.text",
            "body": f"* {plain}",
            "format": "org.matrix.custom.html",
            "formatted_body": html,
            "m.new_content": {
                "msgtype": "m.text",
                "body": plain,
                "format": "org.matrix.custom.html",
                "formatted_body": html,
            },
            "m.relates_to": {"rel_type": "m.replace", "event_id": event_id},
        }
        resp = await self.client.room_send(room_id, "m.room.message", content)
        if not isinstance(resp, RoomSendResponse):
            logger.warning("Board edit failed for %s: %s", event_id, resp)

    # ── Board state persistence ────────────────────────────────────────

    def _load_boards(self) -> None:
        try:
            with open(self._boards_file) as f:
                data = json.load(f)
            agents = data.get("agents", {}) if isinstance(data, dict) else {}
            self._board_events = {str(k): str(v) for k, v in agents.items() if v}
            logger.info(
                "Loaded %d board event ids from %s", len(self._board_events), self._boards_file
            )
        except (FileNotFoundError, ValueError, OSError):
            self._board_events = {}

    def _save_boards(self) -> None:
        tmp = f"{self._boards_file}.tmp"
        try:
            with open(tmp, "w") as f:
                json.dump({"agents": self._board_events}, f, indent=2)
            os.replace(tmp, self._boards_file)
        except OSError as e:
            logger.warning("Failed to persist boards.json: %s", e)

    def _read_digest_stamp(self) -> str:
        try:
            return Path(self._digest_stamp).read_text().strip()
        except OSError:
            return ""

    def _write_digest_stamp(self, day: str) -> None:
        try:
            Path(self._digest_stamp).write_text(day)
        except OSError as e:
            logger.warning("Failed to write digest stamp: %s", e)

    # ── Board rendering + refresh ──────────────────────────────────────

    def _ordered_agents(self, tasks: list[dict]) -> list[str]:
        """BOARD_AGENTS first (config order), then any other agent seen in the queue
        or already holding a board, appended so nothing is ever lost."""
        ordered = list(BOARD_AGENTS)
        extra = sorted(
            {
                t.get("target_agent")
                for t in tasks
                if t.get("target_agent")
                and t.get("target_agent") not in ordered
                and t.get("status") not in {"completed", "failed", "cancelled"}
            }
        )
        for agent in self._board_events:
            if agent not in ordered and agent not in extra:
                extra.append(agent)
        return ordered + extra

    async def _refresh_boards(self) -> None:
        """Rebuild every agent board from a fresh queue scan; edit only what changed."""
        async with self._refresh_lock:
            tasks = await self.task_client.list_tasks(limit=1000)
            ordered = self._ordered_agents(tasks)
            created_new = False
            for agent in ordered:
                rows = board_tasks(agent, tasks)
                sig = board_signature(agent, rows)
                event_id = self._board_events.get(agent)
                if event_id and self._board_sigs.get(agent) == sig:
                    continue  # no meaningful change — skip the edit to avoid churn
                plain, html = format_agent_board(agent, rows)
                if event_id:
                    await self._edit_html(ROOM_ID, event_id, plain, html)
                else:
                    resp = await self._send_html(ROOM_ID, plain, html)
                    if resp is None:
                        continue  # posting failed; retry on next refresh
                    self._board_events[agent] = resp.event_id
                    self._save_boards()
                    created_new = True
                self._board_sigs[agent] = sig
            if created_new:
                await self._pin_boards()

    async def _pin_boards(self) -> None:
        """Pin all agent boards in one ``m.room.pinned_events`` state event (order = BOARD_AGENTS)."""
        tasks = await self.task_client.list_tasks(limit=1000)
        ordered = self._ordered_agents(tasks)
        pinned = [self._board_events[a] for a in ordered if a in self._board_events]
        if not pinned or pinned == self._pinned_ids:
            return
        try:
            resp = await self.client.room_put_state(
                ROOM_ID, "m.room.pinned_events", {"pinned": pinned}
            )
            if isinstance(resp, RoomPutStateError):
                logger.warning(
                    "Could not pin boards (bot power level too low?): %s", resp
                )
                return
            self._pinned_ids = pinned
            logger.info("Pinned %d agent boards", len(pinned))
        except Exception as e:  # noqa: BLE001 — pinning is best-effort
            logger.warning("Pin failed: %s", e)

    # ── Daily morning brief ────────────────────────────────────────────

    async def _post_digest(self) -> None:
        tasks = await self.task_client.list_tasks(limit=1000)
        ordered = self._ordered_agents(tasks)
        agent_tasks = [(a, board_tasks(a, tasks)) for a in ordered]
        agent_tasks = [(a, rows) for a, rows in agent_tasks if rows]  # only agents with open work
        date_str = datetime.now().strftime("%Y-%m-%d")
        plain, html = format_digest(agent_tasks, date_str)
        resp = await self._send_html(ROOM_ID, plain, html)
        if resp is None:
            raise RuntimeError("digest send failed")

    async def _digest_loop(self) -> None:
        """Post one notifying morning brief at DIGEST_HOUR local time, then re-arm for +24h."""
        while True:
            now = datetime.now()
            target = now.replace(hour=DIGEST_HOUR, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            await asyncio.sleep(max(1.0, (target - now).total_seconds()))

            today = datetime.now().strftime("%Y-%m-%d")
            if self._read_digest_stamp() == today:
                logger.info("Digest already sent today (%s); skipping", today)
                continue
            try:
                await self._post_digest()
                self._write_digest_stamp(today)
                logger.info("Morning brief posted for %s", today)
            except Exception as e:  # noqa: BLE001
                logger.exception("Digest post failed: %s", e)

    # ── Matrix event handlers ──────────────────────────────────────────

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

    def _start_file_watcher(self) -> None:
        loop = asyncio.get_running_loop()
        handler = TaskFileHandler(loop, self._refresh_boards, BOARD_COALESCE_SEC)
        self._observer = Observer()
        self._observer.schedule(handler, TASK_QUEUE_DIR, recursive=False)
        self._observer.daemon = True
        self._observer.start()
        logger.info(
            "File watcher started on %s (coalesce %.1fs)", TASK_QUEUE_DIR, BOARD_COALESCE_SEC
        )

    async def run(self) -> None:
        logger.info("Starting task queue bot — homeserver=%s room=%s", HOMESERVER, ROOM_ID)

        # Register callbacks
        self.client.add_event_callback(self._handle_message, RoomMessageText)
        self.client.add_event_callback(self._handle_custom_event, Event)

        # Ensure dirs, load persisted board state, start the file watcher
        Path(TASK_QUEUE_DIR).mkdir(parents=True, exist_ok=True)
        Path(STATE_DIR).mkdir(parents=True, exist_ok=True)
        self._load_boards()
        self._start_file_watcher()

        # Paint boards to reflect current state on startup, then pin them
        try:
            await self._refresh_boards()
            await self._pin_boards()
        except Exception as e:  # noqa: BLE001
            logger.exception("Initial board refresh failed: %s", e)

        digest_task = asyncio.create_task(self._digest_loop())
        try:
            await self.client.sync_forever(timeout=30000, full_state=True)
        finally:
            digest_task.cancel()
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
