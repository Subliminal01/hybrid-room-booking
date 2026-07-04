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


def register_user(client: TestClient, *, email: str, role: str) -> str:
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
            access_token, _ = issue_user_session(session, user)
            return access_token
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
    return response.json()["access_token"]


def workspace_payload(**overrides):
    payload = {
        "title": "Koramangala work room",
        "description": "Quiet room for hybrid workdays",
        "address_line": "12 Residency Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "photo_url": "https://example.com/workspace.jpg",
        "daily_price": "850.00",
        "capacity": 1,
        "amenities": {"wifi": True, "desk": True},
    }
    payload.update(overrides)
    return payload


def test_host_can_create_and_list_own_workspaces():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    token = register_user(client, email="host@example.com", role="host")

    create_response = client.post(
        "/workspaces",
        json=workspace_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["title"] == "Koramangala work room"
    assert created["city"] == "Bengaluru"
    assert created["photo_url"] == "https://example.com/workspace.jpg"
    assert created["review_status"] == "pending"

    list_response = client.get(
        "/workspaces/mine",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert list_response.status_code == 200
    assert [workspace["id"] for workspace in list_response.json()] == [created["id"]]
    assert list_response.json()[0]["photo_url"] == "https://example.com/workspace.jpg"
    assert list_response.json()[0]["review_status"] == "pending"

    app.dependency_overrides.clear()


def test_admin_can_review_workspace():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host_token = register_user(client, email="host@example.com", role="host")
    admin_token = register_user(client, email="admin@example.com", role="admin")
    created = client.post(
        "/workspaces",
        json=workspace_payload(),
        headers={"Authorization": f"Bearer {host_token}"},
    ).json()

    review_response = client.patch(
        f"/admin/workspaces/{created['id']}/review",
        json={"review_status": "approved"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert review_response.status_code == 200
    assert review_response.json()["review_status"] == "approved"

    list_response = client.get(
        "/admin/workspaces/review?review_status=approved",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_response.status_code == 200
    assert [workspace["id"] for workspace in list_response.json()] == [created["id"]]

    audit_response = client.get(
        "/admin/audit-events?action=workspace_reviewed",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit_response.status_code == 200
    audit_items = audit_response.json()["items"]
    assert audit_items[0]["action"] == "workspace_reviewed"
    assert audit_items[0]["actor_user_id"] is not None
    assert audit_items[0]["entity_type"] == "workspace"
    assert audit_items[0]["entity_id"] == created["id"]
    assert audit_items[0]["details"]["previous_review_status"] == "pending"
    assert audit_items[0]["details"]["review_status"] == "approved"

    app.dependency_overrides.clear()


def test_host_cannot_review_workspace():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    host_token = register_user(client, email="host@example.com", role="host")
    created = client.post(
        "/workspaces",
        json=workspace_payload(),
        headers={"Authorization": f"Bearer {host_token}"},
    ).json()

    response = client.patch(
        f"/admin/workspaces/{created['id']}/review",
        json={"review_status": "approved"},
        headers={"Authorization": f"Bearer {host_token}"},
    )

    assert response.status_code == 403

    audit_response = client.get(
        "/admin/audit-events",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert audit_response.status_code == 403

    app.dependency_overrides.clear()


def test_worker_cannot_create_workspace():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    token = register_user(client, email="worker@example.com", role="worker")

    response = client.post(
        "/workspaces",
        json=workspace_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403

    app.dependency_overrides.clear()


def test_host_can_update_own_workspace():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    token = register_user(client, email="host@example.com", role="host")
    created = client.post(
        "/workspaces",
        json=workspace_payload(),
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    update_response = client.patch(
        f"/workspaces/{created['id']}",
        json={"daily_price": "900.00", "status": "paused"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["daily_price"] == "900.00"
    assert update_response.json()["status"] == "paused"

    app.dependency_overrides.clear()


def test_host_can_replace_workspace_availability():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    token = register_user(client, email="host@example.com", role="host")
    created = client.post(
        "/workspaces",
        json=workspace_payload(),
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    response = client.put(
        f"/workspaces/{created['id']}/availability",
        json={
            "rules": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "18:00"},
                {"day_of_week": 2, "start_time": "09:00", "end_time": "18:00"},
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    rules = response.json()
    assert [rule["day_of_week"] for rule in rules] == [0, 2]

    get_response = client.get(f"/workspaces/{created['id']}/availability")
    assert get_response.status_code == 200
    assert [rule["day_of_week"] for rule in get_response.json()] == [0, 2]

    app.dependency_overrides.clear()


def test_host_can_replace_workspace_blackout_dates():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    token = register_user(client, email="host@example.com", role="host")
    created = client.post(
        "/workspaces",
        json=workspace_payload(),
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    response = client.put(
        f"/workspaces/{created['id']}/blackout-dates",
        json={
            "blackout_dates": [
                {"blackout_date": "2026-06-15", "reason": "Maintenance"},
                {"blackout_date": "2026-06-17", "reason": "Personal use"},
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    blackout_dates = response.json()
    assert [item["blackout_date"] for item in blackout_dates] == [
        "2026-06-15",
        "2026-06-17",
    ]

    get_response = client.get(f"/workspaces/{created['id']}/blackout-dates")
    assert get_response.status_code == 200
    assert [item["reason"] for item in get_response.json()] == ["Maintenance", "Personal use"]

    app.dependency_overrides.clear()


def test_host_cannot_update_another_hosts_workspace():
    app.dependency_overrides[get_session] = make_session_override()
    client = TestClient(app)
    owner_token = register_user(client, email="owner@example.com", role="host")
    other_token = register_user(client, email="other@example.com", role="host")
    created = client.post(
        "/workspaces",
        json=workspace_payload(),
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()

    response = client.patch(
        f"/workspaces/{created['id']}",
        json={"daily_price": "900.00"},
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 403

    app.dependency_overrides.clear()
