import hashlib
import hmac
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlmodel import Session, select

from app.config import get_settings
from app.models import Booking, Payment, PaymentStatus, Workspace


MOCK_PAYMENT_PROVIDER = "mock"
DEV_MOCK_WEBHOOK_SECRET = "dev-mock-webhook-secret"
RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"


class PaymentProviderError(RuntimeError):
    pass


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


def amount_to_minor_units(amount: Decimal) -> int:
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def existing_checkout_reference(payments: list[Payment]) -> str | None:
    references = {
        payment.provider_checkout_reference
        for payment in payments
        if payment.provider_checkout_reference
    }
    if len(references) == 1:
        return references.pop()
    return None


def create_razorpay_order(
    *,
    booking_group_id: UUID,
    checkout_reference: str,
    payments: list[Payment],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise PaymentProviderError("Razorpay credentials are not configured")

    amount = total_payment_amount(payments)
    currency = payments[0].currency if payments else "INR"
    payload = {
        "amount": amount_to_minor_units(amount),
        "currency": currency,
        "receipt": checkout_reference[:40],
        "notes": {
            "booking_group_id": str(booking_group_id),
            "checkout_reference": checkout_reference,
            "payment_ids": ",".join(str(payment.id) for payment in payments),
        },
    }
    try:
        response = httpx.post(
            RAZORPAY_ORDERS_URL,
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise PaymentProviderError("Could not create Razorpay order") from exc
    return response.json()


def prepare_provider_checkout(
    *,
    session: Session,
    booking_group_id: UUID,
    payments: list[Payment],
    checkout_reference: str,
) -> dict[str, Any]:
    provider = payments[0].provider if payments else "mock"
    if provider != "razorpay":
        return {}

    existing_reference = existing_checkout_reference(payments)
    if existing_reference:
        return {
            "key_id": get_settings().razorpay_key_id,
            "order_id": existing_reference,
            "amount": amount_to_minor_units(total_payment_amount(payments)),
            "currency": payments[0].currency if payments else "INR",
        }

    order = create_razorpay_order(
        booking_group_id=booking_group_id,
        checkout_reference=checkout_reference,
        payments=payments,
    )
    order_id = order.get("id")
    if not isinstance(order_id, str) or not order_id:
        raise PaymentProviderError("Razorpay order response did not include an id")
    for payment in payments:
        payment.provider_checkout_reference = order_id
        session.add(payment)
    session.commit()
    for payment in payments:
        session.refresh(payment)
    return {
        "key_id": get_settings().razorpay_key_id,
        "order_id": order_id,
        "amount": order.get("amount", amount_to_minor_units(total_payment_amount(payments))),
        "currency": order.get("currency", payments[0].currency if payments else "INR"),
    }


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
