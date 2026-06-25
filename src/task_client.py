"""
Task queue client.

Reads are direct YAML off the queue directory (fast, no dependency). Mutations go
through the task-queue-mcp HTTP control API (shared-secret gated), so they inherit the
MCP core's transition validation + fcntl locking. The bot no longer writes YAML directly.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

_VALID_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

logger = logging.getLogger(__name__)


class TaskQueueClient:
    def __init__(
        self,
        task_dir: str,
        api_base: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self._dir = Path(task_dir)
        self._api_base = (api_base or "").rstrip("/")
        self._api_secret = api_secret or ""

    def _load_all(self) -> list[dict[str, Any]]:
        tasks = []
        for f in self._dir.glob("*.yml"):
            try:
                data = yaml.safe_load(f.read_text())
                if isinstance(data, dict) and "id" in data:
                    tasks.append(data)
            except Exception:
                logger.warning("Failed to parse %s", f)
        return tasks

    async def list_tasks(
        self,
        target_agent: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        tasks = self._load_all()
        if target_agent:
            tasks = [t for t in tasks if t.get("target_agent") == target_agent]
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        tasks.sort(key=lambda t: str(t.get("created", "")), reverse=True)
        return tasks[:limit]

    async def get_task(self, task_id: str) -> dict[str, Any]:
        if not _VALID_ID.match(task_id):
            return {}
        for f in self._dir.glob("*.yml"):
            try:
                data = yaml.safe_load(f.read_text())
                if isinstance(data, dict):
                    fid = str(data.get("id", ""))
                    if fid == task_id or (len(task_id) >= 8 and fid.startswith(task_id)):
                        return data
            except Exception:
                continue
        return {}

    async def update_task(
        self, task_id: str, status: str, actor: str, note: str = ""
    ) -> dict[str, Any]:
        """
        Mutate a task via the MCP control API (the single validated write path).
        Resolves a short id prefix locally (reads stay direct), then POSTs to the API.
        Returns the API result ({"ok": true, ...}) or {} on failure.
        """
        if not _VALID_ID.match(task_id):
            return {}

        # Resolve to a full UUID — the control API requires it.
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
        if not self._api_base or not self._api_secret:
            logger.error(
                "Control API not configured (TASK_QUEUE_API / TASK_QUEUE_API_SECRET); "
                "refusing to mutate %s", path,
            )
            return {}
        url = f"{self._api_base}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"X-Task-Queue-Secret": self._api_secret},
                )
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
