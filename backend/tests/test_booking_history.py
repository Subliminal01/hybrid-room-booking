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


def create_workspace(client: TestClient, *, host_token: str, title: str) -> dict:
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
    admin = register_user(client, email=f"admin-{title.lower().replace(' ', '-')}@example.com", role="admin")
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
        "rota_label": "June office rota",
        "slots": [
            {
                "start_at": f"2026-06-{day:02d}T09:00:00+05:30",
                "end_at": f"2026-06-{day:02d}T18:00:00+05:30",
            }
        ],
    }


def book_workspace(
    client: TestClient,
    *,
    worker_token: str,
    workspace_id: str,
    day: int,
) -> dict:
    response = client.post(
        "/bookings",
        json=booking_payload(workspace_id, day=day),
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert response.status_code == 201
    return response.json()


def test_user_booking_history_only_returns_own_bookings():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker_a = register_user(client, email="a@example.com")
    worker_b = register_user(client, email="b@example.com")
    workspace = create_workspace(client, host_token=host["access_token"], title="Room")

    book_workspace(
        client,
        worker_token=worker_a["access_token"],
        workspace_id=workspace["id"],
        day=15,
    )
    book_workspace(
        client,
        worker_token=worker_b["access_token"],
        workspace_id=workspace["id"],
        day=16,
    )

    response = client.get(
        "/bookings/mine",
        headers={"Authorization": f"Bearer {worker_a['access_token']}"},
    )

    assert response.status_code == 200
    page = response.json()
    bookings = page["items"]
    assert page["total"] == 1
    assert page["limit"] == 20
    assert page["offset"] == 0
    assert len(bookings) == 1
    assert bookings[0]["user_id"] == worker_a["user"]["id"]
    assert bookings[0]["workspace"]["title"] == "Room"
    assert bookings[0]["workspace"]["city"] == "Bengaluru"
    assert bookings[0]["user"]["email"] == "a@example.com"

    app.dependency_overrides.clear()


def test_host_booking_history_only_returns_bookings_for_owned_workspaces():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host_a = register_user(client, email="host-a@example.com", role="host")
    host_b = register_user(client, email="host-b@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace_a = create_workspace(
        client,
        host_token=host_a["access_token"],
        title="Host A room",
    )
    workspace_b = create_workspace(
        client,
        host_token=host_b["access_token"],
        title="Host B room",
    )

    booking_a = book_workspace(
        client,
        worker_token=worker["access_token"],
        workspace_id=workspace_a["id"],
        day=15,
    )["bookings"][0]
    book_workspace(
        client,
        worker_token=worker["access_token"],
        workspace_id=workspace_b["id"],
        day=16,
    )

    response = client.get(
        "/bookings/host",
        headers={"Authorization": f"Bearer {host_a['access_token']}"},
    )

    assert response.status_code == 200
    page = response.json()
    bookings = page["items"]
    assert page["total"] == 1
    assert len(bookings) == 1
    assert bookings[0]["id"] == booking_a["id"]
    assert bookings[0]["workspace_id"] == workspace_a["id"]
    assert bookings[0]["workspace"]["title"] == "Host A room"
    assert bookings[0]["user"]["email"] == "worker@example.com"

    app.dependency_overrides.clear()


def test_worker_cannot_read_host_booking_history():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    worker = register_user(client, email="worker@example.com")

    response = client.get(
        "/bookings/host",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 403

    app.dependency_overrides.clear()


def test_admin_can_read_all_host_booking_history():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    admin = register_user(client, email="admin@example.com", role="admin")
    host_a = register_user(client, email="host-a@example.com", role="host")
    host_b = register_user(client, email="host-b@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace_a = create_workspace(
        client,
        host_token=host_a["access_token"],
        title="Host A room",
    )
    workspace_b = create_workspace(
        client,
        host_token=host_b["access_token"],
        title="Host B room",
    )
    booking_a = book_workspace(
        client,
        worker_token=worker["access_token"],
        workspace_id=workspace_a["id"],
        day=15,
    )["bookings"][0]
    booking_b = book_workspace(
        client,
        worker_token=worker["access_token"],
        workspace_id=workspace_b["id"],
        day=16,
    )["bookings"][0]

    response = client.get(
        "/bookings/host",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2
    assert {booking["id"] for booking in page["items"]} == {
        booking_a["id"],
        booking_b["id"],
    }

    app.dependency_overrides.clear()


def test_booking_history_supports_limit_and_offset():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host = register_user(client, email="host@example.com", role="host")
    worker = register_user(client, email="worker@example.com")
    workspace = create_workspace(client, host_token=host["access_token"], title="Paged room")
    for day in (15, 16, 17):
        book_workspace(
            client,
            worker_token=worker["access_token"],
            workspace_id=workspace["id"],
            day=day,
        )

    response = client.get(
        "/bookings/mine?limit=1&offset=1",
        headers={"Authorization": f"Bearer {worker['access_token']}"},
    )

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert page["limit"] == 1
    assert page["offset"] == 1
    assert len(page["items"]) == 1

    app.dependency_overrides.clear()
