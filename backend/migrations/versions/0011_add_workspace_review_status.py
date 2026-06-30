"""add workspace review status

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-24 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("review_status", sa.String(length=8), nullable=False, server_default="pending"),
    )
    op.create_index("ix_workspaces_review_status", "workspaces", ["review_status"])
    op.alter_column("workspaces", "review_status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_workspaces_review_status", table_name="workspaces")
    op.drop_column("workspaces", "review_status")
