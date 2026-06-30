"""add workspace blackout dates

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-23 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_blackout_dates",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blackout_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=160), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "blackout_date", name="uq_blackout_workspace_date"),
    )
    op.create_index(
        "ix_blackout_workspace_date",
        "workspace_blackout_dates",
        ["workspace_id", "blackout_date"],
    )
    op.create_index("ix_workspace_blackout_dates_id", "workspace_blackout_dates", ["id"])
    op.create_index(
        "ix_workspace_blackout_dates_workspace_id",
        "workspace_blackout_dates",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_blackout_dates_workspace_id",
        table_name="workspace_blackout_dates",
    )
    op.drop_index("ix_workspace_blackout_dates_id", table_name="workspace_blackout_dates")
    op.drop_index("ix_blackout_workspace_date", table_name="workspace_blackout_dates")
    op.drop_table("workspace_blackout_dates")
