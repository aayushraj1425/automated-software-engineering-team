"""work_items: external issue link (Phase 6 — issue-tracker push)

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-13

Two nullable columns on work_items recording the external issue a work item was
pushed to (Linear first): the URL and the human key (e.g. "ENG-42"). Design
note: docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("work_items", sa.Column("external_issue_url", sa.String(512), nullable=True))
    op.add_column("work_items", sa.Column("external_issue_key", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("work_items", "external_issue_key")
    op.drop_column("work_items", "external_issue_url")
