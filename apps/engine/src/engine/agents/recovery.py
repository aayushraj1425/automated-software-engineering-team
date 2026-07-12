"""Resume-after-restart: pick up runs the last engine process left behind.

The agent_tasks board in Postgres is the run's checkpoint — every status
change is committed the moment it happens, and the Supervisor already routes
by reading that board. So recovery is small: at startup, find runs frozen in
a non-terminal state, re-plan the ones that never got an approved plan, and
resume the rest from their board (done tasks stay done, the interrupted task
repeats). Design note: docs/architecture/RUN_RECOVERY.md.
"""

import asyncio
import uuid

import structlog
from sqlalchemy import delete, select

from engine.agents.runner import execute_tasks, plan_run
from engine.db.enums import RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask
from engine.db.session import session_scope
from engine.workspace.manager import remove_workspace

log = structlog.get_logger()

# Planning produced nothing durable yet — start these over.
_REPLAN_STATES = (RunStatus.QUEUED, RunStatus.PLANNING)
# The board (and the workspace's commits) checkpoint these — resume them.
_RESUME_STATES = (RunStatus.EXECUTING, RunStatus.REVIEWING)


async def recover_interrupted_runs() -> list[uuid.UUID]:
    """Find and finish runs interrupted by a restart; returns their ids.

    Awaits each recovered run sequentially so a restart with many interrupted
    runs does not stampede the model provider; the caller (engine startup)
    wraps this in a background task. Runs waiting for human approval and runs
    in terminal states are left exactly as they are.
    """
    to_plan, to_execute = await _reset_interrupted_runs()
    for run_id in to_plan:
        # The half-made workspace is stale; planning re-clones from scratch.
        await asyncio.to_thread(remove_workspace, run_id)
        await plan_run(run_id)
    for run_id in to_execute:
        await execute_tasks(run_id)
    recovered = to_plan + to_execute
    if recovered:
        log.info("runs.recovered", count=len(recovered), run_ids=[str(r) for r in recovered])
    return recovered


async def _reset_interrupted_runs() -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Move interrupted runs back to a resumable state and stamp the timeline."""
    to_plan: list[uuid.UUID] = []
    to_execute: list[uuid.UUID] = []
    async with session_scope() as session:
        runs = (
            (
                await session.execute(
                    select(AgentRun).where(AgentRun.status.in_(_REPLAN_STATES + _RESUME_STATES))
                )
            )
            .scalars()
            .all()
        )
        for run in runs:
            found_in = run.status
            if run.status in _REPLAN_STATES:
                # A half-made plan is discarded, board and all — re-planning
                # writes a fresh one (sequences are unique per run).
                await session.execute(delete(AgentTask).where(AgentTask.run_id == run.id))
                run.plan = None
                run.status = RunStatus.QUEUED  # plan_run only starts a queued run
                action = "replan"
                to_plan.append(run.id)
            else:
                # The interrupted task repeats; done tasks keep their commits.
                tasks = (
                    (await session.execute(select(AgentTask).where(AgentTask.run_id == run.id)))
                    .scalars()
                    .all()
                )
                for task in tasks:
                    if task.status == TaskStatus.IN_PROGRESS:
                        task.status = TaskStatus.PENDING
                run.status = RunStatus.EXECUTING  # execute_tasks only resumes this state
                action = "resume"
                to_execute.append(run.id)
            session.add(
                AgentEvent(
                    run_id=run.id,
                    type="run.recovered",
                    payload={"found_in": found_in, "action": action},
                )
            )
        await session.commit()
    return to_plan, to_execute
