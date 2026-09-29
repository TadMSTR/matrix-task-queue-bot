"""HTML formatters for Matrix messages."""

from __future__ import annotations

from datetime import UTC
from typing import Any


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ago(ts: Any) -> str:
    from datetime import datetime

    try:
        if isinstance(ts, datetime):
            dt = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts)
        else:
            return str(ts)
        delta = datetime.now(UTC) - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except (ValueError, TypeError):
        return str(ts)


def _status_emoji(status: str) -> str:
    return {
        "approved": "\u2705",
        "in-progress": "\u26a1",
        "submitted": "\u23f3",
        "pending-approval": "\u23f3",
        "completed": "\u2714\ufe0f",
        "failed": "\u274c",
    }.get(status, "\u2753")


def _priority_marker(priority: str) -> str:
    return {"urgent": "\u203c\ufe0f", "high": "\u2757"}.get(priority, "")


def format_task_table(tasks: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (plain_text, html) for a task list."""
    if not tasks:
        return "No tasks found.", "<em>No tasks found.</em>"

    lines = []
    html_rows = []
    for t in tasks:
        short_id = t["id"][:8]
        status = t.get("status", "?")
        agent = t.get("target_agent", "?")
        summary = t.get("summary", "")[:60]
        priority = t.get("payload", {}).get("priority", "normal")
        pm = _priority_marker(priority)
        se = _status_emoji(status)
        age = _ago(t.get("created", ""))

        lines.append(f"{short_id} | {agent:10s} | {status:18s} | {summary}")
        html_rows.append(
            f"<tr><td><code>{_esc(short_id)}</code></td>"
            f"<td>{_esc(agent)}</td>"
            f"<td>{se} {_esc(status)}</td>"
            f"<td>{pm} {_esc(summary)}</td>"
            f"<td>{_esc(age)}</td></tr>"
        )

    plain = "\n".join(lines)
    html = (
        "<table><thead><tr>"
        "<th>ID</th><th>Agent</th><th>Status</th><th>Summary</th><th>Age</th>"
        "</tr></thead><tbody>" + "".join(html_rows) + "</tbody></table>"
    )
    return plain, html


def format_task_detail(task: dict[str, Any]) -> tuple[str, str]:
    """Return (plain_text, html) for a single task detail."""
    tid = task.get("id", "?")
    status = task.get("status", "?")
    summary = task.get("summary", "")
    source = task.get("source_agent", "?")
    target = task.get("target_agent", "?")
    task_type = task.get("task_type", "?")
    risk = task.get("risk_level", "?")
    priority = task.get("payload", {}).get("priority", "normal")
    description = task.get("payload", {}).get("description", "")
    created = task.get("created", "")
    history = task.get("history", [])

    se = _status_emoji(status)
    pm = _priority_marker(priority)

    plain_lines = [
        f"Task: {tid}",
        f"Status: {status}",
        f"Summary: {summary}",
        f"Source: {source} -> Target: {target}",
        f"Type: {task_type} | Risk: {risk} | Priority: {priority}",
        f"Created: {_ago(created)}",
        "",
        "Description:",
        description[:500] if description else "(none)",
    ]

    if history:
        plain_lines.append("")
        plain_lines.append("History:")
        for h in history[-5:]:
            plain_lines.append(
                f"  {_ago(h.get('timestamp', ''))} — {h.get('status', '')} "
                f"by {h.get('actor', '')} {h.get('note', '')}"
            )

    plain = "\n".join(plain_lines)

    # HTML version
    history_html = ""
    if history:
        history_rows = "".join(
            f"<tr><td>{_esc(_ago(h.get('timestamp', '')))}</td>"
            f"<td>{_status_emoji(h.get('status', ''))} {_esc(h.get('status', ''))}</td>"
            f"<td>{_esc(h.get('actor', ''))}</td>"
            f"<td>{_esc(h.get('note', ''))}</td></tr>"
            for h in history[-5:]
        )
        history_html = (
            "<br/><strong>History</strong>"
            "<table><thead><tr><th>When</th><th>Status</th><th>Actor</th><th>Note</th></tr></thead>"
            f"<tbody>{history_rows}</tbody></table>"
        )

    desc_html = f"<pre>{_esc(description[:500])}</pre>" if description else "<em>(none)</em>"

    html = (
        f"<strong>{se} {_esc(summary)}</strong><br/>"
        f"<code>{_esc(tid)}</code><br/>"
        f"<strong>Status:</strong> {se} {_esc(status)} "
        f"| <strong>Priority:</strong> {pm} {_esc(priority)} "
        f"| <strong>Risk:</strong> {_esc(risk)}<br/>"
        f"<strong>Source:</strong> {_esc(source)} → <strong>Target:</strong> {_esc(target)} "
        f"| <strong>Type:</strong> {_esc(task_type)}<br/>"
        f"<strong>Created:</strong> {_esc(_ago(created))}<br/><br/>"
        f"<strong>Description</strong><br/>{desc_html}"
        f"{history_html}"
    )

    return plain, html


def format_status_update(task: dict[str, Any], old_status: str) -> tuple[str, str]:
    """Format a status change notification."""
    short_id = task["id"][:8]
    new_status = task.get("status", "?")
    summary = task.get("summary", "")[:60]
    target = task.get("target_agent", "?")
    workflow_mode = task.get("workflow_mode", "semi-auto")
    se = _status_emoji(new_status)

    # SECURITY[accepted]: mode_tag uses raw workflow_mode in plain text. Mitigated: value
    # is validated against task-queue-mcp's VALID_WORKFLOW_MODES at submission time.
    # Manual YAML edits require filesystem access (accepted risk for internal tooling).
    # Audit: 2026-06-08/workflow-qol-2026-06 INFO-2.
    # (The set was {"semi-auto", "auto"} when that note was written; `manual-then-auto`
    # joined it in task-queue-headless-chain-2026-08. The mitigation is unchanged —
    # it rests on there being validation, not on the specific values.)
    mode_tag = f" [{workflow_mode}]" if new_status == "approved" else ""
    plain = f"Task {short_id} ({target}): {old_status} → {new_status}{mode_tag} — {summary}"
    html = (
        f"{se} Task <code>{_esc(short_id)}</code> assigned to <strong>{_esc(target)}</strong> "
        f"moved to <strong>{_esc(new_status)}</strong>"
    )
    # Deliberately the INVERSE of the dispatcher's launch test, not a list of modes.
    # task-dispatcher.py launches on `workflow_mode == "auto"` and sends everything else
    # to operator pickup, so "everything that is not literally auto is waiting for you"
    # is the same rule stated once. Enumerating modes here instead is what left
    # `manual-then-auto` rendering as though it had been launched, when it is in fact
    # sitting and waiting — the single most misleading thing this line could say.
    if new_status == "approved" and workflow_mode != "auto":
        waiting = f"{_esc(workflow_mode)} — awaiting operator pickup"
        if workflow_mode == "manual-then-auto":
            waiting += "; the rest of the chain runs itself"
        html += (
            f" <em>[{waiting}]</em> — {_esc(summary)}"
            f"<br/>Resume: check #{_esc(target)} room for task details."
        )
    else:
        html += f" — {_esc(summary)}"
    return plain, html


# ── Live per-agent status boards ───────────────────────────────────────

# Statuses that keep a task off the boards entirely.
BOARD_TERMINAL = {"completed", "failed", "cancelled"}

_PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
_STATUS_RANK = {"in-progress": 0, "approved": 1, "pending-approval": 2, "submitted": 3}


def _priority_of(task: dict[str, Any]) -> str:
    return task.get("payload", {}).get("priority", "normal") or "normal"


def board_tasks(agent: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One agent's non-terminal tasks, sorted priority → status → age (oldest first)."""
    rows = [
        t for t in tasks if t.get("target_agent") == agent and t.get("status") not in BOARD_TERMINAL
    ]
    rows.sort(
        key=lambda t: (
            _PRIORITY_RANK.get(_priority_of(t), 2),
            _STATUS_RANK.get(t.get("status", ""), 9),
            str(t.get("created", "")),
        )
    )
    return rows


def board_signature(agent: str, tasks: list[dict[str, Any]]) -> str:
    """Volatile-free fingerprint of a board (excludes age / render time) for no-op edit skipping."""
    parts = [
        "|".join(
            (
                str(t.get("id", "")),
                str(t.get("status", "")),
                str(_priority_of(t)),
                str(t.get("task_type", "")),
                str(t.get("summary", "")),
            )
        )
        for t in tasks
    ]
    return f"{agent}::" + ";;".join(parts)


def _now_hhmm() -> str:
    from datetime import datetime

    return datetime.now().strftime("%H:%M")


def _board_rows_html(tasks: list[dict[str, Any]]) -> str:
    rows = []
    for t in tasks:
        short_id = str(t.get("id", ""))[:8]
        status = t.get("status", "?")
        priority = _priority_of(t)
        task_type = t.get("task_type", "?")
        summary = t.get("summary", "")[:60]
        pm = _priority_marker(priority)
        se = _status_emoji(status)
        age = _ago(t.get("created", ""))
        rows.append(
            f"<tr><td><code>{_esc(short_id)}</code></td>"
            f"<td>{pm} {_esc(priority)}</td>"
            f"<td>{se} {_esc(status)}</td>"
            f"<td>{_esc(task_type)}</td>"
            f"<td>{_esc(summary)}</td>"
            f"<td>{_esc(age)}</td></tr>"
        )
    return "".join(rows)


def truncation_notice(truncated: bool, matched: int) -> str:
    """
    The line a board or digest carries when the queue read was cut off, else "".

    Rendered, never dropped. A truncated read makes every count on the board a floor, and
    an agent's board can read "no open tasks" while it has some past the cut.
    """
    if not truncated:
        return ""
    return f"⚠ queue read truncated: {matched} records matched, not all shown"


def format_agent_board(
    agent: str,
    tasks: list[dict[str, Any]],
    truncated: bool = False,
    matched: int = 0,
) -> tuple[str, str]:
    """Return (plain, html) for one agent's live board.

    ``tasks`` must already be filtered + sorted board rows (see ``board_tasks``).
    The ``updated HH:MM`` footer is a wall-clock stamp, not a relative age: an
    edited board does not re-render until the next real change, so a frozen
    "updated 14:32" honestly reports when the board last changed.
    """
    n = len(tasks)
    label = agent.upper()
    updated = _now_hhmm()
    notice = truncation_notice(truncated, matched)

    if not tasks:
        plain = f"{label} ({n}) — no open tasks (updated {updated})"
        html = (
            f"<strong>{_esc(label)} ({n})</strong> — ✔️ no open tasks<br/><em>updated {updated}</em>"
        )
        if notice:
            plain += f"\n  {notice}"
            html += f"<br/><strong>{_esc(notice)}</strong>"
        return plain, html

    plain_lines = [f"{label} ({n})"]
    for t in tasks:
        plain_lines.append(
            f"  {str(t.get('id', ''))[:8]} | {_priority_of(t):6s} | {t.get('status', '?'):15s} "
            f"| {t.get('task_type', '?'):10s} | {t.get('summary', '')[:60]} "
            f"| {_ago(t.get('created', ''))}"
        )
    plain_lines.append(f"  updated {updated}")
    if notice:
        plain_lines.append(f"  {notice}")
    plain = "\n".join(plain_lines)

    html = (
        f"<strong>{_esc(label)} ({n})</strong>"
        "<table><thead><tr>"
        "<th>ID</th><th>Priority</th><th>Status</th><th>Type</th><th>Summary</th><th>Age</th>"
        "</tr></thead><tbody>" + _board_rows_html(tasks) + "</tbody></table>"
        f"<em>updated {updated}</em>"
    )
    if notice:
        html += f"<br/><strong>{_esc(notice)}</strong>"
    return plain, html


def format_digest(
    agent_tasks: list[tuple[str, list[dict[str, Any]]]],
    date_str: str,
    truncated: bool = False,
    matched: int = 0,
) -> tuple[str, str]:
    """Return (plain, html) for the daily morning brief — open boards stacked.

    ``agent_tasks`` is an ordered list of (agent, board_rows); callers should pass
    only agents that have open tasks.
    """
    total = sum(len(t) for _, t in agent_tasks)
    n_agents = len(agent_tasks)
    header = f"Morning brief — {date_str} · {total} non-completed across {n_agents} agents"

    plain_parts = [header, ""]
    html_parts = [f"<strong>\U0001f304 {_esc(header)}</strong>"]
    # Once, at the top, rather than on every stacked board.
    notice = truncation_notice(truncated, matched)
    if notice:
        plain_parts.insert(1, notice)
        html_parts.append(f"<br/><strong>{_esc(notice)}</strong>")
    for agent, tasks in agent_tasks:
        p, h = format_agent_board(agent, tasks)
        plain_parts.append(p)
        plain_parts.append("")
        html_parts.append("<br/>" + h)
    return "\n".join(plain_parts).rstrip(), "".join(html_parts)
