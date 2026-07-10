"""The QA self-correction loop: failing sandbox tests route back to the QA
agent, which fixes and retries, bounded by QA_MAX_ATTEMPTS. The sandbox is faked
(a scripted sequence of results); the QA fix runs its offline path (LLM_FAKE=1),
committing into the scratch workspace. Design note: docs/architecture/QA_AGENT.md.
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


def _failed() -> SandboxResult:
    return SandboxResult("failed", "tests failed (exit code 1)", "FAILED test_x", 1, _PLAN)


def _passed() -> SandboxResult:
    return SandboxResult("passed", "", "1 passed", 0, _PLAN)


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


def _fake_sandbox_sequence(monkeypatch, results: list[SandboxResult]):
    """run_sandbox returns each result in turn; the last one repeats thereafter."""
    seq = list(results)
    calls = {"n": 0}

    async def fake(workspace, run_id):
        result = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return result

    monkeypatch.setattr(agents_runner, "run_sandbox", fake)


async def _events(run_id, type_) -> list[AgentEvent]:
    async with session_scope() as session:
        return list(
            (
                await session.execute(
                    select(AgentEvent).where(AgentEvent.run_id == run_id, AgentEvent.type == type_)
                )
            )
            .scalars()
            .all()
        )


async def test_qa_fixes_and_the_rerun_passes(prepared_db, tmp_path, monkeypatch):
    run_id, ws = await _make_run(tmp_path / "workspaces", monkeypatch)
    _fake_sandbox_sequence(monkeypatch, [_failed(), _passed()])

    proceeded = await _sandbox_gate(run_id, "do the thing", ws)

    assert proceeded is True
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        assert run.status != RunStatus.FAILED
    qa_events = await _events(run_id, "qa.attempt")
    assert len(qa_events) == 1  # one fix was enough
    assert qa_events[0].payload["attempt"] == 1
    statuses = {e.payload["status"] for e in await _events(run_id, "sandbox.run")}
    assert statuses == {"failed", "passed"}  # the red run and then the green re-run

    remove_workspace(run_id)


async def test_qa_exhausts_attempts_then_the_run_fails(prepared_db, tmp_path, monkeypatch):
    run_id, ws = await _make_run(tmp_path / "workspaces", monkeypatch)
    monkeypatch.setattr(get_settings(), "qa_max_attempts", 2)
    _fake_sandbox_sequence(monkeypatch, [_failed()])  # never turns green

    proceeded = await _sandbox_gate(run_id, "do the thing", ws)

    assert proceeded is False
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        assert run.status == RunStatus.FAILED
        assert "still failing after 2 QA attempt" in (run.error or "")
    assert len(await _events(run_id, "qa.attempt")) == 2  # tried the cap
    assert len(await _events(run_id, "sandbox.run")) == 3  # initial + two retries

    remove_workspace(run_id)


async def test_a_passing_sandbox_never_invokes_qa(prepared_db, tmp_path, monkeypatch):
    run_id, ws = await _make_run(tmp_path / "workspaces", monkeypatch)
    _fake_sandbox_sequence(monkeypatch, [_passed()])

    proceeded = await _sandbox_gate(run_id, "do the thing", ws)

    assert proceeded is True
    assert await _events(run_id, "qa.attempt") == []  # nothing failed, so no QA

    remove_workspace(run_id)
