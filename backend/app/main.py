import hashlib
import hmac
import json
from datetime import timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from uuid import UUID, uuid4

from sqlmodel import Session, text, select

from app.auth_service import (
    AccountTokenError,
    AuthError,
    DuplicateEmailError,
    RefreshTokenError,
    authenticate_user,
    confirm_email_verification_token,
    get_user_by_email,
    issue_user_session,
    register_user,
    request_email_verification_token,
    request_password_reset_token,
    reset_password_with_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.booking_service import (
    build_booking_rows,
    calculate_booking_total,
    expire_stale_pending_bookings,
    find_available_workspaces,
    find_workspace_slot_matches,
    workspace_has_blackout_for_slots,
    workspace_is_available_for_slots,
    workspace_has_conflict,
)
from app.config import get_settings
from app.database import get_session
from app.dependencies import get_current_user, require_admin_user, require_host_user
from app.email_service import EmailDeliveryError, get_email_service
from app.models import (
    AuditAction,
    AuditEvent,
    Booking,
    BookingIdempotencyKey,
    BookingStatus,
    Payment,
    PaymentStatus,
    User,
    UserRole,
    Workspace,
    WorkspaceAvailabilityRule,
    WorkspaceBlackoutDate,
    WorkspaceReviewStatus,
    utc_now,
)
from app.observability import configure_error_tracking, configure_logging, configure_observability, logger
from app.payment_service import (
    PaymentProviderError,
    amount_to_minor_units,
    checkout_reference_for_payments,
    get_or_create_pending_payment,
    get_pending_payment,
    get_succeeded_payments,
    mark_payment_failed,
    mark_payment_succeeded,
    checkout_url,
    refund_succeeded_payments_for_booking,
    prepare_provider_checkout,
    total_payment_amount,
    verify_payment_webhook_signature,
)
from app.rate_limit import configure_rate_limiting
from app.schemas import (
    AdminBootstrapRequest,
    AdminBootstrapResponse,
    AdminEmailStatusResponse,
    AdminEmailTestResponse,
    AdminPaymentProviderStatusResponse,
    AdminStorageStatusResponse,
    AuditEventPageResponse,
    AuditEventResponse,
    AvailabilityRuleResponse,
    BlackoutDateResponse,
    BookingCreateRequest,
    BookingCreateResponse,
    BookingGroupCancelResponse,
    BookingGroupCheckoutResponse,
    BookingGroupReceiptResponse,
    ItineraryBookingCreateRequest,
    BookingPageResponse,
    BookingResponse,
    ClientErrorReportRequest,
    ClientErrorReportResponse,
    EmailVerificationConfirmRequest,
    EmailVerificationRequestResponse,
    HostRevenueSummaryResponse,
    LogoutRequest,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    PaymentCheckoutSessionResponse,
    PaymentPageResponse,
    PaymentResponse,
    PaymentWebhookResponse,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserPageResponse,
    UserRegisterRequest,
    UserResponse,
    UserUpdateRequest,
    WorkspaceAvailabilityReplaceRequest,
    WorkspaceBlackoutReplaceRequest,
    WorkspaceCreateRequest,
    WorkspaceReviewRequest,
    WorkspaceResponse,
    WorkspaceSearchRequest,
    WorkspaceSearchResult,
    WorkspaceUpdateRequest,
)
from app.security import hash_password, verify_password
from app.storage_service import get_storage_service

settings = get_settings()
configure_logging(settings.log_level)
configure_error_tracking(settings)
app = FastAPI(title="Hybrid Room Booking API")
storage_service = get_storage_service(settings)
if settings.storage_provider == "local":
    app.mount("/uploads", StaticFiles(directory=storage_service.upload_root), name="uploads")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
configure_rate_limiting(
    app,
    auth_limit_per_minute=settings.auth_rate_limit_per_minute,
    trust_proxy_headers=settings.trust_proxy_headers,
)
configure_observability(app)

def get_owned_workspace(
    workspace_id: UUID,
    current_user: User,
    session: Session,
) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own workspaces",
        )
    return workspace


def can_access_booking(booking: Booking, current_user: User, session: Session) -> bool:
    if current_user.role == UserRole.ADMIN or booking.user_id == current_user.id:
        return True

    if current_user.role == UserRole.HOST:
        workspace = session.get(Workspace, booking.workspace_id)
        return workspace is not None and workspace.owner_id == current_user.id

    return False


def get_visible_booking(
    booking_id: UUID,
    current_user: User,
    session: Session,
) -> Booking:
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if not can_access_booking(booking, current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot access this booking",
        )

    return booking


def as_aware_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def booking_has_started(booking: Booking, now) -> bool:
    return as_aware_utc(booking.start_at) <= now


def booking_refund_allowed(booking: Booking, now) -> bool:
    if booking.status != BookingStatus.CONFIRMED:
        return False
    return as_aware_utc(booking.start_at) - now > timedelta(hours=24)


def ensure_booking_can_be_cancelled(booking: Booking, now) -> None:
    if booking.status == BookingStatus.CANCELLED:
        return
    if booking_has_started(booking, now):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This stay has already started and cannot be cancelled from self-service",
        )


def get_owned_workspace(
    workspace_id: UUID,
    current_user: User,
    session: Session,
) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own workspaces",
        )
    return workspace


def record_audit_event(
    session: Session,
    *,
    actor_user_id: UUID | None,
    action: AuditAction,
    entity_type: str,
    entity_id: UUID | None = None,
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    session.add(event)
    return event


def normalize_idempotency_key(idempotency_key: str | None) -> str | None:
    if idempotency_key is None:
        return None

    normalized = idempotency_key.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key cannot be empty",
        )
    if len(normalized) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key cannot be longer than 128 characters",
        )
    return normalized


def booking_request_hash(request: BookingCreateRequest | ItineraryBookingCreateRequest) -> str:
    payload = request.model_dump(mode="json")
    if "slots" in payload:
        payload["slots"] = sorted(
            payload["slots"],
            key=lambda slot: (slot["start_at"], slot["end_at"]),
        )
    if "items" in payload:
        for item in payload["items"]:
            item["slots"] = sorted(
                item["slots"],
                key=lambda slot: (slot["start_at"], slot["end_at"]),
            )
        payload["items"] = sorted(
            payload["items"],
            key=lambda item: (item["workspace_id"], item["slots"]),
        )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def booking_group_create_response(session: Session, booking_group_id: UUID) -> BookingCreateResponse:
    bookings = session.exec(
        select(Booking)
        .where(Booking.booking_group_id == booking_group_id)
        .order_by(Booking.start_at)
    ).all()
    if not bookings:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotent booking result is no longer available",
        )

    return BookingCreateResponse(
        bookings=[BookingResponse.model_validate(booking) for booking in bookings],
        total_price=sum((booking.total_price for booking in bookings), Decimal("0.00")),
    )


def get_existing_booking_idempotency_key(
    session: Session,
    *,
    user_id: UUID,
    key: str,
) -> BookingIdempotencyKey | None:
    return session.exec(
        select(BookingIdempotencyKey).where(
            BookingIdempotencyKey.user_id == user_id,
            BookingIdempotencyKey.key == key,
        )
    ).first()


def replay_or_reject_idempotent_booking(
    session: Session,
    *,
    existing_key: BookingIdempotencyKey,
    request_hash: str,
) -> BookingCreateResponse:
    if existing_key.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used with a different booking request",
        )
    return booking_group_create_response(session, existing_key.booking_group_id)


