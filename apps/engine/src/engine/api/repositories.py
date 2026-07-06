"""Repositories API: connect a repository, index it, and search the index.

Owner-scoped like the runs API. Indexing runs as a background task; search
embeds the question and returns the closest chunks by cosine distance
(design note: docs/architecture/REPOSITORY_INTELLIGENCE.md).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.models import CodeChunk, Repository
from engine.db.session import get_session
from engine.indexing.indexer import index_repository
from engine.llm.router import model_router

router = APIRouter()

SEARCH_LIMIT = 8
SNIPPET_CHARS = 600


class RepositoryIn(BaseModel):
    url: str = Field(min_length=8, max_length=512)


class RepositoryOut(BaseModel):
    id: uuid.UUID
    url: str
    status: str
    default_branch: str
    last_indexed_at: datetime | None
    chunks: int


class SearchHit(BaseModel):
    path: str
    language: str
    start_line: int
    end_line: int
    snippet: str
    score: float  # 1.0 = identical meaning, 0.0 = unrelated


async def _owned_repository(
    db: AsyncSession, repository_id: uuid.UUID, principal: Principal
) -> Repository:
    repo = await db.get(Repository, repository_id)
    if repo is None or repo.owner_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


async def _chunk_count(db: AsyncSession, repository_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(CodeChunk)
            .where(CodeChunk.repository_id == repository_id)
        )
    ).scalar_one()


def _repository_out(repo: Repository, chunks: int) -> RepositoryOut:
    return RepositoryOut(
        id=repo.id,
        url=repo.url,
        status=repo.status,
        default_branch=repo.default_branch,
        last_indexed_at=repo.last_indexed_at,
        chunks=chunks,
    )


@router.post("/v1/repositories", status_code=201)
async def connect_repository(
    body: RepositoryIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RepositoryOut:
    url = body.url.strip()
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
        await db.commit()
    return _repository_out(repo, await _chunk_count(db, repo.id))


@router.get("/v1/repositories")
async def list_repositories(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[RepositoryOut]:
    rows = (
        (
            await db.execute(
                select(Repository, func.count(CodeChunk.id))
                .outerjoin(CodeChunk, CodeChunk.repository_id == Repository.id)
                .where(Repository.owner_id == principal.user_id)
                .group_by(Repository.id)
                .order_by(Repository.created_at.desc())
                .limit(100)
            )
        )
        .tuples()
        .all()
    )
    return [_repository_out(repo, chunks) for repo, chunks in rows]


@router.post("/v1/repositories/{repository_id}/index", status_code=202)
async def start_indexing(
    repository_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> RepositoryOut:
    repo = await _owned_repository(db, repository_id, principal)
    repo.status = "indexing"
    await db.commit()
    background.add_task(index_repository, repo.id)
    return _repository_out(repo, await _chunk_count(db, repo.id))


@router.get("/v1/repositories/{repository_id}/search")
async def search_repository(
    repository_id: uuid.UUID,
    q: str = Query(min_length=2, max_length=500),
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[SearchHit]:
    await _owned_repository(db, repository_id, principal)
    (query_vector,) = await model_router.embed([q])
    distance = CodeChunk.embedding.cosine_distance(query_vector)
    rows = (
        (
            await db.execute(
                select(CodeChunk, distance.label("distance"))
                .where(CodeChunk.repository_id == repository_id)
                .order_by(distance)
                .limit(SEARCH_LIMIT)
            )
        )
        .tuples()
        .all()
    )
    return [
        SearchHit(
            path=chunk.path,
            language=chunk.language,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            snippet=chunk.content[:SNIPPET_CHARS],
            score=round(max(0.0, 1.0 - float(dist)), 4),
        )
        for chunk, dist in rows
    ]
