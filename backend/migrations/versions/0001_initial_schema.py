"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-08 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "users",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column(
            "role",
            sa.Enum("worker", "host", "admin", name="userrole", native_enum=False),
            nullable=False,
        ),
        sa.Column("phone_number", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_id", "users", ["id"])

    op.create_table(
        "workspaces",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("address_line", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=120), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=False),
        sa.Column("postal_code", sa.String(length=24), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("daily_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "paused", name="workspacestatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("amenities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "daily_price >= 0",
            name="ck_workspaces_daily_price_non_negative",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_city", "workspaces", ["city"])
    op.create_index("ix_workspaces_id", "workspaces", ["id"])
    op.create_index("ix_workspaces_location_price", "workspaces", ["city", "daily_price"])
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])

    op.create_table(
        "bookings",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                "cancelled",
                "expired",
                name="bookingstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("total_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("rota_label", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.CheckConstraint("end_at > start_at", name="ck_bookings_end_after_start"),
        sa.CheckConstraint(
            "total_price >= 0",
            name="ck_bookings_total_price_non_negative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bookings_id", "bookings", ["id"])
    op.create_index("ix_bookings_status", "bookings", ["status"])
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])
    op.create_index("ix_bookings_user_time", "bookings", ["user_id", "start_at", "end_at"])
    op.create_index("ix_bookings_workspace_id", "bookings", ["workspace_id"])
    op.create_index(
        "ix_bookings_workspace_time",
        "bookings",
        ["workspace_id", "start_at", "end_at"],
    )

    op.execute(
        """
        ALTER TABLE bookings
        ADD CONSTRAINT ex_bookings_no_active_workspace_overlap
        EXCLUDE USING gist (
            workspace_id WITH =,
            tstzrange(start_at, end_at, '[)') WITH &&
        )
        WHERE (status IN ('pending', 'confirmed'))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ex_bookings_no_active_workspace_overlap"
    )
    op.drop_index("ix_bookings_workspace_time", table_name="bookings")
    op.drop_index("ix_bookings_workspace_id", table_name="bookings")
    op.drop_index("ix_bookings_user_time", table_name="bookings")
    op.drop_index("ix_bookings_user_id", table_name="bookings")
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_id", table_name="bookings")
    op.drop_table("bookings")

    op.drop_index("ix_workspaces_owner_id", table_name="workspaces")
    op.drop_index("ix_workspaces_location_price", table_name="workspaces")
    op.drop_index("ix_workspaces_id", table_name="workspaces")
    op.drop_index("ix_workspaces_city", table_name="workspaces")
    op.drop_table("workspaces")

    op.drop_index("ix_users_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
