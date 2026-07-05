"""agent_runs.base_sha: the commit each run's workspace started from

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-05

A run's workspace is created while planning and used again after the human
approves the plan. The branch name was already stored; the base commit is
needed too so diffs (and later the pull request) measure against the exact
starting point.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("base_sha", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "base_sha")
