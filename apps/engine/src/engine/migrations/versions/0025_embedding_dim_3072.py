"""Widen embedding columns from vector(768) to vector(3072)

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-04

gemini-embedding-001 produces 3072-dimensional vectors; the old default
(text-embedding-004) was 768. The HNSW index must be dropped before the
column type can change and recreated afterwards.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing vectors are from text-embedding-004 (768-dim) and are invalid
    # for the new model; clear them so the column type change can proceed.
    op.execute("TRUNCATE TABLE code_chunks CASCADE")
    op.execute("TRUNCATE TABLE knowledge_items CASCADE")
    # Both HNSW and IVFFlat cap at 2000 dims — no ANN index for 3072-dim vectors.
    # Similarity search falls back to an exact sequential scan, which is correct
    # and fast enough for typical dev repo sizes. Upgrade to halfvec in production.
    op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_hnsw")
    op.execute("ALTER TABLE code_chunks ALTER COLUMN embedding TYPE vector(3072)")
    op.execute("ALTER TABLE knowledge_items ALTER COLUMN embedding TYPE vector(3072)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_ivfflat")
    op.execute("TRUNCATE TABLE code_chunks CASCADE")
    op.execute("TRUNCATE TABLE knowledge_items CASCADE")
    op.execute("ALTER TABLE code_chunks ALTER COLUMN embedding TYPE vector(768)")
    op.execute("ALTER TABLE knowledge_items ALTER COLUMN embedding TYPE vector(768)")
    op.execute(
        "CREATE INDEX ix_code_chunks_embedding_hnsw "
        "ON code_chunks USING hnsw (embedding vector_cosine_ops)"
    )
