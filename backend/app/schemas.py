from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    AuditAction,
    BookingStatus,
    PaymentStatus,
    UserRole,
    WorkspaceReviewStatus,
    WorkspaceStatus,
)

SAFE_AMENITY_KEY_PATTERN = re.compile(r"^[a-z0-9_:-]{1,64}$")


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def validate_https_url(value: str | None) -> str | None:
    value = normalize_optional_text(value)
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("photo_url must be a valid https URL")
    return value


def validate_amenities(value: dict | None) -> dict | None:
    if value is None:
        return None
    cleaned = {}
    for key, enabled in value.items():
        if not isinstance(key, str) or not SAFE_AMENITY_KEY_PATTERN.fullmatch(key):
            raise ValueError("amenity keys must use lowercase letters, numbers, _, :, or -")
        if not isinstance(enabled, bool):
            raise ValueError("amenity values must be booleans")
        cleaned[key] = enabled
    return cleaned


class UserRegisterRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=160)
    phone_number: str | None = Field(default=None, max_length=32)
    role: UserRole = UserRole.WORKER

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("email must be valid")
        return value

    @field_validator("role")
    @classmethod
    def reject_public_admin_registration(cls, value: UserRole) -> UserRole:
        if value == UserRole.ADMIN:
            raise ValueError("admin users cannot be created through public registration")
        return value


class UserLoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    role: UserRole
    phone_number: str | None
    is_active: bool
    email_verified_at: datetime | None


class UserPageResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class AdminBootstrapRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(default="Platform Admin", min_length=1, max_length=160)
    bootstrap_secret: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("email must be valid")
        return value

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return value.strip()


class AdminBootstrapResponse(BaseModel):
    user: UserResponse
    created: bool
    message: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    phone_number: str | None = Field(default=None, max_length=32)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class EmailVerificationRequestResponse(BaseModel):
    message: str
    verification_token: str | None = None


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=1)


class PasswordResetRequest(BaseModel):
    email: str = Field(max_length=320)


class PasswordResetRequestResponse(BaseModel):
    message: str
    reset_token: str | None = None


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class AdminEmailTestResponse(BaseModel):
    message: str
    provider: str
    recipient: str


class AdminEmailStatusResponse(BaseModel):
    provider: str
    ready: bool
    from_address: str
    smtp_host: str | None
    smtp_port: int | None
    smtp_use_tls: bool
    smtp_use_ssl: bool
    required_settings: list[str]
    missing_settings: list[str]
    test_supported: bool


class AdminPaymentProviderStatusResponse(BaseModel):
    provider: str
    ready: bool
    webhook_url: str
    required_settings: list[str]
    missing_settings: list[str]
    manual_confirmation_enabled: bool


class AdminStorageStatusResponse(BaseModel):
    provider: str
    ready: bool
    durable: bool
    public_base_url: str | None
    required_settings: list[str]
    missing_settings: list[str]


class ClientErrorReportRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    source: str = Field(default="frontend", max_length=80)
    url: str | None = Field(default=None, max_length=2048)
    stack: str | None = Field(default=None, max_length=6000)
    component_stack: str | None = Field(default=None, max_length=6000)
    user_agent: str | None = Field(default=None, max_length=500)


class ClientErrorReportResponse(BaseModel):
    status: str
    request_id: str


