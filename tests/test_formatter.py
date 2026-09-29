"""The truncation notice on boards and the digest: rendered when set, absent otherwise."""

from src.formatter import format_agent_board, format_digest, truncation_notice

ROW = {"id": "abcdef12-0000", "status": "approved", "task_type": "build", "summary": "s"}


def test_no_notice_when_not_truncated():
    assert truncation_notice(False, 10) == ""
    plain, html = format_agent_board("developer", [ROW])
    assert "truncated" not in plain and "truncated" not in html


def test_a_truncated_board_says_so_even_when_empty():
    plain, html = format_agent_board("developer", [], truncated=True, matched=1200)
    assert "truncated" in plain and "1200" in plain
    assert "truncated" in html


def test_a_truncated_board_with_rows_says_so():
    plain, html = format_agent_board("developer", [ROW], truncated=True, matched=1200)
    assert "truncated" in plain and "truncated" in html


def test_the_digest_carries_the_notice_once():
    plain, html = format_digest(
        [("developer", [ROW]), ("writer", [ROW])], "2026-09-29", truncated=True, matched=1200
    )
    assert plain.count("truncated") == 1
    assert html.count("truncated") == 1
