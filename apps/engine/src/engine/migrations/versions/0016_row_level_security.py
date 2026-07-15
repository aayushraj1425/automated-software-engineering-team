"""Row-level security on the ownership-carrying tables.

Postgres itself now refuses to hand a pinned session another user's rows —
defense in depth behind the API's owner-scoping (a forgotten WHERE clause can
no longer leak). Sessions that set no ``app.user_id`` (the runner, webhooks,
data migrations like this one) are the trusted internal context and behave
exactly as before. FORCE matters: the engine connects as the table owner, and
owners bypass RLS without it.

This is a frozen copy of the statements in ``engine/db/rls.py`` (the living
source of truth, which the test suite applies).
Design note: docs/architecture/ROW_LEVEL_SECURITY.md.

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None

USER_OWNED_TABLES: dict[str, str] = {
    "repositories": "owner_id",
    "conversations": "user_id",
    "agent_runs": "user_id",
    "provider_keys": "user_id",
    "integration_connections": "user_id",
}


def upgrade() -> None:
    for table, owner_column in USER_OWNED_TABLES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_owner_rows ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_owner_rows ON {table} FOR ALL
            USING (
                NULLIF(current_setting('app.user_id', true), '') IS NULL
                OR {owner_column} = current_setting('app.user_id', true)
            )
            WITH CHECK (
                NULLIF(current_setting('app.user_id', true), '') IS NULL
                OR {owner_column} = current_setting('app.user_id', true)
            )
            """
        )


def downgrade() -> None:
    for table in USER_OWNED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_owner_rows ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
