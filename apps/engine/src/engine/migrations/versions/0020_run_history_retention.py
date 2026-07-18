"""Run history outlives its repository: the FK cascade becomes SET NULL.

Deleting a repository used to erase every run made on it — timelines, task
boards, audit events, costs. Runs are the platform's audit record; the
repository FK becomes nullable with ON DELETE SET NULL, so disconnecting a
repository detaches its runs instead of destroying them.
Design note: docs/architecture/RUN_HISTORY_RETENTION.md.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels = None
depends_on = None

_FK = "agent_runs_repository_id_fkey"


def upgrade() -> None:
    op.alter_column("agent_runs", "repository_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint(_FK, "agent_runs", type_="foreignkey")
    op.create_foreign_key(
        _FK, "agent_runs", "repositories", ["repository_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    # Detached runs cannot survive a NOT NULL cascade FK — they are removed,
    # which is exactly the data loss the upgrade exists to prevent.
    op.execute("DELETE FROM agent_runs WHERE repository_id IS NULL")
    op.drop_constraint(_FK, "agent_runs", type_="foreignkey")
    op.create_foreign_key(
        _FK, "agent_runs", "repositories", ["repository_id"], ["id"], ondelete="CASCADE"
    )
    op.alter_column("agent_runs", "repository_id", existing_type=sa.UUID(), nullable=False)
