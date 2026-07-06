"""Shared retrieval: a question becomes a vector, the closest chunks answer.

Used by the repository search endpoint and by grounded chat
(design note: docs/architecture/GROUNDED_CHAT.md).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.models import CodeChunk
from engine.llm.router import model_router

RETRIEVAL_LIMIT = 8


@dataclass(frozen=True)
class RetrievedChunk:
    path: str
    language: str
    start_line: int
    end_line: int
    content: str
    score: float  # 1.0 = identical meaning, 0.0 = unrelated


async def retrieve_chunks(
    db: AsyncSession, repository_id: uuid.UUID, query: str, limit: int = RETRIEVAL_LIMIT
) -> list[RetrievedChunk]:
    """The `limit` chunks of the repository closest in meaning to the query."""
    (query_vector,) = await model_router.embed([query])
    distance = CodeChunk.embedding.cosine_distance(query_vector)
    rows = (
        (
            await db.execute(
                select(CodeChunk, distance.label("distance"))
                .where(CodeChunk.repository_id == repository_id)
                .order_by(distance)
                .limit(limit)
            )
        )
        .tuples()
        .all()
    )
    return [
        RetrievedChunk(
            path=chunk.path,
            language=chunk.language,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            content=chunk.content,
            score=round(max(0.0, 1.0 - float(dist)), 4),
        )
        for chunk, dist in rows
    ]
