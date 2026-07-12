"""Runs API: start an agent run, list runs, watch one run's progress.

The UI streams GET /v1/runs/{id}/events/stream for live timeline entries
(design note: docs/architecture/RUN_EVENT_STREAMING.md) and polls
GET /v1/runs/{id} for the task board; the plain events endpoint
(?after=<last event id>) remains as the polling fallback.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.enums import RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask, Repository
from engine.db.session import get_session, session_scope
from engine.events.bus import RunEventSubscription, publish_run_ping
from engine.jobs import dispatch_execute, dispatch_plan
from engine.knowledge.capture import capture_plan_rejected
from engine.workspace.manager import WorkspaceError, load_workspace, remove_workspace, run_git

router = APIRouter()


class RunCreate(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    repository_url: str = Field(min_length=8, max_length=512)
    max_cost_usd: Decimal | None = Field(default=None, gt=0)

    @field_validator("request", "repository_url")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # min_length runs before stripping, so "   " would otherwise pass.
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


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
    pr_url: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunDetailOut(RunOut):
    plan: dict[str, Any] | None
    tasks: list[TaskOut]
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int


class DiffOut(BaseModel):
    diff: str


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
        pr_url=run.pr_url,
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

    background.add_task(dispatch_plan, run.id)
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
    new_status = RunStatus.EXECUTING if body.approved else RunStatus.CANCELLED
    # Claim the decision atomically: two concurrent decisions (a double-click,
    # two tabs) must never both pass a plain status check and execute twice.
    claim = await db.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == RunStatus.AWAITING_APPROVAL)
        .values(status=new_status)
    )
    if cast(CursorResult, claim).rowcount != 1:
        raise HTTPException(status_code=409, detail="This run is not waiting for approval")
    run.status = new_status

    if body.approved:
        db.add(AgentEvent(run_id=run.id, type="plan.approved", payload={"by": principal.user_id}))
        db.add(
            AgentEvent(
                run_id=run.id,
                type="run.status_changed",
                payload={"from": RunStatus.AWAITING_APPROVAL, "to": RunStatus.EXECUTING},
            )
        )
    else:
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
        # A rejection is a preference worth remembering (KNOWLEDGE_AND_MEMORY.md);
        # capture never fails the request.
        await capture_plan_rejected(db, run, principal.user_id)
    await db.commit()
    await publish_run_ping(run.id)  # wake any open timeline stream

    if body.approved:
        background.add_task(dispatch_execute, run.id)
    else:
        # The workspace was cloned during planning; a rejected run won't use it.
        await asyncio.to_thread(remove_workspace, run.id)
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
        total_cost_usd=float(run.total_cost_usd),
        total_input_tokens=run.total_input_tokens,
        total_output_tokens=run.total_output_tokens,
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


@router.get("/v1/runs/{run_id}/diff")
async def get_run_diff(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> DiffOut:
    """Everything the agents changed in the run's workspace since its base commit."""
    run = await _owned_run(db, run_id, principal)
    if not run.base_sha:
        raise HTTPException(status_code=404, detail="This run has no workspace yet")
    try:
        ws = load_workspace(run.id, run.branch_name or "", run.base_sha)
        diff = await run_git(ws.path, "diff", run.base_sha)
    except WorkspaceError:
        raise HTTPException(status_code=404, detail="This run's workspace is gone") from None
    return DiffOut(diff=diff)


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


# The event stream ends with an `end` event once the run reaches one of these.
# A run waiting for approval keeps its stream open: EventSource auto-reconnects
# on close, so ending a merely-paused stream would loop reconnects instead.
_TERMINAL_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})
_STREAM_BATCH = 500


async def _drain_events(run_id: uuid.UUID, after: int) -> tuple[list[EventOut], str]:
    """New timeline entries past the cursor, plus the run's current status.
    One short-lived session per drain — the stream holds no connection while
    it waits (see session_scope's docstring for why not a request session)."""
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        rows = (
            (
                await db.execute(
                    select(AgentEvent)
                    .where(AgentEvent.run_id == run_id, AgentEvent.id > after)
                    .order_by(AgentEvent.id)
                    .limit(_STREAM_BATCH)
                )
            )
            .scalars()
            .all()
        )
    events = [
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
    return events, run.status if run is not None else RunStatus.FAILED


@router.get("/v1/runs/{run_id}/events/stream")
async def stream_events(
    run_id: uuid.UUID,
    request: Request,
    after: int = 0,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Live timeline: push each event as it lands, close when the run ends.
    Postgres is the record, Redis only wakes the stream — a missed ping costs
    one heartbeat of latency, never an event (RUN_EVENT_STREAMING.md).

    Each message carries its event id, so a reconnecting EventSource resumes
    from Last-Event-ID; the `after` query parameter seeds a fresh start.
    """
    await _owned_run(db, run_id, principal)
    last_event_id = request.headers.get("last-event-id", "")
    cursor = max(after, int(last_event_id)) if last_event_id.isdigit() else after

    async def event_stream(cursor: int) -> AsyncIterator[str]:
        async with RunEventSubscription(run_id) as subscription:
            while True:
                events, status = await _drain_events(run_id, cursor)
                for event in events:
                    cursor = event.id
                    yield f"id: {event.id}\ndata: {event.model_dump_json()}\n\n"
                if len(events) < _STREAM_BATCH and status in _TERMINAL_STATUSES:
                    yield f'event: end\ndata: {{"status": "{status}"}}\n\n'
                    return
                await subscription.wait()

    return StreamingResponse(
        event_stream(cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
