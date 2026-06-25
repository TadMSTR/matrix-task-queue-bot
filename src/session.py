"""Agent session launcher — headless claude -p or trigger-proxy."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess

import httpx

logger = logging.getLogger(__name__)

HOME = os.path.expanduser("~")
LAUNCH_LOG_DIR = os.path.join(HOME, ".claude", "comms", "artifacts", "task-launches")
_VALID_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

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
    if not _VALID_ID.match(task_id):
        return {"ok": "false", "error": f"Invalid task id: {task_id}"}

    project_dir = AGENT_PROJECTS.get(target_agent)
    if not project_dir:
        return {"ok": "false", "error": f"Unknown agent: {target_agent}"}
    if not os.path.isdir(project_dir):
        return {"ok": "false", "error": f"Project dir missing: {project_dir}"}

    # Resolve the binary up front so a missing CLI is a clean error, not a silent exit.
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return {"ok": "false", "error": "claude CLI not found on PATH"}

    prompt = _build_prompt(task_id, mode)
    permission_mode = "plan" if mode == "review" else "default"

    # Per-launch log replaces DEVNULL so a failed launch is diagnosable.
    # cwd=project_dir is how Claude Code resolves project config — `--project` is not a valid flag.
    os.makedirs(LAUNCH_LOG_DIR, exist_ok=True)
    log_path = os.path.join(LAUNCH_LOG_DIR, f"{task_id}.log")
    with open(log_path, "a") as log_fh:
        proc = subprocess.Popen(
            [claude_bin, "-p", prompt, "--permission-mode", permission_mode],
            cwd=project_dir,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
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
