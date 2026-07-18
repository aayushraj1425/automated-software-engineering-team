"""Deny by default: a session with no context reads and writes zero rows.

Until now an *unset* ``app.user_id`` was the trusted internal context — a
forgotten pin (or any connection outside the engine's session helpers) saw
everything. The policies now require an explicit assertion: the internal
entry point sets ``app.service='1'``, API sessions pin ``app.user_id`` (and
``app.org_id``), and a session that asserts neither is denied. The alembic
connection itself asserts the service context (migrations/env.py), so data
migrations keep working.

This is a frozen copy of the statements in ``engine/db/rls.py`` (the living
source of truth, which the test suite applies).
Design note: docs/architecture/ROW_LEVEL_SECURITY.md.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels = None
depends_on = None

USER_OWNED_TABLES: dict[str, str] = {
    "repositories": "owner_id",
    "conversations": "user_id",
    "agent_runs": "user_id",
    "provider_keys": "user_id",
    "integration_connections": "user_id",
}

ORG_SHARED_TABLES: frozenset[str] = frozenset({"repositories", "agent_runs"})


def _predicate(table: str, owner_column: str, deny_by_default: bool) -> str:
    context_clause = (
        "current_setting('app.service', true) = '1'"
        if deny_by_default
        else "NULLIF(current_setting('app.user_id', true), '') IS NULL"
    )
    predicate = f"""
                {context_clause}
                OR {owner_column} = current_setting('app.user_id', true)"""
    if table in ORG_SHARED_TABLES:
        predicate += """
                OR (
                    org_id IS NOT NULL
                    AND org_id = NULLIF(current_setting('app.org_id', true), '')
                )"""
    return predicate


def _apply_policies(deny_by_default: bool) -> None:
    for table, owner_column in USER_OWNED_TABLES.items():
        predicate = _predicate(table, owner_column, deny_by_default)
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_owner_rows ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_owner_rows ON {table} FOR ALL
            USING ({predicate}
            )
            WITH CHECK ({predicate}
            )
            """
        )


def upgrade() -> None:
    _apply_policies(deny_by_default=True)


def downgrade() -> None:
    # Back to unset-context-is-trusted, exactly as revision 0017 wrote it.
    _apply_policies(deny_by_default=False)
