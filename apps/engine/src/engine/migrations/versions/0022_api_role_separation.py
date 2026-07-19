"""Privilege separation: the service context requires being the service role.

The policies' service clause becomes `app.service='1' AND current_user =
'asep'`. User-pinned API sessions connect as the non-owner `asep_api` role
(DATABASE_URL_API), which gets DML-only grants here: it cannot drop or
disable a policy (not the owner, no DDL), and setting the app.service GUC
gains it nothing (wrong role). The role itself is created by the operator
(postgres-init / CI / the runbook line below) — a NOSUPERUSER login role
with no special attributes:

    CREATE ROLE asep_api LOGIN PASSWORD '…' NOSUPERUSER;

Grants are skipped quietly when the role does not exist (single-role mode
keeps working). This is a frozen copy of the statements in
``engine/db/rls.py`` (the living source of truth the test suite applies).
Design note: docs/architecture/ROW_LEVEL_SECURITY.md.

Revision ID: 0022
Revises: 0021
"""

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels = None
depends_on = None

USER_OWNED_TABLES: dict[str, str] = {
    "repositories": "owner_id",
    "conversations": "user_id",
    "agent_runs": "user_id",
    "provider_keys": "user_id",
    "integration_connections": "user_id",
}
ORG_SHARED_TABLES = frozenset({"repositories", "agent_runs", "provider_keys"})
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

_WITH_ROLE = "(current_setting('app.service', true) = '1' AND current_user = 'asep')"
_FLAG_ONLY = "current_setting('app.service', true) = '1'"

_GRANTS = [
    "GRANT USAGE ON SCHEMA public TO asep_api",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO asep_api",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO asep_api",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO asep_api",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO asep_api",
]


def _owner_predicate(table: str, owner_column: str, service: str) -> str:
    predicate = f"{service}\n        OR {owner_column} = current_setting('app.user_id', true)"
    if table in ORG_SHARED_TABLES:
        predicate += (
            "\n        OR (org_id IS NOT NULL"
            " AND org_id = NULLIF(current_setting('app.org_id', true), ''))"
        )
    return predicate


def _apply(service: str) -> None:
    for table, owner_column in USER_OWNED_TABLES.items():
        predicate = _owner_predicate(table, owner_column, service)
        op.execute(f"DROP POLICY IF EXISTS {table}_owner_rows ON {table}")
        op.execute(
            f"CREATE POLICY {table}_owner_rows ON {table} FOR ALL"
            f" USING ({predicate}) WITH CHECK ({predicate})"
        )
    for table, (parent, fk_column) in CHILD_TABLES.items():
        predicate = (
            f"{service}\n        OR EXISTS"
            f" (SELECT 1 FROM {parent} parent WHERE parent.id = {fk_column})"
        )
        op.execute(f"DROP POLICY IF EXISTS {table}_via_parent ON {table}")
        op.execute(
            f"CREATE POLICY {table}_via_parent ON {table} FOR ALL"
            f" USING ({predicate}) WITH CHECK ({predicate})"
        )


def upgrade() -> None:
    _apply(_WITH_ROLE)
    body = "\n".join(f"        EXECUTE '{grant}';" for grant in _GRANTS)
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'asep_api') THEN
{body}
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    # Back to the flag-only service clause (0021's world). The grants stay —
    # harmless without the policies honoring the role, and the role belongs
    # to the operator.
    _apply(_FLAG_ONLY)
