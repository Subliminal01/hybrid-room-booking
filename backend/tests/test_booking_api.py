import hashlib
import hmac
import json

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from app.auth_service import issue_user_session, register_user as register_user_service
from app.database import get_session
from app.main import app
from app.config import get_settings
from app.models import UserRole


def make_session_override():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    return override_get_session


def reset_settings_cache():
    get_settings.cache_clear()


def mock_webhook_signature(payload: bytes) -> str:
    return hmac.new(
        b"dev-mock-webhook-secret",
        payload,
        hashlib.sha256,
    ).hexdigest()


def razorpay_webhook_signature(payload: bytes) -> str:
    return hmac.new(
        b"rzp_webhook_secret",
        payload,
        hashlib.sha256,
    ).hexdigest()


def register_user(client: TestClient, *, email: str, role: str = "worker") -> dict:
    if role == "admin":
        session_override = app.dependency_overrides[get_session]
        session_generator = session_override()
        session = next(session_generator)
        try:
            user = register_user_service(
                session,
                email=email,
                password="strong-password",
                full_name="Test User",
                role=UserRole.ADMIN,
            )
            access_token, refresh_token = issue_user_session(session, user)
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role.value,
                },
            }
        finally:
            session_generator.close()

    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "strong-password",
            "full_name": "Test User",
            "role": role,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_workspace(
    client: TestClient,
    *,
    host_token: str,
    title: str = "Koramangala work room",
    daily_price: str = "850.00",
    admin_email: str = "admin-review@example.com",
) -> dict:
    response = client.post(
        "/workspaces",
        json={
            "title": title,
            "description": "Quiet room for hybrid workdays",
            "address_line": "12 Residency Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "daily_price": daily_price,
            "amenities": {"wifi": True, "desk": True},
        },
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert response.status_code == 201
    workspace = response.json()
    admin = register_user(client, email=admin_email, role="admin")
    review_response = client.patch(
        f"/admin/workspaces/{workspace['id']}/review",
        json={"review_status": "approved"},
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )
    assert review_response.status_code == 200
    return review_response.json()


def booking_payload(workspace_id: str, **overrides):
    payload = {
        "workspace_id": workspace_id,
        "rota_label": "June office rota",
        "slots": [
            {
                "start_at": "2026-06-15T09:00:00+05:30",
                "end_at": "2026-06-15T18:00:00+05:30",
            },
            {
                "start_at": "2026-06-17T09:00:00+05:30",
                "end_at": "2026-06-17T18:00:00+05:30",
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_authenticated_booking_uses_current_user_id():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])

    response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["total_price"] == "1700.00"
    assert {booking["user_id"] for booking in body["bookings"]} == {worker["user"]["id"]}
    assert {booking["status"] for booking in body["bookings"]} == {"pending"}

    app.dependency_overrides.clear()


def test_booking_create_idempotency_key_replays_same_response():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    headers = {
        "Authorization": f"Bearer {worker['access_token']}",
        "Idempotency-Key": "june-rota-submit-1",
    }

    first_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers=headers,
    )
    second_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers=headers,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert second_response.json() == first_response.json()

    history_response = client.get(
        "/bookings/mine",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert history_response.status_code == 200
    assert history_response.json()["total"] == 2

    app.dependency_overrides.clear()


def test_booking_create_idempotency_key_rejects_different_payload():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    headers = {
        "Authorization": f"Bearer {worker['access_token']}",
        "Idempotency-Key": "june-rota-submit-1",
    }
    first_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers=headers,
    )

    second_response = client.post(
        "/bookings",
        json=booking_payload(
            workspace["id"],
            slots=[
                {
                    "start_at": "2026-06-19T09:00:00+05:30",
                    "end_at": "2026-06-19T18:00:00+05:30",
                },
            ],
        ),
        headers=headers,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert (
        second_response.json()["detail"]
        == "Idempotency key was already used with a different booking request"
    )

    app.dependency_overrides.clear()


def test_booking_payment_flow_confirms_pending_booking():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]

    intent_response = client.post(
        f"/bookings/{booking['id']}/payment-intent",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert intent_response.status_code == 200
    intent = intent_response.json()
    assert intent["amount"] == "850.00"
    assert intent["status"] == "pending"
    assert intent["provider"] == "mock"

    duplicate_intent = client.post(
        f"/bookings/{booking['id']}/payment-intent",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert duplicate_intent.status_code == 200
    assert duplicate_intent.json()["id"] == intent["id"]

    confirm_response = client.post(
        f"/bookings/{booking['id']}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "confirmed"

    app.dependency_overrides.clear()


def test_booking_group_payment_confirms_all_rota_days():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    bookings = booking_response.json()["bookings"]
    booking_group_id = bookings[0]["booking_group_id"]

    assert {booking["booking_group_id"] for booking in bookings} == {booking_group_id}

    intent_response = client.post(
        f"/booking-groups/{booking_group_id}/payment-intent",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert intent_response.status_code == 200
    payments = intent_response.json()
    assert len(payments) == 2
    assert sum(float(payment["amount"]) for payment in payments) == 1700.0

    confirm_response = client.post(
        f"/booking-groups/{booking_group_id}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert confirm_response.status_code == 200
    body = confirm_response.json()
    assert body["booking_group_id"] == booking_group_id
    assert body["total_paid"] == "1700.00"
    assert {booking["status"] for booking in body["bookings"]} == {"confirmed"}
    assert {payment["status"] for payment in body["payments"]} == {"succeeded"}

    app.dependency_overrides.clear()


def test_booking_itinerary_creates_one_group_across_multiple_workspaces():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    first_workspace = create_workspace(
        client,
        host_token=host["access_token"],
        title="Monday focus room",
    )
    second_workspace = create_workspace(
        client,
        host_token=host["access_token"],
        title="Wednesday quiet room",
        daily_price="650.00",
        admin_email="admin-review-second@example.com",
    )

    response = client.post(
        "/booking-itineraries",
        json={
            "rota_label": "Split office rota",
            "items": [
                {
                    "workspace_id": first_workspace["id"],
                    "slots": [
                        {
                            "start_at": "2026-06-15T09:00:00+05:30",
                            "end_at": "2026-06-15T18:00:00+05:30",
                        }
                    ],
                },
                {
                    "workspace_id": second_workspace["id"],
                    "slots": [
                        {
                            "start_at": "2026-06-17T09:00:00+05:30",
                            "end_at": "2026-06-17T18:00:00+05:30",
                        }
                    ],
                },
            ],
        },
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 201
    body = response.json()
    bookings = body["bookings"]
    booking_group_id = bookings[0]["booking_group_id"]
    assert body["total_price"] == "1500.00"
    assert len(bookings) == 2
    assert {booking["booking_group_id"] for booking in bookings} == {booking_group_id}
    assert {booking["workspace_id"] for booking in bookings} == {
        first_workspace["id"],
        second_workspace["id"],
    }

    checkout_response = client.post(
        f"/booking-groups/{booking_group_id}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert checkout_response.status_code == 200
    checkout = checkout_response.json()
    assert checkout["total_amount"] == "1500.00"
    assert len(checkout["payments"]) == 2

    app.dependency_overrides.clear()


def test_booking_group_receipt_available_after_payment():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking_group_id = booking_response.json()["bookings"][0]["booking_group_id"]
    intent_response = client.post(
        f"/booking-groups/{booking_group_id}/payment-intent",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert intent_response.status_code == 200
    confirm_response = client.post(
        f"/booking-groups/{booking_group_id}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert confirm_response.status_code == 200

    receipt_response = client.get(
        f"/booking-groups/{booking_group_id}/receipt",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert receipt_response.status_code == 200
    body = receipt_response.json()
    assert body["booking_group_id"] == booking_group_id
    assert body["total_paid"] == "1700.00"
    assert body["total_refunded"] == "0.00"
    assert body["net_paid"] == "1700.00"
    assert body["currency"] == "INR"
    assert body["receipt_number"].startswith("FS-")
    assert body["supplier"]["name"] == "FlexiStay"
    assert body["customer"]["email"] == "worker@example.com"
    assert body["host"]["email"] == "host@example.com"
    assert body["workspace_title"] == workspace["title"]
    assert "Bengaluru" in body["workspace_address"]
    assert body["subtotal"] == "1700.00"
    assert body["tax_total"] == "0.00"
    assert len(body["bookings"]) == 2
    assert len(body["payments"]) == 2
    assert len(body["line_items"]) == 2
    assert len(body["payment_summary"]) == 2
    assert {item["amount"] for item in body["line_items"]} == {"850.00"}
    assert {payment["status"] for payment in body["payments"]} == {"succeeded"}

    host_receipt_response = client.get(
        f"/booking-groups/{booking_group_id}/receipt",
        headers={"Authorization": f"Bearer {host['access_token']}"},
    )
    assert host_receipt_response.status_code == 200

    app.dependency_overrides.clear()


def test_booking_group_receipt_requires_successful_payment():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking_group_id = booking_response.json()["bookings"][0]["booking_group_id"]

    receipt_response = client.get(
        f"/booking-groups/{booking_group_id}/receipt",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert receipt_response.status_code == 409
    assert receipt_response.json()["detail"] == "Receipt is available after payment succeeds"

    app.dependency_overrides.clear()


def test_booking_group_checkout_session_returns_provider_metadata():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking_group_id = booking_response.json()["bookings"][0]["booking_group_id"]

    response = client.post(
        f"/booking-groups/{booking_group_id}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["booking_group_id"] == booking_group_id
    assert body["total_amount"] == "1700.00"
    assert body["currency"] == "INR"
    assert body["provider"] == "mock"
    assert body["checkout_reference"].startswith("checkout_")
    assert body["checkout_url"].startswith(f"/checkout/mock/{booking_group_id}")
    assert len(body["payments"]) == 2
    assert {payment["status"] for payment in body["payments"]} == {"pending"}

    app.dependency_overrides.clear()


def test_booking_group_checkout_session_reuses_pending_payments():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking_group_id = booking_response.json()["bookings"][0]["booking_group_id"]

    first_response = client.post(
        f"/booking-groups/{booking_group_id}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    second_response = client.post(
        f"/booking-groups/{booking_group_id}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["checkout_reference"] == first_response.json()["checkout_reference"]
    assert [payment["id"] for payment in second_response.json()["payments"]] == [
        payment["id"] for payment in first_response.json()["payments"]
    ]

    app.dependency_overrides.clear()


def test_razorpay_checkout_session_creates_order(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "order_test_123",
                "amount": 170000,
                "currency": "INR",
            }

    requests = []

    def fake_post(url, *, auth, json, timeout):
        requests.append({"url": url, "auth": auth, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_test_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "rzp_webhook_secret")
    reset_settings_cache()
    monkeypatch.setattr("app.payment_service.httpx.post", fake_post)
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking_group_id = booking_response.json()["bookings"][0]["booking_group_id"]

    response = client.post(
        f"/booking-groups/{booking_group_id}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "razorpay"
    assert body["checkout_payload"] == {
        "key_id": "rzp_test_key",
        "order_id": "order_test_123",
        "amount": 170000,
        "currency": "INR",
    }
    assert {payment["provider_checkout_reference"] for payment in body["payments"]} == {
        "order_test_123"
    }
    assert requests[0]["url"] == "https://api.razorpay.com/v1/orders"
    assert requests[0]["auth"] == ("rzp_test_key", "rzp_test_secret")
    assert requests[0]["json"]["amount"] == 170000
    assert requests[0]["json"]["currency"] == "INR"
    assert requests[0]["json"]["notes"]["booking_group_id"] == booking_group_id

    app.dependency_overrides.clear()
    reset_settings_cache()


def test_razorpay_webhook_confirms_all_rota_days(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "order_test_group",
                "amount": 170000,
                "currency": "INR",
            }

    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_test_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "rzp_webhook_secret")
    reset_settings_cache()
    monkeypatch.setattr(
        "app.payment_service.httpx.post",
        lambda url, *, auth, json, timeout: FakeResponse(),
    )
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    bookings = booking_response.json()["bookings"]
    booking_group_id = bookings[0]["booking_group_id"]
    checkout_response = client.post(
        f"/booking-groups/{booking_group_id}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert checkout_response.status_code == 200
    payload = json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test_group",
                        "order_id": "order_test_group",
                        "amount": 170000,
                        "currency": "INR",
                    },
                },
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")

    response = client.post(
        "/payments/webhooks/razorpay",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": razorpay_webhook_signature(payload),
        },
    )

    assert response.status_code == 200
    assert response.json()["processed"] is True
    for booking in bookings:
        history_response = client.get(
            f"/bookings/{booking['id']}",
            headers={"Authorization": f"Bearer {worker['access_token']}"},
        )
        assert history_response.status_code == 200
        assert history_response.json()["status"] == "confirmed"

    app.dependency_overrides.clear()
    reset_settings_cache()


def test_razorpay_webhook_rejects_amount_mismatch(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "order_test_group",
                "amount": 170000,
                "currency": "INR",
            }

    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_test_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "rzp_webhook_secret")
    reset_settings_cache()
    monkeypatch.setattr(
        "app.payment_service.httpx.post",
        lambda url, *, auth, json, timeout: FakeResponse(),
    )
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking_group_id = booking_response.json()["bookings"][0]["booking_group_id"]
    checkout_response = client.post(
        f"/booking-groups/{booking_group_id}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert checkout_response.status_code == 200
    payload = json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test_group",
                        "order_id": "order_test_group",
                        "amount": 169999,
                        "currency": "INR",
                    },
                },
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")

    response = client.post(
        "/payments/webhooks/razorpay",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": razorpay_webhook_signature(payload),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Razorpay payment amount does not match booking total"

    app.dependency_overrides.clear()
    reset_settings_cache()


def test_payment_webhook_confirms_signed_payment_success():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(
            workspace["id"],
            slots=[
                {
                    "start_at": "2026-06-20T09:00:00+05:30",
                    "end_at": "2026-06-20T18:00:00+05:30",
                },
            ],
        ),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]
    checkout_response = client.post(
        f"/booking-groups/{booking['booking_group_id']}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    payment = checkout_response.json()["payments"][0]
    payload = json.dumps(
        {
            "event": "payment.succeeded",
            "provider_reference": payment["provider_reference"],
        },
        separators=(",", ":"),
    ).encode("utf-8")

    response = client.post(
        "/payments/webhooks/mock",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Mock-Signature": mock_webhook_signature(payload),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["status"] == "succeeded"

    history_response = client.get(
        f"/bookings/{booking['id']}",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert history_response.status_code == 200
    assert history_response.json()["status"] == "confirmed"

    app.dependency_overrides.clear()


def test_payment_webhook_rejects_invalid_signature():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    payload = json.dumps(
        {
            "event": "payment.succeeded",
            "provider_reference": "mock_missing",
        },
        separators=(",", ":"),
    ).encode("utf-8")

    response = client.post(
        "/payments/webhooks/mock",
        content=payload,
        headers={"Content-Type": "application/json", "X-Mock-Signature": "bad"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid payment webhook signature"

    app.dependency_overrides.clear()


def test_payment_webhook_is_idempotent_after_success():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(
            workspace["id"],
            slots=[
                {
                    "start_at": "2026-06-21T09:00:00+05:30",
                    "end_at": "2026-06-21T18:00:00+05:30",
                },
            ],
        ),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]
    checkout_response = client.post(
        f"/booking-groups/{booking['booking_group_id']}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    payment = checkout_response.json()["payments"][0]
    payload = json.dumps(
        {
            "event": "payment.succeeded",
            "provider_reference": payment["provider_reference"],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Mock-Signature": mock_webhook_signature(payload),
    }

    first_response = client.post("/payments/webhooks/mock", content=payload, headers=headers)
    second_response = client.post("/payments/webhooks/mock", content=payload, headers=headers)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["processed"] is True
    assert second_response.json()["processed"] is False
    assert second_response.json()["payment_id"] == first_response.json()["payment_id"]

    app.dependency_overrides.clear()


def test_payment_failure_after_success_does_not_downgrade_booking():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(
            workspace["id"],
            slots=[
                {
                    "start_at": "2026-06-24T09:00:00+05:30",
                    "end_at": "2026-06-24T18:00:00+05:30",
                },
            ],
        ),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]
    checkout_response = client.post(
        f"/booking-groups/{booking['booking_group_id']}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    payment = checkout_response.json()["payments"][0]
    success_payload = json.dumps(
        {
            "event": "payment.succeeded",
            "provider_reference": payment["provider_reference"],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    success_response = client.post(
        "/payments/webhooks/mock",
        content=success_payload,
        headers={
            "Content-Type": "application/json",
            "X-Mock-Signature": mock_webhook_signature(success_payload),
        },
    )
    assert success_response.status_code == 200
    assert success_response.json()["processed"] is True

    failure_payload = json.dumps(
        {
            "event": "payment.failed",
            "provider_reference": payment["provider_reference"],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    failure_response = client.post(
        "/payments/webhooks/mock",
        content=failure_payload,
        headers={
            "Content-Type": "application/json",
            "X-Mock-Signature": mock_webhook_signature(failure_payload),
        },
    )

    assert failure_response.status_code == 200
    assert failure_response.json()["processed"] is False
    assert failure_response.json()["status"] == "succeeded"

    history_response = client.get(
        f"/bookings/{booking['id']}",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert history_response.status_code == 200
    assert history_response.json()["status"] == "confirmed"

    app.dependency_overrides.clear()


def test_payment_webhook_records_failure_without_confirming_booking():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(
            workspace["id"],
            slots=[
                {
                    "start_at": "2026-06-22T09:00:00+05:30",
                    "end_at": "2026-06-22T18:00:00+05:30",
                },
            ],
        ),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]
    checkout_response = client.post(
        f"/booking-groups/{booking['booking_group_id']}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    payment = checkout_response.json()["payments"][0]
    payload = json.dumps(
        {
            "event": "payment.failed",
            "provider_reference": payment["provider_reference"],
        },
        separators=(",", ":"),
    ).encode("utf-8")

    response = client.post(
        "/payments/webhooks/mock",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Mock-Signature": mock_webhook_signature(payload),
        },
    )

    assert response.status_code == 200
    assert response.json()["processed"] is True
    assert response.json()["status"] == "failed"

    history_response = client.get(
        f"/bookings/{booking['id']}",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert history_response.status_code == 200
    assert history_response.json()["status"] == "pending"

    admin = register_user(client, email="payment-audit-admin@example.com", role="admin")
    audit_response = client.get(
        "/admin/audit-events?action=payment_failed",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )
    assert audit_response.status_code == 200
    audit_event = audit_response.json()["items"][0]
    assert audit_event["entity_type"] == "payment"
    assert audit_event["entity_id"] == payment["id"]
    assert audit_event["details"]["provider_reference"] == payment["provider_reference"]

    app.dependency_overrides.clear()


def test_checkout_session_creates_new_payment_after_failure():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(
            workspace["id"],
            slots=[
                {
                    "start_at": "2026-06-23T09:00:00+05:30",
                    "end_at": "2026-06-23T18:00:00+05:30",
                },
            ],
        ),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]
    first_checkout = client.post(
        f"/booking-groups/{booking['booking_group_id']}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    first_payment = first_checkout.json()["payments"][0]
    payload = json.dumps(
        {
            "event": "payment.failed",
            "provider_reference": first_payment["provider_reference"],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    failed_response = client.post(
        "/payments/webhooks/mock",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Mock-Signature": mock_webhook_signature(payload),
        },
    )
    assert failed_response.status_code == 200

    second_checkout = client.post(
        f"/booking-groups/{booking['booking_group_id']}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    second_payment = second_checkout.json()["payments"][0]

    assert second_checkout.status_code == 200
    assert second_payment["id"] != first_payment["id"]
    assert second_payment["status"] == "pending"

    app.dependency_overrides.clear()


def test_booking_group_payment_confirm_is_idempotent_after_success():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking_group_id = booking_response.json()["bookings"][0]["booking_group_id"]

    intent_response = client.post(
        f"/booking-groups/{booking_group_id}/payment-intent",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert intent_response.status_code == 200

    first_confirm = client.post(
        f"/booking-groups/{booking_group_id}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    second_confirm = client.post(
        f"/booking-groups/{booking_group_id}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert first_confirm.status_code == 200
    assert second_confirm.status_code == 200
    assert second_confirm.json()["booking_group_id"] == booking_group_id
    assert second_confirm.json()["total_paid"] == "1700.00"
    assert {booking["status"] for booking in second_confirm.json()["bookings"]} == {"confirmed"}
    assert {payment["status"] for payment in second_confirm.json()["payments"]} == {"succeeded"}

    app.dependency_overrides.clear()


def test_manual_group_payment_confirm_is_blocked_for_real_provider(monkeypatch):
    app.dependency_overrides[get_session] = make_session_override()
    monkeypatch.setenv("PAYMENT_PROVIDER", "stripe")
    reset_settings_cache()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(
            workspace["id"],
            slots=[
                {
                    "start_at": "2026-06-24T09:00:00+05:30",
                    "end_at": "2026-06-24T18:00:00+05:30",
                },
            ],
        ),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking_group_id = booking_response.json()["bookings"][0]["booking_group_id"]
    checkout_response = client.post(
        f"/booking-groups/{booking_group_id}/checkout-session",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert checkout_response.status_code == 200
    assert checkout_response.json()["provider"] == "stripe"

    confirm_response = client.post(
        f"/booking-groups/{booking_group_id}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert confirm_response.status_code == 409
    assert (
        confirm_response.json()["detail"]
        == "Manual payment confirmation is only available for mock payments"
    )

    app.dependency_overrides.clear()
    reset_settings_cache()


def test_manual_single_payment_confirm_is_blocked_for_real_provider(monkeypatch):
    app.dependency_overrides[get_session] = make_session_override()
    monkeypatch.setenv("PAYMENT_PROVIDER", "stripe")
    reset_settings_cache()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(
            workspace["id"],
            slots=[
                {
                    "start_at": "2026-06-25T09:00:00+05:30",
                    "end_at": "2026-06-25T18:00:00+05:30",
                },
            ],
        ),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]
    intent_response = client.post(
        f"/bookings/{booking['id']}/payment-intent",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert intent_response.status_code == 200
    assert intent_response.json()["provider"] == "stripe"

    confirm_response = client.post(
        f"/bookings/{booking['id']}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert confirm_response.status_code == 409
    assert (
        confirm_response.json()["detail"]
        == "Manual payment confirmation is only available for mock payments"
    )

    app.dependency_overrides.clear()
    reset_settings_cache()


def test_booking_payment_requires_booking_owner():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    other_worker = register_user(client, email="other@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]

    response = client.post(
        f"/bookings/{booking['id']}/payment-intent",
        headers={"Authorization": f"Bearer {other_worker['access_token']}"},
    )

    assert response.status_code == 403

    app.dependency_overrides.clear()


def test_payment_confirm_requires_payment_intent_first():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]

    response = client.post(
        f"/bookings/{booking['id']}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Create a payment intent before confirming payment"

    app.dependency_overrides.clear()


def test_host_revenue_summary_splits_paid_and_pending_bookings():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    first_booking = booking_response.json()["bookings"][0]

    intent_response = client.post(
        f"/bookings/{first_booking['id']}/payment-intent",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert intent_response.status_code == 200
    confirm_response = client.post(
        f"/bookings/{first_booking['id']}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert confirm_response.status_code == 200

    revenue_response = client.get(
        "/bookings/host/revenue",
        headers={"Authorization": f"Bearer {host['access_token']}"},
    )

    assert revenue_response.status_code == 200
    body = revenue_response.json()
    assert body["total_paid"] == "850.00"
    assert body["total_refunded"] == "0.00"
    assert body["gross_revenue"] == "850.00"
    assert body["platform_commission_rate"] == "0.1"
    assert body["platform_commission"] == "85.00"
    assert body["host_net_revenue"] == "765.00"
    assert body["pending_payout"] == "765.00"
    assert body["pending_hold_value"] == "850.00"
    assert body["confirmed_booking_count"] == 1
    assert body["cancelled_booking_count"] == 0
    assert body["pending_booking_count"] == 1
    assert body["paid_payment_count"] == 1

    app.dependency_overrides.clear()


def test_cancel_paid_booking_refunds_payment_and_updates_revenue():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(
            workspace["id"],
            slots=[
                {
                    "start_at": "2026-06-20T09:00:00+05:30",
                    "end_at": "2026-06-20T18:00:00+05:30",
                },
            ],
        ),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking = booking_response.json()["bookings"][0]
    intent_response = client.post(
        f"/bookings/{booking['id']}/payment-intent",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert intent_response.status_code == 200
    confirm_response = client.post(
        f"/bookings/{booking['id']}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert confirm_response.status_code == 200

    cancel_response = client.patch(
        f"/bookings/{booking['id']}/cancel",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    revenue_response = client.get(
        "/bookings/host/revenue",
        headers={"Authorization": f"Bearer {host['access_token']}"},
    )
    assert revenue_response.status_code == 200
    body = revenue_response.json()
    assert body["total_paid"] == "0.00"
    assert body["total_refunded"] == "850.00"
    assert body["gross_revenue"] == "0.00"
    assert body["platform_commission"] == "0.00"
    assert body["host_net_revenue"] == "0.00"
    assert body["pending_payout"] == "0.00"
    assert body["confirmed_booking_count"] == 0
    assert body["cancelled_booking_count"] == 1

    app.dependency_overrides.clear()


def test_booking_group_cancel_refunds_all_paid_rota_days():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    booking_group_id = booking_response.json()["bookings"][0]["booking_group_id"]
    intent_response = client.post(
        f"/booking-groups/{booking_group_id}/payment-intent",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert intent_response.status_code == 200
    confirm_response = client.post(
        f"/booking-groups/{booking_group_id}/payment-confirm",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert confirm_response.status_code == 200

    cancel_response = client.patch(
        f"/booking-groups/{booking_group_id}/cancel",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert cancel_response.status_code == 200
    body = cancel_response.json()
    assert body["booking_group_id"] == booking_group_id
    assert body["total_refunded"] == "1700.00"
    assert {booking["status"] for booking in body["bookings"]} == {"cancelled"}
    assert {payment["status"] for payment in body["refunded_payments"]} == {"refunded"}

    revenue_response = client.get(
        "/bookings/host/revenue",
        headers={"Authorization": f"Bearer {host['access_token']}"},
    )
    assert revenue_response.status_code == 200
    revenue = revenue_response.json()
    assert revenue["total_paid"] == "0.00"
    assert revenue["total_refunded"] == "1700.00"
    assert revenue["gross_revenue"] == "0.00"
    assert revenue["pending_payout"] == "0.00"
    assert revenue["cancelled_booking_count"] == 2

    app.dependency_overrides.clear()


def test_booking_request_rejects_client_supplied_user_id():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    other_worker = register_user(client, email="other@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])

    response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"], user_id=other_worker["user"]["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 422

    app.dependency_overrides.clear()


def test_booking_requires_authentication():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    workspace = create_workspace(client, host_token=host["access_token"])

    response = client.post("/bookings", json=booking_payload(workspace["id"]))

    assert response.status_code == 401

    app.dependency_overrides.clear()


def test_pending_review_workspace_cannot_be_booked():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    response = client.post(
        "/workspaces",
        json={
            "title": "Pending room",
            "description": "Waiting for review",
            "address_line": "12 Residency Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "daily_price": "850.00",
            "amenities": {"wifi": True, "desk": True},
        },
        headers={"Authorization": f"Bearer {host['access_token']}"},
    )
    assert response.status_code == 201
    workspace = response.json()

    search_response = client.post(
        "/workspaces/search",
        json=booking_payload(workspace["id"]),
    )
    assert search_response.status_code == 200
    assert search_response.json() == []

    booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )
    assert booking_response.status_code == 409
    assert booking_response.json()["detail"] == "Workspace is not approved for booking"

    app.dependency_overrides.clear()


def test_workspace_search_rejects_invalid_price_range():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)

    response = client.post(
        "/workspaces/search",
        json={
            "city": "Bengaluru",
            "min_daily_price": "1500.00",
            "max_daily_price": "1000.00",
            "slots": booking_payload("00000000-0000-0000-0000-000000000000")["slots"],
        },
    )

    assert response.status_code == 422
    assert "min_daily_price cannot be higher than max_daily_price" in response.text

    app.dependency_overrides.clear()


def test_workspace_search_returns_estimated_rota_total():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    workspace = create_workspace(client, host_token=host["access_token"])

    response = client.post(
        "/workspaces/search",
        json={
            "city": "Bengaluru",
            "min_daily_price": "500.00",
            "max_daily_price": "1000.00",
            "slots": [
                {
                    "start_at": "2026-06-15T09:00:00+05:30",
                    "end_at": "2026-06-15T18:00:00+05:30",
                },
                {
                    "start_at": "2026-06-17T09:00:00+05:30",
                    "end_at": "2026-06-17T18:00:00+05:30",
                },
                {
                    "start_at": "2026-06-19T09:00:00+05:30",
                    "end_at": "2026-06-19T18:00:00+05:30",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == workspace["id"]
    assert body[0]["daily_price"] == "850.00"
    assert body[0]["estimated_total_price"] == "2550.00"
    assert body[0]["matched_slot_count"] == 3

    app.dependency_overrides.clear()


def test_workspace_search_returns_partial_matches_with_matched_slots():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    workspace = create_workspace(client, host_token=host["access_token"])
    availability_response = client.put(
        f"/workspaces/{workspace['id']}/availability",
        json={
            "rules": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "18:00"},
                {"day_of_week": 2, "start_time": "09:00", "end_time": "18:00"},
            ]
        },
        headers={"Authorization": f"Bearer {host['access_token']}"},
    )
    assert availability_response.status_code == 200

    response = client.post(
        "/workspaces/search",
        json={
            "city": "Bengaluru",
            "max_daily_price": "1000.00",
            "slots": [
                {
                    "start_at": "2026-06-15T09:00:00+05:30",
                    "end_at": "2026-06-15T18:00:00+05:30",
                },
                {
                    "start_at": "2026-06-16T09:00:00+05:30",
                    "end_at": "2026-06-16T18:00:00+05:30",
                },
                {
                    "start_at": "2026-06-17T09:00:00+05:30",
                    "end_at": "2026-06-17T18:00:00+05:30",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == workspace["id"]
    assert body[0]["estimated_total_price"] == "1700.00"
    assert body[0]["matched_slot_count"] == 2
    assert [slot["start_at"][:10] for slot in body[0]["matched_slots"]] == [
        "2026-06-15",
        "2026-06-17",
    ]

    app.dependency_overrides.clear()


def test_overlapping_authenticated_booking_returns_conflict():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker_a = register_user(client, email="a@example.com")
    worker_b = register_user(client, email="b@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])

    first_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker_a['access_token']}"},
    )
    second_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker_b['access_token']}"},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409

    app.dependency_overrides.clear()


def test_booking_outside_workspace_availability_returns_conflict():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    availability_response = client.put(
        f"/workspaces/{workspace['id']}/availability",
        json={
            "rules": [
                {"day_of_week": 1, "start_time": "09:00", "end_time": "18:00"},
            ]
        },
        headers={"Authorization": f"Bearer {host['access_token']}"},
    )
    assert availability_response.status_code == 200

    response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Workspace is not available during one or more requested slots"

    app.dependency_overrides.clear()


def test_booking_on_workspace_blackout_date_returns_conflict():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"])
    blackout_response = client.put(
        f"/workspaces/{workspace['id']}/blackout-dates",
        json={
            "blackout_dates": [
                {"blackout_date": "2026-06-15", "reason": "Maintenance"},
            ]
        },
        headers={"Authorization": f"Bearer {host['access_token']}"},
    )
    assert blackout_response.status_code == 200

    response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Workspace is blocked on one or more requested dates"

    app.dependency_overrides.clear()
