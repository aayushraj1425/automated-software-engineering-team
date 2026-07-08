"""indexed_files: content fingerprints for incremental re-indexing (Phase 2)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-08

One row per source file with a SHA-256 of its bytes from the last index, so a
re-index re-embeds only the files that changed. Design note:
docs/architecture/INCREMENTAL_INDEXING.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "indexed_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("repository_id", "path", name="uq_indexed_files_repo_path"),
    )
    op.create_index("ix_indexed_files_repository_id", "indexed_files", ["repository_id"])


def downgrade() -> None:
    op.drop_index("ix_indexed_files_repository_id", table_name="indexed_files")
    op.drop_table("indexed_files")
