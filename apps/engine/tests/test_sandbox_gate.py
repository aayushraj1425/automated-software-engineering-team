"""The runner's sandbox gate: failing tests block the pull request.

The sandbox itself is faked (its own lifecycle is covered in test_sandbox.py);
these tests check what the gate does with each outcome — fail the run, record
the timeline event, or let the run proceed. Design note:
docs/architecture/SANDBOX_EXECUTION.md.
"""

import uuid

from sqlalchemy import select

from engine.agents import runner as agents_runner
from engine.agents.runner import _sandbox_gate
from engine.config import get_settings
from engine.db.enums import RunStatus
from engine.db.models import AgentEvent, AgentRun, Repository
from engine.db.session import session_scope
from engine.sandbox.runner import SandboxPlan, SandboxResult
from engine.workspace.manager import create_scratch_workspace, remove_workspace

_PLAN = SandboxPlan(image="python:3.12-slim", install=None, test="python -m pytest -q")


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


def _fake_sandbox(monkeypatch, result: SandboxResult):
    async def fake(workspace, run_id):
        return result

    monkeypatch.setattr(agents_runner, "run_sandbox", fake)


async def _sandbox_event(run_id):
    async with session_scope() as session:
        return (
            await session.execute(
                select(AgentEvent).where(
                    AgentEvent.run_id == run_id, AgentEvent.type == "sandbox.run"
                )
            )
        ).scalar_one()


async def test_passing_tests_let_the_run_proceed(prepared_db, tmp_path, monkeypatch):
    run_id, ws = await _make_run(tmp_path / "workspaces", monkeypatch)
    _fake_sandbox(
        monkeypatch,
        SandboxResult(status="passed", reason="", output="2 passed", exit_code=0, plan=_PLAN),
    )

    proceeded = await _sandbox_gate(run_id, "do the thing", ws)

    assert proceeded is True
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        assert run.status != RunStatus.FAILED
    event = await _sandbox_event(run_id)
    assert event.payload["status"] == "passed"
    assert event.payload["test_command"] == "python -m pytest -q"

    remove_workspace(run_id)


async def test_a_skipped_sandbox_proceeds_but_is_recorded(prepared_db, tmp_path, monkeypatch):
    run_id, ws = await _make_run(tmp_path / "workspaces", monkeypatch)
    _fake_sandbox(
        monkeypatch,
        SandboxResult(
            status="skipped",
            reason="docker is not available",
            output="",
            exit_code=None,
            plan=None,
        ),
    )

    proceeded = await _sandbox_gate(run_id, "do the thing", ws)

    assert proceeded is True
    event = await _sandbox_event(run_id)
    assert event.payload["status"] == "skipped"
    assert event.payload["reason"] == "docker is not available"

    remove_workspace(run_id)
