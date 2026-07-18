"""Row-level security reaches the child tables.

Messages, agent tasks/events, artifacts, code chunks/edges, indexed files,
work items, knowledge items, and generated documents carry no ownership
column — until now they were guarded only by the API checking their parent
first. Each now gets a policy of its own: visible exactly when the parent
row is visible to the session (an EXISTS subquery that runs under the
parent's policy, so the owner/org logic stays written once), or in the
explicit service context. The parent policies from revision 0018 are
untouched.

This is a frozen copy of the statements in ``engine/db/rls.py`` (the living
source of truth, which the test suite applies).
Design note: docs/architecture/ROW_LEVEL_SECURITY.md.

Revision ID: 0019
Revises: 0018
"""

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels = None
depends_on = None

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


def upgrade() -> None:
    for table, (parent, fk_column) in CHILD_TABLES.items():
        predicate = f"""
                current_setting('app.service', true) = '1'
                OR EXISTS (
                    SELECT 1 FROM {parent} parent WHERE parent.id = {fk_column}
                )"""
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_via_parent ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_via_parent ON {table} FOR ALL
            USING ({predicate}
            )
            WITH CHECK ({predicate}
            )
            """
        )


def downgrade() -> None:
    for table in CHILD_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_via_parent ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
