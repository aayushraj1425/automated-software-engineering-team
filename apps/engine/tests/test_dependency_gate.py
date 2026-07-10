"""The runner's dependency gate blocks a known-vulnerable dependency.

Exercises _dependency_gate against a real per-run workspace: committing a
vulnerable pin must fail the run and record a dependency.scan event; a clean
manifest must let the run proceed. Design note:
docs/architecture/DEPENDENCY_SCANNING.md.
"""

import uuid

from sqlalchemy import select

from engine.agents.runner import _dependency_gate
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


async def _dependency_scan_event(run_id):
    async with session_scope() as session:
        return (
            await session.execute(
                select(AgentEvent).where(
                    AgentEvent.run_id == run_id, AgentEvent.type == "dependency.scan"
                )
            )
        ).scalar_one()


async def test_gate_blocks_a_vulnerable_dependency(prepared_db, tmp_path, monkeypatch):
    run_id, ws = await _make_run(tmp_path / "workspaces", monkeypatch)
    (ws.path / "requirements.txt").write_text("flask==2.2.4\n")
    await run_git(ws.path, "add", ".")
    await run_git(ws.path, "commit", "-m", "add flask")

    proceeded = await _dependency_gate(run_id, ws)

    assert proceeded is False
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        assert run.status == RunStatus.FAILED
        assert "dependency scan blocked" in (run.error or "")
    event = await _dependency_scan_event(run_id)
    assert event.payload["blocked"] is True
    assert event.payload["findings"][0]["package"] == "flask"
    assert event.payload["findings"][0]["advisory"] == "CVE-2023-30861"

    remove_workspace(run_id)


async def test_gate_passes_a_safe_dependency(prepared_db, tmp_path, monkeypatch):
    run_id, ws = await _make_run(tmp_path / "workspaces", monkeypatch)
    (ws.path / "requirements.txt").write_text("flask==2.3.3\n")
    await run_git(ws.path, "add", ".")
    await run_git(ws.path, "commit", "-m", "add safe flask")

    proceeded = await _dependency_gate(run_id, ws)

    assert proceeded is True
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        assert run.status != RunStatus.FAILED
    event = await _dependency_scan_event(run_id)
    assert event.payload["blocked"] is False

    remove_workspace(run_id)