def get_bookable_workspace_or_raise(
    session: Session,
    *,
    workspace_id: UUID,
    slots: list,
) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.review_status != WorkspaceReviewStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace is not approved for booking",
        )

    if not workspace_is_available_for_slots(session, workspace, slots):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace is not available during one or more requested slots",
        )

    if workspace_has_blackout_for_slots(session, workspace, slots):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace is blocked on one or more requested dates",
        )

    if workspace_has_conflict(session, workspace_id, slots):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace is not available for one or more requested slots",
        )

    return workspace


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready(session: Session = Depends(get_session)) -> dict[str, str]:
    session.exec(text("SELECT 1")).one()
    return {"status": "ready", "database": "ok"}


@app.post("/monitoring/client-errors", response_model=ClientErrorReportResponse)
def report_client_error(
    request_body: ClientErrorReportRequest,
    request: Request,
) -> ClientErrorReportResponse:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or "unknown"
    logger.error(
        "client_error_reported",
        extra={
            "request_id": request_id,
            "source": request_body.source,
            "client_url": request_body.url,
            "client_message": request_body.message,
            "stack": request_body.stack,
            "component_stack": request_body.component_stack,
            "user_agent": request_body.user_agent,
        },
    )
    return ClientErrorReportResponse(status="accepted", request_id=request_id)


@app.post("/admin/bootstrap", response_model=AdminBootstrapResponse)
def bootstrap_admin_user(
    request: AdminBootstrapRequest,
    session: Session = Depends(get_session),
) -> AdminBootstrapResponse:
    if settings.admin_bootstrap_secret is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin bootstrap is not enabled",
        )

    if not hmac.compare_digest(request.bootstrap_secret, settings.admin_bootstrap_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin bootstrap secret",
        )

    user = get_user_by_email(session, request.email)
    created = user is None
    if user is None:
        user = register_user(
            session,
            email=request.email,
            password=request.password,
            full_name=request.full_name,
            role=UserRole.ADMIN,
        )
    else:
        user.role = UserRole.ADMIN
        user.full_name = request.full_name
        user.hashed_password = hash_password(request.password)
        user.is_active = True
        session.add(user)

    record_audit_event(
        session,
        actor_user_id=user.id,
        action=AuditAction.ADMIN_BOOTSTRAPPED,
        entity_type="user",
        entity_id=user.id,
        details={
            "email": user.email,
            "created": created,
        },
    )
    session.commit()
    session.refresh(user)

    return AdminBootstrapResponse(
        user=UserResponse.model_validate(user),
        created=created,
        message="Admin user created" if created else "Admin user updated",
    )


@app.post(
    "/auth/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: UserRegisterRequest,
    session: Session = Depends(get_session),
) -> TokenResponse:
    try:
        user = register_user(
            session,
            email=request.email,
            password=request.password,
            full_name=request.full_name,
            phone_number=request.phone_number,
            role=request.role,
        )
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        ) from exc

    access_token, refresh_token = issue_user_session(session, user)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@app.post("/auth/login", response_model=TokenResponse)
def login(
    request: UserLoginRequest,
    session: Session = Depends(get_session),
) -> TokenResponse:
    try:
        user = authenticate_user(session, email=request.email, password=request.password)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    access_token, refresh_token = issue_user_session(session, user)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@app.post("/auth/refresh", response_model=TokenResponse)
def refresh_session(
    request: RefreshTokenRequest,
    session: Session = Depends(get_session),
) -> TokenResponse:
    try:
        user, access_token, refresh_token = rotate_refresh_token(
            session,
            request.refresh_token,
        )
    except RefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: LogoutRequest,
    session: Session = Depends(get_session),
) -> None:
    revoke_refresh_token(session, request.refresh_token)


