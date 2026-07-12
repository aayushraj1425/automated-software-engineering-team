"""The arq worker: executes runs outside the API process.

Start it alongside the API (with RUN_QUEUE=arq in .env):

    uv run arq engine.worker.WorkerSettings

Both job functions are re-entrant: before running, each puts an interrupted
run back into a startable state the same way startup recovery does. That is
what makes a graceful shutdown safe — stopping the worker mid-run cancels the
job, Postgres keeps the checkpoint (status, board, workspace commits), arq
re-delivers the job, and the reset lets it finish what the last worker
started. Design note: docs/architecture/BACKGROUND_WORKER.md.
"""

import asyncio
import sys

# psycopg async cannot run on Windows' default ProactorEventLoop; the policy
# must be set before arq creates its loop (same story as engine/serve.py).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uuid
from typing import Any

from arq.connections import RedisSettings

from engine.agents.recovery import reset_interrupted_execution, reset_interrupted_planning
from engine.agents.runner import execute_tasks, plan_run
from engine.config import get_settings
from engine.db.session import dispose_engine
from engine.events.bus import dispose_bus
from engine.jobs import QUEUE_NAME
from engine.logging import setup_logging


async def plan_run_job(ctx: dict[str, Any], run_id: str) -> None:
    """Plan the run. Re-delivery after a shutdown mid-planning discards the
    half-made plan first; a fresh queued run passes straight through."""
    run_uuid = uuid.UUID(run_id)
    await reset_interrupted_planning(run_uuid)
    await plan_run(run_uuid)


async def execute_tasks_job(ctx: dict[str, Any], run_id: str) -> None:
    """Execute the approved run. Re-delivery resumes from the task board —
    done tasks keep their commits, the interrupted task repeats; a first
    delivery is recognized and left untouched (no recovery event)."""
    run_uuid = uuid.UUID(run_id)
    await reset_interrupted_execution(run_uuid, quiet_when_clean=True)
    await execute_tasks(run_uuid)


async def _on_startup(ctx: dict[str, Any]) -> None:
    setup_logging(get_settings().log_level)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    await dispose_bus()
    await dispose_engine()


class WorkerSettings:
    """arq entrypoint: `uv run arq engine.worker.WorkerSettings`."""

    functions = [plan_run_job, execute_tasks_job]
    queue_name = QUEUE_NAME
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    job_timeout = 3600  # a real-model run can take a while
    max_tries = 3  # re-deliveries after interruptions; the resets make this safe
    keep_result = 60
