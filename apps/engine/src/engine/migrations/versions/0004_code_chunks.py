"""code_chunks: the repository search index (Phase 2 — Repository Intelligence)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-06

One row per indexed piece of a repository file, with a pgvector embedding for
similarity search. Design note: docs/architecture/REPOSITORY_INTELLIGENCE.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from engine.config import EMBEDDING_DIM

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "repositories",
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "code_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("end_line", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_code_chunks_repository_id", "code_chunks", ["repository_id"])


def downgrade() -> None:
    op.drop_index("ix_code_chunks_repository_id", table_name="code_chunks")
    op.drop_table("code_chunks")
    op.drop_column("repositories", "last_indexed_at")
