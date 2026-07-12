"""provider_keys: encrypted bring-your-own LLM keys (Identity & Keys)

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-12

One row per (user, provider). Only AES-GCM ciphertext and the last four
characters are stored — never the plaintext key. Design note:
docs/architecture/PROVIDER_KEYS.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("last4", sa.String(8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "provider", name="uq_provider_keys_user"),
    )
    op.create_index("ix_provider_keys_user_id", "provider_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_provider_keys_user_id", table_name="provider_keys")
    op.drop_table("provider_keys")
