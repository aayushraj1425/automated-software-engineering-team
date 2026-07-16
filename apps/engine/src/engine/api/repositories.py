"""Repositories API: connect a repository, index it, and search the index.

Scoped to the caller's own repositories plus the active organization's
shared ones (docs/architecture/ORGANIZATION_SHARING.md), like the runs API.
Indexing runs as a background task; search embeds the question and returns
the closest chunks by cosine distance
(design note: docs/architecture/REPOSITORY_INTELLIGENCE.md).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.models import CodeChunk, CodeEdge, Repository
from engine.db.session import get_session
from engine.db.visibility import can_access, visible_clause
from engine.indexing.chunker import LANGUAGES
from engine.indexing.indexer import index_repository
from engine.indexing.retrieval import retrieve_chunks

router = APIRouter()

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


class GraphNode(BaseModel):
    path: str
    language: str
    in_degree: int  # files that import this one
    out_degree: int  # files this one imports


class GraphEdge(BaseModel):
    source: str
    target: str


class DependencyGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def _language_for(path: str) -> str:
    dot = path.rfind(".")
    return LANGUAGES.get(path[dot:].lower(), "other") if dot != -1 else "other"


async def _visible_repository(
    db: AsyncSession, repository_id: uuid.UUID, principal: Principal
) -> Repository:
    repo = await db.get(Repository, repository_id)
    if repo is None or not can_access(principal, repo.owner_id, repo.org_id):
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
                .where(visible_clause(Repository.owner_id, Repository.org_id, principal))
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
    repo = await _visible_repository(db, repository_id, principal)
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
    await _visible_repository(db, repository_id, principal)
    chunks = await retrieve_chunks(db, repository_id, q)
    return [
        SearchHit(
            path=chunk.path,
            language=chunk.language,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            snippet=chunk.content[:SNIPPET_CHARS],
            score=chunk.score,
        )
        for chunk in chunks
    ]


@router.get("/v1/repositories/{repository_id}/graph")
async def repository_graph(
    repository_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> DependencyGraph:
    await _visible_repository(db, repository_id, principal)

    chunk_rows = (
        (
            await db.execute(
                select(CodeChunk.path, CodeChunk.language)
                .where(CodeChunk.repository_id == repository_id)
                .distinct()
            )
        )
        .tuples()
        .all()
    )
    edge_rows = (
        (
            await db.execute(
                select(CodeEdge.source_path, CodeEdge.target_path).where(
                    CodeEdge.repository_id == repository_id
                )
            )
        )
        .tuples()
        .all()
    )

    languages = {path: language for path, language in chunk_rows}
    edges = [GraphEdge(source=source, target=target) for source, target in edge_rows]
    out_degree: dict[str, int] = {}
    in_degree: dict[str, int] = {}
    for edge in edges:
        out_degree[edge.source] = out_degree.get(edge.source, 0) + 1
        in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

    paths = set(languages) | {edge.source for edge in edges} | {edge.target for edge in edges}
    nodes = [
        GraphNode(
            path=path,
            language=languages.get(path) or _language_for(path),
            in_degree=in_degree.get(path, 0),
            out_degree=out_degree.get(path, 0),
        )
        for path in paths
    ]
    nodes.sort(key=lambda node: (-(node.in_degree + node.out_degree), node.path))
    return DependencyGraph(nodes=nodes, edges=edges)
