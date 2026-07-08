"""code_chunks full-text column for hybrid retrieval (Phase 2)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-07

Adds a generated `content_tsv` column (Postgres keeps it in sync with
`content`) and a GIN index, powering the full-text arm of hybrid retrieval.
Design note: docs/architecture/HYBRID_RETRIEVAL.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "code_chunks",
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_code_chunks_content_tsv",
        "code_chunks",
        ["content_tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_code_chunks_content_tsv", table_name="code_chunks")
    op.drop_column("code_chunks", "content_tsv")
