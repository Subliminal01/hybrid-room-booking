from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from app.auth_service import issue_user_session, register_user as register_user_service
from app.database import get_session
from app.email_service import EmailService
from app.main import app
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


def create_workspace(client: TestClient, *, host_token: str, admin_token: str, title: str) -> dict:
    response = client.post(
        "/workspaces",
        json={
            "title": title,
            "description": "Quiet room for hybrid workdays",
            "address_line": "12 Residency Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "daily_price": "850.00",
            "amenities": {"wifi": True, "desk": True},
        },
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert response.status_code == 201
    workspace = response.json()
    review_response = client.patch(
        f"/admin/workspaces/{workspace['id']}/review",
        json={"review_status": "approved"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert review_response.status_code == 200
    return review_response.json()


def book_workspace(client: TestClient, *, worker_token: str, workspace_id: str, day: int) -> dict:
    response = client.post(
        "/bookings",
        json={
            "workspace_id": workspace_id,
            "rota_label": "Office rota",
            "slots": [
                {
                    "start_at": f"2026-07-{day:02d}T09:00:00+05:30",
                    "end_at": f"2026-07-{day:02d}T18:00:00+05:30",
                }
            ],
        },
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert response.status_code == 201
    return response.json()["bookings"][0]


def setup_admin_fixture():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    admin = register_user(client, email="admin@example.com", role="admin")
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(
        client,
        host_token=host["access_token"],
        admin_token=admin["access_token"],
        title="Admin ops room",
    )
    booking = book_workspace(
        client,
        worker_token=worker["access_token"],
        workspace_id=workspace["id"],
        day=8,
    )
    return client, admin, host, worker, workspace, booking


def test_admin_can_list_users_with_role_filter_and_pagination():
    client, admin, *_ = setup_admin_fixture()

    response = client.get(
        "/admin/users?role=worker&limit=1&offset=0",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    assert page["limit"] == 1
    assert page["offset"] == 0
    assert page["items"][0]["email"] == "worker@example.com"
    assert page["items"][0]["role"] == "worker"

    app.dependency_overrides.clear()


def test_non_admin_cannot_list_admin_operations():
    client, _, _, worker, *_ = setup_admin_fixture()
    headers = {"Authorization": f"Bearer {worker['access_token']}"}

    assert client.get("/admin/users", headers=headers).status_code == 403
    assert client.get("/admin/bookings", headers=headers).status_code == 403
    assert client.get("/admin/payments", headers=headers).status_code == 403
    assert client.get("/admin/email/status", headers=headers).status_code == 403
    assert client.get("/admin/payment-provider/status", headers=headers).status_code == 403
    assert client.get("/admin/storage/status", headers=headers).status_code == 403

    app.dependency_overrides.clear()


def test_admin_can_send_email_delivery_test(monkeypatch):
    client, admin, *_ = setup_admin_fixture()
    sent_to = []

    def fake_send_admin_test_email(self, user):
        sent_to.append(user.email)

    monkeypatch.setattr(EmailService, "send_admin_test_email", fake_send_admin_test_email)

    response = client.post(
        "/admin/email/test",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "Test email sent",
        "provider": "log",
        "recipient": "admin@example.com",
    }
    assert sent_to == ["admin@example.com"]

    app.dependency_overrides.clear()


def test_non_admin_cannot_send_email_delivery_test():
    client, _, _, worker, *_ = setup_admin_fixture()

    response = client.post(
        "/admin/email/test",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 403

    app.dependency_overrides.clear()


def test_admin_can_read_log_email_status():
    client, admin, *_ = setup_admin_fixture()

    response = client.get(
        "/admin/email/status",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "log"
    assert body["ready"] is True
    assert body["from_address"] == "noreply@hybridrooms.local"
    assert body["smtp_host"] is None
    assert body["smtp_port"] is None
    assert body["smtp_use_tls"] is True
    assert body["smtp_use_ssl"] is False
    assert body["required_settings"] == []
    assert body["missing_settings"] == []
    assert body["test_supported"] is True

    app.dependency_overrides.clear()


def test_admin_email_status_reports_missing_smtp_settings(monkeypatch):
    client, admin, *_ = setup_admin_fixture()
    monkeypatch.setattr("app.main.settings.email_provider", "smtp")
    monkeypatch.setattr("app.main.settings.email_from", "support@example.com")
    monkeypatch.setattr("app.main.settings.smtp_host", "smtp.example.com")
    monkeypatch.setattr("app.main.settings.smtp_port", 587)
    monkeypatch.setattr("app.main.settings.smtp_username", None)
    monkeypatch.setattr("app.main.settings.smtp_password", None)
    monkeypatch.setattr("app.main.settings.smtp_use_tls", True)
    monkeypatch.setattr("app.main.settings.smtp_use_ssl", False)

    response = client.get(
        "/admin/email/status",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "smtp"
    assert body["ready"] is False
    assert body["from_address"] == "support@example.com"
    assert body["smtp_host"] == "smtp.example.com"
    assert body["smtp_port"] == 587
    assert body["required_settings"] == [
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
    ]
    assert body["missing_settings"] == [
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
    ]
    assert body["test_supported"] is True

    app.dependency_overrides.clear()


def test_admin_can_read_mock_payment_provider_status():
    client, admin, *_ = setup_admin_fixture()

    response = client.get(
        "/admin/payment-provider/status",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert body["ready"] is True
    assert body["manual_confirmation_enabled"] is True
    assert body["required_settings"] == []
    assert body["missing_settings"] == []
    assert body["webhook_url"] == "http://testserver/payments/webhooks/mock"

    app.dependency_overrides.clear()


def test_admin_payment_provider_status_reports_missing_razorpay_settings(monkeypatch):
    client, admin, *_ = setup_admin_fixture()
    monkeypatch.setattr("app.main.settings.payment_provider", "razorpay")
    monkeypatch.setattr("app.main.settings.razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr("app.main.settings.razorpay_key_secret", None)
    monkeypatch.setattr("app.main.settings.razorpay_webhook_secret", None)
    monkeypatch.setattr("app.main.settings.public_api_base_url", "https://api.example.com")

    response = client.get(
        "/admin/payment-provider/status",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "razorpay"
    assert body["ready"] is False
    assert body["manual_confirmation_enabled"] is False
    assert body["required_settings"] == [
        "RAZORPAY_KEY_ID",
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
    ]
    assert body["missing_settings"] == [
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
    ]
    assert body["webhook_url"] == "https://api.example.com/payments/webhooks/razorpay"

    app.dependency_overrides.clear()


def test_admin_can_read_local_storage_status():
    client, admin, *_ = setup_admin_fixture()

    response = client.get(
        "/admin/storage/status",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "local"
    assert body["ready"] is True
    assert body["durable"] is False
    assert body["public_base_url"] is None
    assert body["required_settings"] == []
    assert body["missing_settings"] == []

    app.dependency_overrides.clear()


def test_admin_storage_status_reports_missing_s3_settings(monkeypatch):
    client, admin, *_ = setup_admin_fixture()
    monkeypatch.setattr("app.main.settings.storage_provider", "s3")
    monkeypatch.setattr("app.main.settings.s3_bucket", "workspace-photos")
    monkeypatch.setattr("app.main.settings.s3_access_key_id", None)
    monkeypatch.setattr("app.main.settings.s3_secret_access_key", None)
    monkeypatch.setattr("app.main.settings.s3_public_base_url", "https://cdn.example.com")

    response = client.get(
        "/admin/storage/status",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "s3"
    assert body["ready"] is False
    assert body["durable"] is True
    assert body["public_base_url"] == "https://cdn.example.com"
    assert body["required_settings"] == [
        "S3_BUCKET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_PUBLIC_BASE_URL",
    ]
    assert body["missing_settings"] == [
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
    ]

    app.dependency_overrides.clear()


def test_admin_can_list_all_bookings_with_status_filter():
    client, admin, *_, booking = setup_admin_fixture()

    response = client.get(
        "/admin/bookings?status=pending",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == booking["id"]
    assert page["items"][0]["workspace"]["title"] == "Admin ops room"
    assert page["items"][0]["user"]["email"] == "worker@example.com"

    app.dependency_overrides.clear()


def test_admin_can_list_payments_with_status_filter():
    client, admin, *_, booking = setup_admin_fixture()
    checkout_response = client.post(
        f"/booking-groups/{booking['booking_group_id']}/payment-intent",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )
    assert checkout_response.status_code == 200

    response = client.get(
        "/admin/payments?status=pending",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    assert page["items"][0]["booking_id"] == booking["id"]
    assert page["items"][0]["status"] == "pending"
    assert page["items"][0]["provider"] == "mock"

    app.dependency_overrides.clear()
