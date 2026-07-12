"""Run dispatch: inline background execution or the arq queue (ADR-0004).

The one seam between "a run should start" and "where it runs". In `inline`
mode (the default) the work runs in the calling process, exactly as before.
In `arq` mode the run id — never a payload; the Postgres row is the job's
state — is enqueued on Redis for the worker process (`engine/worker.py`).
A broken queue degrades to inline with a warning; it never strands a run.
Design note: docs/architecture/BACKGROUND_WORKER.md.
"""

import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from engine.agents.runner import execute_tasks, plan_run
from engine.config import get_settings

log = structlog.get_logger()

QUEUE_NAME = "asep:runs"
PLAN_JOB = "plan_run_job"
EXECUTE_JOB = "execute_tasks_job"

_pool: ArqRedis | None = None


async def _get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(
            RedisSettings.from_dsn(get_settings().redis_url), default_queue_name=QUEUE_NAME
        )
    return _pool


async def dispose_jobs() -> None:
    """Close the shared queue connection (engine shutdown). Never raises."""
    global _pool
    if _pool is not None:
        pool, _pool = _pool, None
        with suppress(Exception):  # a dead-loop connection just gets dropped
            await pool.aclose()


async def dispatch_plan(run_id: uuid.UUID) -> None:
    """Start planning the run — on the worker if queued, here otherwise."""
    await _dispatch(PLAN_JOB, run_id, plan_run)


async def dispatch_execute(run_id: uuid.UUID) -> None:
    """Start executing the approved run — worker or inline, same as planning."""
    await _dispatch(EXECUTE_JOB, run_id, execute_tasks)


async def _dispatch(
    job_name: str, run_id: uuid.UUID, inline: Callable[[uuid.UUID], Awaitable[None]]
) -> None:
    global _pool
    if get_settings().run_queue == "arq":
        try:
            pool = await _get_pool()
            await pool.enqueue_job(job_name, str(run_id))
            return
        except Exception as exc:
            # Drop the pool so the next use rebuilds it, then fall back —
            # a dead queue must degrade to today's behavior, never park a run.
            _pool = None
            log.warning("jobs.queue_unavailable", job=job_name, error=str(exc)[:200])
    await inline(run_id)
