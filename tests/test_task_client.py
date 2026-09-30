"""
Tests for task_client: the token file, and the read/write calls to task-queue-mcp.

The HTTP side runs against httpx.MockTransport, so nothing here needs a server, and the
token is a test constant. Only task_client is imported: bot.py reads its configuration at
import time and would exit without a Matrix credential.
"""

import asyncio
import json
import os
import uuid

import httpx
import pytest

from src.task_client import (
    LIST_PAGE_MAX,
    TOKEN_HEADER,
    TaskQueueClient,
    TaskQueueError,
    TokenFileError,
    load_token,
)

TOKEN = "synthetic-test-token-0123456789abcdef"
BASE = "http://127.0.0.1:8485"


# ── load_token ──────────────────────────────────────────────────────────


def test_a_token_file_loads_with_its_newline_stripped(tmp_path):
    f = tmp_path / "token"
    f.write_text(TOKEN + "\n")
    assert load_token(f) == TOKEN


def test_a_missing_token_file_fails_and_names_the_path(tmp_path):
    f = tmp_path / "absent"
    with pytest.raises(TokenFileError, match="is missing") as exc:
        load_token(f)
    assert str(f) in str(exc.value)


@pytest.mark.parametrize("content", ["", "\n", "  \t\n"])
def test_an_empty_token_file_fails(tmp_path, content):
    f = tmp_path / "token"
    f.write_text(content)
    with pytest.raises(TokenFileError, match="is empty"):
        load_token(f)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads through mode 000")
def test_an_unreadable_token_file_fails_without_its_content(tmp_path):
    f = tmp_path / "token"
    f.write_text(TOKEN)
    f.chmod(0o000)
    try:
        with pytest.raises(TokenFileError, match="unreadable") as exc:
            load_token(f)
        assert TOKEN not in str(exc.value)
    finally:
        f.chmod(0o600)


def test_a_tilde_path_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "token").write_text(TOKEN)
    assert load_token("~/token") == TOKEN


# ── HTTP ────────────────────────────────────────────────────────────────


def _client(handler):
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return TaskQueueClient(BASE, TOKEN, transport=httpx.MockTransport(record)), seen


def _page(tasks, count=None, truncated=False):
    body = {"ok": True, "tasks": tasks, "count": len(tasks) if count is None else count}
    body["truncated"] = truncated
    return httpx.Response(200, json=body)


def test_every_request_carries_the_token_header_and_no_bearer():
    client, seen = _client(lambda r: _page([]))
    asyncio.run(client.list_tasks())
    assert seen[0].headers[TOKEN_HEADER] == TOKEN
    assert "authorization" not in seen[0].headers
    assert "x-task-queue-secret" not in seen[0].headers


def test_list_passes_filters_and_caps_the_limit():
    client, seen = _client(lambda r: _page([]))
    asyncio.run(client.list_tasks(target_agent="developer", status="approved", limit=5000))
    q = dict(seen[0].url.params)
    assert q == {"limit": str(LIST_PAGE_MAX), "target_agent": "developer", "status": "approved"}
    assert seen[0].url.path == "/tasks"


def test_list_page_reports_truncation(caplog):
    client, _ = _client(lambda r: _page([{"id": "a"}], count=7, truncated=True))
    page = asyncio.run(client.list_page(limit=1))
    assert (len(page.tasks), page.count, page.truncated) == (1, 7, True)
    assert any("truncated" in rec.getMessage() for rec in caplog.records)


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_failed_list_raises_rather_than_returning_an_empty_queue(status):
    client, _ = _client(lambda r: httpx.Response(status, json={"ok": False, "error": "no"}))
    with pytest.raises(TaskQueueError):
        asyncio.run(client.list_tasks())


def test_an_unreachable_api_raises():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    client, _ = _client(boom)
    with pytest.raises(TaskQueueError, match="unreachable"):
        asyncio.run(client.list_tasks())


def test_get_task_by_full_id_uses_the_detail_route():
    tid = str(uuid.uuid4())
    client, seen = _client(lambda r: httpx.Response(200, json={"ok": True, "task": {"id": tid}}))
    assert asyncio.run(client.get_task(tid)) == {"id": tid}
    assert seen[0].url.path == f"/tasks/{tid}"


@pytest.mark.parametrize("status", [400, 404])
def test_get_task_not_found_is_empty(status):
    client, _ = _client(lambda r: httpx.Response(status, json={"ok": False}))
    assert asyncio.run(client.get_task(str(uuid.uuid4()))) == {}


def test_get_task_by_prefix_resolves_one_match():
    tid = "abcdef12-0000-4000-8000-000000000000"
    other = "99999999-0000-4000-8000-000000000000"
    client, seen = _client(lambda r: _page([{"id": other}, {"id": tid}]))
    assert asyncio.run(client.get_task("abcdef12"))["id"] == tid
    assert seen[0].url.path == "/tasks"


