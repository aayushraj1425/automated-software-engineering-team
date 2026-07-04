"""Executes one agent run from start to finish.

Day 1 version: the machinery is real (statuses, task board, event diary in
Postgres) but the agents are stubs that pretend to work for a moment and
report success. Real agents replace the stubs on Day 2; an arq worker
replaces the in-process background task when runs get long (backlog).
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.supervisor import TaskState, build_supervisor_graph
from engine.db.enums import AgentRole, RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask
from engine.db.session import session_scope

log = structlog.get_logger()

# How long a stub agent "works" on a task. Tests set this to 0.
STUB_TASK_SECONDS = 0.4

# The stub plan every Day 1 run gets: a small diamond of dependencies so the
# timeline visibly shows ordering (spec first, backend+frontend in between,
# devops last).
_STUB_PLAN = [
    (AgentRole.PRODUCT_MANAGER, "Write the mini-specification", []),
    (AgentRole.BACKEND, "Implement the backend change", [0]),
    (AgentRole.FRONTEND, "Implement the frontend change", [0]),
    (AgentRole.DEVOPS, "Wire up configuration and checks", [1, 2]),
]


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


async def execute_run(run_id: uuid.UUID) -> None:
    """Background entrypoint: everything a run does happens in here."""
    try:
        await _execute_run(run_id)
    except Exception:
        log.exception("run.crashed", run_id=str(run_id))
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            if run is not None:
                run.status = RunStatus.FAILED
                run.error = "internal error while executing the run"
                run.finished_at = _now()
                _emit(session, run_id, "run.finished", {"status": RunStatus.FAILED})
                await session.commit()


async def _execute_run(run_id: uuid.UUID) -> None:
    # Phase 1 of the run: plan it (stub Product Manager).
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status != RunStatus.QUEUED:
            return
        run.started_at = _now()
        _emit(session, run_id, "run.started", {"request": run.request})
        _set_run_status(session, run, RunStatus.PLANNING)
        await session.commit()

    await asyncio.sleep(STUB_TASK_SECONDS)  # the stub PM "thinks"

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        tasks: list[AgentTask] = []
        for sequence, (role, title, dep_indexes) in enumerate(_STUB_PLAN, start=1):
            task = AgentTask(
                run_id=run_id,
                sequence=sequence,
                role=role,
                title=title,
                description=f"Stub task for: {run.request[:120]}",
            )
            session.add(task)
            await session.flush()
            task.depends_on = [str(tasks[i].id) for i in dep_indexes]
            tasks.append(task)
        plan: dict[str, Any] = {
            "summary": f"Stub plan for: {run.request[:200]}",
            "tasks": [t.title for t in tasks],
        }
        run.plan = plan
        _emit(session, run_id, "plan.created", plan, agent=AgentRole.PRODUCT_MANAGER)
        # Day 1 has no approval gate yet — go straight to work (Day 2 adds it).
        _set_run_status(session, run, RunStatus.EXECUTING)
        await session.commit()
        board = [_to_task_state(t) for t in tasks]

    # Phase 2 of the run: the Supervisor hands tasks to the (stub) agents.
    graph = build_supervisor_graph(_stub_agent)
    final = await graph.ainvoke(
        {"tasks": board, "current_task_id": None, "failure": None},
        {"recursion_limit": 100},
    )

    # Phase 3 of the run: record how it ended.
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


async def _stub_agent(task: TaskState) -> str:
    """Pretends to be the agent named in task['role']: marks the task started,
    'works', marks it done. Replaced by real agents on Day 2."""
    task_id = uuid.UUID(task["id"])
    async with session_scope() as session:
        row = await session.get(AgentTask, task_id)
        assert row is not None
        row.status = TaskStatus.IN_PROGRESS
        row.attempts = task["attempts"]
        row.started_at = _now()
        _emit(
            session,
            row.run_id,
            "task.status_changed",
            {"from": TaskStatus.PENDING, "to": TaskStatus.IN_PROGRESS, "title": task["title"]},
            agent=task["role"],
            task_id=task_id,
        )
        await session.commit()
        run_id = row.run_id

    await asyncio.sleep(STUB_TASK_SECONDS)
    result = f"[stub {task['role']}] finished: {task['title']}"

    async with session_scope() as session:
        row = await session.get(AgentTask, task_id)
        assert row is not None
        row.status = TaskStatus.DONE
        row.result = result
        row.finished_at = _now()
        _emit(
            session,
            run_id,
            "task.status_changed",
            {"from": TaskStatus.IN_PROGRESS, "to": TaskStatus.DONE, "result": result},
            agent=task["role"],
            task_id=task_id,
        )
        await session.commit()
    return result
