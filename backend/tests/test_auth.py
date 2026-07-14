from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.testclient import TestClient

from app.database import get_session
from app.main import app
from app.models import User, UserRole
from scripts import create_admin


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


def test_register_login_and_me_flow():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={
            "email": "Worker@Example.com",
            "password": "strong-password",
            "full_name": "Hybrid Worker",
        },
    )

    assert register_response.status_code == 201
    register_body = register_response.json()
    assert register_body["token_type"] == "bearer"
    assert register_body["access_token"]
    assert register_body["refresh_token"]
    assert register_body["user"]["email"] == "worker@example.com"

    login_response = client.post(
        "/auth/login",
        json={"email": "worker@example.com", "password": "strong-password"},
    )

    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    me_response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["email"] == "worker@example.com"

    app.dependency_overrides.clear()


def test_refresh_token_rotation_and_logout():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    register_response = client.post(
        "/auth/register",
        json={
            "email": "worker@example.com",
            "password": "strong-password",
            "full_name": "Hybrid Worker",
        },
    )
    refresh_token = register_response.json()["refresh_token"]

    refresh_response = client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert refresh_response.status_code == 200
    refreshed_body = refresh_response.json()
    assert refreshed_body["access_token"]
    assert refreshed_body["refresh_token"] != refresh_token
    assert refreshed_body["user"]["email"] == "worker@example.com"

    reused_response = client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert reused_response.status_code == 401

    logout_response = client.post(
        "/auth/logout",
        json={"refresh_token": refreshed_body["refresh_token"]},
    )
    assert logout_response.status_code == 204

    logged_out_refresh = client.post(
        "/auth/refresh",
        json={"refresh_token": refreshed_body["refresh_token"]},
    )
    assert logged_out_refresh.status_code == 401

    app.dependency_overrides.clear()


