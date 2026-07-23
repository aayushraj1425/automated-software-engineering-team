"""Builds a repository's search index: clone, chunk, embed, store.

Runs as a background task after POST /v1/repositories/{id}/index. The clone is
temporary and always cleaned up. Re-indexing is incremental: a per-file content
fingerprint (`indexed_files`) lets us re-embed only the files whose bytes
changed and drop the chunks of files that vanished, leaving unchanged files
untouched. The first index of a repository fingerprints nothing yet, so every
file counts as new — a full build. Import edges are cheap to recompute, so the
dependency graph is rebuilt in full each time. Failure marks the repository
index_failed instead of crashing the API.

Design note: docs/architecture/INCREMENTAL_INDEXING.md.
"""

import hashlib
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.models import CodeChunk, CodeEdge, IndexedFile, Repository
from engine.db.session import session_scope
from engine.indexing.chunker import Chunk, chunk_file, iter_source_files
from engine.indexing.dependency_graph import build_dependency_graph
from engine.llm.router import model_router
from engine.workspace.manager import ensure_cloneable_url, remove_tree, run_git

log = structlog.get_logger(__name__)

EMBED_BATCH = 64


@dataclass
class IndexResult:
    files: int  # total source files in the repository after this index
    changed: int  # files re-embedded (new or modified)
    deleted: int  # files removed since the last index
    chunks_written: int  # chunks embedded and inserted this run


async def index_repository(repository_id: uuid.UUID) -> None:
    """Background entrypoint: (re)build one repository's index."""
    async with session_scope() as session:
        repo = await session.get(Repository, repository_id)
        if repo is None:
            return
        url = repo.url

    try:
        result = await _build_index(repository_id, url)
    except Exception as exc:
        log.exception("index.failed", repository_id=str(repository_id))
        async with session_scope() as session:
            repo = await session.get(Repository, repository_id)
            if repo is not None:
                repo.status = "index_failed"
                # A short reason the user can act on (bad URL, private repo, …).
                repo.status_detail = str(exc)[:500] or type(exc).__name__
                await session.commit()
        raise exc from None

    async with session_scope() as session:
        repo = await session.get(Repository, repository_id)
        if repo is not None:
            repo.status = "indexed"
            repo.status_detail = None  # a good index clears any prior failure reason
            repo.last_indexed_at = datetime.now(UTC)
            await session.commit()
    log.info(
        "index.completed",
        repository_id=str(repository_id),
        files=result.files,
        changed=result.changed,
        deleted=result.deleted,
        chunks_written=result.chunks_written,
    )


async def _build_index(repository_id: uuid.UUID, url: str) -> IndexResult:
    tmp = Path(tempfile.mkdtemp(prefix="asep-index-"))
    try:
        clone = tmp / "clone"
        await run_git(tmp, "clone", "--depth", "1", "--", ensure_cloneable_url(url), str(clone))

        sources = list(iter_source_files(clone))
        current_hashes = {rel_path: _digest(file) for file, rel_path, _ in sources}

        async with session_scope() as session:
            previous_hashes = await _load_fingerprints(session, repository_id)

        changed = {
            rel for rel, digest in current_hashes.items() if previous_hashes.get(rel) != digest
        }
        deleted = set(previous_hashes) - set(current_hashes)

        # Chunk only the changed files, while the clone is still on disk.
        new_chunks: list[Chunk] = [
            chunk
            for file, rel_path, language in sources
            if rel_path in changed
            for chunk in chunk_file(file, rel_path, language)
        ]
        edges = build_dependency_graph(clone)
    finally:
        remove_tree(tmp)

    vectors = await _embed([chunk.content for chunk in new_chunks])

    stale = changed | deleted
    async with session_scope() as session:
        if stale:
            await session.execute(
                delete(CodeChunk).where(
                    CodeChunk.repository_id == repository_id, CodeChunk.path.in_(stale)
                )
            )
        # Edges are recomputed from the whole tree every time (cheap, always correct).
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
            for chunk, vector in zip(new_chunks, vectors, strict=True)
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
        await _apply_fingerprints(session, repository_id, changed, deleted, current_hashes)
        await session.commit()

    return IndexResult(
        files=len(current_hashes),
        changed=len(changed),
        deleted=len(deleted),
        chunks_written=len(new_chunks),
    )


async def _embed(contents: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for offset in range(0, len(contents), EMBED_BATCH):
        vectors.extend(await model_router.embed(contents[offset : offset + EMBED_BATCH]))
    return vectors


def _digest(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


async def _load_fingerprints(session: AsyncSession, repository_id: uuid.UUID) -> dict[str, str]:
    rows = (
        await session.execute(
            select(IndexedFile.path, IndexedFile.content_hash).where(
                IndexedFile.repository_id == repository_id
            )
        )
    ).all()
    return {path: content_hash for path, content_hash in rows}


async def _apply_fingerprints(
    session: AsyncSession,
    repository_id: uuid.UUID,
    changed: set[str],
    deleted: set[str],
    current_hashes: dict[str, str],
) -> None:
    stale = changed | deleted
    if stale:
        await session.execute(
            delete(IndexedFile).where(
                IndexedFile.repository_id == repository_id, IndexedFile.path.in_(stale)
            )
        )
    session.add_all(
        IndexedFile(repository_id=repository_id, path=rel, content_hash=current_hashes[rel])
        for rel in changed
    )
