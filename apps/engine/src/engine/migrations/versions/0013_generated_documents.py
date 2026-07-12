"""generated_documents: human-facing docs from the index (Phase 6)

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-12

One row per generated document — a README, API reference, changelog, or
architecture overview written by the Technical Writer from the repository
index. Repository-scoped and durable; a snapshot kept until deleted. Design
note: docs/architecture/DOCUMENTATION_SUITE.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generated_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False, server_default="readme"),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_generated_documents_repository_id", "generated_documents", ["repository_id"]
    )
    op.create_index("ix_generated_documents_kind", "generated_documents", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_generated_documents_kind", table_name="generated_documents")
    op.drop_index("ix_generated_documents_repository_id", table_name="generated_documents")
    op.drop_table("generated_documents")
