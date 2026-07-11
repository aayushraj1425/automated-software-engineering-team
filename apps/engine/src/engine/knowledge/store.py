"""The memory write path: embed one knowledge item and store it.

Everything that remembers — the runner's automatic capture, the rejection
gate, the knowledge API — goes through `remember()`, so every memory gets an
embedding and the same length caps. Design note:
docs/architecture/KNOWLEDGE_AND_MEMORY.md.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.enums import KnowledgeKind
from engine.db.models import KnowledgeItem
from engine.llm.router import model_router

# One memory is a summary, not an archive — cap what a single row can hold.
MAX_TITLE = 256
MAX_CONTENT = 4000


async def remember(
    db: AsyncSession,
    repository_id: uuid.UUID,
    kind: KnowledgeKind | str,
    title: str,
    content: str,
    source_run_id: uuid.UUID | None = None,
    created_by: str | None = None,
) -> KnowledgeItem:
    """Embed and store one memory. The caller commits."""
    title = title.strip()[:MAX_TITLE]
    content = content.strip()[:MAX_CONTENT]
    (embedding,) = await model_router.embed([f"{title}\n{content}"])
    item = KnowledgeItem(
        repository_id=repository_id,
        kind=str(kind),
        title=title,
        content=content,
        source_run_id=source_run_id,
        created_by=created_by,
        embedding=embedding,
    )
    db.add(item)
    return item
