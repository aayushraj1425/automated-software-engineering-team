"""Automatic memory capture: runs write their own history.

When a run reaches a terminal state the platform remembers what happened —
the approved plan as a `decision`, the result (pull request or failure
reason) as an `outcome`. Rejecting a plan at the approval gate records a
`preference`. Capture must never break a run or a request: a memory write
failure is logged and swallowed. Design note:
docs/architecture/KNOWLEDGE_AND_MEMORY.md.
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.enums import KnowledgeKind, RunStatus
from engine.db.models import AgentRun, KnowledgeItem
from engine.db.session import session_scope
from engine.knowledge.store import remember

log = structlog.get_logger()


def _headline(request: str) -> str:
    """The first line of the request, short enough for a memory title."""
    return request.strip().splitlines()[0][:180]


async def capture_run_memory(run_id: uuid.UUID) -> None:
    """Remember a run that ended: its approved plan and its outcome.

    Runs after the background entrypoints finish, so it never blocks or breaks
    the run itself. Idempotent — a run that already has an outcome memory is
    not captured twice.
    """
    try:
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            if run is None or run.status not in (RunStatus.COMPLETED, RunStatus.FAILED):
                return
            if run.repository_id is None:
                return  # repository disconnected — nowhere for the memory to live
            already = await session.execute(
                select(KnowledgeItem.id).where(
                    KnowledgeItem.source_run_id == run_id,
                    KnowledgeItem.kind == KnowledgeKind.OUTCOME,
                )
            )
            if already.first() is not None:
                return

            plan_summary = str((run.plan or {}).get("summary", "")).strip()
            if run.status == RunStatus.COMPLETED and plan_summary:
                await remember(
                    session,
                    run.repository_id,
                    KnowledgeKind.DECISION,
                    f"Approved plan: {_headline(run.request)}",
                    plan_summary,
                    source_run_id=run_id,
                )
            await remember(
                session,
                run.repository_id,
                KnowledgeKind.OUTCOME,
                f"Run {run.status}: {_headline(run.request)}",
                _outcome_text(run),
                source_run_id=run_id,
            )
            await session.commit()
    except Exception:
        # Memory is a byproduct; the run's own record is already saved.
        log.exception("memory.capture_failed", run_id=str(run_id))


def _outcome_text(run: AgentRun) -> str:
    if run.status == RunStatus.COMPLETED:
        published = (
            f"Pull request: {run.pr_url}"
            if run.pr_url
            else "The branch was published without a pull request."
        )
        return f"The request was implemented and approved by review. {published}"
    return f"The run failed: {run.error or 'no reason recorded'}"


async def capture_plan_rejected(
    db: AsyncSession, run: AgentRun, user_id: str
) -> KnowledgeItem | None:
    """Remember a rejected plan as a team preference (the caller commits).

    A rejection is a strong signal about how the team wants things done —
    the next planning round recalls it. Never fails the rejection request.
    """
    try:
        if run.repository_id is None:
            return None  # repository disconnected — nowhere for the memory to live
        plan_summary = str((run.plan or {}).get("summary", "")).strip()
        content = (
            "The human rejected this proposed plan at the approval gate. "
            f"Request: {run.request.strip()[:500]}"
            + (f" Rejected plan summary: {plan_summary}" if plan_summary else "")
        )
        return await remember(
            db,
            run.repository_id,
            KnowledgeKind.PREFERENCE,
            f"Plan rejected: {_headline(run.request)}",
            content,
            source_run_id=run.id,
            created_by=user_id,
        )
    except Exception:
        log.exception("memory.capture_failed", run_id=str(run.id))
        return None
