"""The in-browser terminal: sandboxed command console for finished runs.

The docker CLI is faked (recording calls, scripted answers) so the whole
path — session creation, hardening flags, TTL refresh, timeout reset, the
API's guards — runs offline, the same approach as the sandbox tests.
Design note: docs/architecture/IN_BROWSER_TERMINAL.md.
"""

import time
import uuid

import pytest

import engine.sandbox.terminal as terminal_module
from engine.config import get_settings
from engine.sandbox.terminal import (
    SESSION_TTL_SECONDS,
    TerminalUnavailable,
    run_terminal_command,
)
from tests.conftest import auth_headers

REPO = "https://github.com/acme/demo"


class FakeDocker:
    """Scripted docker CLI: records every call, answers by subcommand."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.session_running = False
        self.created_at = int(time.time())
        self.exec_result: tuple[int, str] = (0, "README.md\nsrc")

    async def __call__(self, *args: str, timeout: int = 60) -> tuple[int, str]:
        self.calls.append(args)
        command = args[0]
        if command == "inspect":
            if not self.session_running:
                return 1, "No such object"
            return 0, f"true {self.created_at}"
        if command == "run":
            self.session_running = True
            self.created_at = int(time.time())
            return 0, "container-id"
        if command == "cp":
            return 0, ""
        if command == "exec":
            return self.exec_result
        if command == "rm":
            self.session_running = False
            return 0, ""
        if command == "version":
            return 0, "27.0"
        return 0, ""


@pytest.fixture
def fake_docker(monkeypatch, tmp_path):
    fake = FakeDocker()
    monkeypatch.setattr(terminal_module, "_docker", fake)
    monkeypatch.setattr(terminal_module, "docker_available", lambda: _true())
    monkeypatch.setattr(get_settings(), "sandbox_enabled", True)
    return fake


async def _true() -> bool:
    return True


async def test_first_command_creates_a_hardened_offline_session(fake_docker, tmp_path):
    result = await run_terminal_command(uuid.uuid4(), tmp_path, "ls")
    assert result.fresh_session is True
    assert result.exit_code == 0
    assert "README.md" in result.output

    run_call = next(c for c in fake_docker.calls if c[0] == "run")
    # The line ADR-0008 draws: no network at all, capabilities dropped.
    assert run_call[run_call.index("--network") + 1] == "none"
    assert "--cap-drop" in run_call and "no-new-privileges" in run_call
    assert "asep.terminal=1" in run_call
    # Copied in, never mounted.
    assert any(c[0] == "cp" for c in fake_docker.calls)
    assert not any("-v" in c or "--mount" in c for c in fake_docker.calls if c[0] == "run")


async def test_second_command_reuses_the_session(fake_docker, tmp_path):
    run_id = uuid.uuid4()
    await run_terminal_command(run_id, tmp_path, "ls")
    fake_docker.exec_result = (0, "hello")
    result = await run_terminal_command(run_id, tmp_path, "cat greeting.txt")
    assert result.fresh_session is False
    assert len([c for c in fake_docker.calls if c[0] == "run"]) == 1  # one container


async def test_an_expired_session_is_recreated(fake_docker, tmp_path):
    run_id = uuid.uuid4()
    await run_terminal_command(run_id, tmp_path, "ls")
    fake_docker.created_at = int(time.time()) - SESSION_TTL_SECONDS - 60
    result = await run_terminal_command(run_id, tmp_path, "ls")
    assert result.fresh_session is True
    assert len([c for c in fake_docker.calls if c[0] == "run"]) == 2


async def test_a_timed_out_command_resets_the_session(fake_docker, tmp_path):
    run_id = uuid.uuid4()
    fake_docker.exec_result = (-1, "timed out after 60s")
    result = await run_terminal_command(run_id, tmp_path, "sleep 999")
    assert result.exit_code == -1
    assert "timed out" in result.output
    assert fake_docker.session_running is False  # discarded, not left wedged


async def test_disabled_sandbox_refuses_plainly(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "sandbox_enabled", False)
    with pytest.raises(TerminalUnavailable, match="SANDBOX_ENABLED=0"):
        await run_terminal_command(uuid.uuid4(), tmp_path, "ls")


# ── The API seam ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def workspaces_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


async def _completed_run(client, headers) -> str:
    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": REPO},
        headers=headers,
    )
    run_id = resp.json()["id"]
    await client.post(f"/v1/runs/{run_id}/decision", json={"approved": True}, headers=headers)
    return run_id


async def test_terminal_endpoint_runs_a_command(client, fake_docker):
    headers = _headers()
    run_id = await _completed_run(client, headers)
    resp = await client.post(f"/v1/runs/{run_id}/terminal", json={"command": "ls"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["exit_code"] == 0 and body["fresh_session"] is True

    reset = await client.delete(f"/v1/runs/{run_id}/terminal", headers=headers)
    assert reset.status_code == 204
    assert fake_docker.session_running is False


async def test_terminal_refuses_an_in_flight_run(client, fake_docker):
    headers = _headers()
    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": REPO},
        headers=headers,
    )
    run_id = resp.json()["id"]  # awaiting_approval — the agent loop owns it
    resp = await client.post(f"/v1/runs/{run_id}/terminal", json={"command": "ls"}, headers=headers)
    assert resp.status_code == 409


async def test_terminal_is_visibility_scoped(client, fake_docker):
    headers = _headers()
    run_id = await _completed_run(client, headers)
    intruder = _headers()
    resp = await client.post(
        f"/v1/runs/{run_id}/terminal", json={"command": "ls"}, headers=intruder
    )
    assert resp.status_code == 404
