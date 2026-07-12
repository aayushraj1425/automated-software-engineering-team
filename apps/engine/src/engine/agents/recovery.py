"""Resume-after-restart: pick up runs an interrupted process left behind.

The agent_tasks board in Postgres is the run's checkpoint — every status
change is committed the moment it happens, and the Supervisor already routes
by reading that board. So recovery is small: put an interrupted run back into
a startable state (a half-made plan is discarded; in-progress tasks return to
pending while done tasks keep their commits), then start it again.

Two callers share these resets: API startup recovery (inline mode) and the
arq worker's re-entrant job functions (queue mode). Design notes:
docs/architecture/RUN_RECOVERY.md, docs/architecture/BACKGROUND_WORKER.md.
"""

import asyncio
import uuid

import structlog
from sqlalchemy import delete, select

from engine.agents.runner import execute_tasks, plan_run
from engine.db.enums import RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask
from engine.db.session import session_scope
from engine.events.bus import publish_run_ping
from engine.workspace.manager import remove_workspace

log = structlog.get_logger()

# Planning produced nothing durable yet — start these over.
_REPLAN_STATES = (RunStatus.QUEUED, RunStatus.PLANNING)
# The board (and the workspace's commits) checkpoint these — resume them.
_RESUME_STATES = (RunStatus.EXECUTING, RunStatus.REVIEWING)


async def recover_interrupted_runs() -> list[uuid.UUID]:
    """Find and finish runs interrupted by a restart; returns their ids.

    Inline-mode startup recovery: awaits each recovered run sequentially so a
    restart with many interrupted runs does not stampede the model provider;
    the caller (engine startup) wraps this in a background task. Runs waiting
    for human approval and runs in terminal states are left exactly as they
    are. In queue mode this never runs — the queue itself re-delivers
    interrupted jobs to the worker (BACKGROUND_WORKER.md).
    """
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(AgentRun.id, AgentRun.status).where(
                    AgentRun.status.in_(_REPLAN_STATES + _RESUME_STATES)
                )
            )
        ).all()

    recovered: list[uuid.UUID] = []
    for run_id, status in rows:
        if status in _REPLAN_STATES:
            if await reset_interrupted_planning(run_id, include_queued=True):
                await plan_run(run_id)
                recovered.append(run_id)
        elif await reset_interrupted_execution(run_id):
            await execute_tasks(run_id)
            recovered.append(run_id)
    if recovered:
        log.info("runs.recovered", count=len(recovered), run_ids=[str(r) for r in recovered])
    return recovered


async def reset_interrupted_planning(run_id: uuid.UUID, include_queued: bool = False) -> bool:
    """Put a run frozen mid-planning back to the start; True when it was.

    The half-made plan is discarded, board and all — nothing approved existed
    yet, so a fresh plan is cheaper than untangling a half-written one. The
    stale workspace goes with it; planning re-clones from scratch. `include_queued`
    also treats a still-queued run as interrupted (startup recovery, where a
    queued run means the planning task died with the process — in queue mode a
    queued run is just waiting for the worker and must not be touched).
    """
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        states = _REPLAN_STATES if include_queued else (RunStatus.PLANNING,)
        if run is None or run.status not in states:
            return False
        found_in = run.status
        await session.execute(delete(AgentTask).where(AgentTask.run_id == run_id))
        run.plan = None
        run.status = RunStatus.QUEUED  # plan_run only starts a queued run
        session.add(
            AgentEvent(
                run_id=run_id,
                type="run.recovered",
                payload={"found_in": found_in, "action": "replan"},
            )
        )
        await session.commit()
    await publish_run_ping(run_id)
    await asyncio.to_thread(remove_workspace, run_id)
    return True


async def reset_interrupted_execution(run_id: uuid.UUID, quiet_when_clean: bool = False) -> bool:
    """Put a run frozen mid-execution back on its board; True when resumable.

    The interrupted task repeats (in-progress back to pending); done tasks
    keep their commits; a reviewing run falls straight through the Supervisor
    to review. With `quiet_when_clean` (worker re-entry), an executing run
    with nothing in progress is a first delivery, not an interruption — it is
    left untouched and gets no recovery event.
    """
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status not in _RESUME_STATES:
            return False
        tasks = (
            (await session.execute(select(AgentTask).where(AgentTask.run_id == run_id)))
            .scalars()
            .all()
        )
        in_progress = [task for task in tasks if task.status == TaskStatus.IN_PROGRESS]
        if quiet_when_clean and run.status == RunStatus.EXECUTING and not in_progress:
            return True  # fresh delivery: nothing to reset, no event
        for task in in_progress:
            task.status = TaskStatus.PENDING
        found_in = run.status
        run.status = RunStatus.EXECUTING  # execute_tasks only resumes this state
        session.add(
            AgentEvent(
                run_id=run_id,
                type="run.recovered",
                payload={"found_in": found_in, "action": "resume"},
            )
        )
        await session.commit()
    await publish_run_ping(run_id)
    return True
