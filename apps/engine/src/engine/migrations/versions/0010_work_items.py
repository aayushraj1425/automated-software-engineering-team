"""work_items: durable, repository-scoped backlog items (Phase 4)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-10

One row per planned unit of work. Unlike agent_tasks (which live inside a single
run), a work item is planned once and persists — estimated, reordered, blocked,
and eventually linked to the run that implements it. Design note:
docs/architecture/PLANNING_SUITE.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="feature"),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("estimate", sa.String(16), nullable=True),
        sa.Column("priority", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("milestone", sa.String(128), nullable=True),
        sa.Column(
            "depends_on",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "implemented_by_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_work_items_repository_id", "work_items", ["repository_id"])
    op.create_index("ix_work_items_status", "work_items", ["status"])
    op.create_index("ix_work_items_priority", "work_items", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_work_items_priority", table_name="work_items")
    op.drop_index("ix_work_items_status", table_name="work_items")
    op.drop_index("ix_work_items_repository_id", table_name="work_items")
    op.drop_table("work_items")
