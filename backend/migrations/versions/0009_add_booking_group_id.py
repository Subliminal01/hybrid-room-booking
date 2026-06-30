"""add booking group id

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-23 00:00:00.000000
"""
from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("booking_group_id", postgresql.UUID(as_uuid=True), nullable=True))
    connection = op.get_bind()
    bookings = connection.execute(sa.text("SELECT id FROM bookings")).fetchall()
    for booking in bookings:
        connection.execute(
            sa.text("UPDATE bookings SET booking_group_id = :group_id WHERE id = :booking_id"),
            {"group_id": str(uuid4()), "booking_id": str(booking.id)},
        )
    op.alter_column("bookings", "booking_group_id", nullable=False)
    op.create_index("ix_bookings_booking_group_id", "bookings", ["booking_group_id"])
    op.create_index("ix_bookings_group_status", "bookings", ["booking_group_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_bookings_group_status", table_name="bookings")
    op.drop_index("ix_bookings_booking_group_id", table_name="bookings")
    op.drop_column("bookings", "booking_group_id")
