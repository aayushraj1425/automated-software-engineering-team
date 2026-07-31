"""Row-level security reaches audit_logs.

audit_logs — the general actor/action log (a chat message, and now every agent
tool call — AUDIT_LOG.md) — was the one ownership-carrying table still without a
policy: any role with a table grant could read every actor's rows. It now gets
the standard owner-or-service policy on ``actor_id``, so a session sees only its
own audit rows and Postgres refuses the rest. This closes the last FORCE-RLS
exception; owner-only (audit is personal, never org-shared).

Frozen copy of the statements in ``engine/db/rls.py`` (the living source of
truth, which the test suite applies).
Design note: docs/architecture/ROW_LEVEL_SECURITY.md, docs/architecture/AUDIT_LOG.md.

Revision ID: 0024
Revises: 0023
"""

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels = None
depends_on = None

# Post-0022 service context: the flag alone is not enough — the session must
# *be* the owner role, which a user-pinned asep_api session never is.
_PREDICATE = """
                (current_setting('app.service', true) = '1' AND current_user = 'asep')
                OR actor_id = current_setting('app.user_id', true)"""


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS audit_logs_owner_rows ON audit_logs")
    op.execute(
        f"""
        CREATE POLICY audit_logs_owner_rows ON audit_logs FOR ALL
        USING ({_PREDICATE}
        )
        WITH CHECK ({_PREDICATE}
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS audit_logs_owner_rows ON audit_logs")
    op.execute("ALTER TABLE audit_logs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY")
