"""Row-level security: Postgres itself refuses to leak another user's rows.

Deny by default: a session sees a row only when it asserts a context — the
transaction-local ``app.user_id`` matching the owner column (API sessions),
or the explicit ``app.service`` flag the internal entry point sets (the
runner, webhooks, workers, migrations — everything that goes through
``session_scope()`` without a user). A session that asserts *nothing* — a
forgotten pin, a connection outside the helpers — reads and writes zero
rows instead of everything. ``FORCE`` matters: the engine connects as the
table owner, and owners bypass RLS without it.

Org-shared tables (repositories, agent_runs) additionally open a row to
sessions whose ``app.org_id`` — the JWT's membership-checked active
organization — matches the row's ``org_id``, for reads and writes alike:
organization members are equal collaborators
(docs/architecture/ORGANIZATION_SHARING.md). Conversations, provider keys,
and integrations stay strictly owner-only.

This module is the single source of truth for the policy SQL. The Alembic
migrations freeze copies in time; the test suite applies this living version
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

# The subset whose rows the active organization shares. Every table here
# carries a nullable ``org_id`` column stamped at creation time.
ORG_SHARED_TABLES: frozenset[str] = frozenset({"repositories", "agent_runs"})


def _policy_predicate(table: str, owner_column: str) -> str:
    """Visible when: explicit service context, owner, or (shared tables) the
    active org. No context at all sees nothing — deny by default."""
    predicate = f"""
                current_setting('app.service', true) = '1'
                OR {owner_column} = current_setting('app.user_id', true)"""
    if table in ORG_SHARED_TABLES:
        predicate += """
                OR (
                    org_id IS NOT NULL
                    AND org_id = NULLIF(current_setting('app.org_id', true), '')
                )"""
    return predicate


def rls_statements() -> list[str]:
    """The DDL applying every policy. Idempotent: safe to run twice."""
    statements: list[str] = []
    for table, owner_column in USER_OWNED_TABLES.items():
        predicate = _policy_predicate(table, owner_column)
        statements += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {table}_owner_rows ON {table}",
            # app.service='1' = the explicit internal context; app.user_id =
            # the owner's rows plus the active organization's shared rows,
            # for reads and writes alike. Neither set = zero rows.
            f"""
            CREATE POLICY {table}_owner_rows ON {table} FOR ALL
            USING ({predicate}
            )
            WITH CHECK ({predicate}
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
