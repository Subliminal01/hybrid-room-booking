import hashlib
import hmac
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlmodel import Session, select

from app.config import get_settings
from app.models import Booking, Payment, PaymentStatus, Workspace


MOCK_PAYMENT_PROVIDER = "mock"
DEV_MOCK_WEBHOOK_SECRET = "dev-mock-webhook-secret"


def provider_reference(provider: str = MOCK_PAYMENT_PROVIDER) -> str:
    return f"{provider}_{uuid4().hex}"


def checkout_reference_for_payments(payments: list[Payment]) -> str:
    joined_references = "_".join(sorted(payment.provider_reference for payment in payments))
    digest = hashlib.sha256(joined_references.encode("utf-8")).hexdigest()[:24]
    return f"checkout_{digest}"


def payment_provider() -> str:
    return get_settings().payment_provider


def checkout_url(booking_group_id: UUID, checkout_reference: str, provider: str) -> str:
    if provider == "mock":
        return f"/checkout/mock/{booking_group_id}?reference={checkout_reference}"
    return f"/checkout/{provider}/{booking_group_id}?reference={checkout_reference}"


def total_payment_amount(payments: list[Payment]) -> Decimal:
    return sum((payment.amount for payment in payments), Decimal("0.00"))


def payment_webhook_secret(provider: str) -> str | None:
    settings = get_settings()
    if provider == "mock":
        return DEV_MOCK_WEBHOOK_SECRET
    if provider == "razorpay":
        return settings.razorpay_webhook_secret
    if provider == "stripe":
        return settings.stripe_webhook_secret
    return None


def hmac_sha256_hex(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_payment_webhook_signature(
    *,
    provider: str,
    payload: bytes,
    signature_header: str | None,
) -> bool:
    secret = payment_webhook_secret(provider)
    if not secret or not signature_header:
        return False

    if provider in {"mock", "razorpay"}:
        expected = hmac_sha256_hex(secret, payload)
        return hmac.compare_digest(expected, signature_header)

    if provider == "stripe":
        signature_parts = dict(
            part.split("=", 1)
            for part in signature_header.split(",")
            if "=" in part
        )
        timestamp = signature_parts.get("t")
        signature = signature_parts.get("v1")
        if not timestamp or not signature:
            return False
        expected = hmac_sha256_hex(secret, f"{timestamp}.".encode("utf-8") + payload)
        return hmac.compare_digest(expected, signature)

    return False


def get_pending_payment(session: Session, booking_id) -> Payment | None:
    return session.exec(
        select(Payment).where(
            Payment.booking_id == booking_id,
            Payment.status == PaymentStatus.PENDING,
        )
    ).first()


def get_succeeded_payments(session: Session, booking_id) -> list[Payment]:
    return session.exec(
        select(Payment).where(
            Payment.booking_id == booking_id,
            Payment.status == PaymentStatus.SUCCEEDED,
        )
    ).all()


def get_or_create_pending_payment(session: Session, booking: Booking) -> Payment:
    existing_payment = get_pending_payment(session, booking.id)
    if existing_payment is not None:
        return existing_payment

    workspace = session.get(Workspace, booking.workspace_id)
    provider = payment_provider()
    payment = Payment(
        booking_id=booking.id,
        amount=booking.total_price,
        currency=workspace.currency if workspace is not None else "INR",
        provider=provider,
        provider_reference=provider_reference(provider),
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)
    return payment


def mark_payment_succeeded(payment: Payment, paid_at: datetime) -> None:
    payment.status = PaymentStatus.SUCCEEDED
    payment.paid_at = paid_at


def mark_payment_failed(payment: Payment) -> None:
    payment.status = PaymentStatus.FAILED


def refund_succeeded_payments_for_booking(
    session: Session,
    booking: Booking,
    refunded_at: datetime,
) -> list[Payment]:
    succeeded_payments = get_succeeded_payments(session, booking.id)
    for payment in succeeded_payments:
        payment.status = PaymentStatus.REFUNDED
        payment.refunded_at = refunded_at
        session.add(payment)
    return succeeded_payments
