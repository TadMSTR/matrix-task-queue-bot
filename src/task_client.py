"""
Task queue client — every read and write goes through task-queue-mcp's HTTP API.

Mutations go through the control API, so they inherit the MCP core's transition
validation and fcntl locking. Since task-queue-mcp v0.11.0, reads go through its read
API too (GET /tasks, GET /tasks/{id}), so the queue's TTL, dead-letter and status rules
are applied by the queue's owner rather than re-implemented here. The bot parses no
queue YAML. Its file watcher is only a change trigger (see bot.py).

The bot authenticates with its own client token, sent as ``X-Task-Queue-Token`` and
never as ``Authorization``: task-queue-mcp's framework offers any bearer to its
agent-token verifier, and the control routes read only their own header. The token is
read from the file named by ``TASK_QUEUE_TOKEN_FILE``. The token value is never in any
environment, and the path is stripped from the environment of every session the bot
launches (see session.child_env).
"""

from __future__ import annotations

import ipaddress
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

_VALID_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

TOKEN_HEADER = "X-Task-Queue-Token"

# The largest page task-queue-mcp's GET /tasks returns. The boards read the whole active
# queue in one call; if that ever needs more than one page, report the number rather
# than paging silently or raising the server's cap.
LIST_PAGE_MAX = 1000

# The shortest id prefix a command may use. Shorter prefixes collide too easily.
MIN_PREFIX = 8

logger = logging.getLogger(__name__)


class TokenFileError(RuntimeError):
    """The token file is missing, empty or unreadable. The message never contains its content."""


class TaskQueueError(RuntimeError):
    """A read the API refused or could not serve. Raised, never returned as an empty list."""


class InsecureApiBaseError(ValueError):
    """TASK_QUEUE_API would carry the token in cleartext off this host."""


def check_api_base(api_base: str) -> str:
    """
    Return ``api_base`` without a trailing slash, or raise InsecureApiBaseError.

    The bot's token carries ``read,operator-write`` and goes on every request, reads
    included. Over plain HTTP to another host, anything on the path could take it and act
    as the operator. So ``http://`` is accepted only for a loopback host (the deployed
    default, ``http://127.0.0.1:8485``), and anything else must be ``https://``.
    """
    parts = urlsplit(api_base)
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and host:
        return api_base.rstrip("/")
    if parts.scheme == "http" and host:
        if host == "localhost":
            return api_base.rstrip("/")
        try:
            if ipaddress.ip_address(host).is_loopback:
                return api_base.rstrip("/")
        except ValueError:
            pass
    raise InsecureApiBaseError(
        f"TASK_QUEUE_API={api_base!r}: the client token may only be sent over https://, "
        "or over http:// to a loopback host"
    )


def load_token(path: str | Path) -> str:
    """
    Read the client token from ``path``. Raises TokenFileError when the file is missing,
    unreadable or empty.

    Surrounding whitespace is stripped, so a trailing newline from an editor or ``echo``
    does not become part of the token. A token is URL-safe base64 and has none.
    """
    p = Path(path).expanduser()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise TokenFileError(f"task-queue token file {p} is missing") from None
    except UnicodeError:
        # Named, not echoed: the bytes may still be most of a live token.
        raise TokenFileError(f"task-queue token file {p} is not valid UTF-8") from None
    except OSError as exc:
        raise TokenFileError(
            f"task-queue token file {p} is unreadable ({exc.__class__.__name__})"
        ) from None
    token = text.strip()
    if not token:
        raise TokenFileError(f"task-queue token file {p} is empty")
    return token


@dataclass
class TaskPage:
    tasks: list[dict[str, Any]] = field(default_factory=list)
    # How many records matched, which exceeds len(tasks) when the API truncated.
    count: int = 0
    truncated: bool = False


