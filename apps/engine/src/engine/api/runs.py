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
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.enums import RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask, Repository
from engine.db.session import get_session, session_scope
from engine.db.visibility import can_access, visible_clause
from engine.events.bus import RunEventSubscription, publish_run_ping
from engine.integrations.hosts import host_connection, push_credential
from engine.jobs import dispatch_execute, dispatch_plan
from engine.knowledge.capture import capture_plan_rejected
from engine.reporting import build_run_report
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
    )
    db.add(run)
    await db.commit()

    background.add_task(dispatch_plan, run.id)
    return _run_out(run, url)


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
) -> list[RunOut]:
    rows = (
        await db.execute(
            select(AgentRun, Repository.url)
            .outerjoin(Repository, AgentRun.repository_id == Repository.id)
            .where(visible_clause(AgentRun.user_id, AgentRun.org_id, principal))
            .order_by(AgentRun.created_at.desc())
            .limit(50)
        )
    ).all()
    return [_run_out(run, url or DISCONNECTED_REPOSITORY) for run, url in rows]


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
    per-task outcome, cost, and result (RUN_REPORT.md). Built from the run
    record, so it works even after the workspace is gone."""
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
    markdown = build_run_report(run, list(tasks), repo.url if repo else None)
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
