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
