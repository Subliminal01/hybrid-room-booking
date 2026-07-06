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


def test_auth_endpoints_are_rate_limited():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    limiter = app.state.rate_limiter
    original_limit = limiter.limit
    limiter.reset()
    limiter.limit = 2

    payload = {"email": "missing@example.com", "password": "strong-password"}
    first_response = client.post("/auth/login", json=payload, headers={"X-Request-ID": "rate-1"})
    second_response = client.post("/auth/login", json=payload, headers={"X-Request-ID": "rate-2"})
    limited_response = client.post("/auth/login", json=payload, headers={"X-Request-ID": "rate-3"})

    assert first_response.status_code == 401
    assert first_response.headers["X-RateLimit-Limit"] == "2"
    assert first_response.headers["X-RateLimit-Remaining"] == "1"
    assert second_response.status_code == 401
    assert second_response.headers["X-RateLimit-Remaining"] == "0"
    assert limited_response.status_code == 429
    assert limited_response.headers["Retry-After"]
    assert limited_response.headers["X-Request-ID"] == "rate-3"
    assert limited_response.json()["error_code"] == "rate_limited"
    assert limited_response.json()["request_id"] == "rate-3"

    limiter.limit = original_limit
    limiter.reset()
    app.dependency_overrides.clear()


def test_auth_rate_limit_tracks_account_across_forwarded_ips():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    limiter = app.state.rate_limiter
    original_limit = limiter.limit
    limiter.reset()
    limiter.limit = 2

    original_trust_proxy_headers = app.state.trust_proxy_headers
    app.state.trust_proxy_headers = True
    payload = {"email": "target@example.com", "password": "wrong-password"}
    first_response = client.post(
        "/auth/login",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.1"},
    )
    second_response = client.post(
        "/auth/login",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.2"},
    )
    limited_response = client.post(
        "/auth/login",
        json=payload,
        headers={"X-Forwarded-For": "203.0.113.3"},
    )

    assert first_response.status_code == 401
    assert second_response.status_code == 401
    assert limited_response.status_code == 429

    app.state.trust_proxy_headers = original_trust_proxy_headers
    limiter.limit = original_limit
    limiter.reset()
    app.dependency_overrides.clear()


def test_forwarded_for_is_ignored_unless_proxy_headers_are_trusted():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    limiter = app.state.rate_limiter
    original_limit = limiter.limit
    limiter.reset()
    limiter.limit = 1

    original_trust_proxy_headers = app.state.trust_proxy_headers
    app.state.trust_proxy_headers = False
    payload_a = {"email": "a@example.com", "password": "wrong-password"}
    payload_b = {"email": "b@example.com", "password": "wrong-password"}
    first_response = client.post(
        "/auth/login",
        json=payload_a,
        headers={"X-Forwarded-For": "203.0.113.1"},
    )
    limited_response = client.post(
        "/auth/login",
        json=payload_b,
        headers={"X-Forwarded-For": "203.0.113.2"},
    )

    assert first_response.status_code == 401
    assert limited_response.status_code == 429

    app.state.trust_proxy_headers = original_trust_proxy_headers
    limiter.limit = original_limit
    limiter.reset()
    app.dependency_overrides.clear()