class TimeSlot(BaseModel):
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def validate_interval(self) -> "TimeSlot":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self

    @field_validator("start_at", "end_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("datetime values must include timezone information")
        return value


class WorkspaceSearchRequest(BaseModel):
    city: str | None = Field(default=None, max_length=120)
    max_daily_price: Decimal | None = Field(default=None, ge=0)
    min_daily_price: Decimal | None = Field(default=None, ge=0)
    slots: list[TimeSlot] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_price_range(self) -> "WorkspaceSearchRequest":
        if (
            self.min_daily_price is not None
            and self.max_daily_price is not None
            and self.min_daily_price > self.max_daily_price
        ):
            raise ValueError("min_daily_price cannot be higher than max_daily_price")
        return self


class AvailabilityRuleRequest(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0 is Monday, 6 is Sunday.")
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def validate_time_range(self) -> "AvailabilityRuleRequest":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class WorkspaceAvailabilityReplaceRequest(BaseModel):
    rules: list[AvailabilityRuleRequest] = Field(default_factory=list)


class AvailabilityRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    day_of_week: int
    start_time: time
    end_time: time


class BlackoutDateRequest(BaseModel):
    blackout_date: date
    reason: str | None = Field(default=None, max_length=160)


class WorkspaceBlackoutReplaceRequest(BaseModel):
    blackout_dates: list[BlackoutDateRequest] = Field(default_factory=list)


class BlackoutDateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    blackout_date: date
    reason: str | None


class WorkspaceCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = None
    address_line: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str = Field(default="India", min_length=1, max_length=120)
    postal_code: str | None = Field(default=None, max_length=24)
    photo_url: str | None = Field(default=None, max_length=2048)
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    daily_price: Decimal = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    capacity: int = Field(default=1, ge=1)
    status: WorkspaceStatus = WorkspaceStatus.ACTIVE
    amenities: dict = Field(default_factory=dict)

    @field_validator("title", "address_line", "city", "state", "country", "postal_code", "description", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, value: str | None) -> str | None:
        return validate_https_url(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("amenities")
    @classmethod
    def validate_amenity_flags(cls, value: dict) -> dict:
        return validate_amenities(value) or {}


class WorkspaceUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    address_line: str | None = Field(default=None, min_length=1, max_length=255)
    city: str | None = Field(default=None, min_length=1, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, min_length=1, max_length=120)
    postal_code: str | None = Field(default=None, max_length=24)
    photo_url: str | None = Field(default=None, max_length=2048)
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    daily_price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    capacity: int | None = Field(default=None, ge=1)
    status: WorkspaceStatus | None = None
    amenities: dict | None = None

    @field_validator("title", "address_line", "city", "state", "country", "postal_code", "description", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, value: str | None) -> str | None:
        return validate_https_url(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @field_validator("amenities")
    @classmethod
    def validate_amenity_flags(cls, value: dict | None) -> dict | None:
        return validate_amenities(value)


class WorkspaceReviewRequest(BaseModel):
    review_status: WorkspaceReviewStatus
    review_note: str | None = Field(default=None, max_length=500)

    @field_validator("review_note", mode="before")
    @classmethod
    def normalize_review_note(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    title: str
    description: str | None
    address_line: str
    city: str
    state: str | None
    country: str
    postal_code: str | None
    photo_url: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    daily_price: Decimal
    currency: str
    capacity: int
    status: WorkspaceStatus
    review_status: WorkspaceReviewStatus
    amenities: dict
    availability_rules: list[AvailabilityRuleResponse] = Field(default_factory=list)
    blackout_dates: list[BlackoutDateResponse] = Field(default_factory=list)


class WorkspaceSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    address_line: str
    city: str
    state: str | None
    country: str
    photo_url: str | None
    daily_price: Decimal
    estimated_total_price: Decimal
    matched_slot_count: int
    matched_slots: list[TimeSlot] = Field(default_factory=list)
    currency: str
    capacity: int
    review_status: WorkspaceReviewStatus
    amenities: dict


class BookingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    slots: list[TimeSlot] = Field(min_length=1)
    rota_label: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class ItineraryBookingItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    slots: list[TimeSlot] = Field(min_length=1)


class ItineraryBookingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ItineraryBookingItemRequest] = Field(min_length=1)
    rota_label: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class BookingWorkspaceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    address_line: str
    city: str
    photo_url: str | None
    currency: str


class BookingUserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: str


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    booking_group_id: UUID
    user_id: UUID
    workspace_id: UUID
    start_at: datetime
    end_at: datetime
    status: BookingStatus
    total_price: Decimal
    rota_label: str | None
    notes: str | None
    expires_at: datetime | None
    workspace: BookingWorkspaceSummary | None = None
    user: BookingUserSummary | None = None


class BookingCreateResponse(BaseModel):
    bookings: list[BookingResponse]
    total_price: Decimal


class BookingPageResponse(BaseModel):
    items: list[BookingResponse]
    total: int
    limit: int
    offset: int


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    booking_id: UUID
    amount: Decimal
    currency: str
    status: PaymentStatus
    provider: str
    provider_reference: str
    provider_checkout_reference: str | None = None
    paid_at: datetime | None
    refunded_at: datetime | None


class PaymentPageResponse(BaseModel):
    items: list[PaymentResponse]
    total: int
    limit: int
    offset: int


class PaymentCheckoutSessionResponse(BaseModel):
    booking_group_id: UUID
    payments: list[PaymentResponse]
    total_amount: Decimal
    currency: str
    provider: str
    checkout_reference: str
    checkout_url: str
    checkout_payload: dict[str, Any] = Field(default_factory=dict)


class PaymentWebhookResponse(BaseModel):
    provider: str
    provider_reference: str
    payment_id: UUID
    booking_id: UUID
    status: PaymentStatus
    processed: bool


class BookingGroupCheckoutResponse(BaseModel):
    booking_group_id: UUID
    bookings: list[BookingResponse]
    payments: list[PaymentResponse]
    total_paid: Decimal


class BookingGroupCancelResponse(BaseModel):
    booking_group_id: UUID
    bookings: list[BookingResponse]
    refunded_payments: list[PaymentResponse]
    total_refunded: Decimal


class ReceiptPartyResponse(BaseModel):
    name: str
    email: str | None = None
    address: str | None = None


class ReceiptLineItemResponse(BaseModel):
    booking_id: UUID
    description: str
    service_date: date
    start_at: datetime
    end_at: datetime
    quantity: int = 1
    unit_price: Decimal
    amount: Decimal


class ReceiptPaymentResponse(BaseModel):
    payment_id: UUID
    provider: str
    provider_reference: str
    provider_checkout_reference: str | None = None
    status: PaymentStatus
    amount: Decimal
    paid_at: datetime | None
    refunded_at: datetime | None


class BookingGroupReceiptResponse(BaseModel):
    booking_group_id: UUID
    receipt_number: str
    supplier: ReceiptPartyResponse
    customer: ReceiptPartyResponse
    host: ReceiptPartyResponse
    workspace_title: str
    workspace_address: str
    line_items: list[ReceiptLineItemResponse]
    payment_summary: list[ReceiptPaymentResponse]
    bookings: list[BookingResponse]
    payments: list[PaymentResponse]
    subtotal: Decimal
    tax_total: Decimal
    total_paid: Decimal
    total_refunded: Decimal
    net_paid: Decimal
    currency: str
    issued_at: datetime
    paid_at: datetime | None


class HostRevenueSummaryResponse(BaseModel):
    total_paid: Decimal
    total_refunded: Decimal
    gross_revenue: Decimal
    platform_commission_rate: Decimal
    platform_commission: Decimal
    host_net_revenue: Decimal
    pending_payout: Decimal
    pending_hold_value: Decimal
    confirmed_booking_count: int
    cancelled_booking_count: int
    pending_booking_count: int
    paid_payment_count: int
    currency: str = "INR"


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID | None
    action: AuditAction
    entity_type: str
    entity_id: UUID | None
    details: dict
    created_at: datetime


class AuditEventPageResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    limit: int
    offset: int
