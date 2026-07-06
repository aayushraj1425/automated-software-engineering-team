"""messages.citations: the sources behind a grounded chat answer

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06

Grounded chat answers questions about a connected repository from retrieved
code excerpts. The excerpts' locations (path, start/end line, score) are kept
on the assistant message so reopening a conversation shows its sources again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("citations", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "citations")
