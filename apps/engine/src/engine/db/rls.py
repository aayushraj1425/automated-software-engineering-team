"""Row-level security: Postgres itself refuses to leak another user's rows.

Deny by default: a session sees a row only when it asserts a context — the
transaction-local ``app.user_id`` matching the owner column (API sessions),
or the explicit ``app.service`` flag the internal entry point sets (the
runner, webhooks, workers, migrations — everything that goes through
``session_scope()`` without a user). A session that asserts *nothing* — a
forgotten pin, a connection outside the helpers — reads and writes zero
rows instead of everything. ``FORCE`` matters: the engine connects as the
table owner, and owners bypass RLS without it.

Child tables (messages, agent tasks/events, code chunks, work items…) carry
no ownership column; their policy is "visible exactly when the parent row
is" — an EXISTS subquery that runs under the parent's own policy, so the
owner/org logic is written once.

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

# Privilege separation: the owner role (the runner, workers, migrations —
# everything internal) and the non-owner role user-pinned API sessions
# connect as when DATABASE_URL_API is set. The service clause below requires
# *being* the service role, so the API role gains nothing by setting the
# app.service GUC — and as a non-owner it cannot drop or disable a policy.
SERVICE_ROLE = "asep"
API_ROLE = "asep_api"

_SERVICE_CONTEXT = (
    f"(current_setting('app.service', true) = '1' AND current_user = '{SERVICE_ROLE}')"
)

# Table → the column naming the owning better-auth user.
USER_OWNED_TABLES: dict[str, str] = {
    "repositories": "owner_id",
    "conversations": "user_id",
    "agent_runs": "user_id",
    "provider_keys": "user_id",
    "integration_connections": "user_id",
}

# Child table → (parent table, foreign-key column). A child row is visible
# exactly when its parent row is: the EXISTS subquery consults the *parent's*
# policy, so the owner/org logic lives in one place and can never drift.
# (audit_logs stays out: no owning parent, written by the service only.)
CHILD_TABLES: dict[str, tuple[str, str]] = {
    "messages": ("conversations", "conversation_id"),
    "agent_tasks": ("agent_runs", "run_id"),
    "agent_events": ("agent_runs", "run_id"),
    "artifacts": ("agent_runs", "run_id"),
    "code_chunks": ("repositories", "repository_id"),
    "code_edges": ("repositories", "repository_id"),
    "indexed_files": ("repositories", "repository_id"),
    "work_items": ("repositories", "repository_id"),
    "knowledge_items": ("repositories", "repository_id"),
    "generated_documents": ("repositories", "repository_id"),
}

# The subset whose rows the active organization shares. Every table here
# carries a nullable ``org_id`` column. For provider keys the org clause
# opens *explicitly shared* keys only — personal keys have org_id NULL and
# stay behind the owner clause (PROVIDER_KEYS.md).
ORG_SHARED_TABLES: frozenset[str] = frozenset({"repositories", "agent_runs", "provider_keys"})


def _policy_predicate(table: str, owner_column: str) -> str:
    """Visible when: explicit service context (flag AND role), owner, or
    (shared tables) the active org. No context sees nothing."""
    predicate = f"""
                {_SERVICE_CONTEXT}
                OR {owner_column} = current_setting('app.user_id', true)"""
    if table in ORG_SHARED_TABLES:
        predicate += """
                OR (
                    org_id IS NOT NULL
                    AND org_id = NULLIF(current_setting('app.org_id', true), '')
                )"""
    return predicate


def _child_predicate(parent: str, fk_column: str) -> str:
    """Visible when: explicit service context, or the parent row is visible
    to this session (the subquery runs under the parent's own policy)."""
    return f"""
                {_SERVICE_CONTEXT}
                OR EXISTS (
                    SELECT 1 FROM {parent} parent WHERE parent.id = {fk_column}
                )"""


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
    for table, (parent, fk_column) in CHILD_TABLES.items():
        predicate = _child_predicate(parent, fk_column)
        statements += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {table}_via_parent ON {table}",
            f"""
            CREATE POLICY {table}_via_parent ON {table} FOR ALL
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
    for table in CHILD_TABLES:
        statements += [
            f"DROP POLICY IF EXISTS {table}_via_parent ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ]
    return statements


def api_role_grants() -> list[str]:
    """DML-only grants for the API role, runnable by the owner. No DDL, no
    ownership — the API role cannot drop a policy or disable RLS, and the
    role check in the service clause makes the GUC worthless to it. Grants
    are skipped quietly when the role does not exist (single-role mode)."""
    grants = [
        f"GRANT USAGE ON SCHEMA public TO {API_ROLE}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {API_ROLE}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {API_ROLE}",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {API_ROLE}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {API_ROLE}",
    ]
    body = "\n".join(f"        EXECUTE '{grant}';" for grant in grants)
    return [
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{API_ROLE}') THEN
{body}
            END IF;
        END $$
        """
    ]


async def apply_row_level_security(conn: AsyncConnection) -> None:
    """Apply the policies (and API-role grants) over an open connection
    (tests, tooling)."""
    for statement in rls_statements() + api_role_grants():
        await conn.exec_driver_sql(statement)