@app.get("/auth/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@app.patch("/auth/me", response_model=UserResponse)
def update_current_user(
    request: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> User:
    changed_fields: list[str] = []
    for field_name, value in request.model_dump(exclude_unset=True).items():
        if field_name == "full_name" and value is not None:
            value = value.strip()
        if getattr(current_user, field_name) != value:
            setattr(current_user, field_name, value)
            changed_fields.append(field_name)

    session.add(current_user)
    if changed_fields:
        record_audit_event(
            session,
            actor_user_id=current_user.id,
            action=AuditAction.USER_PROFILE_UPDATED,
            entity_type="user",
            entity_id=current_user.id,
            details={"changed_fields": sorted(changed_fields)},
        )
    session.commit()
    session.refresh(current_user)
    return current_user


@app.post("/auth/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    request: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = hash_password(request.new_password)
    session.add(current_user)
    record_audit_event(
        session,
        actor_user_id=current_user.id,
        action=AuditAction.PASSWORD_CHANGED,
        entity_type="user",
        entity_id=current_user.id,
        details={"method": "authenticated"},
    )
    session.commit()


@app.post("/auth/email-verification/request", response_model=EmailVerificationRequestResponse)
def request_email_verification(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> EmailVerificationRequestResponse:
    user, token = request_email_verification_token(session, current_user)
    dev_token = get_email_service(settings).send_email_verification(user, token)
    return EmailVerificationRequestResponse(
        message="Email verification instructions sent",
        verification_token=dev_token,
    )


@app.post("/auth/email-verification/confirm", response_model=UserResponse)
def confirm_email_verification(
    request: EmailVerificationConfirmRequest,
    session: Session = Depends(get_session),
) -> User:
    try:
        return confirm_email_verification_token(session, request.token)
    except AccountTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@app.post("/auth/password-reset/request", response_model=PasswordResetRequestResponse)
def request_password_reset(
    request: PasswordResetRequest,
    session: Session = Depends(get_session),
) -> PasswordResetRequestResponse:
    token_result = request_password_reset_token(session, request.email)
    dev_token = None
    if token_result is not None:
        user, token = token_result
        dev_token = get_email_service(settings).send_password_reset(user, token)
    return PasswordResetRequestResponse(
        message="If the email is registered, password reset instructions have been sent",
        reset_token=dev_token,
    )


@app.post("/auth/password-reset/confirm", response_model=UserResponse)
def confirm_password_reset(
    request: PasswordResetConfirmRequest,
    session: Session = Depends(get_session),
) -> User:
    try:
        user = reset_password_with_token(session, request.token, request.new_password)
    except AccountTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    record_audit_event(
        session,
        actor_user_id=user.id,
        action=AuditAction.PASSWORD_CHANGED,
        entity_type="user",
        entity_id=user.id,
        details={"method": "password_reset"},
    )
    session.commit()
    session.refresh(user)
    return user


@app.post(
    "/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace(
    request: WorkspaceCreateRequest,
    current_user: User = Depends(require_host_user),
    session: Session = Depends(get_session),
) -> Workspace:
    workspace = Workspace(owner_id=current_user.id, **request.model_dump())
    session.add(workspace)
    record_audit_event(
        session,
        actor_user_id=current_user.id,
        action=AuditAction.WORKSPACE_CREATED,
        entity_type="workspace",
        entity_id=workspace.id,
        details={
            "title": workspace.title,
            "city": workspace.city,
            "review_status": workspace.review_status.value,
        },
    )
    session.commit()
    session.refresh(workspace)
    return workspace


@app.get("/workspaces/mine", response_model=list[WorkspaceResponse])
def list_my_workspaces(
    current_user: User = Depends(require_host_user),
    session: Session = Depends(get_session),
) -> list[Workspace]:
    return session.exec(
        select(Workspace)
        .where(Workspace.owner_id == current_user.id)
        .order_by(Workspace.created_at.desc())
    ).all()


@app.get("/admin/workspaces/review", response_model=list[WorkspaceResponse])
def list_workspaces_for_review(
    review_status: WorkspaceReviewStatus | None = None,
    current_user: User = Depends(require_admin_user),
    session: Session = Depends(get_session),
) -> list[Workspace]:
    query = select(Workspace)
    if review_status is not None:
        query = query.where(Workspace.review_status == review_status)
    return session.exec(query.order_by(Workspace.created_at.desc())).all()


@app.post("/admin/email/test", response_model=AdminEmailTestResponse)
def send_admin_email_test(
    current_user: User = Depends(require_admin_user),
) -> AdminEmailTestResponse:
    try:
        get_email_service(settings).send_admin_test_email(current_user)
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return AdminEmailTestResponse(
        message="Test email sent",
        provider=settings.email_provider,
        recipient=current_user.email,
    )


@app.get("/admin/email/status", response_model=AdminEmailStatusResponse)
def read_admin_email_status(
    current_user: User = Depends(require_admin_user),
) -> AdminEmailStatusResponse:
    provider_settings = {
        "log": [],
        "brevo": [
            ("BREVO_API_KEY", settings.brevo_api_key),
        ],
        "smtp": [
            ("SMTP_HOST", settings.smtp_host),
            ("SMTP_USERNAME", settings.smtp_username),
            ("SMTP_PASSWORD", settings.smtp_password),
        ],
    }
    provider_requirements = provider_settings.get(settings.email_provider, [])
    missing_settings = [name for name, value in provider_requirements if not value]
    return AdminEmailStatusResponse(
        provider=settings.email_provider,
        ready=len(missing_settings) == 0,
        from_address=settings.email_from,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port if settings.email_provider == "smtp" else None,
        smtp_use_tls=settings.smtp_use_tls,
        smtp_use_ssl=settings.smtp_use_ssl,
        required_settings=[name for name, _ in provider_requirements],
        missing_settings=missing_settings,
        test_supported=True,
    )


@app.get("/admin/payment-provider/status", response_model=AdminPaymentProviderStatusResponse)
def read_admin_payment_provider_status(
    request: Request,
    current_user: User = Depends(require_admin_user),
) -> AdminPaymentProviderStatusResponse:
    provider_settings = {
        "mock": [],
        "razorpay": [
            ("RAZORPAY_KEY_ID", settings.razorpay_key_id),
            ("RAZORPAY_KEY_SECRET", settings.razorpay_key_secret),
            ("RAZORPAY_WEBHOOK_SECRET", settings.razorpay_webhook_secret),
        ],
        "stripe": [
            ("STRIPE_SECRET_KEY", settings.stripe_secret_key),
            ("STRIPE_WEBHOOK_SECRET", settings.stripe_webhook_secret),
        ],
    }
    provider_requirements = provider_settings.get(settings.payment_provider, [])
    missing_settings = [name for name, value in provider_requirements if not value]
    public_base_url = settings.public_api_base_url or str(request.base_url).rstrip("/")
    webhook_url = f"{public_base_url}/payments/webhooks/{settings.payment_provider}"
    return AdminPaymentProviderStatusResponse(
        provider=settings.payment_provider,
        ready=len(missing_settings) == 0,
        webhook_url=webhook_url,
        required_settings=[name for name, _ in provider_requirements],
        missing_settings=missing_settings,
        manual_confirmation_enabled=settings.payment_provider == "mock",
    )


@app.get("/admin/storage/status", response_model=AdminStorageStatusResponse)
def read_admin_storage_status(
    current_user: User = Depends(require_admin_user),
) -> AdminStorageStatusResponse:
    storage_settings = {
        "local": [],
        "s3": [
            ("S3_BUCKET", settings.s3_bucket),
            ("S3_ACCESS_KEY_ID", settings.s3_access_key_id),
            ("S3_SECRET_ACCESS_KEY", settings.s3_secret_access_key),
            ("S3_PUBLIC_BASE_URL", settings.s3_public_base_url),
        ],
    }
    storage_requirements = storage_settings.get(settings.storage_provider, [])
    missing_settings = [name for name, value in storage_requirements if not value]
    return AdminStorageStatusResponse(
        provider=settings.storage_provider,
        ready=len(missing_settings) == 0,
        durable=settings.storage_provider == "s3",
        public_base_url=settings.s3_public_base_url,
        required_settings=[name for name, _ in storage_requirements],
        missing_settings=missing_settings,
    )


@app.get("/admin/users", response_model=UserPageResponse)
def list_admin_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    role: UserRole | None = None,
    is_active: bool | None = None,
    current_user: User = Depends(require_admin_user),
    session: Session = Depends(get_session),
) -> UserPageResponse:
    query = select(User)
    count_query = select(func.count(User.id))
    if role is not None:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
        count_query = count_query.where(User.is_active == is_active)

    total = session.exec(count_query).one()
    items = session.exec(query.order_by(User.created_at.desc()).offset(offset).limit(limit)).all()
    return UserPageResponse(
        items=[UserResponse.model_validate(user) for user in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/admin/bookings", response_model=BookingPageResponse)
def list_admin_bookings(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: BookingStatus | None = Query(default=None, alias="status"),
    current_user: User = Depends(require_admin_user),
    session: Session = Depends(get_session),
) -> BookingPageResponse:
    expire_stale_pending_bookings(session)
    query = select(Booking)
    count_query = select(func.count(Booking.id))
    if status_filter is not None:
        query = query.where(Booking.status == status_filter)
        count_query = count_query.where(Booking.status == status_filter)

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Booking.start_at.desc()).offset(offset).limit(limit)
    ).all()
    return BookingPageResponse(
        items=[BookingResponse.model_validate(booking) for booking in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/admin/payments", response_model=PaymentPageResponse)
def list_admin_payments(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: PaymentStatus | None = Query(default=None, alias="status"),
    provider: str | None = Query(default=None, max_length=40),
    current_user: User = Depends(require_admin_user),
    session: Session = Depends(get_session),
) -> PaymentPageResponse:
    query = select(Payment)
    count_query = select(func.count(Payment.id))
    if status_filter is not None:
        query = query.where(Payment.status == status_filter)
        count_query = count_query.where(Payment.status == status_filter)
    if provider is not None:
        query = query.where(Payment.provider == provider)
        count_query = count_query.where(Payment.provider == provider)

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Payment.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return PaymentPageResponse(
        items=[PaymentResponse.model_validate(payment) for payment in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/admin/audit-events", response_model=AuditEventPageResponse)
def list_audit_events(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: AuditAction | None = None,
    entity_type: str | None = Query(default=None, max_length=80),
    current_user: User = Depends(require_admin_user),
    session: Session = Depends(get_session),
) -> AuditEventPageResponse:
    query = select(AuditEvent)
    count_query = select(func.count(AuditEvent.id))
    if action is not None:
        query = query.where(AuditEvent.action == action)
        count_query = count_query.where(AuditEvent.action == action)
    if entity_type is not None:
        query = query.where(AuditEvent.entity_type == entity_type)
        count_query = count_query.where(AuditEvent.entity_type == entity_type)

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return AuditEventPageResponse(
        items=[AuditEventResponse.model_validate(event) for event in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.patch("/admin/workspaces/{workspace_id}/review", response_model=WorkspaceResponse)
def review_workspace(
    workspace_id: UUID,
    request: WorkspaceReviewRequest,
    current_user: User = Depends(require_admin_user),
    session: Session = Depends(get_session),
) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    previous_status = workspace.review_status
    workspace.review_status = request.review_status
    session.add(workspace)
    record_audit_event(
        session,
        actor_user_id=current_user.id,
        action=AuditAction.WORKSPACE_REVIEWED,
        entity_type="workspace",
        entity_id=workspace.id,
        details={
            "title": workspace.title,
            "previous_review_status": previous_status.value,
            "review_status": workspace.review_status.value,
            **({"review_note": request.review_note} if request.review_note else {}),
        },
    )
    session.commit()
    session.refresh(workspace)
    return workspace


@app.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: UUID,
    session: Session = Depends(get_session),
) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return workspace


@app.patch("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: UUID,
    request: WorkspaceUpdateRequest,
    current_user: User = Depends(require_host_user),
    session: Session = Depends(get_session),
) -> Workspace:
    workspace = get_owned_workspace(workspace_id, current_user, session)

    for field_name, value in request.model_dump(exclude_unset=True).items():
        setattr(workspace, field_name, value)

    session.add(workspace)
    session.commit()
    session.refresh(workspace)
    return workspace


@app.post("/workspaces/{workspace_id}/photo", response_model=WorkspaceResponse)
async def upload_workspace_photo(
    workspace_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_host_user),
    session: Session = Depends(get_session),
) -> Workspace:
    workspace = get_owned_workspace(workspace_id, current_user, session)
    base_url = settings.public_api_base_url or str(request.base_url).rstrip("/")
    workspace.photo_url = await storage_service.upload_workspace_photo(file, base_url)
    session.add(workspace)
    session.commit()
    session.refresh(workspace)
    return workspace


@app.get(
    "/workspaces/{workspace_id}/availability",
    response_model=list[AvailabilityRuleResponse],
)
def get_workspace_availability(
    workspace_id: UUID,
    session: Session = Depends(get_session),
) -> list[WorkspaceAvailabilityRule]:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return session.exec(
        select(WorkspaceAvailabilityRule)
        .where(WorkspaceAvailabilityRule.workspace_id == workspace_id)
        .order_by(WorkspaceAvailabilityRule.day_of_week, WorkspaceAvailabilityRule.start_time)
    ).all()


@app.put(
    "/workspaces/{workspace_id}/availability",
    response_model=list[AvailabilityRuleResponse],
)
def replace_workspace_availability(
    workspace_id: UUID,
    request: WorkspaceAvailabilityReplaceRequest,
    current_user: User = Depends(require_host_user),
    session: Session = Depends(get_session),
) -> list[WorkspaceAvailabilityRule]:
    get_owned_workspace(workspace_id, current_user, session)

    existing_rules = session.exec(
        select(WorkspaceAvailabilityRule).where(
            WorkspaceAvailabilityRule.workspace_id == workspace_id,
        )
    ).all()
    for rule in existing_rules:
        session.delete(rule)

    for rule_request in request.rules:
        session.add(
            WorkspaceAvailabilityRule(
                workspace_id=workspace_id,
                day_of_week=rule_request.day_of_week,
                start_time=rule_request.start_time,
                end_time=rule_request.end_time,
            )
        )

    session.commit()
    return session.exec(
        select(WorkspaceAvailabilityRule)
        .where(WorkspaceAvailabilityRule.workspace_id == workspace_id)
        .order_by(WorkspaceAvailabilityRule.day_of_week, WorkspaceAvailabilityRule.start_time)
    ).all()


@app.get(
    "/workspaces/{workspace_id}/blackout-dates",
    response_model=list[BlackoutDateResponse],
)
def get_workspace_blackout_dates(
    workspace_id: UUID,
    session: Session = Depends(get_session),
) -> list[WorkspaceBlackoutDate]:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return session.exec(
        select(WorkspaceBlackoutDate)
        .where(WorkspaceBlackoutDate.workspace_id == workspace_id)
        .order_by(WorkspaceBlackoutDate.blackout_date)
    ).all()


@app.put(
    "/workspaces/{workspace_id}/blackout-dates",
    response_model=list[BlackoutDateResponse],
)
def replace_workspace_blackout_dates(
    workspace_id: UUID,
    request: WorkspaceBlackoutReplaceRequest,
    current_user: User = Depends(require_host_user),
    session: Session = Depends(get_session),
) -> list[WorkspaceBlackoutDate]:
    get_owned_workspace(workspace_id, current_user, session)

    existing_dates = session.exec(
        select(WorkspaceBlackoutDate).where(
            WorkspaceBlackoutDate.workspace_id == workspace_id,
        )
    ).all()
    for blackout_date in existing_dates:
        session.delete(blackout_date)

    seen_dates = set()
    for blackout_request in request.blackout_dates:
        if blackout_request.blackout_date in seen_dates:
            continue
        seen_dates.add(blackout_request.blackout_date)
        session.add(
            WorkspaceBlackoutDate(
                workspace_id=workspace_id,
                blackout_date=blackout_request.blackout_date,
                reason=blackout_request.reason,
            )
        )

    session.commit()
    return session.exec(
        select(WorkspaceBlackoutDate)
        .where(WorkspaceBlackoutDate.workspace_id == workspace_id)
        .order_by(WorkspaceBlackoutDate.blackout_date)
    ).all()


@app.post("/workspaces/search", response_model=list[WorkspaceSearchResult])
def search_workspaces(
    request: WorkspaceSearchRequest,
    session: Session = Depends(get_session),
) -> list[WorkspaceSearchResult]:
    expire_stale_pending_bookings(session)
    workspace_matches = find_workspace_slot_matches(
        session,
        slots=request.slots,
        city=request.city,
        min_daily_price=request.min_daily_price,
        max_daily_price=request.max_daily_price,
    )
    return [
        WorkspaceSearchResult(
            id=workspace.id,
            title=workspace.title,
            description=workspace.description,
            address_line=workspace.address_line,
            city=workspace.city,
            state=workspace.state,
            country=workspace.country,
            photo_url=workspace.photo_url,
            daily_price=workspace.daily_price,
            estimated_total_price=calculate_booking_total(workspace, matched_slots),
            matched_slot_count=len(matched_slots),
            matched_slots=matched_slots,
            currency=workspace.currency,
            capacity=workspace.capacity,
            review_status=workspace.review_status,
            amenities=workspace.amenities,
        )
        for workspace, matched_slots in workspace_matches
    ]


@app.post(
    "/bookings",
    response_model=BookingCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_booking(
    request: BookingCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookingCreateResponse:
    expire_stale_pending_bookings(session)
    normalized_idempotency_key = normalize_idempotency_key(idempotency_key)
    request_hash = booking_request_hash(request)
    if normalized_idempotency_key is not None:
        existing_key = get_existing_booking_idempotency_key(
            session,
            user_id=current_user.id,
            key=normalized_idempotency_key,
        )
        if existing_key is not None:
            return replay_or_reject_idempotent_booking(
                session,
                existing_key=existing_key,
                request_hash=request_hash,
            )

    workspace = get_bookable_workspace_or_raise(
        session,
        workspace_id=request.workspace_id,
        slots=request.slots,
    )

    bookings = build_booking_rows(
        workspace=workspace,
        user_id=current_user.id,
        slots=request.slots,
        rota_label=request.rota_label,
        notes=request.notes,
    )

    if normalized_idempotency_key is not None:
        session.add(
            BookingIdempotencyKey(
                user_id=current_user.id,
                key=normalized_idempotency_key,
                request_hash=request_hash,
                booking_group_id=bookings[0].booking_group_id,
            )
        )

    for booking in bookings:
        session.add(booking)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if normalized_idempotency_key is not None:
            existing_key = get_existing_booking_idempotency_key(
                session,
                user_id=current_user.id,
                key=normalized_idempotency_key,
            )
            if existing_key is not None:
                return replay_or_reject_idempotent_booking(
                    session,
                    existing_key=existing_key,
                    request_hash=request_hash,
                )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace was booked by another request",
        ) from exc

    for booking in bookings:
        session.refresh(booking)

    return booking_group_create_response(session, bookings[0].booking_group_id)


@app.post(
    "/booking-itineraries",
    response_model=BookingCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_booking_itinerary(
    request: ItineraryBookingCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookingCreateResponse:
    expire_stale_pending_bookings(session)
    normalized_idempotency_key = normalize_idempotency_key(idempotency_key)
    request_hash = booking_request_hash(request)
    if normalized_idempotency_key is not None:
        existing_key = get_existing_booking_idempotency_key(
            session,
            user_id=current_user.id,
            key=normalized_idempotency_key,
        )
        if existing_key is not None:
            return replay_or_reject_idempotent_booking(
                session,
                existing_key=existing_key,
                request_hash=request_hash,
            )

    all_slots = sorted(
        [slot for item in request.items for slot in item.slots],
        key=lambda slot: slot.start_at,
    )
    for index, slot in enumerate(all_slots[:-1]):
        next_slot = all_slots[index + 1]
        if slot.start_at < next_slot.end_at and slot.end_at > next_slot.start_at:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Itinerary contains overlapping stays",
            )

    booking_group_id = uuid4()
    bookings = []
    for item in request.items:
        workspace = get_bookable_workspace_or_raise(
            session,
            workspace_id=item.workspace_id,
            slots=item.slots,
        )
        bookings.extend(
            build_booking_rows(
                workspace=workspace,
                user_id=current_user.id,
                slots=item.slots,
                rota_label=request.rota_label,
                notes=request.notes,
                booking_group_id=booking_group_id,
            )
        )

    if normalized_idempotency_key is not None:
        session.add(
            BookingIdempotencyKey(
                user_id=current_user.id,
                key=normalized_idempotency_key,
                request_hash=request_hash,
                booking_group_id=booking_group_id,
            )
        )

    for booking in bookings:
        session.add(booking)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if normalized_idempotency_key is not None:
            existing_key = get_existing_booking_idempotency_key(
                session,
                user_id=current_user.id,
                key=normalized_idempotency_key,
            )
            if existing_key is not None:
                return replay_or_reject_idempotent_booking(
                    session,
                    existing_key=existing_key,
                    request_hash=request_hash,
                )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more stays were booked by another request",
        ) from exc

    for booking in bookings:
        session.refresh(booking)

    return booking_group_create_response(session, booking_group_id)


@app.post("/bookings/{booking_id}/payment-intent", response_model=PaymentResponse)
def create_booking_payment_intent(
    booking_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Payment:
    expire_stale_pending_bookings(session)
    booking = get_visible_booking(booking_id, current_user, session)
    if booking.user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the booking owner can pay for this booking",
        )
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cancelled bookings cannot be paid",
        )
    if booking.status == BookingStatus.EXPIRED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking hold has expired",
        )
    if booking.status == BookingStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking is already confirmed",
        )

    return get_or_create_pending_payment(session, booking)


def ensure_payable_booking_owner(booking: Booking, current_user: User) -> None:
    if booking.user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the booking owner can pay for this booking",
        )
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cancelled bookings cannot be paid",
        )
    if booking.status == BookingStatus.EXPIRED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking hold has expired",
        )
    if booking.status == BookingStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking is already confirmed",
        )


def get_payable_booking_group(
    session: Session,
    *,
    booking_group_id: UUID,
    current_user: User,
) -> list[Booking]:
    bookings = session.exec(
        select(Booking)
        .where(Booking.booking_group_id == booking_group_id)
        .order_by(Booking.start_at)
    ).all()
    if not bookings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking group not found",
        )

    for booking in bookings:
        ensure_payable_booking_owner(booking, current_user)
    return bookings


