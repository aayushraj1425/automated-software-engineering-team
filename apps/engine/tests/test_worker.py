"""The background worker: re-entrant jobs and graceful-shutdown checkpoints.

The headline test cancels a run mid-execution — exactly what stopping the
worker does — and proves the Postgres checkpoint holds: the run is left
resumable and the worker's re-entrant job function finishes it. The arq
round trip runs against the real dev Redis and is skipped when it is down.
Design note: docs/architecture/BACKGROUND_WORKER.md.
"""

import asyncio
import uuid
from contextlib import suppress

import pytest
from sqlalchemy import select

import engine.agents.runner as runner_module
import engine.jobs as jobs
from engine.agents.runner import execute_tasks
from engine.config import get_settings
from engine.db.enums import RunStatus, TaskStatus
from engine.db.models import AgentRun, AgentTask
from engine.db.session import session_scope
from engine.worker import execute_tasks_job, plan_run_job
from tests.conftest import auth_headers

REPO = "https://github.com/acme/demo"


@pytest.fixture(autouse=True)
def workspaces_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


async def _planned_run(client, headers) -> str:
    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": REPO},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _force_executing(run_id: str) -> None:
    """The state the decision endpoint leaves before the job is delivered."""
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.status = RunStatus.EXECUTING
        await session.commit()


async def _run_status(run_id: str) -> tuple[str, list[str]]:
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        tasks = (
            (
                await session.execute(
                    select(AgentTask).where(AgentTask.run_id == run.id).order_by(AgentTask.sequence)
                )
            )
            .scalars()
            .all()
        )
        return run.status, [t.status for t in tasks]


async def test_cancelled_run_checkpoints_and_the_worker_finishes_it(client, monkeypatch):
    """Graceful shutdown mid-run: cancellation must leave the run resumable
    (the checkpoint), and the re-delivered job must finish it (re-entry)."""
    headers = _headers()
    run_id = await _planned_run(client, headers)
    await _force_executing(run_id)

    # The first task hangs, standing in for a long real-model task.
    original_execute_task = runner_module.execute_task
    calls = {"count": 0}

    async def hang_on_first_call(task, request, ws, usage, on_tool=None, on_reasoning=None):
        calls["count"] += 1
        if calls["count"] == 1:
            await asyncio.sleep(60)
        return await original_execute_task(task, request, ws, usage, on_tool, on_reasoning)

    monkeypatch.setattr(runner_module, "execute_task", hang_on_first_call)

    running = asyncio.create_task(execute_tasks(uuid.UUID(run_id)))
    for _ in range(100):  # wait until a task is genuinely mid-flight
        await asyncio.sleep(0.05)
        _, task_statuses = await _run_status(run_id)
        if TaskStatus.IN_PROGRESS in task_statuses:
            break
    running.cancel()  # what SIGTERM does to the worker's job
    with suppress(asyncio.CancelledError):
        await running

    # The checkpoint: not failed, not lost — frozen exactly where it was.
    status, task_statuses = await _run_status(run_id)
    assert status == RunStatus.EXECUTING
    assert TaskStatus.IN_PROGRESS in task_statuses

    # Re-delivery: the worker's job function resets the board and finishes.
    await execute_tasks_job({}, run_id)
    status, task_statuses = await _run_status(run_id)
    assert status == RunStatus.COMPLETED
    assert all(s == TaskStatus.DONE for s in task_statuses)
    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    recovered = [e for e in events if e["type"] == "run.recovered"]
    assert recovered and recovered[0]["payload"]["action"] == "resume"


async def test_first_delivery_executes_without_a_recovery_event(client):
    """A fresh approved run through the worker is not an interruption."""
    headers = _headers()
    run_id = await _planned_run(client, headers)
    await _force_executing(run_id)

    await execute_tasks_job({}, run_id)

    status, task_statuses = await _run_status(run_id)
    assert status == RunStatus.COMPLETED
    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    assert "run.recovered" not in [e["type"] for e in events]


async def test_plan_job_replans_after_a_shutdown_mid_planning(client):
    headers = _headers()
    run_id = await _planned_run(client, headers)
    async with session_scope() as session:  # forge the mid-planning freeze
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.status = RunStatus.PLANNING
        await session.commit()

    await plan_run_job({}, run_id)

    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "awaiting_approval"
    assert detail["plan"]["tasks"]


async def test_queue_falls_back_inline_when_redis_is_unreachable(client, monkeypatch):
    """A dead queue degrades to today's behavior — it never parks a run."""
    monkeypatch.setattr(get_settings(), "run_queue", "arq")
    monkeypatch.setattr(get_settings(), "redis_url", "redis://localhost:1/0")
    monkeypatch.setattr(jobs, "_pool", None)

    headers = _headers()
    run_id = await _planned_run(client, headers)  # dispatch fell back inline

    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "awaiting_approval"


async def test_arq_round_trip_plans_and_executes_through_the_worker(client, monkeypatch):
    """The real thing: enqueue on Redis, a burst worker delivers both jobs."""
    from arq.connections import RedisSettings
    from arq.worker import Worker

    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    try:
        pool = await jobs.create_pool(redis_settings)
        await pool.ping()
        await pool.aclose()
    except Exception:
        pytest.skip("Redis is not running (pnpm db:up)")

    monkeypatch.setattr(get_settings(), "run_queue", "arq")
    monkeypatch.setattr(jobs, "_pool", None)

    async def run_worker_until_idle() -> None:
        worker = Worker(
            functions=[plan_run_job, execute_tasks_job],
            redis_settings=redis_settings,
            queue_name=jobs.QUEUE_NAME,
            burst=True,
            poll_delay=0.1,
            handle_signals=False,
        )
        try:
            await worker.main()
        finally:
            try:
                await worker.close()
            except AttributeError:
                # arq's close() raises SIGUSR1 at itself — not a thing on
                # Windows. Closing the pool is all the cleanup that matters.
                if worker.pool is not None:
                    await worker.pool.aclose()

    headers = _headers()
    run_id = await _planned_run(client, headers)
    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "queued"  # parked on the queue, not planned yet

    await run_worker_until_idle()
    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "awaiting_approval"

    decided = await client.post(
        f"/v1/runs/{run_id}/decision", json={"approved": True}, headers=headers
    )
    assert decided.status_code == 200, decided.text
    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "executing"  # enqueued, awaiting the worker

    await run_worker_until_idle()
    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert all(t["status"] == "done" for t in detail["tasks"])
