"""Adaptive teams, preview approval checkpoints, and organization model policy.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, default in (("team", "[]"), ("model_overrides", "{}"), ("stages_completed", "[]")):
        op.add_column(
            "agent_runs",
            sa.Column(name, postgresql.JSONB(), nullable=False, server_default=default),
        )
    for name in ("preview_options", "preview_deployment"):
        op.add_column("agent_runs", sa.Column(name, postgresql.JSONB(), nullable=True))
    op.add_column("agent_runs", sa.Column("design_note", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("preview_requested", sa.Boolean(), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column(
            "deployment_status", sa.String(32), nullable=False, server_default="not_requested"
        ),
    )
    op.add_column("agent_runs", sa.Column("deployment_approved_at", sa.DateTime(timezone=True)))
    op.add_column("agent_runs", sa.Column("deployment_approved_by", sa.String(64)))
    op.add_column("agent_runs", sa.Column("deployment_approved_sha", sa.String(64)))
    op.add_column(
        "agent_tasks", sa.Column("level", sa.String(16), nullable=False, server_default="engineer")
    )
    op.add_column("agent_tasks", sa.Column("model", sa.String(256), nullable=True))

    def timestamps():
        return [
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ]

    op.create_table(
        "organization_model_policies",
        sa.Column("org_id", sa.String(64), primary_key=True),
        sa.Column("level_pins", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "allow_open_source_auto", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        *timestamps(),
    )
    op.create_table(
        "preview_credentials",
        sa.Column("org_id", sa.String(64), primary_key=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("encrypted_credentials", sa.Text(), nullable=False),
        *timestamps(),
    )
    for table in ("organization_model_policies", "preview_credentials"):
        predicate = (
            "(current_setting('app.service', true) = '1' AND current_user = 'asep') "
            "OR org_id = NULLIF(current_setting('app.org_id', true), '')"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_org_rows ON {table} FOR ALL "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
        op.execute(f"""DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'asep_api') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO asep_api;
            END IF;
        END $$""")


def downgrade() -> None:
    op.drop_table("preview_credentials")
    op.drop_table("organization_model_policies")
    for name in ("model", "level"):
        op.drop_column("agent_tasks", name)
    for name in (
        "deployment_approved_sha",
        "deployment_approved_by",
        "deployment_approved_at",
        "deployment_status",
        "preview_requested",
        "design_note",
        "preview_deployment",
        "preview_options",
        "stages_completed",
        "model_overrides",
        "team",
    ):
        op.drop_column("agent_runs", name)
