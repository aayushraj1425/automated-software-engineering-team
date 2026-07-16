"""Knowledge API: the repository's long-term memory (Knowledge & Memory).

Owner-scoped like the work-items API. Lists a repository's memories newest
first, searches them with the same hybrid recall the agents use, accepts
hand-written notes and preferences, and deletes memories that turned out to be
wrong. Design note: docs/architecture/KNOWLEDGE_AND_MEMORY.md.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.enums import KnowledgeKind
from engine.db.models import KnowledgeItem, Repository
from engine.db.session import get_session
from engine.db.visibility import can_access
from engine.knowledge.recall import recall_memories
from engine.knowledge.store import MAX_CONTENT, remember

router = APIRouter()

_LIST_LIMIT = 100
_SEARCH_LIMIT = 20


class KnowledgeItemIn(BaseModel):
    """A hand-written memory. Decisions and outcomes are captured automatically
    by runs; the page adds notes and preferences (and corrections as notes)."""

    kind: KnowledgeKind = KnowledgeKind.NOTE
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=MAX_CONTENT)

    @field_validator("title", "content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # min_length runs before stripping, so "   " would otherwise pass.
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class KnowledgeItemOut(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    kind: str
    title: str
    content: str
    source_run_id: uuid.UUID | None
    created_by: str | None
    created_at: datetime
    score: float | None = None  # similarity when the list came from a search


def _item_out(item: KnowledgeItem, score: float | None = None) -> KnowledgeItemOut:
    return KnowledgeItemOut(
        id=item.id,
        repository_id=item.repository_id,
        kind=item.kind,
        title=item.title,
        content=item.content,
        source_run_id=item.source_run_id,
        created_by=item.created_by,
        created_at=item.created_at,
        score=score,
    )


async def _visible_repository(
    db: AsyncSession, repository_id: uuid.UUID, principal: Principal
) -> Repository:
    repo = await db.get(Repository, repository_id)
    if repo is None or not can_access(principal, repo.owner_id, repo.org_id):
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.get("/v1/repositories/{repository_id}/knowledge")
async def list_knowledge(
    repository_id: uuid.UUID,
    q: str | None = None,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[KnowledgeItemOut]:
    """Newest memories first; with `q`, the hybrid-recall ranking instead."""
    await _visible_repository(db, repository_id, principal)
    if q and q.strip():
        recalled = await recall_memories(db, repository_id, q.strip(), limit=_SEARCH_LIMIT)
        ids = [m.id for m in recalled]
        rows = (
            (await db.execute(select(KnowledgeItem).where(KnowledgeItem.id.in_(ids))))
            .scalars()
            .all()
        )
        by_id = {item.id: item for item in rows}
        return [_item_out(by_id[m.id], score=m.score) for m in recalled if m.id in by_id]
    rows = (
        (
            await db.execute(
                select(KnowledgeItem)
                .where(KnowledgeItem.repository_id == repository_id)
                .order_by(KnowledgeItem.created_at.desc())
                .limit(_LIST_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return [_item_out(item) for item in rows]


@router.post("/v1/repositories/{repository_id}/knowledge", status_code=201)
async def create_knowledge(
    repository_id: uuid.UUID,
    body: KnowledgeItemIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> KnowledgeItemOut:
    await _visible_repository(db, repository_id, principal)
    item = await remember(
        db,
        repository_id,
        body.kind,
        body.title,
        body.content,
        created_by=principal.user_id,
    )
    await db.commit()
    await db.refresh(item)
    return _item_out(item)


@router.delete("/v1/repositories/{repository_id}/knowledge/{item_id}", status_code=204)
async def delete_knowledge(
    repository_id: uuid.UUID,
    item_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Memories that turn out to be wrong are deleted, not argued with."""
    await _visible_repository(db, repository_id, principal)
    item = await db.get(KnowledgeItem, item_id)
    if item is None or item.repository_id != repository_id:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    await db.delete(item)
    await db.commit()
