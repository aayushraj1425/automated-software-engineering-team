"""code_chunks HNSW index for approximate-nearest-neighbor search (Phase 2)

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-08

An HNSW index over the embedding column keeps cosine-distance vector search fast
as repositories outgrow an exact scan. Retrieval already orders by `<=>`, so it
uses this index automatically. Design note:
docs/architecture/INCREMENTAL_INDEXING.md.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_code_chunks_embedding_hnsw "
        "ON code_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_hnsw")
