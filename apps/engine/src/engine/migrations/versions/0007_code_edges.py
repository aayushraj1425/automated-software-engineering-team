"""code_edges: the repository import graph (Phase 2 — Repository Intelligence)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-08

One row per first-party import (source file imports target file within the same
repository). Rebuilt on every re-index, like code_chunks. Design note:
docs/architecture/DEPENDENCY_GRAPH.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "code_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_path", sa.String(512), nullable=False),
        sa.Column("target_path", sa.String(512), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="import"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_code_edges_repository_id", "code_edges", ["repository_id"])


def downgrade() -> None:
    op.drop_index("ix_code_edges_repository_id", table_name="code_edges")
    op.drop_table("code_edges")
