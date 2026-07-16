"""Organization-aware sharing in the row-level-security policies.

Repositories and agent runs become visible — and writable — to sessions
whose ``app.org_id`` (the JWT's membership-checked active organization)
matches the row's ``org_id``, on top of the existing owner rule. The other
policy-carrying tables (conversations, provider keys, integrations) keep
their owner-only policies, re-stated here unchanged so this migration owns
the complete policy set.

This is a frozen copy of the statements in ``engine/db/rls.py`` (the living
source of truth, which the test suite applies).
Design note: docs/architecture/ORGANIZATION_SHARING.md.

Revision ID: 0017
Revises: 0016
"""

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
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


def _predicate(table: str, owner_column: str, with_org: bool) -> str:
    predicate = f"""
                NULLIF(current_setting('app.user_id', true), '') IS NULL
                OR {owner_column} = current_setting('app.user_id', true)"""
    if with_org and table in ORG_SHARED_TABLES:
        predicate += """
                OR (
                    org_id IS NOT NULL
                    AND org_id = NULLIF(current_setting('app.org_id', true), '')
                )"""
    return predicate


def _apply_policies(with_org: bool) -> None:
    for table, owner_column in USER_OWNED_TABLES.items():
        predicate = _predicate(table, owner_column, with_org)
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
    _apply_policies(with_org=True)


def downgrade() -> None:
    # Back to the owner-only policies exactly as revision 0016 wrote them.
    _apply_policies(with_org=False)
