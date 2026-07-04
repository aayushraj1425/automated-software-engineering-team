"""Round-trip tests for the agent-runtime domain model (AGENT_RUNTIME.md)."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.enums import AgentRole, ArtifactKind, RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask, Artifact, Repository
from engine.db.session import session_scope


async def _make_run(session: AsyncSession) -> AgentRun:
    repo = Repository(owner_id="user_test", url="https://github.com/acme/demo")
    session.add(repo)
    await session.flush()
    run = AgentRun(
        user_id="user_test",
        repository_id=repo.id,
        request="Add a /status endpoint",
        max_cost_usd=Decimal("5"),
    )
    session.add(run)
    await session.flush()
    return run


async def test_run_defaults_and_round_trip(prepared_db):
    async with session_scope() as session:
        run = await _make_run(session)
        await session.commit()

        loaded = await session.get(AgentRun, run.id)
        assert loaded is not None
        assert loaded.status == RunStatus.QUEUED
        assert loaded.total_cost_usd == Decimal("0")
        assert loaded.total_input_tokens == 0
        assert loaded.plan is None
        assert loaded.started_at is None


async def test_tasks_events_artifacts_attach_to_run(prepared_db):
    async with session_scope() as session:
        run = await _make_run(session)
        spec_task = AgentTask(
            run_id=run.id,
            sequence=1,
            role=AgentRole.PRODUCT_MANAGER,
            title="Write the mini-specification",
        )
        session.add(spec_task)
        await session.flush()
        build_task = AgentTask(
            run_id=run.id,
            sequence=2,
            role=AgentRole.BACKEND,
            title="Implement the endpoint",
            depends_on=[str(spec_task.id)],
        )
        session.add_all(
            [
                build_task,
                AgentEvent(run_id=run.id, agent=AgentRole.SUPERVISOR, type="run.started"),
                AgentEvent(
                    run_id=run.id,
                    task_id=spec_task.id,
                    agent=AgentRole.PRODUCT_MANAGER,
                    type="task.status_changed",
                    payload={"from": TaskStatus.PENDING, "to": TaskStatus.IN_PROGRESS},
                ),
                Artifact(
                    run_id=run.id,
                    task_id=spec_task.id,
                    kind=ArtifactKind.SPECIFICATION,
                    name="mini-spec.md",
                    content="# Spec",
                ),
            ]
        )
        await session.commit()

        tasks = (
            (
                await session.execute(
                    select(AgentTask).where(AgentTask.run_id == run.id).order_by(AgentTask.sequence)
                )
            )
            .scalars()
            .all()
        )
        assert [t.sequence for t in tasks] == [1, 2]
        assert all(t.status == TaskStatus.PENDING for t in tasks)
        assert tasks[1].depends_on == [str(spec_task.id)]

        events = (
            (
                await session.execute(
                    select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.id)
                )
            )
            .scalars()
            .all()
        )
        # bigint identity gives the stream cursor its total order
        assert [e.type for e in events] == ["run.started", "task.status_changed"]
        assert events[0].id < events[1].id
        assert events[1].payload == {"from": "pending", "to": "in_progress"}


async def test_deleting_a_run_cascades(prepared_db):
    async with session_scope() as session:
        run = await _make_run(session)
        task = AgentTask(run_id=run.id, sequence=1, role=AgentRole.BACKEND, title="t")
        session.add(task)
        await session.flush()
        session.add_all(
            [
                AgentEvent(run_id=run.id, task_id=task.id, type="run.started"),
                Artifact(run_id=run.id, kind=ArtifactKind.LOG, name="log", content=""),
            ]
        )
        await session.commit()
        run_id = run.id

        await session.delete(run)
        await session.commit()

        for model in (AgentTask, AgentEvent, Artifact):
            count = (
                await session.execute(
                    select(func.count()).select_from(model).where(model.run_id == run_id)
                )
            ).scalar_one()
            assert count == 0, f"{model.__name__} rows survived the run delete"


async def test_task_sequence_unique_per_run(prepared_db):
    async with session_scope() as session:
        run = await _make_run(session)
        session.add_all(
            [
                AgentTask(run_id=run.id, sequence=1, role=AgentRole.BACKEND, title="a"),
                AgentTask(run_id=run.id, sequence=1, role=AgentRole.FRONTEND, title="b"),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_run_rejects_unknown_repository(prepared_db):
    async with session_scope() as session:
        session.add(AgentRun(user_id="user_test", repository_id=uuid.uuid4(), request="orphan run"))
        with pytest.raises(IntegrityError):
            await session.commit()