def test_update_profile_and_change_password():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    register_response = client.post(
        "/auth/register",
        json={
            "email": "worker@example.com",
            "password": "strong-password",
            "full_name": "Hybrid Worker",
        },
    )
    token = register_response.json()["access_token"]

    update_response = client.patch(
        "/auth/me",
        json={"full_name": "Updated Worker", "phone_number": "+919999999999"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["full_name"] == "Updated Worker"
    assert update_response.json()["phone_number"] == "+919999999999"

    password_response = client.post(
        "/auth/password",
        json={
            "current_password": "strong-password",
            "new_password": "new-strong-password",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert password_response.status_code == 204

    old_login = client.post(
        "/auth/login",
        json={"email": "worker@example.com", "password": "strong-password"},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/auth/login",
        json={"email": "worker@example.com", "password": "new-strong-password"},
    )
    assert new_login.status_code == 200

    app.dependency_overrides.clear()


def test_change_password_rejects_wrong_current_password():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    register_response = client.post(
        "/auth/register",
        json={
            "email": "worker@example.com",
            "password": "strong-password",
            "full_name": "Hybrid Worker",
        },
    )
    token = register_response.json()["access_token"]

    response = client.post(
        "/auth/password",
        json={
            "current_password": "wrong-password",
            "new_password": "new-strong-password",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect"

    app.dependency_overrides.clear()


def test_email_verification_flow_and_reuse_rejection():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    register_response = client.post(
        "/auth/register",
        json={
            "email": "worker@example.com",
            "password": "strong-password",
            "full_name": "Hybrid Worker",
        },
    )
    token = register_response.json()["access_token"]
    assert register_response.json()["user"]["email_verified_at"] is None

    request_response = client.post(
        "/auth/email-verification/request",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert request_response.status_code == 200
    verification_token = request_response.json()["verification_token"]
    assert verification_token

    confirm_response = client.post(
        "/auth/email-verification/confirm",
        json={"token": verification_token},
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json()["email_verified_at"] is not None

    reused_response = client.post(
        "/auth/email-verification/confirm",
        json={"token": verification_token},
    )
    assert reused_response.status_code == 400

    app.dependency_overrides.clear()


def test_new_email_verification_request_invalidates_old_token():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    register_response = client.post(
        "/auth/register",
        json={
            "email": "worker@example.com",
            "password": "strong-password",
            "full_name": "Hybrid Worker",
        },
    )
    token = register_response.json()["access_token"]

    first_request = client.post(
        "/auth/email-verification/request",
        headers={"Authorization": f"Bearer {token}"},
    )
    second_request = client.post(
        "/auth/email-verification/request",
        headers={"Authorization": f"Bearer {token}"},
    )

    old_token = first_request.json()["verification_token"]
    new_token = second_request.json()["verification_token"]
    assert old_token != new_token

    old_confirm_response = client.post(
        "/auth/email-verification/confirm",
        json={"token": old_token},
    )
    new_confirm_response = client.post(
        "/auth/email-verification/confirm",
        json={"token": new_token},
    )

    assert old_confirm_response.status_code == 400
    assert new_confirm_response.status_code == 200

    app.dependency_overrides.clear()


def test_email_verification_request_hides_token_in_production():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    from app.main import settings

    original_app_env = settings.app_env
    try:
        settings.app_env = "production"
        register_response = client.post(
            "/auth/register",
            json={
                "email": "worker@example.com",
                "password": "strong-password",
                "full_name": "Hybrid Worker",
            },
        )
        token = register_response.json()["access_token"]

        request_response = client.post(
            "/auth/email-verification/request",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert request_response.status_code == 200
        assert request_response.json()["verification_token"] is None
    finally:
        settings.app_env = original_app_env
        app.dependency_overrides.clear()


def test_password_reset_flow_revokes_old_refresh_token():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    register_response = client.post(
        "/auth/register",
        json={
            "email": "worker@example.com",
            "password": "strong-password",
            "full_name": "Hybrid Worker",
        },
    )
    old_refresh_token = register_response.json()["refresh_token"]

    request_response = client.post(
        "/auth/password-reset/request",
        json={"email": "worker@example.com"},
    )

    assert request_response.status_code == 200
    reset_token = request_response.json()["reset_token"]
    assert reset_token

    confirm_response = client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "new-strong-password"},
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json()["email"] == "worker@example.com"

    old_login = client.post(
        "/auth/login",
        json={"email": "worker@example.com", "password": "strong-password"},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/auth/login",
        json={"email": "worker@example.com", "password": "new-strong-password"},
    )
    assert new_login.status_code == 200

    old_refresh_response = client.post(
        "/auth/refresh",
        json={"refresh_token": old_refresh_token},
    )
    assert old_refresh_response.status_code == 401

    reused_response = client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "another-strong-password"},
    )
    assert reused_response.status_code == 400

    app.dependency_overrides.clear()


def test_new_password_reset_request_invalidates_old_token():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    client.post(
        "/auth/register",
        json={
            "email": "worker@example.com",
            "password": "strong-password",
            "full_name": "Hybrid Worker",
        },
    )

    first_request = client.post(
        "/auth/password-reset/request",
        json={"email": "worker@example.com"},
    )
    second_request = client.post(
        "/auth/password-reset/request",
        json={"email": "worker@example.com"},
    )

    old_token = first_request.json()["reset_token"]
    new_token = second_request.json()["reset_token"]
    assert old_token != new_token

    old_confirm_response = client.post(
        "/auth/password-reset/confirm",
        json={"token": old_token, "new_password": "new-strong-password"},
    )
    new_confirm_response = client.post(
        "/auth/password-reset/confirm",
        json={"token": new_token, "new_password": "new-strong-password"},
    )

    assert old_confirm_response.status_code == 400
    assert new_confirm_response.status_code == 200

    app.dependency_overrides.clear()


def test_password_reset_request_hides_token_in_production():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    from app.main import settings

    original_app_env = settings.app_env
    try:
        settings.app_env = "production"
        client.post(
            "/auth/register",
            json={
                "email": "worker@example.com",
                "password": "strong-password",
                "full_name": "Hybrid Worker",
            },
        )

        request_response = client.post(
            "/auth/password-reset/request",
            json={"email": "worker@example.com"},
        )

        assert request_response.status_code == 200
        assert request_response.json()["reset_token"] is None
    finally:
        settings.app_env = original_app_env
        app.dependency_overrides.clear()


def test_password_reset_request_does_not_reveal_unknown_email():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)

    response = client.post(
        "/auth/password-reset/request",
        json={"email": "missing@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["reset_token"] is None

    app.dependency_overrides.clear()


def test_duplicate_register_is_rejected():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    payload = {
        "email": "worker@example.com",
        "password": "strong-password",
        "full_name": "Hybrid Worker",
    }

    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409

    app.dependency_overrides.clear()


def test_public_registration_rejects_admin_role():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)

    response = client.post(
        "/auth/register",
        json={
            "email": "admin@example.com",
            "password": "strong-password",
            "full_name": "Platform Admin",
            "role": "admin",
        },
    )

    assert response.status_code == 422

    app.dependency_overrides.clear()


def test_admin_bootstrap_disabled_without_secret(monkeypatch):
    app.dependency_overrides[get_session] = make_session_override()
    monkeypatch.setattr("app.main.settings.admin_bootstrap_secret", None)
    client = TestClient(app)

    response = client.post(
        "/admin/bootstrap",
        json={
            "email": "admin@example.com",
            "password": "strong-admin-password",
            "full_name": "Platform Admin",
            "bootstrap_secret": "missing-secret",
        },
    )

    assert response.status_code == 404

    app.dependency_overrides.clear()


def test_admin_bootstrap_rejects_invalid_secret(monkeypatch):
    app.dependency_overrides[get_session] = make_session_override()
    monkeypatch.setattr(
        "app.main.settings.admin_bootstrap_secret",
        "valid-bootstrap-secret-value",
    )
    client = TestClient(app)

    response = client.post(
        "/admin/bootstrap",
        json={
            "email": "admin@example.com",
            "password": "strong-admin-password",
            "full_name": "Platform Admin",
            "bootstrap_secret": "wrong-secret",
        },
    )

    assert response.status_code == 403

    app.dependency_overrides.clear()


def test_admin_bootstrap_creates_admin_user(monkeypatch):
    app.dependency_overrides[get_session] = make_session_override()
    monkeypatch.setattr(
        "app.main.settings.admin_bootstrap_secret",
        "valid-bootstrap-secret-value",
    )
    client = TestClient(app)

    response = client.post(
        "/admin/bootstrap",
        json={
            "email": "Admin@Example.com",
            "password": "strong-admin-password",
            "full_name": "Platform Admin",
            "bootstrap_secret": "valid-bootstrap-secret-value",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["user"]["email"] == "admin@example.com"
    assert body["user"]["role"] == "admin"

    login_response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "strong-admin-password"},
    )
    assert login_response.status_code == 200
    admin_token = login_response.json()["access_token"]
    assert login_response.json()["user"]["role"] == "admin"

    audit_response = client.get(
        "/admin/audit-events?action=admin_bootstrapped",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit_response.status_code == 200
    audit_body = audit_response.json()
    assert audit_body["total"] == 1
    assert audit_body["items"][0]["action"] == "admin_bootstrapped"
    assert audit_body["items"][0]["details"] == {
        "email": "admin@example.com",
        "created": True,
    }

    app.dependency_overrides.clear()


def test_account_security_changes_are_audited(monkeypatch):
    app.dependency_overrides[get_session] = make_session_override()
    monkeypatch.setattr(
        "app.main.settings.admin_bootstrap_secret",
        "valid-bootstrap-secret-value",
    )
    client = TestClient(app)
    client.post(
        "/admin/bootstrap",
        json={
            "email": "admin@example.com",
            "password": "strong-admin-password",
            "full_name": "Platform Admin",
            "bootstrap_secret": "valid-bootstrap-secret-value",
        },
    )
    login_response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "strong-admin-password"},
    )
    admin_token = login_response.json()["access_token"]

    update_response = client.patch(
        "/auth/me",
        json={"full_name": "Updated Admin", "phone_number": "+919999999999"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert update_response.status_code == 200

    password_response = client.post(
        "/auth/password",
        json={
            "current_password": "strong-admin-password",
            "new_password": "new-strong-admin-password",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert password_response.status_code == 204

    profile_audit_response = client.get(
        "/admin/audit-events?action=user_profile_updated",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert profile_audit_response.status_code == 200
    profile_audit = profile_audit_response.json()["items"][0]
    assert profile_audit["entity_type"] == "user"
    assert profile_audit["details"] == {
        "changed_fields": ["full_name", "phone_number"],
    }

    password_audit_response = client.get(
        "/admin/audit-events?action=password_changed",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert password_audit_response.status_code == 200
    password_audit = password_audit_response.json()["items"][0]
    assert password_audit["entity_type"] == "user"
    assert password_audit["details"] == {"method": "authenticated"}

    app.dependency_overrides.clear()


def test_admin_bootstrap_promotes_existing_user(monkeypatch):
    app.dependency_overrides[get_session] = make_session_override()
    monkeypatch.setattr(
        "app.main.settings.admin_bootstrap_secret",
        "valid-bootstrap-secret-value",
    )
    client = TestClient(app)
    client.post(
        "/auth/register",
        json={
            "email": "worker@example.com",
            "password": "old-password",
            "full_name": "Hybrid Worker",
        },
    )

    response = client.post(
        "/admin/bootstrap",
        json={
            "email": "worker@example.com",
            "password": "strong-admin-password",
            "full_name": "Platform Admin",
            "bootstrap_secret": "valid-bootstrap-secret-value",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    assert body["user"]["role"] == "admin"
    assert body["user"]["full_name"] == "Platform Admin"

    login_response = client.post(
        "/auth/login",
        json={"email": "worker@example.com", "password": "strong-admin-password"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["role"] == "admin"

    app.dependency_overrides.clear()


def test_create_admin_script_creates_admin_user(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(create_admin, "engine", engine)
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-admin-password")
    monkeypatch.setenv("ADMIN_FULL_NAME", "Platform Admin")

    create_admin.main()

    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == "admin@example.com")).one()
        assert user.role == UserRole.ADMIN
        assert user.full_name == "Platform Admin"


def test_login_rejects_wrong_password():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    client.post(
        "/auth/register",
        json={
            "email": "worker@example.com",
            "password": "strong-password",
            "full_name": "Hybrid Worker",
        },
    )

    response = client.post(
        "/auth/login",
        json={"email": "worker@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401

    app.dependency_overrides.clear()
