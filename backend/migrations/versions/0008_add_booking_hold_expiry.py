"""add booking hold expiry

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-23 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_bookings_status_expires", "bookings", ["status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_bookings_status_expires", table_name="bookings")
    op.drop_column("bookings", "expires_at")
