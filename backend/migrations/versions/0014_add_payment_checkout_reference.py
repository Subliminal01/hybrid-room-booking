"""add payment checkout reference

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("provider_checkout_reference", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_payments_provider_checkout_reference",
        "payments",
        ["provider_checkout_reference"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payments_provider_checkout_reference", table_name="payments")
    op.drop_column("payments", "provider_checkout_reference")
