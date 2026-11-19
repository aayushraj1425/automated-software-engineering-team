"""Runs API: start an agent run, list runs, watch one run's progress.

The UI streams GET /v1/runs/{id}/events/stream for live timeline entries
(design note: docs/architecture/agents/RUN_EVENT_STREAMING.md) and polls
GET /v1/runs/{id} for the task board; the plain events endpoint
(?after=<last event id>) remains as the polling fallback.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.teams_types import Seat
from engine.agents.triage import Complexity, template_for
from engine.auth import Principal, require_service_auth
from engine.config import get_settings
from engine.db.enums import AgentRole, RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask, Repository
from engine.db.session import get_session, session_scope
from engine.db.visibility import can_access, visible_clause
from engine.deploy.contracts import PreviewDeployment, PreviewOptions
from engine.events.bus import RunEventSubscription, publish_run_ping
from engine.integrations.hosts import host_connection, push_credential
from engine.jobs import dispatch_execute, dispatch_plan
from engine.knowledge.capture import capture_plan_rejected
from engine.llm.catalog import SeatLevel
from engine.reporting import build_run_report
from engine.security.preview_credentials import load_preview_credentials
from engine.workspace.jail import JailViolation, resolve_inside
from engine.workspace.manager import (
    Workspace,
    WorkspaceError,
    load_workspace,
    push_branch,
    remove_workspace,
    run_git,
)

# The file browser reads the run's persisted workspace (WORKSPACE_PANELS.md).
MAX_WORKSPACE_FILES = 2000
MAX_VIEW_BYTES = 200_000

router = APIRouter()


def _model_overrides(value: dict[str, str]) -> dict[str, str]:
    for key, model in value.items():
        role, separator, level = key.partition(":")
        if not separator:
            raise ValueError("Seat keys must use role:level")
        AgentRole(role)
        SeatLevel(level)
        if not model.strip() or len(model) > 256:
            raise ValueError("Model ids must be nonempty and at most 256 characters")
    return value


class RunCreate(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    repository_url: str = Field(min_length=8, max_length=512)
    max_cost_usd: Decimal | None = Field(default=None, gt=0)
    complexity: Complexity | None = None
    model_overrides: dict[str, str] = Field(default_factory=dict, max_length=24)
    preview_requested: bool | None = None
    preview_options: PreviewOptions | None = None
    _validate_overrides = field_validator("model_overrides")(_model_overrides)

    @model_validator(mode="after")
    def _preview_requires_complex_team(self):
        if self.preview_requested:
            if self.complexity not in (None, Complexity.COMPLEX):
                raise ValueError("Preview deployment requires Complex task complexity")
            self.complexity = Complexity.COMPLEX
        return self

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
    level: str = "engineer"
    model: str | None = None


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
    complexity: Complexity | None = None
    triage_reason: str | None = None
    team_template: str = "standard"
    test_only: bool = False


class RunDetailOut(RunOut):
    plan: dict[str, Any] | None
    tasks: list[TaskOut]
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    test_report: dict[str, Any] | None = None
    team: list[Seat] = Field(default_factory=list)
    model_overrides: dict[str, str] = Field(default_factory=dict)
    design_note: str | None = None
    stages_completed: list[str] = Field(default_factory=list)
    preview_requested: bool | None = None
    preview_options: PreviewOptions | None = None
    preview_deployment: PreviewDeployment | None = None
    deployment_status: str = "not_requested"
    deployment_source_sha: str | None = None


class DiffOut(BaseModel):
    diff: str


class WorkspaceFile(BaseModel):
    path: str  # relative to the workspace root, posix separators
    size: int


class WorkspaceFilesOut(BaseModel):
    files: list[WorkspaceFile]
    truncated: bool  # more files than the cap; the list is the first MAX_WORKSPACE_FILES


class FileContentOut(BaseModel):
    path: str
    content: str
    truncated: bool  # the file was larger than the view cap


class FileWriteIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=1_000_000)


class FileWriteOut(BaseModel):
    path: str
    size: int


class GitChange(BaseModel):
    path: str
    code: str  # git porcelain status, e.g. " M", "??", "A "


class GitStatusOut(BaseModel):
    changes: list[GitChange]


class CommitIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("commit message must not be blank")
        return value


class CommitOut(BaseModel):
    sha: str
    message: str


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
        complexity=Complexity(run.complexity) if run.complexity else None,
        triage_reason=run.triage_reason,
        team_template=run.team_template,
        test_only=run.test_only,
    )


async def _visible_run(db: AsyncSession, run_id: uuid.UUID, principal: Principal) -> AgentRun:
    run = await db.get(AgentRun, run_id)
    if run is None or not can_access(principal, run.user_id, run.org_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return run


# What the runs list shows where the URL was, after a disconnect
# (RUN_HISTORY_RETENTION.md — history survives the repository).
DISCONNECTED_REPOSITORY = "(repository disconnected)"


async def _run_repository(db: AsyncSession, run: AgentRun) -> Repository | None:
    """The run's repository, or None once it has been disconnected."""
    if run.repository_id is None:
        return None
    return await db.get(Repository, run.repository_id)


