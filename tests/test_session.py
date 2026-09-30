"""A session launched from Matrix must not inherit the bot's own credentials."""

import src.session as session

BOT_ENV = {
    "PATH": "/usr/bin",
    "HOME": "/home/x",
    "MATRIX_ACCESS_TOKEN": "syt_synthetic",
    "MATRIX_HOMESERVER_URL": "http://localhost:8008",
    "TASK_QUEUE_API": "http://127.0.0.1:8485",
    "TASK_QUEUE_API_SECRET": "synthetic-secret-value",
    "TASK_QUEUE_TOKEN_FILE": "/home/x/.secrets/t.token",
    "TASK_QUEUE_TOKEN_DEVELOPER": "synthetic-agent-token",
    "TASK_QUEUE_CLIENT_MATRIX_BOT": "sha256:00",
}


def test_child_env_drops_every_bot_credential():
    env = session.child_env(BOT_ENV)
    for name in (
        "MATRIX_ACCESS_TOKEN",
        "TASK_QUEUE_API_SECRET",
        "TASK_QUEUE_TOKEN_FILE",
        "TASK_QUEUE_TOKEN_DEVELOPER",
        "TASK_QUEUE_CLIENT_MATRIX_BOT",
    ):
        assert name not in env, name


def test_child_env_keeps_what_a_session_needs():
    env = session.child_env(BOT_ENV)
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/x"
    # Non-secret configuration passes through.
    assert env["TASK_QUEUE_API"] == "http://127.0.0.1:8485"


def test_launch_passes_the_stripped_env(monkeypatch, tmp_path):
    seen = {}

    class _Proc:
        pid = 4242

    def fake_popen(argv, **kwargs):
        seen.update(kwargs)
        return _Proc()

    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(session, "AGENT_PROJECTS", {"developer": str(project)})
    monkeypatch.setattr(session, "LAUNCH_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(session.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(session.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "syt_synthetic")
    monkeypatch.setenv("TASK_QUEUE_API_SECRET", "synthetic-secret-value")

    result = session.launch_headless("abcdef12-0000-4000-8000-000000000000", "developer", "review")
    assert result["ok"] == "true"
    assert "env" in seen, "launch_headless must pass an explicit env"
    assert "MATRIX_ACCESS_TOKEN" not in seen["env"]
    assert "TASK_QUEUE_API_SECRET" not in seen["env"]
