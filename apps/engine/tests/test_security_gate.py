"""The runner's pre-pull-request secrets gate blocks a leaked secret.

Exercises _security_gate against a real per-run workspace: a committed secret
must fail the run and record a security.scan event; a clean workspace must let
the run proceed. Design note: docs/architecture/SECRETS_SCANNING.md.
"""

import uuid

from sqlalchemy import select

from engine.agents.runner import _security_gate
from engine.config import get_settings
from engine.db.enums import RunStatus
from engine.db.models import AgentEvent, AgentRun, Repository
from engine.db.session import session_scope
from engine.workspace.manager import create_scratch_workspace, remove_workspace, run_git


async def _make_run(workspace_root, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(workspace_root))
    run_id = uuid.uuid4()
    async with session_scope() as session:
        repo = Repository(owner_id="user_test", url="https://github.com/acme/demo")
        session.add(repo)
        await session.flush()
        session.add(
            AgentRun(id=run_id, user_id="user_test", repository_id=repo.id, request="do the thing")
        )
        await session.commit()
    ws = await create_scratch_workspace(run_id)
    return run_id, ws


async def _security_scan_event(run_id):
    async with session_scope() as session:
        return (
            await session.execute(
                select(AgentEvent).where(
                    AgentEvent.run_id == run_id, AgentEvent.type == "security.scan"
                )
            )
        ).scalar_one()


async def test_gate_blocks_a_committed_secret(prepared_db, tmp_path, monkeypatch):
    run_id, ws = await _make_run(tmp_path / "workspaces", monkeypatch)
    (ws.path / "config.py").write_text('AWS_KEY = "AKIA0000TESTKEY00000"\n')
    await run_git(ws.path, "add", ".")
    await run_git(ws.path, "commit", "-m", "leak a key")

    proceeded = await _security_gate(run_id, ws)

    assert proceeded is False
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        assert run.status == RunStatus.FAILED
        assert "secret scan blocked" in (run.error or "")
    event = await _security_scan_event(run_id)
    assert event.payload["blocked"] is True
    assert event.payload["findings"][0]["rule"] == "aws_access_key_id"

    remove_workspace(run_id)


async def test_gate_passes_a_clean_workspace(prepared_db, tmp_path, monkeypatch):
    run_id, ws = await _make_run(tmp_path / "workspaces", monkeypatch)
    (ws.path / "main.py").write_text("def add(a, b):\n    return a + b\n")
    await run_git(ws.path, "add", ".")
    await run_git(ws.path, "commit", "-m", "clean change")

    proceeded = await _security_gate(run_id, ws)

    assert proceeded is True
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        assert run.status != RunStatus.FAILED
    event = await _security_scan_event(run_id)
    assert event.payload["blocked"] is False

    remove_workspace(run_id)
