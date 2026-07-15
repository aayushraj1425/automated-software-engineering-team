"""Row-level security: Postgres itself refuses to leak another user's rows.

The policy on each ownership-carrying table makes a row visible and writable
only when the transaction-local ``app.user_id`` setting matches the owner
column — or when the setting is unset, the trusted internal context (the
runner, webhooks, migrations), which behaves exactly as before RLS existed.
``FORCE`` matters: the engine connects as the table owner, and owners bypass
RLS without it.

This module is the single source of truth for the policy SQL. The Alembic
migration freezes a copy in time; the test suite applies this living version
after creating the schema, so the entire suite runs under FORCE RLS.
Design note: docs/architecture/ROW_LEVEL_SECURITY.md.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

# Table → the column naming the owning better-auth user. Tables without a
# direct ownership column (messages, agent_tasks, code_chunks, work_items…)
# are guarded through their parents at the API layer — see the design note.
USER_OWNED_TABLES: dict[str, str] = {
    "repositories": "owner_id",
    "conversations": "user_id",
    "agent_runs": "user_id",
    "provider_keys": "user_id",
    "integration_connections": "user_id",
}


def rls_statements() -> list[str]:
    """The DDL applying every policy. Idempotent: safe to run twice."""
    statements: list[str] = []
    for table, owner_column in USER_OWNED_TABLES.items():
        statements += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {table}_owner_rows ON {table}",
            # Unset (NULL or empty) app.user_id = trusted internal context;
            # set = only the owner's rows, for reads and writes alike.
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
            """,
        ]
    return statements


def rls_teardown_statements() -> list[str]:
    """The mirror image, for the migration's downgrade."""
    statements: list[str] = []
    for table in USER_OWNED_TABLES:
        statements += [
            f"DROP POLICY IF EXISTS {table}_owner_rows ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ]
    return statements


async def apply_row_level_security(conn: AsyncConnection) -> None:
    """Apply the policies over an open connection (tests, tooling)."""
    for statement in rls_statements():
        await conn.exec_driver_sql(statement)
