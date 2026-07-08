"""Shared retrieval: hybrid search over the code index.

Two arms find candidate chunks — a vector arm (embed the question, order by
cosine distance, finds meaning) and a full-text arm (Postgres `to_tsquery`,
finds exact words) — and reciprocal-rank fusion blends the two rankings so a
chunk either arm likes rises to the top. The displayed score stays the cosine
similarity; fusion only decides the order.

Used by the repository search endpoint, grounded chat, and the agents'
search_code tool. Design note: docs/architecture/HYBRID_RETRIEVAL.md.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.models import CodeChunk
from engine.llm.router import model_router

RETRIEVAL_LIMIT = 8
CANDIDATES = 30  # how many chunks each arm contributes before fusion
RRF_K = 60  # reciprocal-rank-fusion damping (the standard default)
TEXT_CONFIG = "english"  # Postgres full-text configuration

_WORD = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class RetrievedChunk:
    path: str
    language: str
    start_line: int
    end_line: int
    content: str
    score: float  # cosine similarity: 1.0 = identical meaning, 0.0 = unrelated


async def retrieve_chunks(
    db: AsyncSession, repository_id: uuid.UUID, query: str, limit: int = RETRIEVAL_LIMIT
) -> list[RetrievedChunk]:
    """The `limit` most relevant chunks of the repository for the query,
    ranked by fusing vector similarity and full-text matching."""
    (query_vector,) = await model_router.embed([query])
    vector_hits = await _vector_candidates(db, repository_id, query_vector)
    text_hits = await _text_candidates(db, repository_id, query, query_vector)
    return _fuse(vector_hits, text_hits, limit)


async def _vector_candidates(
    db: AsyncSession, repository_id: uuid.UUID, query_vector: list[float]
) -> list[Row]:
    """Chunks closest in meaning, best-first, each with its cosine distance."""
    distance = CodeChunk.embedding.cosine_distance(query_vector)
    result = await db.execute(
        select(CodeChunk, distance.label("distance"))
        .where(CodeChunk.repository_id == repository_id)
        .order_by(distance)
        .limit(CANDIDATES)
    )
    return list(result.all())


async def _text_candidates(
    db: AsyncSession, repository_id: uuid.UUID, query: str, query_vector: list[float]
) -> list[Row]:
    """Chunks whose text matches the question's words, ranked by ts_rank.

    The words are OR-ed together so any of them can match; each row still
    carries its cosine distance so a fused chunk always has a real similarity.
    """
    words = _WORD.findall(query.lower())
    if not words:
        return []
    tsquery = func.to_tsquery(TEXT_CONFIG, " | ".join(words))
    distance = CodeChunk.embedding.cosine_distance(query_vector)
    rank = func.ts_rank(CodeChunk.content_tsv, tsquery)
    result = await db.execute(
        select(CodeChunk, distance.label("distance"))
        .where(CodeChunk.repository_id == repository_id)
        .where(CodeChunk.content_tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(CANDIDATES)
    )
    return list(result.all())


def _fuse(vector_hits: list[Row], text_hits: list[Row], limit: int) -> list[RetrievedChunk]:
    """Reciprocal-rank fusion: a chunk's score sums 1/(k + rank) across arms."""
    fused: dict[uuid.UUID, float] = {}
    chunks: dict[uuid.UUID, CodeChunk] = {}
    distances: dict[uuid.UUID, float] = {}
    for arm in (vector_hits, text_hits):
        for position, row in enumerate(arm, start=1):
            chunk: CodeChunk = row[0]
            fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (RRF_K + position)
            chunks[chunk.id] = chunk
            distances[chunk.id] = float(row.distance)
    ranked = sorted(fused, key=lambda cid: (-fused[cid], distances[cid], str(cid)))[:limit]
    return [
        RetrievedChunk(
            path=chunks[cid].path,
            language=chunks[cid].language,
            start_line=chunks[cid].start_line,
            end_line=chunks[cid].end_line,
            content=chunks[cid].content,
            score=round(max(0.0, 1.0 - distances[cid]), 4),
        )
        for cid in ranked
    ]
