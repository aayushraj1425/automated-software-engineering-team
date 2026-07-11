"""Work-items API: the durable, repository-scoped backlog (Planning Suite).

Owner-scoped like the repositories and runs APIs. A work item is planned once
and lives on — created, listed, updated, and reordered on the task board — until
a coding run implements it. Dependencies must reference items in the same
repository so blocker detection has no dangling edges. Design note:
docs/architecture/PLANNING_SUITE.md.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.scrum_master import generate_roadmap, persist_roadmap
from engine.auth import Principal, require_service_auth
from engine.db.enums import Estimate, Priority, WorkItemKind, WorkItemStatus
from engine.db.models import CodeChunk, Repository, WorkItem
from engine.db.session import get_session
from engine.knowledge.recall import format_memories, recall_memories
from engine.planning.insights import plan_insights

router = APIRouter()

# How many existing file paths to hand the Scrum Master as repository context.
_CONTEXT_FILE_LIMIT = 60


def _stripped_title(value: str | None) -> str | None:
    """min_length validates before stripping, so '   ' would otherwise pass
    and be stored as an empty title."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("title must not be blank")
    return stripped


class WorkItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None
    kind: WorkItemKind = WorkItemKind.FEATURE
    priority: Priority = Priority.MEDIUM
    estimate: Estimate | None = None
    milestone: str | None = Field(default=None, max_length=128)
    depends_on: list[uuid.UUID] = Field(default_factory=list)

    _title = field_validator("title")(_stripped_title)


class WorkItemUpdate(BaseModel):
    """Every field optional; only the fields sent are changed (partial update)."""

    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    kind: WorkItemKind | None = None
    status: WorkItemStatus | None = None
    priority: Priority | None = None
    estimate: Estimate | None = None
    milestone: str | None = Field(default=None, max_length=128)
    depends_on: list[uuid.UUID] | None = None
    rationale: str | None = None
    position: int | None = None

    _title = field_validator("title")(_stripped_title)


class ReorderIn(BaseModel):
    ordered_ids: list[uuid.UUID] = Field(min_length=1)


class RoadmapIn(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)


class WorkItemOut(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    title: str
    description: str | None
    kind: str
    status: str
    estimate: str | None
    priority: str
    milestone: str | None
    depends_on: list[str]
    rationale: str | None
    position: int
    implemented_by_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class BlockedItemOut(BaseModel):
    item_id: uuid.UUID
    title: str
    waiting_on: list[str]  # ids of the unfinished dependencies


class PlanInsightsOut(BaseModel):
    blocked: list[BlockedItemOut]
    recommended: WorkItemOut | None  # the next unblocked, highest-priority item


def _work_item_out(item: WorkItem) -> WorkItemOut:
    return WorkItemOut(
        id=item.id,
        repository_id=item.repository_id,
        title=item.title,
        description=item.description,
        kind=item.kind,
        status=item.status,
        estimate=item.estimate,
        priority=item.priority,
        milestone=item.milestone,
        depends_on=item.depends_on,
        rationale=item.rationale,
        position=item.position,
        implemented_by_run_id=item.implemented_by_run_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _owned_repository(
    db: AsyncSession, repository_id: uuid.UUID, principal: Principal
) -> Repository:
    repo = await db.get(Repository, repository_id)
    if repo is None or repo.owner_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


async def _owned_work_item(
    db: AsyncSession, repository_id: uuid.UUID, item_id: uuid.UUID, principal: Principal
) -> WorkItem:
    await _owned_repository(db, repository_id, principal)
    item = await db.get(WorkItem, item_id)
    if item is None or item.repository_id != repository_id:
        raise HTTPException(status_code=404, detail="Work item not found")
    return item


async def _validate_dependencies(
    db: AsyncSession,
    repository_id: uuid.UUID,
    depends_on: list[uuid.UUID],
    this_id: uuid.UUID | None,
) -> list[str]:
    """Every dependency must be another work item in the same repository."""
    ids = [d for d in depends_on if d != this_id]  # an item never depends on itself
    if not ids:
        return []
    found = set(
        (
            await db.execute(
                select(WorkItem.id).where(
                    WorkItem.repository_id == repository_id, WorkItem.id.in_(ids)
                )
            )
        )
        .scalars()
        .all()
    )
    missing = [str(d) for d in ids if d not in found]
    if missing:
        raise HTTPException(
            status_code=400, detail=f"Unknown dependency work item(s): {', '.join(missing)}"
        )
    if this_id is not None:
        await _reject_dependency_cycles(db, repository_id, this_id, ids)
    return [str(d) for d in ids]


async def _reject_dependency_cycles(
    db: AsyncSession, repository_id: uuid.UUID, this_id: uuid.UUID, new_deps: list[uuid.UUID]
) -> None:
    """A dependency cycle (A waits on B, B waits on A) deadlocks the plan:
    blocker detection would report both items blocked forever with nothing to
    recommend. Walk the existing graph from each proposed dependency; if the
    item being updated is reachable, the update would close a cycle."""
    rows = (
        await db.execute(
            select(WorkItem.id, WorkItem.depends_on).where(WorkItem.repository_id == repository_id)
        )
    ).all()
    graph = {str(item_id): list(deps or []) for item_id, deps in rows}
    stack = [str(d) for d in new_deps]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == str(this_id):
            raise HTTPException(status_code=400, detail="These dependencies would create a cycle")
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, []))