class TaskQueueClient:
    def __init__(
        self,
        api_base: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Checked here as well as at startup, so no construction path can skip it.
        self._api_base = check_api_base(api_base)
        self._token = token
        # Injectable for tests; production uses httpx's default transport.
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=10.0,
            transport=self._transport,
            headers={TOKEN_HEADER: self._token},
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        try:
            async with self._client() as client:
                return await client.get(f"{self._api_base}{path}", params=params)
        except httpx.HTTPError as e:
            raise TaskQueueError(f"task-queue API unreachable for {path}: {e}") from None

    async def list_page(
        self,
        target_agent: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> TaskPage:
        """
        One page of GET /tasks, with the API's ``count`` and ``truncated``. Raises
        TaskQueueError when the API fails, rather than returning an empty page that a
        caller would render as an empty queue.
        """
        params: dict[str, Any] = {"limit": max(1, min(limit, LIST_PAGE_MAX))}
        if target_agent:
            params["target_agent"] = target_agent
        if status:
            params["status"] = status
        resp = await self._get("/tasks", params)
        if resp.status_code != 200:
            raise TaskQueueError(f"GET /tasks -> {resp.status_code}: {resp.text[:200]}")
        # A malformed body is a failed read, not an empty queue. Iterating a dict or a string
        # "tasks" would otherwise filter down to [] and repaint every board as empty.
        try:
            data = resp.json()
            if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
                raise ValueError("expected an object with a 'tasks' list")
            tasks = [t for t in data["tasks"] if isinstance(t, dict)]
            count = int(data.get("count", len(tasks)))
        except (ValueError, TypeError) as exc:
            raise TaskQueueError(f"GET /tasks returned a malformed body: {exc}") from None
        page = TaskPage(tasks=tasks, count=count, truncated=data.get("truncated") is True)
        if page.truncated:
            logger.warning(
                "task list truncated: %d of %d matching records returned (limit %d)",
                len(page.tasks),
                page.count,
                params["limit"],
            )
        return page

    async def list_tasks(
        self,
        target_agent: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Tasks from GET /tasks, created descending. See list_page for errors."""
        return (await self.list_page(target_agent, status, limit)).tasks

    async def get_task(self, task_id: str) -> dict[str, Any]:
        """
        A task by full id or by a prefix of at least MIN_PREFIX characters. Returns {}
        when no task matches, or when a prefix matches more than one.

        A full id goes to GET /tasks/{id}, which also finds archived and dead-lettered
        records. A prefix is resolved against the active queue listing, because the API
        takes only full ids.
        """
        task_id = task_id.strip()
        if not _VALID_ID.match(task_id):
            return {}

        try:
            full = str(uuid.UUID(task_id))
        except ValueError:
            full = None

        if full is not None:
            resp = await self._get(f"/tasks/{full}")
            if resp.status_code in (400, 404):
                return {}
            if resp.status_code != 200:
                raise TaskQueueError(f"GET /tasks/{{id}} -> {resp.status_code}: {resp.text[:200]}")
            try:
                data = resp.json()
            except ValueError:
                raise TaskQueueError("GET /tasks/{id} returned a malformed body") from None
            if not isinstance(data, dict):
                raise TaskQueueError("GET /tasks/{id} returned a malformed body")
            task = data.get("task")
            return task if isinstance(task, dict) else {}

        if len(task_id) < MIN_PREFIX:
            return {}
        prefix = task_id.lower()
        page = await self.list_page(limit=LIST_PAGE_MAX)
        matches = [t for t in page.tasks if str(t.get("id", "")).startswith(prefix)]
        if page.truncated and matches:
            # A truncated page cannot prove the prefix is unique: a second match may sit
            # past the cut. Refuse rather than act on the one that happened to be visible.
            logger.warning(
                "id prefix %s: queue listing truncated, cannot prove it is unique; use the full id",
                prefix,
            )
            return {}
        if len(matches) > 1:
            # The old reader returned whichever file it met first. Acting on an arbitrary
            # one of two tasks is worse than asking for a longer id.
            logger.warning("id prefix %s matches %d tasks; refusing to guess", prefix, len(matches))
            return {}
        return matches[0] if matches else {}

    async def update_task(
        self, task_id: str, status: str, actor: str, note: str = ""
    ) -> dict[str, Any]:
        """
        Mutate a task via the control API. Resolves a short id prefix through the read
        API first, since the control API takes only full ids. Returns the API result
        ({"ok": true, ...}) or {} on failure.

        ``actor`` is sent for readability; the server pins every control-route write to
        `operator` and records this bot as ``channel: matrix-bot``.
        """
        if not _VALID_ID.match(task_id):
            return {}

        task = await self.get_task(task_id)
        if not task:
            return {}
        full_id = str(task.get("id", ""))
        if not full_id:
            return {}

        if status == "approved":
            return await self._post(f"/tasks/{full_id}/approve", {"actor": actor, "note": note})
        if status == "cancelled":
            return await self._post(f"/tasks/{full_id}/cancel", {"actor": actor, "note": note})
        return await self._post(
            f"/tasks/{full_id}/status",
            {"status": status, "actor": actor, "note": note},
        )

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._client() as client:
                resp = await client.post(f"{self._api_base}{path}", json=payload)
        except httpx.HTTPError as e:
            logger.error("Control API request to %s failed: %s", path, e)
            return {}
        if resp.status_code >= 400:
            logger.error("Control API %s -> %s: %s", path, resp.status_code, resp.text[:200])
            return {}
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    async def close(self) -> None:
        pass
