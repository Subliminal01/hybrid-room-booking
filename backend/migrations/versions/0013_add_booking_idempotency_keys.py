"""add booking idempotency keys

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-29 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "booking_idempotency_keys",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("booking_group_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", name="uq_booking_idempotency_user_key"),
    )
    op.create_index(
        "ix_booking_idempotency_booking_group_id",
        "booking_idempotency_keys",
        ["booking_group_id"],
    )
    op.create_index("ix_booking_idempotency_id", "booking_idempotency_keys", ["id"])
    op.create_index("ix_booking_idempotency_user_id", "booking_idempotency_keys", ["user_id"])
    op.create_index(
        "ix_booking_idempotency_user_key",
        "booking_idempotency_keys",
        ["user_id", "key"],
    )


def downgrade() -> None:
    op.drop_index("ix_booking_idempotency_user_key", table_name="booking_idempotency_keys")
    op.drop_index("ix_booking_idempotency_user_id", table_name="booking_idempotency_keys")
    op.drop_index("ix_booking_idempotency_id", table_name="booking_idempotency_keys")
    op.drop_index(
        "ix_booking_idempotency_booking_group_id",
        table_name="booking_idempotency_keys",
    )
    op.drop_table("booking_idempotency_keys")
