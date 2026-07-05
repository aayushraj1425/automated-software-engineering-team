"""Executes one agent run from start to finish.

Planning: clone the repository into a jailed per-run workspace, let the
Product Manager write the plan, save the task board, and stop at
awaiting_approval. Execution (after the human approves): reopen the workspace
and let the Supervisor route each task to the engineer agents. Every status
change lands in Postgres as an event, so the UI timeline is a full audit of
the run. An arq worker replaces the in-process background task when runs get
long (backlog).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.engineer import execute_task
from engine.agents.loop import LlmUsage
from engine.agents.product_manager import create_plan
from engine.agents.supervisor import TaskState, build_supervisor_graph
from engine.config import get_settings
from engine.db.enums import AgentRole, RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask, Repository
from engine.db.session import session_scope
from engine.workspace.manager import (
    Workspace,
    create_scratch_workspace,
    create_workspace,
    load_workspace,
)

log = structlog.get_logger()


def _now() -> datetime:
    return datetime.now(UTC)


def _emit(
    session: AsyncSession,
    run_id: uuid.UUID,
    type_: str,
    payload: dict[str, Any] | None = None,
    agent: str | None = None,
    task_id: uuid.UUID | None = None,
) -> None:
    session.add(
        AgentEvent(run_id=run_id, task_id=task_id, agent=agent, type=type_, payload=payload or {})
    )


def _set_run_status(session: AsyncSession, run: AgentRun, status: RunStatus) -> None:
    old = run.status
    run.status = status
    _emit(session, run.id, "run.status_changed", {"from": old, "to": status})


def _apply_usage(run: AgentRun, usage: LlmUsage) -> None:
    run.total_input_tokens += usage.input_tokens
    run.total_output_tokens += usage.output_tokens
    run.total_cost_usd += Decimal(str(round(usage.cost_usd, 6)))


async def plan_run(run_id: uuid.UUID) -> None:
    """Background entrypoint after POST /v1/runs: plan, then wait for approval."""
    await _guarded(_plan_run, run_id)


async def execute_tasks(run_id: uuid.UUID) -> None:
    """Background entrypoint after the human approves the plan."""
    await _guarded(_execute_tasks, run_id)


async def _guarded(work, run_id: uuid.UUID) -> None:
    """Whatever breaks inside a run must end as a failed run, never a crash."""
    try:
        await work(run_id)
    except Exception as exc:
        log.exception("run.crashed", run_id=str(run_id))
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            if run is not None:
                run.status = RunStatus.FAILED
                run.error = str(exc)[:500] or "internal error while executing the run"
                run.finished_at = _now()
                _emit(
                    session,
                    run_id,
                    "run.finished",
                    {"status": RunStatus.FAILED, "error": run.error},
                )
                await session.commit()


async def _open_workspace(run_id: uuid.UUID, repo_url: str) -> Workspace:
    # Offline mode still clones local fixture repositories; with a remote URL
    # it starts from an empty scratch repository instead of touching the network.
    if get_settings().llm_fake and not Path(repo_url).exists():
        return await create_scratch_workspace(run_id)
    return await create_workspace(run_id, repo_url)


async def _plan_run(run_id: uuid.UUID) -> None:
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status != RunStatus.QUEUED:
            return
        repo = await session.get(Repository, run.repository_id)
        assert repo is not None
        repo_url = repo.url
        request = run.request
        run.started_at = _now()
        _emit(session, run_id, "run.started", {"request": run.request})
        _set_run_status(session, run, RunStatus.PLANNING)
        await session.commit()

    ws = await _open_workspace(run_id, repo_url)
    usage = LlmUsage()
    plan = await create_plan(request, ws, usage)

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        run.branch_name = ws.branch
        run.base_sha = ws.base_sha
        tasks: list[AgentTask] = []
        for sequence, item in enumerate(plan["tasks"], start=1):
            task = AgentTask(
                run_id=run_id,
                sequence=sequence,
                role=item["role"],
                title=item["title"],
                description=item["description"],
            )
            session.add(task)
            await session.flush()
            task.depends_on = [str(tasks[dep - 1].id) for dep in item["depends_on"]]
            tasks.append(task)
        run.plan = {"summary": plan["summary"], "tasks": [t.title for t in tasks]}
        _apply_usage(run, usage)
        _emit(session, run_id, "plan.created", run.plan, agent=AgentRole.PRODUCT_MANAGER)
        # Stop here: nothing executes until the human approves the plan.
        _set_run_status(session, run, RunStatus.AWAITING_APPROVAL)
        await session.commit()


async def _execute_tasks(run_id: uuid.UUID) -> None:
    # The human approved — reopen the workspace and let the Supervisor work.
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status != RunStatus.EXECUTING:
            return
        request = run.request
        branch = run.branch_name or ""
        base_sha = run.base_sha or ""
        rows = (
            (
                await session.execute(
                    select(AgentTask).where(AgentTask.run_id == run_id).order_by(AgentTask.sequence)
                )
            )
            .scalars()
            .all()
        )
        board = [_to_task_state(t) for t in rows]

    ws = load_workspace(run_id, branch, base_sha)
    graph = build_supervisor_graph(_make_task_executor(run_id, request, ws))
    final = await graph.ainvoke(
        {"tasks": board, "current_task_id": None, "failure": None},
        {"recursion_limit": 100},
    )

    # Record how the run ended.
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        rows = (
            (await session.execute(select(AgentTask).where(AgentTask.run_id == run_id)))
            .scalars()
            .all()
        )
        by_id = {str(row.id): row for row in rows}
        for state in final["tasks"]:
            row = by_id[state["id"]]
            if row.status != state["status"]:
                _emit(
                    session,
                    run_id,
                    "task.status_changed",
                    {"from": row.status, "to": state["status"]},
                    task_id=row.id,
                )
                row.status = state["status"]
                row.attempts = state["attempts"]
        if final["failure"] is None:
            _set_run_status(session, run, RunStatus.COMPLETED)
        else:
            run.error = final["failure"]
            _set_run_status(session, run, RunStatus.FAILED)
        run.finished_at = _now()
        _emit(session, run_id, "run.finished", {"status": run.status, "error": run.error})
        await session.commit()


def _to_task_state(task: AgentTask) -> TaskState:
    return TaskState(
        id=str(task.id),
        sequence=task.sequence,
        role=task.role,
        title=task.title,
        description=task.description,
        status=task.status,
        depends_on=list(task.depends_on),
        attempts=task.attempts,
        result=task.result,
    )


def _make_task_executor(run_id: uuid.UUID, request: str, ws: Workspace):
    """Wraps the engineer agents with the task board's bookkeeping: statuses,
    timestamps, events, and the run's token/cost totals."""

    async def _execute(task: TaskState) -> str:
        task_id = uuid.UUID(task["id"])
        async with session_scope() as session:
            row = await session.get(AgentTask, task_id)
            assert row is not None
            row.status = TaskStatus.IN_PROGRESS
            row.attempts = task["attempts"]
            row.started_at = _now()
            _emit(
                session,
                run_id,
                "task.status_changed",
                {"from": TaskStatus.PENDING, "to": TaskStatus.IN_PROGRESS, "title": task["title"]},
                agent=task["role"],
                task_id=task_id,
            )
            await session.commit()

        usage = LlmUsage()
        try:
            result = await execute_task(task, request, ws, usage)
        except Exception as exc:
            async with session_scope() as session:
                row = await session.get(AgentTask, task_id)
                run = await session.get(AgentRun, run_id)
                assert row is not None and run is not None
                row.status = TaskStatus.PENDING  # the supervisor decides retry vs fail
                _apply_usage(run, usage)
                _emit(
                    session,
                    run_id,
                    "task.attempt_failed",
                    {
                        "attempt": task["attempts"],
                        "title": task["title"],
                        "error": str(exc)[:500],
                    },
                    agent=task["role"],
                    task_id=task_id,
                )
                await session.commit()
            raise

        async with session_scope() as session:
            row = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            assert row is not None and run is not None
            row.status = TaskStatus.DONE
            row.result = result
            row.finished_at = _now()
            _apply_usage(run, usage)
            _emit(
                session,
                run_id,
                "task.status_changed",
                {"from": TaskStatus.IN_PROGRESS, "to": TaskStatus.DONE, "result": result[:500]},
                agent=task["role"],
                task_id=task_id,
            )
            await session.commit()
        return result

    return _execute
