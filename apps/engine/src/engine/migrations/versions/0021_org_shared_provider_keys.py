"""Provider keys can be shared with an organization — explicitly.

`provider_keys` gains a nullable `org_id`: NULL means personal (one per
user+provider, as before), set means shared with that organization (one per
org+provider) — partial unique indexes replace the old constraint. The
table's RLS policy gains the org clause, so Postgres itself shows a shared
key to whoever has that organization active and nobody else.
Frozen from ``engine/db/rls.py`` like every policy migration.
Design note: docs/architecture/PROVIDER_KEYS.md (organization-shared keys).

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels = None
depends_on = None

_POLICY_WITH_ORG = """
    CREATE POLICY provider_keys_owner_rows ON provider_keys FOR ALL
    USING (
        current_setting('app.service', true) = '1'
        OR user_id = current_setting('app.user_id', true)
        OR (
            org_id IS NOT NULL
            AND org_id = NULLIF(current_setting('app.org_id', true), '')
        )
    )
    WITH CHECK (
        current_setting('app.service', true) = '1'
        OR user_id = current_setting('app.user_id', true)
        OR (
            org_id IS NOT NULL
            AND org_id = NULLIF(current_setting('app.org_id', true), '')
        )
    )
"""

_POLICY_OWNER_ONLY = """
    CREATE POLICY provider_keys_owner_rows ON provider_keys FOR ALL
    USING (
        current_setting('app.service', true) = '1'
        OR user_id = current_setting('app.user_id', true)
    )
    WITH CHECK (
        current_setting('app.service', true) = '1'
        OR user_id = current_setting('app.user_id', true)
    )
"""


def upgrade() -> None:
    op.add_column("provider_keys", sa.Column("org_id", sa.String(64), nullable=True))
    op.create_index("ix_provider_keys_org_id", "provider_keys", ["org_id"])
    op.drop_constraint("uq_provider_keys_user", "provider_keys", type_="unique")
    op.create_index(
        "uq_provider_keys_user",
        "provider_keys",
        ["user_id", "provider"],
        unique=True,
        postgresql_where=sa.text("org_id IS NULL"),
    )
    op.create_index(
        "uq_provider_keys_org",
        "provider_keys",
        ["org_id", "provider"],
        unique=True,
        postgresql_where=sa.text("org_id IS NOT NULL"),
    )
    op.execute("DROP POLICY IF EXISTS provider_keys_owner_rows ON provider_keys")
    op.execute(_POLICY_WITH_ORG)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS provider_keys_owner_rows ON provider_keys")
    op.execute(_POLICY_OWNER_ONLY)
    op.execute("DELETE FROM provider_keys WHERE org_id IS NOT NULL")
    op.drop_index("uq_provider_keys_org", table_name="provider_keys")
    op.drop_index("uq_provider_keys_user", table_name="provider_keys")
    op.create_unique_constraint("uq_provider_keys_user", "provider_keys", ["user_id", "provider"])
    op.drop_index("ix_provider_keys_org_id", table_name="provider_keys")
    op.drop_column("provider_keys", "org_id")
