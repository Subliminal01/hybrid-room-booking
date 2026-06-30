"""add account tokens and email verification status

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-23 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "account_tokens",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum("email_verification", "password_reset", name="accounttokenpurpose", native_enum=False),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_account_tokens_id", "account_tokens", ["id"])
    op.create_index("ix_account_tokens_purpose", "account_tokens", ["purpose"])
    op.create_index("ix_account_tokens_token_hash", "account_tokens", ["token_hash"])
    op.create_index("ix_account_tokens_user_id", "account_tokens", ["user_id"])
    op.create_index(
        "ix_account_tokens_user_purpose",
        "account_tokens",
        ["user_id", "purpose", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_tokens_user_purpose", table_name="account_tokens")
    op.drop_index("ix_account_tokens_user_id", table_name="account_tokens")
    op.drop_index("ix_account_tokens_token_hash", table_name="account_tokens")
    op.drop_index("ix_account_tokens_purpose", table_name="account_tokens")
    op.drop_index("ix_account_tokens_id", table_name="account_tokens")
    op.drop_table("account_tokens")
    op.drop_column("users", "email_verified_at")
