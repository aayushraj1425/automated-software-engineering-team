"""knowledge_items: durable, repository-scoped memory (Phase 5)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-11

One row per memory — a decision, a run outcome, a team preference, or a note —
with a pgvector embedding and a generated full-text column so recall can use
the same hybrid retrieval as the code index. The optional source-run link is
the first edge of the knowledge graph; the memory outlives the run (SET NULL).
Design note: docs/architecture/KNOWLEDGE_AND_MEMORY.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from engine.config import EMBEDDING_DIM

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False, server_default="note"),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "source_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('english', title || ' ' || content)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_knowledge_items_repository_id", "knowledge_items", ["repository_id"])
    op.create_index("ix_knowledge_items_kind", "knowledge_items", ["kind"])
    op.create_index(
        "ix_knowledge_items_content_tsv",
        "knowledge_items",
        ["content_tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_items_content_tsv", table_name="knowledge_items")
    op.drop_index("ix_knowledge_items_kind", table_name="knowledge_items")
    op.drop_index("ix_knowledge_items_repository_id", table_name="knowledge_items")
    op.drop_table("knowledge_items")
