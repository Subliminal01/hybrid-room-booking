from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Index, JSON, Time, UniqueConstraint, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB
from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enum_values(enum_cls: type[Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class TimestampedModel(SQLModel):
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class UserRole(str, Enum):
    WORKER = "worker"
    HOST = "host"
    ADMIN = "admin"


class WorkspaceStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"


class WorkspaceReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class BookingStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class AuditAction(str, Enum):
    WORKSPACE_CREATED = "workspace_created"
    WORKSPACE_REVIEWED = "workspace_reviewed"
    BOOKING_PAID = "booking_paid"
    BOOKING_CANCELLED = "booking_cancelled"
    PAYMENT_FAILED = "payment_failed"
    PAYMENT_REFUNDED = "payment_refunded"


class AccountTokenPurpose(str, Enum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class User(TimestampedModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    email: str = Field(nullable=False, unique=True, index=True, max_length=320)
    hashed_password: str = Field(nullable=False, max_length=255)
    full_name: str = Field(nullable=False, max_length=160)
    role: UserRole = Field(
        default=UserRole.WORKER,
        sa_column=Column(
            SAEnum(UserRole, values_callable=enum_values, native_enum=False),
            nullable=False,
        ),
    )
    phone_number: Optional[str] = Field(default=None, max_length=32)
    is_active: bool = Field(default=True, nullable=False)
    email_verified_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )

    owned_workspaces: List["Workspace"] = Relationship(back_populates="owner")
    bookings: List["Booking"] = Relationship(back_populates="user")
    refresh_tokens: List["RefreshToken"] = Relationship(back_populates="user")
    account_tokens: List["AccountToken"] = Relationship(back_populates="user")


class RefreshToken(TimestampedModel, table=True):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_active", "user_id", "revoked_at", "expires_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: UUID = Field(foreign_key="users.id", nullable=False, index=True)
    token_hash: str = Field(nullable=False, unique=True, index=True, max_length=64)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))

    user: User = Relationship(back_populates="refresh_tokens")


class AccountToken(TimestampedModel, table=True):
    __tablename__ = "account_tokens"
    __table_args__ = (
        Index("ix_account_tokens_user_purpose", "user_id", "purpose", "expires_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: UUID = Field(foreign_key="users.id", nullable=False, index=True)
    token_hash: str = Field(nullable=False, unique=True, index=True, max_length=64)
    purpose: AccountTokenPurpose = Field(
        sa_column=Column(
            SAEnum(AccountTokenPurpose, values_callable=enum_values, native_enum=False),
            nullable=False,
            index=True,
        ),
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    used_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))

    user: User = Relationship(back_populates="account_tokens")


class Workspace(TimestampedModel, table=True):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("daily_price >= 0", name="ck_workspaces_daily_price_non_negative"),
        Index("ix_workspaces_location_price", "city", "daily_price"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    owner_id: UUID = Field(foreign_key="users.id", nullable=False, index=True)
    title: str = Field(nullable=False, max_length=160)
    description: Optional[str] = Field(default=None)
    address_line: str = Field(nullable=False, max_length=255)
    city: str = Field(nullable=False, index=True, max_length=120)
    state: Optional[str] = Field(default=None, max_length=120)
    country: str = Field(default="India", nullable=False, max_length=120)
    postal_code: Optional[str] = Field(default=None, max_length=24)
    photo_url: Optional[str] = Field(default=None, max_length=2048)
    latitude: Optional[Decimal] = Field(default=None, max_digits=9, decimal_places=6)
    longitude: Optional[Decimal] = Field(default=None, max_digits=9, decimal_places=6)
    daily_price: Decimal = Field(nullable=False, max_digits=10, decimal_places=2)
    currency: str = Field(default="INR", nullable=False, min_length=3, max_length=3)
    capacity: int = Field(default=1, nullable=False, ge=1)
    status: WorkspaceStatus = Field(
        default=WorkspaceStatus.ACTIVE,
        sa_column=Column(
            SAEnum(WorkspaceStatus, values_callable=enum_values, native_enum=False),
            nullable=False,
        ),
    )
    review_status: WorkspaceReviewStatus = Field(
        default=WorkspaceReviewStatus.PENDING,
        sa_column=Column(
            SAEnum(WorkspaceReviewStatus, values_callable=enum_values, native_enum=False),
            nullable=False,
            index=True,
        ),
    )
    amenities: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON().with_variant(JSONB, "postgresql"), nullable=False),
    )

    owner: User = Relationship(back_populates="owned_workspaces")
    bookings: List["Booking"] = Relationship(back_populates="workspace")
    availability_rules: List["WorkspaceAvailabilityRule"] = Relationship(
        back_populates="workspace",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    blackout_dates: List["WorkspaceBlackoutDate"] = Relationship(
        back_populates="workspace",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class WorkspaceAvailabilityRule(TimestampedModel, table=True):
    __tablename__ = "workspace_availability_rules"
    __table_args__ = (
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_availability_day_range"),
        CheckConstraint("end_time > start_time", name="ck_availability_time_order"),
        UniqueConstraint(
            "workspace_id",
            "day_of_week",
            "start_time",
            "end_time",
            name="uq_availability_workspace_day_time",
        ),
        Index("ix_availability_workspace_day", "workspace_id", "day_of_week"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", nullable=False, index=True)
    day_of_week: int = Field(nullable=False, ge=0, le=6)
    start_time: time = Field(sa_column=Column(Time(), nullable=False))
    end_time: time = Field(sa_column=Column(Time(), nullable=False))

    workspace: Workspace = Relationship(back_populates="availability_rules")


class WorkspaceBlackoutDate(TimestampedModel, table=True):
    __tablename__ = "workspace_blackout_dates"
    __table_args__ = (
        UniqueConstraint("workspace_id", "blackout_date", name="uq_blackout_workspace_date"),
        Index("ix_blackout_workspace_date", "workspace_id", "blackout_date"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", nullable=False, index=True)
    blackout_date: date = Field(sa_column=Column(Date(), nullable=False))
    reason: Optional[str] = Field(default=None, max_length=160)

    workspace: Workspace = Relationship(back_populates="blackout_dates")


class Booking(TimestampedModel, table=True):
    """A single reserved interval for one workspace.

    A hybrid schedule such as Monday/Wednesday/Friday should create one booking
    row per requested day. PostgreSQL then prevents active overlaps per room.
    """

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_bookings_end_after_start"),
        CheckConstraint("total_price >= 0", name="ck_bookings_total_price_non_negative"),
        Index("ix_bookings_group_status", "booking_group_id", "status"),
        Index("ix_bookings_workspace_time", "workspace_id", "start_at", "end_at"),
        Index("ix_bookings_user_time", "user_id", "start_at", "end_at"),
        Index("ix_bookings_status_expires", "status", "expires_at"),
        ExcludeConstraint(
            ("workspace_id", "="),
            (text("tstzrange(start_at, end_at, '[)')"), "&&"),
            name="ex_bookings_no_active_workspace_overlap",
            using="gist",
            where=text("status IN ('pending', 'confirmed')"),
        ).ddl_if(dialect="postgresql"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    booking_group_id: UUID = Field(default_factory=uuid4, nullable=False, index=True)
    user_id: UUID = Field(foreign_key="users.id", nullable=False, index=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", nullable=False, index=True)
    start_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    end_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    status: BookingStatus = Field(
        default=BookingStatus.PENDING,
        sa_column=Column(
            SAEnum(BookingStatus, values_callable=enum_values, native_enum=False),
            nullable=False,
            index=True,
        ),
    )
    total_price: Decimal = Field(nullable=False, max_digits=10, decimal_places=2)
    rota_label: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Optional grouping label, e.g. 'June office rota'.",
    )
    notes: Optional[str] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))

    user: User = Relationship(back_populates="bookings")
    workspace: Workspace = Relationship(back_populates="bookings")
    payments: List["Payment"] = Relationship(back_populates="booking")


class BookingIdempotencyKey(TimestampedModel, table=True):
    __tablename__ = "booking_idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_booking_idempotency_user_key"),
        Index("ix_booking_idempotency_user_key", "user_id", "key"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: UUID = Field(foreign_key="users.id", nullable=False, index=True)
    key: str = Field(nullable=False, max_length=128)
    request_hash: str = Field(nullable=False, max_length=64)
    booking_group_id: UUID = Field(nullable=False, index=True)


class Payment(TimestampedModel, table=True):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),
        Index("ix_payments_booking_status", "booking_id", "status"),
        Index("ix_payments_provider_checkout_reference", "provider_checkout_reference"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    booking_id: UUID = Field(foreign_key="bookings.id", nullable=False, index=True)
    amount: Decimal = Field(nullable=False, max_digits=10, decimal_places=2)
    currency: str = Field(default="INR", nullable=False, min_length=3, max_length=3)
    status: PaymentStatus = Field(
        default=PaymentStatus.PENDING,
        sa_column=Column(
            SAEnum(PaymentStatus, values_callable=enum_values, native_enum=False),
            nullable=False,
            index=True,
        ),
    )
    provider: str = Field(default="mock", nullable=False, max_length=40)
    provider_reference: str = Field(nullable=False, unique=True, index=True, max_length=120)
    provider_checkout_reference: Optional[str] = Field(default=None, max_length=120)
    paid_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    refunded_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))

    booking: Booking = Relationship(back_populates="payments")


class AuditEvent(TimestampedModel, table=True):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_actor_created", "actor_user_id", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    actor_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id", index=True)
    action: AuditAction = Field(
        sa_column=Column(
            SAEnum(AuditAction, values_callable=enum_values, native_enum=False),
            nullable=False,
            index=True,
        ),
    )
    entity_type: str = Field(nullable=False, index=True, max_length=80)
    entity_id: Optional[UUID] = Field(default=None, index=True)
    details: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON().with_variant(JSONB, "postgresql"), nullable=False),
    )


__all__ = [
    "AccountToken",
    "AccountTokenPurpose",
    "AuditAction",
    "AuditEvent",
    "Booking",
    "BookingIdempotencyKey",
    "BookingStatus",
    "Payment",
    "PaymentStatus",
    "RefreshToken",
    "User",
    "UserRole",
    "Workspace",
    "WorkspaceAvailabilityRule",
    "WorkspaceBlackoutDate",
    "WorkspaceReviewStatus",
    "WorkspaceStatus",
]
