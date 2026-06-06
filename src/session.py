"""Agent session launcher — headless claude -p or trigger-proxy."""

from __future__ import annotations

import logging
import os
import subprocess

import httpx

logger = logging.getLogger(__name__)

HOME = os.path.expanduser("~")

AGENT_PROJECTS: dict[str, str] = {
    "sysadmin": os.path.join(HOME, ".claude", "projects", "sysadmin"),
    "developer": os.path.join(HOME, ".claude", "projects", "developer"),
    "research": os.path.join(HOME, ".claude", "projects", "research"),
    "writer": os.path.join(HOME, ".claude", "projects", "writer"),
    "security": os.path.join(HOME, ".claude", "projects", "security"),
}


def _build_prompt(task_id: str, mode: str) -> str:
    if mode == "review":
        return (
            f"You have a pending task (id={task_id}). "
            "Read it from task-queue-mcp via get_task. "
            "Present a summary of the work entailed. Do NOT begin execution — wait for operator approval."
        )
    return (
        f"You have a pending task (id={task_id}). "
        "Read it from task-queue-mcp via get_task. "
        "Claim it (update status to in-progress), then execute the task."
    )


def launch_headless(task_id: str, target_agent: str, mode: str) -> dict[str, str]:
    """Launch a headless claude session."""
    project_dir = AGENT_PROJECTS.get(target_agent)
    if not project_dir:
        return {"ok": "false", "error": f"Unknown agent: {target_agent}"}
    if not os.path.isdir(project_dir):
        return {"ok": "false", "error": f"Project dir missing: {project_dir}"}

    prompt = _build_prompt(task_id, mode)
    permission_mode = "plan" if mode == "review" else "default"

    proc = subprocess.Popen(
        ["claude", "--project", project_dir, "-p", prompt, "--permission-mode", permission_mode],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("Launched headless session: pid=%d agent=%s task=%s mode=%s", proc.pid, target_agent, task_id, mode)
    return {"ok": "true", "pid": str(proc.pid)}


async def launch_trigger_proxy(
    task_id: str,
    target_agent: str,
    trigger_id: str,
    proxy_url: str,
    secret: str,
) -> dict[str, str]:
    """Launch via trigger-proxy."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{proxy_url}/fire-trigger",
            json={
                "trigger_id": trigger_id,
                "target_agent": target_agent,
                "task_id": task_id,
            },
            headers={"X-Trigger-Secret": secret, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return {"ok": "true", "trigger_id": trigger_id}
