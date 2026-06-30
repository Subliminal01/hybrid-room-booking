"""add workspace availability rules

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-23 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_availability_rules",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.CheckConstraint(
            "day_of_week >= 0 AND day_of_week <= 6",
            name="ck_availability_day_range",
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_availability_time_order"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "day_of_week",
            "start_time",
            "end_time",
            name="uq_availability_workspace_day_time",
        ),
    )
    op.create_index(
        "ix_availability_workspace_day",
        "workspace_availability_rules",
        ["workspace_id", "day_of_week"],
    )
    op.create_index(
        "ix_workspace_availability_rules_id",
        "workspace_availability_rules",
        ["id"],
    )
    op.create_index(
        "ix_workspace_availability_rules_workspace_id",
        "workspace_availability_rules",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_availability_rules_workspace_id",
        table_name="workspace_availability_rules",
    )
    op.drop_index("ix_workspace_availability_rules_id", table_name="workspace_availability_rules")
    op.drop_index("ix_availability_workspace_day", table_name="workspace_availability_rules")
    op.drop_table("workspace_availability_rules")