@router.post("/v1/repositories/{repository_id}/work-items", status_code=201)
async def create_work_item(
    repository_id: uuid.UUID,
    body: WorkItemIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    await _owned_repository(db, repository_id, principal)
    depends_on = await _validate_dependencies(db, repository_id, body.depends_on, None)
    item = WorkItem(
        repository_id=repository_id,
        title=body.title,
        description=body.description,
        kind=body.kind,
        priority=body.priority,
        estimate=body.estimate,
        milestone=body.milestone,
        depends_on=depends_on,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _work_item_out(item)


@router.get("/v1/repositories/{repository_id}/work-items")
async def list_work_items(
    repository_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[WorkItemOut]:
    await _owned_repository(db, repository_id, principal)
    rows = (
        (
            await db.execute(
                select(WorkItem)
                .where(WorkItem.repository_id == repository_id)
                .order_by(WorkItem.position, WorkItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_work_item_out(item) for item in rows]


@router.patch("/v1/repositories/{repository_id}/work-items/{item_id}")
async def update_work_item(
    repository_id: uuid.UUID,
    item_id: uuid.UUID,
    body: WorkItemUpdate,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    item = await _owned_work_item(db, repository_id, item_id, principal)
    changes = body.model_dump(exclude_unset=True)
    if "depends_on" in changes:
        changes["depends_on"] = await _validate_dependencies(
            db, repository_id, body.depends_on or [], item_id
        )
    for field, value in changes.items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return _work_item_out(item)


@router.post("/v1/repositories/{repository_id}/work-items/reorder")
async def reorder_work_items(
    repository_id: uuid.UUID,
    body: ReorderIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[WorkItemOut]:
    """Set each item's board position from its index in `ordered_ids`."""
    await _owned_repository(db, repository_id, principal)
    rows = (
        (await db.execute(select(WorkItem).where(WorkItem.repository_id == repository_id)))
        .scalars()
        .all()
    )
    by_id = {item.id: item for item in rows}
    unknown = [str(i) for i in body.ordered_ids if i not in by_id]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown work item(s): {', '.join(unknown)}")
    for position, item_id in enumerate(body.ordered_ids):
        by_id[item_id].position = position
    await db.commit()
    # Re-query ordered rather than reading the just-committed (expired) objects.
    ordered = (
        (
            await db.execute(
                select(WorkItem)
                .where(WorkItem.repository_id == repository_id)
                .order_by(WorkItem.position, WorkItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_work_item_out(item) for item in ordered]


async def _repository_context(db: AsyncSession, repository_id: uuid.UUID) -> str:
    """A newline list of existing file paths to ground the Scrum Master's plan."""
    paths = (
        (
            await db.execute(
                select(CodeChunk.path)
                .where(CodeChunk.repository_id == repository_id)
                .distinct()
                .order_by(CodeChunk.path)
                .limit(_CONTEXT_FILE_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return "\n".join(paths)


@router.post("/v1/repositories/{repository_id}/roadmap", status_code=201)
async def generate_repository_roadmap(
    repository_id: uuid.UUID,
    body: RoadmapIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[WorkItemOut]:
    """Scrum Master: turn a one-line goal into work items saved to the backlog."""
    await _owned_repository(db, repository_id, principal)
    context = await _repository_context(db, repository_id)
    memory = format_memories(await recall_memories(db, repository_id, body.goal))
    roadmap = await generate_roadmap(body.goal, context, memory)
    created = await persist_roadmap(db, repository_id, roadmap)
    return [_work_item_out(item) for item in created]


@router.get("/v1/repositories/{repository_id}/work-items/insights")
async def work_item_insights(
    repository_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> PlanInsightsOut:
    """Blocked items and the recommended next item — computed, never stored."""
    await _owned_repository(db, repository_id, principal)
    items = (
        (
            await db.execute(
                select(WorkItem)
                .where(WorkItem.repository_id == repository_id)
                .order_by(WorkItem.position, WorkItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    insights = plan_insights(items)
    by_id = {str(item.id): item for item in items}
    recommended = by_id.get(insights.recommended_id) if insights.recommended_id else None
    return PlanInsightsOut(
        blocked=[
            BlockedItemOut(
                item_id=uuid.UUID(entry.item_id), title=entry.title, waiting_on=entry.waiting_on
            )
            for entry in insights.blocked
        ],
        recommended=_work_item_out(recommended) if recommended is not None else None,
    )
