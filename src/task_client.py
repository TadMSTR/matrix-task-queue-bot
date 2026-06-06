"""Task queue client — reads YAML files directly from the task queue directory."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_VALID_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

logger = logging.getLogger(__name__)


class TaskQueueClient:
    def __init__(self, task_dir: str) -> None:
        self._dir = Path(task_dir)

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
        if not _VALID_ID.match(task_id):
            return {}
        for f in self._dir.glob("*.yml"):
            try:
                data = yaml.safe_load(f.read_text())
                if not isinstance(data, dict):
                    continue
                fid = str(data.get("id", ""))
                if fid == task_id or (len(task_id) >= 8 and fid.startswith(task_id)):
                    data["status"] = status
                    now = datetime.now(timezone.utc).isoformat()
                    if "history" not in data or not isinstance(data["history"], list):
                        data["history"] = []
                    data["history"].append({
                        "timestamp": now,
                        "status": status,
                        "actor": actor,
                        "note": note,
                    })
                    tmp = f.with_suffix(".tmp")
                    tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
                    tmp.rename(f)
                    return data
            except Exception:
                logger.warning("Failed to update %s", f)
        return {}

    async def close(self) -> None:
        pass
