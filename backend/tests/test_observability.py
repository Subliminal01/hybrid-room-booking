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


def test_request_id_header_is_returned_on_success():
    client = TestClient(app)

    response = client.get("/health", headers={"X-Request-ID": "req-test-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"


def test_liveness_and_readiness_endpoints():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)

    live_response = client.get("/health/live")
    ready_response = client.get("/health/ready", headers={"X-Request-ID": "ready-123"})

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "ok"}
    assert ready_response.status_code == 200
    assert ready_response.headers["X-Request-ID"] == "ready-123"
    assert ready_response.json() == {"status": "ready", "database": "ok"}

    app.dependency_overrides.clear()


def test_http_errors_include_request_id_and_error_code():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)

    response = client.get("/auth/me", headers={"X-Request-ID": "req-auth-123"})

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "req-auth-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.json()["detail"] == "Authentication required"
    assert response.json()["error_code"] == "unauthorized"
    assert response.json()["request_id"] == "req-auth-123"

    app.dependency_overrides.clear()


def test_validation_errors_include_request_id_and_error_code():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)

    response = client.post(
        "/auth/register",
        json={
            "email": "invalid",
            "password": "short",
            "full_name": "",
        },
        headers={"X-Request-ID": "req-validation-123"},
    )

    assert response.status_code == 422
    assert response.headers["X-Request-ID"] == "req-validation-123"
    assert response.json()["error_code"] == "validation_error"
    assert response.json()["request_id"] == "req-validation-123"
    assert isinstance(response.json()["detail"], list)

    app.dependency_overrides.clear()
