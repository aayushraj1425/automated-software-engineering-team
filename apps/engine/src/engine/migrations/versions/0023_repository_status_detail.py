"""Surface the indexing-failure reason: repositories.status_detail.

When indexing failed the status became 'index_failed', but the reason lived only
in the engine logs — the user saw a failure with no explanation. A nullable
status_detail column carries a short human reason, set on failure and cleared on
a successful index.
Design note: docs/architecture/INDEXING_ERROR_SURFACING.md.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("repositories", sa.Column("status_detail", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("repositories", "status_detail")
