"""HTML formatters for Matrix messages."""

from __future__ import annotations

from typing import Any


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ago(ts: Any) -> str:
    from datetime import datetime, timezone

    try:
        if isinstance(ts, datetime):
            dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts)
        else:
            return str(ts)
        delta = datetime.now(timezone.utc) - dt
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
        "</tr></thead><tbody>"
        + "".join(html_rows)
        + "</tbody></table>"
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
                f"  {_ago(h.get('timestamp', ''))} — {h.get('status', '')} by {h.get('actor', '')} {h.get('note', '')}"
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

    mode_tag = f" [{workflow_mode}]" if new_status == "approved" else ""
    plain = f"Task {short_id} ({target}): {old_status} → {new_status}{mode_tag} — {summary}"
    html = (
        f"{se} Task <code>{_esc(short_id)}</code> assigned to <strong>{_esc(target)}</strong> "
        f"moved to <strong>{_esc(new_status)}</strong>"
    )
    if new_status == "approved" and workflow_mode == "semi-auto":
        html += (
            f" <em>[semi-auto — awaiting operator pickup]</em> — {_esc(summary)}"
            f"<br/>Resume: check #{_esc(target)} room for task details."
        )
    else:
        html += f" — {_esc(summary)}"
    return plain, html
