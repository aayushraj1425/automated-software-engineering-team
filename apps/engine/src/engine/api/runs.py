"""Runs API: start an agent run, list runs, watch one run's progress.

The UI polls GET /v1/runs/{id} for the task board and
GET /v1/runs/{id}/events?after=<last event id> for new timeline entries.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.runner import execute_tasks, plan_run
from engine.auth import Principal, require_service_auth
from engine.db.enums import RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask, Repository
from engine.db.session import get_session

router = APIRouter()


class RunCreate(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    repository_url: str = Field(min_length=8, max_length=512)
    max_cost_usd: Decimal | None = Field(default=None, gt=0)


class TaskOut(BaseModel):
    id: uuid.UUID
    sequence: int
    role: str
    title: str
    description: str | None
    status: str
    depends_on: list[str]
    result: str | None
    attempts: int


class RunOut(BaseModel):
    id: uuid.UUID
    status: str
    request: str
    repository_url: str
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunDetailOut(RunOut):
    plan: dict[str, Any] | None
    tasks: list[TaskOut]


class EventOut(BaseModel):
    id: int
    type: str
    agent: str | None
    task_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: datetime


def _run_out(run: AgentRun, repository_url: str) -> RunOut:
    return RunOut(
        id=run.id,
        status=run.status,
        request=run.request,
        repository_url=repository_url,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def _owned_run(db: AsyncSession, run_id: uuid.UUID, principal: Principal) -> AgentRun:
    run = await db.get(AgentRun, run_id)
    if run is None or run.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/v1/runs", status_code=201)
async def create_run(
    body: RunCreate,
    background: BackgroundTasks,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunOut:
    url = body.repository_url.strip()
    repo = (
        await db.execute(
            select(Repository).where(
                Repository.owner_id == principal.user_id, Repository.url == url
            )
        )
    ).scalar_one_or_none()
    if repo is None:
        repo = Repository(owner_id=principal.user_id, org_id=principal.org_id, url=url)
        db.add(repo)
        await db.flush()

    run = AgentRun(
        user_id=principal.user_id,
        org_id=principal.org_id,
        repository_id=repo.id,
        request=body.request.strip(),
        status=RunStatus.QUEUED,
        max_cost_usd=body.max_cost_usd,
    )
    db.add(run)
    await db.commit()

    background.add_task(plan_run, run.id)
    return _run_out(run, url)


class DecisionIn(BaseModel):
    approved: bool


@router.post("/v1/runs/{run_id}/decision")
async def decide_run(
    run_id: uuid.UUID,
    body: DecisionIn,
    background: BackgroundTasks,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunOut:
    """The human approval gate: approve starts the work, reject ends the run."""
    run = await _owned_run(db, run_id, principal)
    if run.status != RunStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="This run is not waiting for approval")

    if body.approved:
        run.status = RunStatus.EXECUTING
        db.add(AgentEvent(run_id=run.id, type="plan.approved", payload={"by": principal.user_id}))
        db.add(
            AgentEvent(
                run_id=run.id,
                type="run.status_changed",
                payload={"from": RunStatus.AWAITING_APPROVAL, "to": RunStatus.EXECUTING},
            )
        )
    else:
        run.status = RunStatus.CANCELLED
        run.finished_at = datetime.now(UTC)
        tasks = (
            (await db.execute(select(AgentTask).where(AgentTask.run_id == run.id))).scalars().all()
        )
        for task in tasks:
            task.status = TaskStatus.SKIPPED
        db.add(AgentEvent(run_id=run.id, type="plan.rejected", payload={"by": principal.user_id}))
        db.add(
            AgentEvent(
                run_id=run.id,
                type="run.finished",
                payload={"status": RunStatus.CANCELLED, "error": None},
            )
        )
    await db.commit()

    if body.approved:
        background.add_task(execute_tasks, run.id)
    repo = await db.get(Repository, run.repository_id)
    return _run_out(run, repo.url if repo else "")


@router.get("/v1/runs")
async def list_runs(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[RunOut]:
    rows = (
        await db.execute(
            select(AgentRun, Repository.url)
            .join(Repository, AgentRun.repository_id == Repository.id)
            .where(AgentRun.user_id == principal.user_id)
            .order_by(AgentRun.created_at.desc())
            .limit(50)
        )
    ).all()
    return [_run_out(run, url) for run, url in rows]


@router.get("/v1/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunDetailOut:
    run = await _owned_run(db, run_id, principal)
    repo = await db.get(Repository, run.repository_id)
    tasks = (
        (
            await db.execute(
                select(AgentTask).where(AgentTask.run_id == run_id).order_by(AgentTask.sequence)
            )
        )
        .scalars()
        .all()
    )
    base = _run_out(run, repo.url if repo else "")
    return RunDetailOut(
        **base.model_dump(),
        plan=run.plan,
        tasks=[
            TaskOut(
                id=t.id,
                sequence=t.sequence,
                role=t.role,
                title=t.title,
                description=t.description,
                status=t.status,
                depends_on=list(t.depends_on),
                result=t.result,
                attempts=t.attempts,
            )
            for t in tasks
        ],
    )


@router.get("/v1/runs/{run_id}/events")
async def list_events(
    run_id: uuid.UUID,
    after: int = 0,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[EventOut]:
    await _owned_run(db, run_id, principal)
    rows = (
        (
            await db.execute(
                select(AgentEvent)
                .where(AgentEvent.run_id == run_id, AgentEvent.id > after)
                .order_by(AgentEvent.id)
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    return [
        EventOut(
            id=e.id,
            type=e.type,
            agent=e.agent,
            task_id=e.task_id,
            payload=e.payload,
            created_at=e.created_at,
        )
        for e in rows
    ]
