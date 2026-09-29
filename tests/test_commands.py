"""!task start/run launch only live, unfinished work (not archived or dead-lettered)."""

import asyncio

import pytest

import src.commands as commands


class _Client:
    def __init__(self, task):
        self._task = task

    async def get_task(self, task_id):
        return self._task


@pytest.fixture
def launches(monkeypatch):
    calls = []
    monkeypatch.setattr(
        commands, "launch_headless", lambda tid, agent, mode: calls.append(tid) or {"ok": "true"}
    )
    return calls


TID = "abcdef12-0000-4000-8000-000000000000"


@pytest.mark.parametrize(
    ("status", "location"),
    [
        ("approved", "archive"),
        ("failed", "dead-letters"),
        ("completed", "queue"),
        ("cancelled", "queue"),
    ],
)
def test_start_refuses_anything_but_live_unfinished_work(launches, status, location):
    task = {"id": TID, "target_agent": "developer", "status": status, "queue_location": location}
    plain, _ = asyncio.run(commands._start_task(TID, "review", _Client(task)))
    assert "Not launching" in plain
    assert launches == []


def test_start_launches_live_work(launches):
    task = {"id": TID, "target_agent": "developer", "status": "approved", "queue_location": "queue"}
    plain, _ = asyncio.run(commands._start_task(TID, "review", _Client(task)))
    assert "Session launched" in plain
    assert launches == [TID]


def test_launch_refusal_names_the_reason():
    assert commands.launch_refusal({"queue_location": "archive"}) == "archive"
    assert commands.launch_refusal({"status": "completed"}) == "status completed"
    assert commands.launch_refusal({"status": "approved"}) is None
