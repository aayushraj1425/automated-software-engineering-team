"""Builds a repository's search index: clone, chunk, embed, store.

Runs as a background task after POST /v1/repositories/{id}/index. The clone
is temporary and always cleaned up; the chunks land in Postgres and replace
whatever the previous indexing left. Failure marks the repository
index_failed instead of crashing the API.
"""

import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import delete

from engine.db.models import CodeChunk, CodeEdge, Repository
from engine.db.session import session_scope
from engine.indexing.chunker import chunk_repository
from engine.indexing.dependency_graph import build_dependency_graph
from engine.llm.router import model_router
from engine.workspace.manager import remove_tree, run_git

log = structlog.get_logger(__name__)

EMBED_BATCH = 64


async def index_repository(repository_id: uuid.UUID) -> None:
    """Background entrypoint: (re)build one repository's index."""
    async with session_scope() as session:
        repo = await session.get(Repository, repository_id)
        if repo is None:
            return
        url = repo.url

    try:
        count = await _build_index(repository_id, url)
    except Exception as exc:
        log.exception("index.failed", repository_id=str(repository_id))
        async with session_scope() as session:
            repo = await session.get(Repository, repository_id)
            if repo is not None:
                repo.status = "index_failed"
                await session.commit()
        raise exc from None

    async with session_scope() as session:
        repo = await session.get(Repository, repository_id)
        if repo is not None:
            repo.status = "indexed"
            repo.last_indexed_at = datetime.now(UTC)
            await session.commit()
    log.info("index.completed", repository_id=str(repository_id), chunks=count)


async def _build_index(repository_id: uuid.UUID, url: str) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="asep-index-"))
    try:
        clone = tmp / "clone"
        await run_git(tmp, "clone", "--depth", "1", url, str(clone))
        chunks = chunk_repository(clone)
        edges = build_dependency_graph(clone)
    finally:
        remove_tree(tmp)

    vectors: list[list[float]] = []
    for offset in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[offset : offset + EMBED_BATCH]
        vectors.extend(await model_router.embed([chunk.content for chunk in batch]))

    async with session_scope() as session:
        await session.execute(delete(CodeChunk).where(CodeChunk.repository_id == repository_id))
        await session.execute(delete(CodeEdge).where(CodeEdge.repository_id == repository_id))
        session.add_all(
            CodeChunk(
                repository_id=repository_id,
                path=chunk.path,
                language=chunk.language,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=chunk.content,
                embedding=vector,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        )
        session.add_all(
            CodeEdge(
                repository_id=repository_id,
                source_path=edge.source,
                target_path=edge.target,
                kind=edge.kind,
            )
            for edge in edges
        )
        await session.commit()
    return len(chunks)