def get_visible_booking_group(
    session: Session,
    *,
    booking_group_id: UUID,
    current_user: User,
) -> list[Booking]:
    bookings = session.exec(
        select(Booking)
        .where(Booking.booking_group_id == booking_group_id)
        .order_by(Booking.start_at)
    ).all()
    if not bookings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking group not found",
        )

    for booking in bookings:
        if not can_access_booking(booking, current_user, session):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot access this booking group",
            )
    return bookings


def ensure_manual_payment_confirmation_allowed() -> None:
    if get_settings().payment_provider != "mock":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manual payment confirmation is only available for mock payments",
        )


@app.post("/booking-groups/{booking_group_id}/payment-intent", response_model=list[PaymentResponse])
def create_booking_group_payment_intent(
    booking_group_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[Payment]:
    expire_stale_pending_bookings(session)
    bookings = get_payable_booking_group(
        session,
        booking_group_id=booking_group_id,
        current_user=current_user,
    )

    payments = []
    for booking in bookings:
        payments.append(get_or_create_pending_payment(session, booking))

    return payments


@app.post(
    "/booking-groups/{booking_group_id}/checkout-session",
    response_model=PaymentCheckoutSessionResponse,
)
def create_booking_group_checkout_session(
    booking_group_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> PaymentCheckoutSessionResponse:
    expire_stale_pending_bookings(session)
    bookings = get_payable_booking_group(
        session,
        booking_group_id=booking_group_id,
        current_user=current_user,
    )
    payments = [get_or_create_pending_payment(session, booking) for booking in bookings]
    checkout_reference = checkout_reference_for_payments(payments)
    try:
        checkout_payload = prepare_provider_checkout(
            session=session,
            booking_group_id=booking_group_id,
            payments=payments,
            checkout_reference=checkout_reference,
        )
    except PaymentProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return PaymentCheckoutSessionResponse(
        booking_group_id=booking_group_id,
        payments=[PaymentResponse.model_validate(payment) for payment in payments],
        total_amount=total_payment_amount(payments),
        currency=payments[0].currency if payments else "INR",
        provider=payments[0].provider if payments else "mock",
        checkout_reference=checkout_reference,
        checkout_url=checkout_url(
            booking_group_id,
            checkout_reference,
            payments[0].provider if payments else "mock",
        ),
        checkout_payload=checkout_payload,
    )


@app.get(
    "/booking-groups/{booking_group_id}/receipt",
    response_model=BookingGroupReceiptResponse,
)
def get_booking_group_receipt(
    booking_group_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookingGroupReceiptResponse:
    bookings = get_visible_booking_group(
        session,
        booking_group_id=booking_group_id,
        current_user=current_user,
    )
    booking_ids = [booking.id for booking in bookings]
    payments = session.exec(
        select(Payment)
        .where(Payment.booking_id.in_(booking_ids))
        .order_by(Payment.created_at)
    ).all()
    settled_payments = [
        payment
        for payment in payments
        if payment.status in {PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED}
    ]
    if not settled_payments:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Receipt is available after payment succeeds",
        )

    total_paid = sum(
        (
            payment.amount
            for payment in settled_payments
            if payment.status == PaymentStatus.SUCCEEDED
        ),
        Decimal("0.00"),
    )
    total_refunded = sum(
        (
            payment.amount
            for payment in settled_payments
            if payment.status == PaymentStatus.REFUNDED
        ),
        Decimal("0.00"),
    )
    paid_at_values = [
        payment.paid_at
        for payment in settled_payments
        if payment.paid_at is not None
    ]
    first_booking = bookings[0]
    workspaces = [booking.workspace for booking in bookings if booking.workspace is not None]
    unique_workspace_ids = {workspace.id for workspace in workspaces}
    workspace = workspaces[0] if len(unique_workspace_ids) == 1 and workspaces else None
    hosts = [workspace.owner for workspace in workspaces if workspace.owner is not None]
    unique_host_ids = {host.id for host in hosts}
    host = hosts[0] if len(unique_host_ids) == 1 and hosts else None
    customer = first_booking.user
    workspace_title = (
        workspace.title
        if workspace is not None
        else "Multiple workspaces"
        if len(unique_workspace_ids) > 1
        else "Workspace booking"
    )
    workspace_address = (
        ", ".join(
            item
            for item in [
                workspace.address_line if workspace is not None else None,
                workspace.city if workspace is not None else None,
                workspace.state if workspace is not None else None,
                workspace.country if workspace is not None else None,
            ]
            if item
        )
        or ("Multiple workspace addresses" if len(unique_workspace_ids) > 1 else "Address unavailable")
    )
    line_items = [
        {
            "booking_id": booking.id,
            "description": f"{booking.workspace.title if booking.workspace is not None else 'Workspace booking'} - {booking.start_at.date().isoformat()}",
            "service_date": booking.start_at.date(),
            "start_at": booking.start_at,
            "end_at": booking.end_at,
            "quantity": 1,
            "unit_price": booking.total_price,
            "amount": booking.total_price,
        }
        for booking in bookings
    ]
    payment_summary = [
        {
            "payment_id": payment.id,
            "provider": payment.provider,
            "provider_reference": payment.provider_reference,
            "provider_checkout_reference": payment.provider_checkout_reference,
            "status": payment.status,
            "amount": payment.amount,
            "paid_at": payment.paid_at,
            "refunded_at": payment.refunded_at,
        }
        for payment in settled_payments
    ]
    subtotal = sum((booking.total_price for booking in bookings), Decimal("0.00"))
    return BookingGroupReceiptResponse(
        booking_group_id=booking_group_id,
        receipt_number=f"FS-{first_booking.created_at:%Y}-{str(booking_group_id)[:8].upper()}",
        supplier={
            "name": "FlexiStay",
            "email": settings.email_from,
            "address": "India",
        },
        customer={
            "name": customer.full_name if customer is not None else "Guest",
            "email": customer.email if customer is not None else None,
            "address": None,
        },
        host={
            "name": host.full_name if host is not None else "Host",
            "email": host.email if host is not None else None,
            "address": workspace_address,
        },
        workspace_title=workspace_title,
        workspace_address=workspace_address,
        line_items=line_items,
        payment_summary=payment_summary,
        bookings=[BookingResponse.model_validate(booking) for booking in bookings],
        payments=[PaymentResponse.model_validate(payment) for payment in settled_payments],
        subtotal=subtotal,
        tax_total=Decimal("0.00"),
        total_paid=total_paid,
        total_refunded=total_refunded,
        net_paid=total_paid - total_refunded,
        currency=settled_payments[0].currency,
        issued_at=utc_now(),
        paid_at=min(paid_at_values) if paid_at_values else None,
    )


@app.post("/payments/webhooks/{provider}", response_model=PaymentWebhookResponse)
async def handle_payment_webhook(
    provider: str,
    request: Request,
    session: Session = Depends(get_session),
) -> PaymentWebhookResponse:
    normalized_provider = provider.strip().lower()
    payload = await request.body()
    signature_header = (
        request.headers.get("X-Mock-Signature")
        or request.headers.get("X-Razorpay-Signature")
        or request.headers.get("Stripe-Signature")
    )
    if not verify_payment_webhook_signature(
        provider=normalized_provider,
        payload=payload,
        signature_header=signature_header,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid payment webhook signature",
        )

    try:
        body = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook JSON payload",
        ) from exc

    raw_event = body.get("event")
    event = raw_event
    provider_reference = body.get("provider_reference")
    provider_checkout_reference = None
    if normalized_provider == "razorpay":
        payment_entity = (
            body.get("payload", {})
            .get("payment", {})
            .get("entity", {})
        )
        if raw_event == "payment.captured":
            event = "payment.succeeded"
        elif raw_event == "payment.failed":
            event = "payment.failed"
        provider_reference = payment_entity.get("id")
        provider_checkout_reference = payment_entity.get("order_id")
        provider_amount = payment_entity.get("amount")
        provider_currency = payment_entity.get("currency")

    if event not in {"payment.succeeded", "payment.failed"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported payment webhook event",
        )

    if normalized_provider == "razorpay":
        if not isinstance(provider_checkout_reference, str) or not provider_checkout_reference:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Razorpay order_id is required",
            )
    elif not isinstance(provider_reference, str) or not provider_reference:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider_reference is required",
        )

    if normalized_provider == "razorpay":
        payments = session.exec(
            select(Payment)
            .where(Payment.provider_checkout_reference == provider_checkout_reference)
            .order_by(Payment.created_at)
        ).all()
    else:
        payment = session.exec(
            select(Payment).where(Payment.provider_reference == provider_reference)
        ).first()
        payments = [payment] if payment is not None else []
    payments = [payment for payment in payments if payment.provider == normalized_provider]
    if not payments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )

    if event == "payment.succeeded" and normalized_provider == "razorpay":
        expected_amount = amount_to_minor_units(total_payment_amount(payments))
        expected_currency = payments[0].currency if payments else "INR"
        if provider_amount != expected_amount:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Razorpay payment amount does not match booking total",
            )
        if provider_currency != expected_currency:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Razorpay payment currency does not match booking currency",
            )

    booking_pairs = []
    for payment in payments:
        booking = session.get(Booking, payment.booking_id)
        if booking is not None:
            booking_pairs.append((payment, booking))
    if not booking_pairs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )
    first_payment, first_booking = booking_pairs[0]
    response_reference = (
        provider_checkout_reference
        if normalized_provider == "razorpay" and isinstance(provider_checkout_reference, str)
        else provider_reference
    )

    if all(
        payment.status == PaymentStatus.SUCCEEDED and booking.status == BookingStatus.CONFIRMED
        for payment, booking in booking_pairs
    ):
        return PaymentWebhookResponse(
            provider=normalized_provider,
            provider_reference=response_reference,
            payment_id=first_payment.id,
            booking_id=first_booking.id,
            status=first_payment.status,
            processed=False,
        )
    if event == "payment.failed" and all(
        payment.status == PaymentStatus.FAILED for payment, _booking in booking_pairs
    ):
        return PaymentWebhookResponse(
            provider=normalized_provider,
            provider_reference=response_reference,
            payment_id=first_payment.id,
            booking_id=first_booking.id,
            status=first_payment.status,
            processed=False,
        )

    if event == "payment.failed":
        processed = False
        for payment, booking in booking_pairs:
            if payment.status != PaymentStatus.PENDING:
                continue
            mark_payment_failed(payment)
            session.add(payment)
            processed = True
            record_audit_event(
                session,
                actor_user_id=None,
                action=AuditAction.PAYMENT_FAILED,
                entity_type="payment",
                entity_id=payment.id,
                details={
                    "booking_id": str(booking.id),
                    "booking_group_id": str(booking.booking_group_id),
                    "provider": payment.provider,
                    "provider_reference": payment.provider_reference,
                    "provider_checkout_reference": payment.provider_checkout_reference,
                    "amount": str(payment.amount),
                    "currency": payment.currency,
                },
            )
        session.commit()
        session.refresh(first_payment)
        return PaymentWebhookResponse(
            provider=normalized_provider,
            provider_reference=response_reference,
            payment_id=first_payment.id,
            booking_id=first_booking.id,
            status=first_payment.status,
            processed=processed,
        )

    now = utc_now()
    processed = False
    for payment, booking in booking_pairs:
        payment_changed = payment.status != PaymentStatus.SUCCEEDED
        booking_changed = booking.status == BookingStatus.PENDING
        if payment_changed:
            mark_payment_succeeded(payment, now)
        if booking_changed:
            booking.status = BookingStatus.CONFIRMED
        session.add(payment)
        session.add(booking)
        if not payment_changed and not booking_changed:
            continue
        processed = True
        record_audit_event(
            session,
            actor_user_id=None,
            action=AuditAction.BOOKING_PAID,
            entity_type="payment",
            entity_id=payment.id,
            details={
                "booking_id": str(booking.id),
                "booking_group_id": str(booking.booking_group_id),
                "provider": payment.provider,
                "provider_reference": payment.provider_reference,
                "provider_checkout_reference": payment.provider_checkout_reference,
                "amount": str(payment.amount),
                "currency": payment.currency,
            },
        )
    session.commit()
    session.refresh(first_payment)

    return PaymentWebhookResponse(
        provider=normalized_provider,
        provider_reference=response_reference,
        payment_id=first_payment.id,
        booking_id=first_booking.id,
        status=first_payment.status,
        processed=processed,
    )


