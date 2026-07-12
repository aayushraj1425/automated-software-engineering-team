"""integration_connections: encrypted per-user links to external services (Phase 6)

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-12

One row per (user, kind). The secret config is AES-GCM ciphertext of a small
JSON blob (for Slack, the incoming-webhook URL); only that ciphertext and a
non-secret label are stored. Mirrors provider_keys. Design note:
docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="slack"),
        sa.Column("encrypted_config", sa.Text(), nullable=False),
        sa.Column("label", sa.String(256), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "kind", name="uq_integration_connections_user"),
    )
    op.create_index("ix_integration_connections_user_id", "integration_connections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_integration_connections_user_id", table_name="integration_connections")
    op.drop_table("integration_connections")
