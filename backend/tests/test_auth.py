from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from app.database import get_session
from app.main import app


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
