"""Persist run triage, Quick teams, and report-only test outcomes.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("complexity", sa.String(16), nullable=True))
    op.add_column("agent_runs", sa.Column("triage_reason", sa.Text(), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("team_template", sa.String(32), nullable=False, server_default="standard"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("test_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("agent_runs", sa.Column("test_report", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    for column in ("test_report", "test_only", "team_template", "triage_reason", "complexity"):
        op.drop_column("agent_runs", column)
