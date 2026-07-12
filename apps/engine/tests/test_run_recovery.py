"""Resume-after-restart: interrupted runs are recovered from their Postgres
checkpoint (the agent_tasks board) at engine startup.

Each test forges the exact state a crashed process leaves behind — a run
frozen in a non-terminal status — then calls recover_interrupted_runs()
directly (startup recovery is disabled in conftest so tests stay isolated).
Design note: docs/architecture/RUN_RECOVERY.md.
"""

import uuid

import pytest
from sqlalchemy import select

from engine.agents.recovery import recover_interrupted_runs
from engine.config import get_settings
from engine.db.enums import RunStatus, TaskStatus
from engine.db.models import AgentRun, AgentTask
from engine.db.session import session_scope
from tests.conftest import auth_headers

REPO = "https://github.com/acme/demo"


@pytest.fixture(autouse=True)
def workspaces_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


async def _planned_run(client, headers) -> str:
    """A run that planned normally and waits for approval (workspace on disk)."""
    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": REPO},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _force_status(
    run_id: str, status: RunStatus, task_status: TaskStatus | None = None
) -> None:
    """Forge the frozen state a crashed engine process leaves behind."""
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.status = status
        if task_status is not None:
            tasks = (
                (await session.execute(select(AgentTask).where(AgentTask.run_id == run.id)))
                .scalars()
                .all()
            )
            tasks[0].status = task_status
        await session.commit()


async def test_resumes_an_executing_run_to_completion(client):
    headers = _headers()
    run_id = await _planned_run(client, headers)
    # The crash: approval flipped the status but the process died before work.
    await _force_status(run_id, RunStatus.EXECUTING)

    recovered = await recover_interrupted_runs()

    assert uuid.UUID(run_id) in recovered
    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert all(t["status"] == "done" for t in detail["tasks"])
    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    recovered_events = [e for e in events if e["type"] == "run.recovered"]
    assert recovered_events and recovered_events[0]["payload"]["action"] == "resume"


async def test_interrupted_task_repeats_but_done_tasks_stay_done(client):
    headers = _headers()
    run_id = await _planned_run(client, headers)
    # The crash happened mid-task: one task was in progress, none were done.
    await _force_status(run_id, RunStatus.EXECUTING, task_status=TaskStatus.IN_PROGRESS)

    await recover_interrupted_runs()

    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert all(t["status"] == "done" for t in detail["tasks"])


async def test_reviewing_run_resumes_through_review(client):
    headers = _headers()
    run_id = await _planned_run(client, headers)
    # The crash hit during review: every task done, verdict never returned.
    await _force_status(run_id, RunStatus.EXECUTING)
    async with session_scope() as session:
        tasks = (
            (await session.execute(select(AgentTask).where(AgentTask.run_id == uuid.UUID(run_id))))
            .scalars()
            .all()
        )
        for task in tasks:
            task.status = TaskStatus.DONE
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.status = RunStatus.REVIEWING
        await session.commit()

    await recover_interrupted_runs()

    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "completed"
    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    assert "review.verdict" in [e["type"] for e in events]


async def test_run_interrupted_during_planning_is_replanned(client):
    headers = _headers()
    run_id = await _planned_run(client, headers)
    # The crash hit mid-planning: no approved plan existed yet.
    await _force_status(run_id, RunStatus.PLANNING)

    await recover_interrupted_runs()

    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "awaiting_approval"
    assert detail["plan"]["tasks"]
    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    recovered_events = [e for e in events if e["type"] == "run.recovered"]
    assert recovered_events and recovered_events[0]["payload"]["action"] == "replan"


async def test_waiting_and_terminal_runs_are_left_alone(client):
    headers = _headers()
    waiting_id = await _planned_run(client, headers)  # awaiting_approval

    recovered = await recover_interrupted_runs()

    assert uuid.UUID(waiting_id) not in recovered
    detail = (await client.get(f"/v1/runs/{waiting_id}", headers=headers)).json()
    assert detail["status"] == "awaiting_approval"
    events = (await client.get(f"/v1/runs/{waiting_id}/events", headers=headers)).json()
    assert "run.recovered" not in [e["type"] for e in events]
