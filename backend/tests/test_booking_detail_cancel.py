from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from app.auth_service import issue_user_session, register_user as register_user_service
from app.database import get_session
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


def create_workspace(client: TestClient, *, host_token: str) -> dict:
    response = client.post(
        "/workspaces",
        json={
            "title": "Koramangala work room",
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
    admin = register_user(client, email="admin-review@example.com", role="admin")
    review_response = client.patch(
        f"/admin/workspaces/{workspace['id']}/review",
        json={"review_status": "approved"},
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )
    assert review_response.status_code == 200
    return review_response.json()


def booking_payload(workspace_id: str, day: int = 15) -> dict:
    return {
        "workspace_id": workspace_id,
        "slots": [
            {
                "start_at": f"2026-08-{day:02d}T09:00:00+05:30",
                "end_at": f"2026-08-{day:02d}T18:00:00+05:30",
            }
        ],
    }


def create_booking(client: TestClient, *, token: str, workspace_id: str, day: int = 15) -> dict:
    response = client.post(
        "/bookings",
        json=booking_payload(workspace_id, day),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    return response.json()["bookings"][0]


def setup_booking(client: TestClient):
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    other_worker = register_user(client, email="other@example.com")
    admin = register_user(client, email="admin@example.com", role="admin")
    workspace = create_workspace(client, host_token=host["access_token"])
    booking = create_booking(
        client,
        token=worker["access_token"],
        workspace_id=workspace["id"],
    )
    return host, worker, other_worker, admin, workspace, booking


def test_booking_owner_can_read_detail():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    _, worker, _, _, _, booking = setup_booking(client)

    response = client.get(
        f"/bookings/{booking['id']}",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == booking["id"]

    app.dependency_overrides.clear()


def test_workspace_host_can_read_booking_detail():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host, _, _, _, _, booking = setup_booking(client)

    response = client.get(
        f"/bookings/{booking['id']}",
        headers={"Authorization": f"Bearer {host['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == booking["id"]

    app.dependency_overrides.clear()


def test_unrelated_worker_cannot_read_booking_detail():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    _, _, other_worker, _, _, booking = setup_booking(client)

    response = client.get(
        f"/bookings/{booking['id']}",
        headers={"Authorization": f"Bearer {other_worker['access_token']}"},
    )

    assert response.status_code == 403

    app.dependency_overrides.clear()


def test_admin_can_cancel_booking():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    _, _, _, admin, _, booking = setup_booking(client)

    response = client.patch(
        f"/bookings/{booking['id']}/cancel",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    app.dependency_overrides.clear()


def test_cancelled_booking_no_longer_blocks_same_slot():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    _, worker, other_worker, _, workspace, booking = setup_booking(client)
    cancel_response = client.patch(
        f"/bookings/{booking['id']}/cancel",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    second_booking_response = client.post(
        "/bookings",
        json=booking_payload(workspace["id"]),
        headers={"Authorization": f"Bearer {other_worker['access_token']}"},
    )

    assert cancel_response.status_code == 200
    assert second_booking_response.status_code == 201

    app.dependency_overrides.clear()