def test_a_prefix_on_a_truncated_page_resolves_to_nothing():
    tid = "abcdef12-0000-4000-8000-000000000000"
    client, _ = _client(lambda r: _page([{"id": tid}], count=1500, truncated=True))
    assert asyncio.run(client.get_task("abcdef12")) == {}


@pytest.mark.parametrize(
    "body",
    [
        {"ok": True, "tasks": {"id": "x"}, "count": 1},  # dict, would iterate to []
        {"ok": True, "tasks": "abc", "count": 1},  # string
        {"ok": True, "count": 0},  # missing
        ["not", "an", "object"],
        {"ok": True, "tasks": [], "count": "many"},  # unconvertible count
    ],
)
def test_a_malformed_list_body_raises(body):
    client, _ = _client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(TaskQueueError, match="malformed"):
        asyncio.run(client.list_tasks())


def test_a_non_json_list_body_raises():
    client, _ = _client(lambda r: httpx.Response(200, text="<html>proxy error</html>"))
    with pytest.raises(TaskQueueError, match="malformed"):
        asyncio.run(client.list_tasks())


def test_a_numeric_string_count_is_accepted():
    client, _ = _client(lambda r: httpx.Response(200, json={"tasks": [], "count": "3"}))
    assert asyncio.run(client.list_page()).count == 3


def test_an_ambiguous_prefix_resolves_to_nothing():
    a = "abcdef12-0000-4000-8000-000000000000"
    b = "abcdef12-1111-4000-8000-000000000000"
    client, _ = _client(lambda r: _page([{"id": a}, {"id": b}]))
    assert asyncio.run(client.get_task("abcdef12")) == {}


@pytest.mark.parametrize("bad", ["abc", "../etc", "a b c d e f g h", ""])
def test_short_or_malformed_ids_never_reach_the_api(bad):
    client, seen = _client(lambda r: _page([]))
    assert asyncio.run(client.get_task(bad)) == {}
    assert seen == []


def test_approve_resolves_the_id_then_posts_with_the_token():
    tid = str(uuid.uuid4())

    def handler(r):
        if r.method == "GET":
            return httpx.Response(200, json={"ok": True, "task": {"id": tid}})
        return httpx.Response(200, json={"ok": True, "task_id": tid})

    client, seen = _client(handler)
    result = asyncio.run(client.update_task(tid, "approved", "operator", "via test"))
    assert result == {"ok": True, "task_id": tid}
    post = seen[-1]
    assert (post.method, post.url.path) == ("POST", f"/tasks/{tid}/approve")
    assert post.headers[TOKEN_HEADER] == TOKEN
    assert json.loads(post.content) == {"actor": "operator", "note": "via test"}


def test_a_refused_write_returns_empty():
    tid = str(uuid.uuid4())

    def handler(r):
        if r.method == "GET":
            return httpx.Response(200, json={"ok": True, "task": {"id": tid}})
        return httpx.Response(403, json={"ok": False, "error": "scope operator-write required"})

    client, _ = _client(handler)
    assert asyncio.run(client.update_task(tid, "cancelled", "operator")) == {}


# ── transport and input hardening (CodeRabbit on #8) ────────────────────

from src.task_client import InsecureApiBaseError, check_api_base  # noqa: E402


@pytest.mark.parametrize(
    "base",
    [
        "http://127.0.0.1:8485",
        "http://127.0.0.1:8485/",
        "http://localhost:8485",
        "http://[::1]:8485",
        "https://tasks.example.com",
        "https://10.0.0.5:8485",
    ],
)
def test_loopback_http_and_any_https_are_accepted(base):
    assert check_api_base(base) == base.rstrip("/")


@pytest.mark.parametrize(
    "base",
    [
        "http://10.0.0.5:8485",
        "http://tasks.example.com",
        "http://127.0.0.1.evil.example:8485",
        "ftp://127.0.0.1",
        "127.0.0.1:8485",
        "",
    ],
)
def test_cleartext_to_another_host_is_refused(base):
    with pytest.raises(InsecureApiBaseError):
        check_api_base(base)


def test_the_client_refuses_an_insecure_base_at_construction():
    with pytest.raises(InsecureApiBaseError):
        TaskQueueClient("http://10.0.0.5:8485", TOKEN)


def test_a_non_utf8_token_file_is_a_token_file_error(tmp_path):
    f = tmp_path / "token"
    f.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(TokenFileError, match="not valid UTF-8"):
        load_token(f)


@pytest.mark.parametrize("body", [{"text": "<html>"}, {"json": [1]}])
def test_a_malformed_detail_body_raises(body):
    client, _ = _client(lambda r: httpx.Response(200, **body))
    with pytest.raises(TaskQueueError, match="malformed"):
        asyncio.run(client.get_task(str(uuid.uuid4())))