@app.post("/booking-groups/{booking_group_id}/payment-confirm", response_model=BookingGroupCheckoutResponse)
def confirm_booking_group_payment(
    booking_group_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookingGroupCheckoutResponse:
    ensure_manual_payment_confirmation_allowed()
    expire_stale_pending_bookings(session)
    bookings = session.exec(
        select(Booking)
        .where(Booking.booking_group_id == booking_group_id)
        .order_by(Booking.start_at)
    ).all()
    if not bookings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking group not found",
        )

    for booking in bookings:
        if booking.user_id != current_user.id and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the booking owner can pay for this booking",
            )

    if all(booking.status == BookingStatus.CONFIRMED for booking in bookings):
        payments = []
        for booking in bookings:
            payments.extend(get_succeeded_payments(session, booking.id))
        return BookingGroupCheckoutResponse(
            booking_group_id=booking_group_id,
            bookings=[BookingResponse.model_validate(booking) for booking in bookings],
            payments=[PaymentResponse.model_validate(payment) for payment in payments],
            total_paid=sum((payment.amount for payment in payments), Decimal("0.00")),
        )

    payments = []
    for booking in bookings:
        ensure_payable_booking_owner(booking, current_user)
        payment = get_pending_payment(session, booking.id)
        if payment is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Create a payment intent before confirming payment",
            )
        payments.append(payment)

    now = utc_now()
    for booking, payment in zip(bookings, payments):
        mark_payment_succeeded(payment, now)
        booking.status = BookingStatus.CONFIRMED
        session.add(payment)
        session.add(booking)

    total_paid = sum((payment.amount for payment in payments), Decimal("0.00"))
    record_audit_event(
        session,
        actor_user_id=current_user.id,
        action=AuditAction.BOOKING_PAID,
        entity_type="booking_group",
        entity_id=booking_group_id,
        details={
            "booking_count": len(bookings),
            "payment_count": len(payments),
            "total_paid": str(total_paid),
            "currency": payments[0].currency if payments else "INR",
        },
    )
    session.commit()
    for booking in bookings:
        session.refresh(booking)
    for payment in payments:
        session.refresh(payment)

    return BookingGroupCheckoutResponse(
        booking_group_id=booking_group_id,
        bookings=[BookingResponse.model_validate(booking) for booking in bookings],
        payments=[PaymentResponse.model_validate(payment) for payment in payments],
        total_paid=total_paid,
    )


