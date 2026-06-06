"""HTTP client for task-queue-mcp (FastMCP JSON-RPC)."""

from __future__ import annotations

import json
import logging
from itertools import count
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_rpc_counter = count(1)


class TaskQueueClient:
    def __init__(self, mcp_url: str) -> None:
        self._url = mcp_url
        self._http = httpx.AsyncClient(timeout=15.0)

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        rpc_id = next(_rpc_counter)
        body = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "tools/call",
            "params": {"name": method, "arguments": params or {}},
        }
        resp = await self._http.post(self._url, json=body)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data and data["error"]:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        text = data.get("result", {}).get("content", [{}])[0].get("text", "")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    async def list_tasks(
        self,
        target_agent: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if target_agent:
            params["target_agent"] = target_agent
        if status:
            params["status"] = status
        result = await self._call("list_tasks", params)
        return result if isinstance(result, list) else []

    async def get_task(self, task_id: str) -> dict[str, Any]:
        result = await self._call("get_task", {"task_id": task_id})
        return result if isinstance(result, dict) else {}

    async def update_task(
        self, task_id: str, status: str, actor: str, note: str = ""
    ) -> dict[str, Any]:
        result = await self._call(
            "update_task",
            {"task_id": task_id, "status": status, "actor": actor, "note": note},
        )
        return result if isinstance(result, dict) else {}

    async def close(self) -> None:
        await self._http.aclose()
