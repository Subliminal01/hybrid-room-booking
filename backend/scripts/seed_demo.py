from decimal import Decimal
from datetime import time

from sqlmodel import Session, select

from app.auth_service import get_user_by_email, register_user
from app.database import engine
from app.models import UserRole, Workspace, WorkspaceAvailabilityRule


def seed() -> None:
    with Session(engine) as session:
        host = get_user_by_email(session, "host@example.com")
        if host is None:
            host = register_user(
                session,
                email="host@example.com",
                password="strong-password",
                full_name="Demo Host",
                role=UserRole.HOST,
            )

        worker = get_user_by_email(session, "worker@example.com")
        if worker is None:
            register_user(
                session,
                email="worker@example.com",
                password="strong-password",
                full_name="Demo Worker",
                role=UserRole.WORKER,
            )

        existing = session.exec(select(Workspace).where(Workspace.owner_id == host.id)).first()
        if existing is None:
            session.add(
                Workspace(
                    owner_id=host.id,
                    title="Koramangala focus room",
                    description="Quiet room with desk, Wi-Fi and easy metro access.",
                    address_line="12 Residency Road",
                    city="Bengaluru",
                    state="Karnataka",
                    photo_url=(
                        "https://images.unsplash.com/photo-1497366754035-f200968a6e72"
                        "?auto=format&fit=crop&w=1200&q=80"
                    ),
                    daily_price=Decimal("850.00"),
                    amenities={"wifi": True, "desk": True, "ac": True},
                    availability_rules=[
                        WorkspaceAvailabilityRule(day_of_week=0, start_time=time(9), end_time=time(18)),
                        WorkspaceAvailabilityRule(day_of_week=2, start_time=time(9), end_time=time(18)),
                        WorkspaceAvailabilityRule(day_of_week=4, start_time=time(9), end_time=time(18)),
                    ],
                )
            )
            session.add(
                Workspace(
                    owner_id=host.id,
                    title="Indiranagar day studio",
                    description="Compact workspace for hybrid office days.",
                    address_line="7 100 Feet Road",
                    city="Bengaluru",
                    state="Karnataka",
                    photo_url=(
                        "https://images.unsplash.com/photo-1497366811353-6870744d04b2"
                        "?auto=format&fit=crop&w=1200&q=80"
                    ),
                    daily_price=Decimal("950.00"),
                    amenities={"wifi": True, "desk": True, "parking": False},
                    availability_rules=[
                        WorkspaceAvailabilityRule(day_of_week=1, start_time=time(9), end_time=time(18)),
                        WorkspaceAvailabilityRule(day_of_week=3, start_time=time(9), end_time=time(18)),
                    ],
                )
            )
            session.commit()


if __name__ == "__main__":
    seed()