@router.post("/v1/runs", status_code=201)
async def create_run(
    body: RunCreate,
    background: BackgroundTasks,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunOut:
    if body.preview_requested and not get_settings().llm_fake and not principal.org_id:
        raise HTTPException(status_code=400, detail="Choose an organization for a live preview run")
    url = body.repository_url.strip()
    # Reuse any visible connection of the same URL — own or org-shared —
    # preferring an owned row when both exist.
    repo = (
        (
            await db.execute(
                select(Repository)
                .where(
                    visible_clause(Repository.owner_id, Repository.org_id, principal),
                    Repository.url == url,
                )
                .order_by((Repository.owner_id == principal.user_id).desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
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
        complexity=body.complexity,
        model_overrides=body.model_overrides,
        preview_requested=body.preview_requested,
        preview_options=body.preview_options.model_dump() if body.preview_options else None,
    )
    db.add(run)
    await db.commit()

    background.add_task(dispatch_plan, run.id)
    return _run_out(run, url)


@router.post("/v1/runs/{run_id}/rerun", status_code=201)
async def rerun_run(
    run_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunOut:
    """Start a fresh run from an existing one's request and repository — retry a
    failed run, or re-run against updated code. The new run is fully independent:
    its own plan, approval gate, budget, and history (RUN_RERUN.md). It belongs to
    whoever triggers it, and goes through planning like any new run."""
    source = await _visible_run(db, run_id, principal)
    repo = await _run_repository(db, source)
    if repo is None:
        raise HTTPException(
            status_code=409,
            detail="This run's repository is no longer connected — reconnect it to run again",
        )

    run = AgentRun(
        user_id=principal.user_id,
        org_id=principal.org_id,
        repository_id=repo.id,
        request=source.request,
        status=RunStatus.QUEUED,
        max_cost_usd=source.max_cost_usd,
        complexity=source.complexity,
        model_overrides=dict(source.model_overrides or {}),
        preview_requested=source.preview_requested,
        preview_options=dict(source.preview_options) if source.preview_options else None,
    )
    db.add(run)
    await db.commit()

    background.add_task(dispatch_plan, run.id)
    return _run_out(run, repo.url)


class PlanTaskEdit(BaseModel):
    """One task's edit at the approval gate: retitle, re-describe, or drop.
    An omitted description leaves the existing one alone; an empty string
    clears it."""

    id: uuid.UUID
    title: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    drop: bool = False

    @field_validator("title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class PlanEditIn(BaseModel):
    tasks: list[PlanTaskEdit] = Field(min_length=1)


class PlanEditOut(BaseModel):
    edited: int
    dropped: int


@router.put("/v1/runs/{run_id}/plan")
async def edit_plan(
    run_id: uuid.UUID,
    body: PlanEditIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> PlanEditOut:
    """Fix a nearly-right plan at the approval gate instead of rejecting it:
    retitle, re-describe, or drop tasks (PLAN_EDITING.md). Only while the
    run awaits approval — before that there is no plan, after that it runs."""
    run = await _visible_run(db, run_id, principal)
    await db.refresh(run, with_for_update=True)
    if run.status != RunStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="The plan can only be edited before approval")

    rows = (await db.execute(select(AgentTask).where(AgentTask.run_id == run_id))).scalars().all()
    by_id = {row.id: row for row in rows}
    unknown = [str(edit.id) for edit in body.tasks if edit.id not in by_id]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Unknown task id(s) on this run: {', '.join(unknown)}"
        )

    dropped_ids = {edit.id for edit in body.tasks if edit.drop}
    if len(dropped_ids) >= len(rows):
        raise HTTPException(
            status_code=400,
            detail="At least one task must remain — reject the plan if none of it is right",
        )

    edited = 0
    for edit in body.tasks:
        if edit.drop:
            continue
        row = by_id[edit.id]
        new_description = (
            row.description if edit.description is None else (edit.description.strip() or None)
        )
        if row.title != edit.title or row.description != new_description:
            row.title = edit.title
            row.description = new_description
            edited += 1
    for task_id in dropped_ids:
        await db.delete(by_id[task_id])

    # A dropped task must vanish from every surviving depends_on, or the
    # board would deadlock waiting on a ghost.
    dropped_keys = {str(task_id) for task_id in dropped_ids}
    survivors = [row for row in rows if row.id not in dropped_ids]
    for row in survivors:
        if any(dep in dropped_keys for dep in row.depends_on):
            row.depends_on = [dep for dep in row.depends_on if dep not in dropped_keys]

    # The plan header follows the board it summarizes.
    survivors.sort(key=lambda row: row.sequence)
    run.plan = {**(run.plan or {}), "tasks": [row.title for row in survivors]}
    db.add(
        AgentEvent(
            run_id=run_id,
            type="plan.edited",
            payload={"edited": edited, "dropped": len(dropped_ids), "by": principal.user_id},
        )
    )
    await db.commit()
    await publish_run_ping(run_id)
    return PlanEditOut(edited=edited, dropped=len(dropped_ids))


class DecisionIn(BaseModel):
    approved: bool


class TriageUpdate(BaseModel):
    complexity: Complexity


class RosterUpdate(BaseModel):
    model_overrides: dict[str, str] = Field(default_factory=dict, max_length=24)
    _validate_overrides = field_validator("model_overrides")(_model_overrides)


@router.patch("/v1/runs/{run_id}/roster")
async def update_roster(
    run_id: uuid.UUID,
    body: RosterUpdate,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunDetailOut:
    from engine.agents.teams import assemble_run_team

    run = await _visible_run(db, run_id, principal)
    await db.refresh(run, with_for_update=True)
    if run.status != RunStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Models can only change before plan approval")
    keys = {seat["key"] for seat in run.team}
    if set(body.model_overrides) - keys:
        raise HTTPException(status_code=422, detail="Unknown seat key")
    run.model_overrides = body.model_overrides
    try:
        run.team = await assemble_run_team(db, run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.add(AgentEvent(run_id=run_id, type="team.updated", payload={"by": principal.user_id}))
    await db.commit()
    await publish_run_ping(run_id)
    return await get_run(run_id, principal, db)


async def _deployment_source_sha(db: AsyncSession, run_id: uuid.UUID) -> str | None:
    payload = (
        await db.execute(
            select(AgentEvent.payload)
            .where(AgentEvent.run_id == run_id, AgentEvent.type == "deploy.approval_requested")
            .order_by(AgentEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    value = payload.get("source_sha") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


@router.post("/v1/runs/{run_id}/deploy-decision")
async def decide_deployment(
    run_id: uuid.UUID,
    body: DecisionIn,
    background: BackgroundTasks,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunOut:
    run = await _visible_run(db, run_id, principal)
    await db.refresh(run, with_for_update=True)
    if principal.user_id != run.user_id and not principal.is_org_admin:
        raise HTTPException(
            status_code=403, detail="Only the run owner or an org admin may approve deploy"
        )
    if run.status != RunStatus.AWAITING_DEPLOY_APPROVAL:
        raise HTTPException(
            status_code=409, detail="This run is not waiting for deployment approval"
        )
    if body.approved:
        if not get_settings().llm_fake:
            try:
                await load_preview_credentials(db, run.org_id)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from None
        ws = _load_run_workspace(run)
        checked_sha = await _deployment_source_sha(db, run_id)
        current_sha = (await run_git(ws.path, "rev-parse", "HEAD")).strip()
        dirty = (await run_git(ws.path, "status", "--porcelain")).strip()
        if not checked_sha or checked_sha != current_sha or dirty:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Workspace differs from the checked deployment commit; "
                    "rerun checks before deploying"
                ),
            )
        run.deployment_approved_sha = checked_sha
        run.deployment_approved_at = datetime.now(UTC)
        run.deployment_approved_by = principal.user_id
        run.deployment_status = "approved"
        run.status = RunStatus.EXECUTING
        background.add_task(dispatch_execute, run.id)
    else:
        run.deployment_status = "rejected"
        run.status = RunStatus.CANCELLED
        run.finished_at = datetime.now(UTC)
        db.add(
            AgentEvent(
                run_id=run.id,
                type="run.finished",
                payload={
                    "status": RunStatus.CANCELLED,
                    "error": None,
                },
            )
        )
    db.add(
        AgentEvent(
            run_id=run.id,
            type="deploy.approved" if body.approved else "deploy.rejected",
            payload={"by": principal.user_id, "source_sha": run.deployment_approved_sha},
        )
    )
    db.add(
        AgentEvent(
            run_id=run.id,
            type="run.status_changed",
            payload={
                "from": RunStatus.AWAITING_DEPLOY_APPROVAL,
                "to": run.status,
            },
        )
    )
    await db.commit()
    await publish_run_ping(run.id)
    repo = await _run_repository(db, run)
    return _run_out(run, repo.url if repo else DISCONNECTED_REPOSITORY)


@router.patch("/v1/runs/{run_id}/triage")
async def update_triage(
    run_id: uuid.UUID,
    body: TriageUpdate,
    background: BackgroundTasks,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunOut:
    run = await _visible_run(db, run_id, principal)
    # Serialize with plan edits and the atomic approval claim.
    await db.refresh(run, with_for_update=True)
    if run.status != RunStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Complexity can only change before approval")
    tasks = (await db.execute(select(AgentTask).where(AgentTask.run_id == run.id))).scalars().all()
    active = [task for task in tasks if task.status != TaskStatus.SKIPPED]
    if (
        body.complexity == Complexity.QUICK
        and not run.test_only
        and (len(active) > 2 or len({(task.role, task.level) for task in active}) > 1)
    ):
        raise HTTPException(
            status_code=409, detail="Quick needs at most two tasks for one engineer"
        )
    previous = run.complexity
    run.complexity = body.complexity
    run.team_template = template_for(run.complexity, run.test_only)
    run.triage_reason = "human complexity override"
    if (
        run.team
        and run.complexity == Complexity.COMPLEX
        and not run.test_only
        and not run.design_note
    ):
        from engine.jobs import dispatch_prepare_approval

        # Keep the existing edited board; prepare its missing design before approval.
        run.status = RunStatus.PLANNING
        background.add_task(dispatch_prepare_approval, run.id)
        db.add(
            AgentEvent(
                run_id=run.id,
                type="run.status_changed",
                payload={
                    "from": RunStatus.AWAITING_APPROVAL,
                    "to": RunStatus.PLANNING,
                },
            )
        )
    elif run.team:
        from engine.agents.teams import assemble_run_team

        try:
            run.team = await assemble_run_team(db, run)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        valid_keys = {seat["key"] for seat in run.team}
        run.model_overrides = {
            key: model for key, model in run.model_overrides.items() if key in valid_keys
        }
    db.add(
        AgentEvent(
            run_id=run.id,
            type="run.triaged",
            payload={
                "from": previous,
                "complexity": run.complexity,
                "reason": run.triage_reason,
                "source": "human",
                "by": principal.user_id,
                "test_only": run.test_only,
                "team_template": run.team_template,
            },
        )
    )
    await db.commit()
    await publish_run_ping(run.id)
    repo = await _run_repository(db, run)
    return _run_out(run, repo.url if repo else DISCONNECTED_REPOSITORY)


@router.post("/v1/runs/{run_id}/decision")
async def decide_run(
    run_id: uuid.UUID,
    body: DecisionIn,
    background: BackgroundTasks,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunOut:
    """The human approval gate: approve starts the work, reject ends the run."""
    run = await _visible_run(db, run_id, principal)
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
    repo = await _run_repository(db, run)
    return _run_out(run, repo.url if repo else "")


@router.get("/v1/runs")
async def list_runs(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
    status: str | None = Query(default=None, description="Filter to one run status"),
    q: str | None = Query(default=None, description="Case-insensitive search of the request text"),
) -> list[RunOut]:
    stmt = (
        select(AgentRun, Repository.url)
        .outerjoin(Repository, AgentRun.repository_id == Repository.id)
        .where(visible_clause(AgentRun.user_id, AgentRun.org_id, principal))
    )
    if status:
        # An unknown status simply matches nothing — no 422 for a stale filter.
        stmt = stmt.where(AgentRun.status == status)
    if q and q.strip():
        # Escape LIKE wildcards so a literal % or _ in the query stays literal.
        pattern = q.strip().translate({ord("\\"): "\\\\", ord("%"): "\\%", ord("_"): "\\_"})
        stmt = stmt.where(AgentRun.request.ilike(f"%{pattern}%", escape="\\"))
    stmt = stmt.order_by(AgentRun.created_at.desc()).limit(50)
    rows = (await db.execute(stmt)).all()
    return [_run_out(run, url or DISCONNECTED_REPOSITORY) for run, url in rows]


class RunStatsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    completed: int
    failed: int
    success_rate: float | None  # completed / (completed + failed); None with no terminal runs
    total_cost_usd: float
    total_tokens: int


# Declared before /v1/runs/{run_id} so "stats" is not parsed as a run id.
@router.get("/v1/runs/stats")
async def get_run_stats(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunStatsOut:
    """Aggregate outcomes across the caller's visible runs — the product KPI:
    how many runs, how they ended, the success rate, and the spend."""
    rows = (
        await db.execute(
            select(
                AgentRun.status,
                func.count(),
                func.coalesce(func.sum(AgentRun.total_cost_usd), 0),
                func.coalesce(
                    func.sum(AgentRun.total_input_tokens + AgentRun.total_output_tokens), 0
                ),
            )
            .where(visible_clause(AgentRun.user_id, AgentRun.org_id, principal))
            .group_by(AgentRun.status)
        )
    ).all()

    by_status: dict[str, int] = {}
    total_cost = 0.0
    total_tokens = 0
    for status, count, cost, tokens in rows:
        by_status[str(status)] = count
        total_cost += float(cost)
        total_tokens += int(tokens)

    completed = by_status.get(RunStatus.COMPLETED, 0)
    failed = by_status.get(RunStatus.FAILED, 0)
    terminal = completed + failed
    return RunStatsOut(
        total=sum(by_status.values()),
        by_status=by_status,
        completed=completed,
        failed=failed,
        success_rate=(completed / terminal) if terminal else None,
        total_cost_usd=round(total_cost, 6),
        total_tokens=total_tokens,
    )


@router.get("/v1/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunDetailOut:
    run = await _visible_run(db, run_id, principal)
    repo = await _run_repository(db, run)
    tasks = (
        (
            await db.execute(
                select(AgentTask).where(AgentTask.run_id == run_id).order_by(AgentTask.sequence)
            )
        )
        .scalars()
        .all()
    )
    base = _run_out(run, repo.url if repo else DISCONNECTED_REPOSITORY)
    return RunDetailOut(
        **base.model_dump(),
        plan=run.plan,
        test_report=run.test_report,
        team=[Seat.model_validate(seat) for seat in run.team],
        model_overrides=run.model_overrides,
        design_note=run.design_note,
        stages_completed=run.stages_completed,
        preview_requested=run.preview_requested,
        preview_options=PreviewOptions.model_validate(run.preview_options)
        if run.preview_options
        else None,
        preview_deployment=(
            PreviewDeployment.model_validate(run.preview_deployment)
            if run.preview_deployment
            else None
        ),
        deployment_status=run.deployment_status,
        deployment_source_sha=run.deployment_approved_sha
        or (await _deployment_source_sha(db, run_id)),
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
                level=t.level,
                model=t.model,
            )
            for t in tasks
        ],
    )


# While a run is in one of these states a background task may still be working
# on it — deleting the row out from under it would be a race.
_ACTIVE_RUN_STATUSES = {
    RunStatus.QUEUED,
    RunStatus.PLANNING,
    RunStatus.EXECUTING,
    RunStatus.REVIEWING,
    RunStatus.DEPLOYING,
}


@router.delete("/v1/runs/{run_id}", status_code=204)
async def delete_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a run and its history — tasks, events, and artifacts cascade in the
    database, and the workspace is removed from disk. Refused while the run is
    still working. Visible to the run's owner or organization, like the rest of
    the runs API (ORGANIZATION_SHARING.md)."""
    run = await _visible_run(db, run_id, principal)
    if run.status in _ACTIVE_RUN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="This run is still working — wait for it to finish before deleting it",
        )
    if run.preview_deployment and run.deployment_status != "deleted":
        from engine.agents.preview_cleanup import cleanup_run_preview

        if not await cleanup_run_preview(run.id):
            raise HTTPException(
                status_code=409, detail="Preview cleanup must finish before deleting the run"
            )
    await asyncio.to_thread(remove_workspace, run.id)
    await db.delete(run)
    await db.commit()


class RunReportOut(BaseModel):
    markdown: str
    filename: str


@router.get("/v1/runs/{run_id}/report")
async def get_run_report(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RunReportOut:
    """A shareable plain-English markdown summary of the run — request, plan,
    per-task outcome, the agents' key decisions, cost, and result (RUN_REPORT.md).
    Built from the run record, so it works even after the workspace is gone."""
    run = await _visible_run(db, run_id, principal)
    repo = await _run_repository(db, run)
    tasks = (
        (
            await db.execute(
                select(AgentTask).where(AgentTask.run_id == run_id).order_by(AgentTask.sequence)
            )
        )
        .scalars()
        .all()
    )
    reasoning_rows = (
        await db.execute(
            select(AgentEvent.agent, AgentEvent.payload)
            .where(AgentEvent.run_id == run_id, AgentEvent.type == "agent.reasoning")
            .order_by(AgentEvent.id)
        )
    ).all()
    reasoning = [(agent, str((payload or {}).get("text", ""))) for agent, payload in reasoning_rows]
    markdown = build_run_report(run, list(tasks), repo.url if repo else None, reasoning)
    return RunReportOut(markdown=markdown, filename=f"run-{run_id.hex[:8]}.md")


def _load_run_workspace(run: AgentRun) -> Workspace:
    """The run's on-disk workspace, or a 404 explaining why it is unavailable.
    A run before planning has none; a rejected/recovered run's is gone."""
    if not run.base_sha:
        raise HTTPException(status_code=404, detail="This run has no workspace yet")
    try:
        return load_workspace(run.id, run.branch_name or "", run.base_sha)
    except WorkspaceError:
        raise HTTPException(status_code=404, detail="This run's workspace is gone") from None


@router.get("/v1/runs/{run_id}/diff")
async def get_run_diff(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> DiffOut:
    """Everything the agents changed in the run's workspace since its base commit."""
    run = await _visible_run(db, run_id, principal)
    ws = _load_run_workspace(run)
    try:
        diff = await run_git(ws.path, "diff", ws.base_sha)
    except WorkspaceError:
        raise HTTPException(status_code=404, detail="This run's workspace is gone") from None
    return DiffOut(diff=diff)


def _walk_workspace(root: Path) -> tuple[list[WorkspaceFile], bool]:
    """Every file in the workspace (not .git), sorted, capped. Runs in a thread."""
    found = [
        entry
        for entry in root.rglob("*")
        if entry.is_file() and ".git" not in entry.relative_to(root).parts
    ]
    found.sort(key=lambda entry: entry.relative_to(root).as_posix())
    truncated = len(found) > MAX_WORKSPACE_FILES
    files = [
        WorkspaceFile(path=entry.relative_to(root).as_posix(), size=entry.stat().st_size)
        for entry in found[:MAX_WORKSPACE_FILES]
    ]
    return files, truncated


@router.get("/v1/runs/{run_id}/files")
async def list_run_files(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> WorkspaceFilesOut:
    """The run workspace's files, for the run page's file browser."""
    run = await _visible_run(db, run_id, principal)
    ws = _load_run_workspace(run)
    files, truncated = await asyncio.to_thread(_walk_workspace, ws.path)
    return WorkspaceFilesOut(files=files, truncated=truncated)


@router.get("/v1/runs/{run_id}/files/content")
async def get_run_file(
    run_id: uuid.UUID,
    path: str = Query(min_length=1, max_length=1024),
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> FileContentOut:
    """One workspace file's text, jailed and size-capped."""
    run = await _visible_run(db, run_id, principal)
    ws = _load_run_workspace(run)
    try:
        target = resolve_inside(ws.path, path)
    except JailViolation as exc:
        raise HTTPException(status_code=400, detail=f"path not allowed: {exc}") from None
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    def _read() -> tuple[str, bool]:
        size = target.stat().st_size
        raw = target.read_bytes()[:MAX_VIEW_BYTES]
        return raw.decode("utf-8", errors="replace"), size > MAX_VIEW_BYTES

    content, truncated = await asyncio.to_thread(_read)
    return FileContentOut(path=path, content=content, truncated=truncated)


# Editing is safe only when the agent loop no longer owns the workspace.
_EDITABLE_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED})


def _require_editable(run: AgentRun) -> None:
    if run.status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="The workspace can only be edited after the run finishes",
        )


def _jailed_target(ws: Workspace, path: str) -> Path:
    try:
        return resolve_inside(ws.path, path)
    except JailViolation as exc:
        raise HTTPException(status_code=400, detail=f"path not allowed: {exc}") from None


@router.put("/v1/runs/{run_id}/files/content")
async def write_run_file(
    run_id: uuid.UUID,
    body: FileWriteIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> FileWriteOut:
    """Replace one workspace file (finished runs only), jailed to the workspace."""
    run = await _visible_run(db, run_id, principal)
    _require_editable(run)
    ws = _load_run_workspace(run)
    target = _jailed_target(ws, body.path)

    def _write() -> int:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.content, encoding="utf-8", newline="\n")
        return target.stat().st_size

    size = await asyncio.to_thread(_write)
    return FileWriteOut(path=body.path, size=size)


@router.get("/v1/runs/{run_id}/git-status")
async def run_git_status(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> GitStatusOut:
    """The run workspace's working-tree changes (git status --porcelain)."""
    run = await _visible_run(db, run_id, principal)
    ws = _load_run_workspace(run)
    try:
        output = await run_git(ws.path, "status", "--porcelain")
    except WorkspaceError:
        raise HTTPException(status_code=404, detail="This run's workspace is gone") from None
    changes = [
        GitChange(code=line[:2], path=line[3:]) for line in output.splitlines() if len(line) > 3
    ]
    return GitStatusOut(changes=changes)


@router.post("/v1/runs/{run_id}/commit")
async def commit_run_workspace(
    run_id: uuid.UUID,
    body: CommitIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> CommitOut:
    """Stage everything and commit the workspace (finished runs only)."""
    run = await _visible_run(db, run_id, principal)
    _require_editable(run)
    ws = _load_run_workspace(run)
    message = body.message.strip()
    try:
        await run_git(ws.path, "add", "-A")
        if not (await run_git(ws.path, "status", "--porcelain")).strip():
            raise HTTPException(status_code=400, detail="nothing to commit — no files changed")
        await run_git(ws.path, "commit", "-m", message)
        sha = await run_git(ws.path, "rev-parse", "--short", "HEAD")
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return CommitOut(sha=sha, message=message)


class PushOut(BaseModel):
    branch: str
    pushed: bool


@router.post("/v1/runs/{run_id}/push")
async def push_workspace(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> PushOut:
    """Push the run's branch to its host (finished runs only) — the way a
    manual workspace commit leaves the machine (WORKSPACE_PANELS.md). The
    credential logic is the run pipeline's own (integrations/hosts.py): a
    GitLab or Bitbucket repository uses the run owner's encrypted
    connection, GitHub uses the environment token, anything else pushes
    plainly."""
    run = await _visible_run(db, run_id, principal)
    _require_editable(run)
    ws = _load_run_workspace(run)

    repo = await _run_repository(db, run)
    credential: tuple[str, str] | None = None
    if repo is not None:
        credential = push_credential(await host_connection(db, run.user_id, repo.url))

    try:
        pushed = await push_branch(ws, credential)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not pushed:
        raise HTTPException(status_code=400, detail="This run's workspace has no remote to push to")

    db.add(
        AgentEvent(
            run_id=run.id,
            type="branch.pushed",
            payload={"branch": ws.branch, "by": principal.user_id},
        )
    )
    await db.commit()
    await publish_run_ping(run.id)
    return PushOut(branch=ws.branch, pushed=True)


@router.get("/v1/runs/{run_id}/events")
async def list_events(
    run_id: uuid.UUID,
    after: int = 0,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[EventOut]:
    await _visible_run(db, run_id, principal)
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
    await _visible_run(db, run_id, principal)
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