@app.post("/bookings/{booking_id}/payment-confirm", response_model=BookingResponse)
def confirm_booking_payment(
    booking_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Booking:
    ensure_manual_payment_confirmation_allowed()
    expire_stale_pending_bookings(session)
    booking = get_visible_booking(booking_id, current_user, session)
    if booking.user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the booking owner can confirm payment",
        )
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cancelled bookings cannot be paid",
        )
    if booking.status == BookingStatus.EXPIRED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking hold has expired",
        )
    if booking.status == BookingStatus.CONFIRMED:
        return booking

    payment = get_pending_payment(session, booking.id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Create a payment intent before confirming payment",
        )

    mark_payment_succeeded(payment, utc_now())
    booking.status = BookingStatus.CONFIRMED
    session.add(payment)
    session.add(booking)
    record_audit_event(
        session,
        actor_user_id=current_user.id,
        action=AuditAction.BOOKING_PAID,
        entity_type="booking",
        entity_id=booking.id,
        details={
            "booking_group_id": str(booking.booking_group_id),
            "payment_id": str(payment.id),
            "total_paid": str(payment.amount),
            "currency": payment.currency,
        },
    )
    session.commit()
    session.refresh(booking)
    return booking


@app.get("/bookings/mine", response_model=BookingPageResponse)
def list_my_bookings(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookingPageResponse:
    expire_stale_pending_bookings(session)
    total = session.exec(
        select(func.count(Booking.id)).where(Booking.user_id == current_user.id)
    ).one()
    items = session.exec(
        select(Booking)
        .where(Booking.user_id == current_user.id)
        .order_by(Booking.start_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return BookingPageResponse(
        items=[BookingResponse.model_validate(booking) for booking in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/bookings/host", response_model=BookingPageResponse)
def list_host_workspace_bookings(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_host_user),
    session: Session = Depends(get_session),
) -> BookingPageResponse:
    expire_stale_pending_bookings(session)
    query = (
        select(Booking)
        .join(Workspace)
        .where(Workspace.owner_id == current_user.id)
    )
    count_query = (
        select(func.count(Booking.id))
        .join(Workspace)
        .where(Workspace.owner_id == current_user.id)
    )

    if current_user.role == UserRole.ADMIN:
        query = select(Booking)
        count_query = select(func.count(Booking.id))

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Booking.start_at.desc()).offset(offset).limit(limit)
    ).all()

    return BookingPageResponse(
        items=[BookingResponse.model_validate(booking) for booking in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/bookings/host/revenue", response_model=HostRevenueSummaryResponse)
def get_host_revenue_summary(
    current_user: User = Depends(require_host_user),
    session: Session = Depends(get_session),
) -> HostRevenueSummaryResponse:
    expire_stale_pending_bookings(session)

    paid_query = (
        select(func.coalesce(func.sum(Payment.amount), 0), func.count(Payment.id))
        .join(Booking, Payment.booking_id == Booking.id)
        .join(Workspace, Booking.workspace_id == Workspace.id)
        .where(Payment.status == PaymentStatus.SUCCEEDED)
    )
    refunded_query = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Booking, Payment.booking_id == Booking.id)
        .join(Workspace, Booking.workspace_id == Workspace.id)
        .where(Payment.status == PaymentStatus.REFUNDED)
    )
    pending_value_query = (
        select(func.coalesce(func.sum(Booking.total_price), 0))
        .join(Workspace, Booking.workspace_id == Workspace.id)
        .where(Booking.status == BookingStatus.PENDING)
    )
    confirmed_count_query = (
        select(func.count(Booking.id))
        .join(Workspace, Booking.workspace_id == Workspace.id)
        .where(Booking.status == BookingStatus.CONFIRMED)
    )
    cancelled_count_query = (
        select(func.count(Booking.id))
        .join(Workspace, Booking.workspace_id == Workspace.id)
        .where(Booking.status == BookingStatus.CANCELLED)
    )
    pending_count_query = (
        select(func.count(Booking.id))
        .join(Workspace, Booking.workspace_id == Workspace.id)
        .where(Booking.status == BookingStatus.PENDING)
    )

    if current_user.role != UserRole.ADMIN:
        paid_query = paid_query.where(Workspace.owner_id == current_user.id)
        refunded_query = refunded_query.where(Workspace.owner_id == current_user.id)
        pending_value_query = pending_value_query.where(Workspace.owner_id == current_user.id)
        confirmed_count_query = confirmed_count_query.where(Workspace.owner_id == current_user.id)
        cancelled_count_query = cancelled_count_query.where(Workspace.owner_id == current_user.id)
        pending_count_query = pending_count_query.where(Workspace.owner_id == current_user.id)

    total_paid, paid_payment_count = session.exec(paid_query).one()
    total_refunded = session.exec(refunded_query).one()
    pending_hold_value = session.exec(pending_value_query).one()
    confirmed_booking_count = session.exec(confirmed_count_query).one()
    cancelled_booking_count = session.exec(cancelled_count_query).one()
    pending_booking_count = session.exec(pending_count_query).one()
    total_paid_decimal = Decimal(str(total_paid))
    total_refunded_decimal = Decimal(str(total_refunded))
    gross_revenue = max(total_paid_decimal - total_refunded_decimal, Decimal("0.00"))
    commission_rate = Decimal(str(settings.platform_commission_rate))
    platform_commission = (gross_revenue * commission_rate).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    host_net_revenue = gross_revenue - platform_commission

    return HostRevenueSummaryResponse(
        total_paid=total_paid_decimal,
        total_refunded=total_refunded_decimal,
        gross_revenue=gross_revenue,
        platform_commission_rate=commission_rate,
        platform_commission=platform_commission,
        host_net_revenue=host_net_revenue,
        pending_payout=host_net_revenue,
        pending_hold_value=Decimal(str(pending_hold_value)),
        confirmed_booking_count=confirmed_booking_count,
        cancelled_booking_count=cancelled_booking_count,
        pending_booking_count=pending_booking_count,
        paid_payment_count=paid_payment_count,
    )


@app.get("/bookings/{booking_id}", response_model=BookingResponse)
def get_booking(
    booking_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Booking:
    expire_stale_pending_bookings(session)
    return get_visible_booking(booking_id, current_user, session)


@app.patch("/booking-groups/{booking_group_id}/cancel", response_model=BookingGroupCancelResponse)
def cancel_booking_group(
    booking_group_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> BookingGroupCancelResponse:
    expire_stale_pending_bookings(session)
    bookings = session.exec(
        select(Booking)
        .where(Booking.booking_group_id == booking_group_id)
        .order_by(Booking.start_at)
    ).all()
    if not bookings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking group not found",
        )

    for booking in bookings:
        if not can_access_booking(booking, current_user, session):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot access this booking",
            )

    now = utc_now()
    for booking in bookings:
        ensure_booking_can_be_cancelled(booking, now)

    refunded_payments = []
    non_refunded_booking_ids = []
    for booking in bookings:
        if booking.status == BookingStatus.CANCELLED:
            continue
        if booking_refund_allowed(booking, now):
            refunded_payments.extend(refund_succeeded_payments_for_booking(session, booking, now))
        elif booking.status == BookingStatus.CONFIRMED:
            non_refunded_booking_ids.append(str(booking.id))
        booking.status = BookingStatus.CANCELLED
        session.add(booking)

    total_refunded = sum((payment.amount for payment in refunded_payments), Decimal("0.00"))
    record_audit_event(
        session,
        actor_user_id=current_user.id,
        action=AuditAction.BOOKING_CANCELLED,
        entity_type="booking_group",
        entity_id=booking_group_id,
        details={
            "booking_count": len(bookings),
            "refunded_payment_count": len(refunded_payments),
            "total_refunded": str(total_refunded),
            "non_refunded_booking_ids": non_refunded_booking_ids,
            "policy": "Full refund is available more than 24 hours before check-in. Later cancellations are non-refundable.",
        },
    )
    if refunded_payments:
        record_audit_event(
            session,
            actor_user_id=current_user.id,
            action=AuditAction.PAYMENT_REFUNDED,
            entity_type="booking_group",
            entity_id=booking_group_id,
            details={
                "payment_ids": [str(payment.id) for payment in refunded_payments],
                "total_refunded": str(total_refunded),
            },
        )
    session.commit()
    for booking in bookings:
        session.refresh(booking)
    for payment in refunded_payments:
        session.refresh(payment)

    return BookingGroupCancelResponse(
        booking_group_id=booking_group_id,
        bookings=[BookingResponse.model_validate(booking) for booking in bookings],
        refunded_payments=[PaymentResponse.model_validate(payment) for payment in refunded_payments],
        total_refunded=total_refunded,
    )


@app.patch("/bookings/{booking_id}/cancel", response_model=BookingResponse)
def cancel_booking(
    booking_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Booking:
    expire_stale_pending_bookings(session)
    booking = get_visible_booking(booking_id, current_user, session)
    if booking.status == BookingStatus.CANCELLED:
        return booking

    now = utc_now()
    ensure_booking_can_be_cancelled(booking, now)
    refunded_payments = (
        refund_succeeded_payments_for_booking(session, booking, now)
        if booking_refund_allowed(booking, now)
        else []
    )
    total_refunded = sum((payment.amount for payment in refunded_payments), Decimal("0.00"))

    booking.status = BookingStatus.CANCELLED
    session.add(booking)
    record_audit_event(
        session,
        actor_user_id=current_user.id,
        action=AuditAction.BOOKING_CANCELLED,
        entity_type="booking",
        entity_id=booking.id,
        details={
            "booking_group_id": str(booking.booking_group_id),
            "refunded_payment_count": len(refunded_payments),
            "total_refunded": str(total_refunded),
            "policy": "Full refund is available more than 24 hours before check-in. Later cancellations are non-refundable.",
        },
    )
    if refunded_payments:
        record_audit_event(
            session,
            actor_user_id=current_user.id,
            action=AuditAction.PAYMENT_REFUNDED,
            entity_type="booking",
            entity_id=booking.id,
            details={
                "payment_ids": [str(payment.id) for payment in refunded_payments],
                "total_refunded": str(total_refunded),
            },
        )
    session.commit()
    session.refresh(booking)
    return booking
