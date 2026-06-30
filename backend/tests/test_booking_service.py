from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.booking_service import (
    build_booking_rows,
    expire_stale_pending_bookings,
    find_available_workspaces,
    workspace_has_conflict,
)
from app.models import (
    Booking,
    BookingStatus,
    User,
    Workspace,
    WorkspaceAvailabilityRule,
    WorkspaceBlackoutDate,
    WorkspaceReviewStatus,
)
from app.schemas import TimeSlot


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def dt(day: int, hour: int) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=timezone.utc)


def slot(day: int, start_hour: int = 9, end_hour: int = 18) -> TimeSlot:
    return TimeSlot(start_at=dt(day, start_hour), end_at=dt(day, end_hour))


def create_user(session: Session, email: str = "worker@example.com") -> User:
    user = User(
        email=email,
        hashed_password="not-for-production",
        full_name="Hybrid Worker",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def create_workspace(
    session: Session,
    *,
    title: str = "Koramangala work room",
    city: str = "Bengaluru",
    daily_price: Decimal = Decimal("850.00"),
) -> Workspace:
    owner = create_user(session, email=f"{uuid4()}@host.test")
    workspace = Workspace(
        owner_id=owner.id,
        title=title,
        description="Quiet room for hybrid workdays",
        address_line="12 Residency Road",
        city=city,
        state="Karnataka",
        daily_price=daily_price,
        review_status=WorkspaceReviewStatus.APPROVED,
        amenities={"wifi": True, "desk": True},
    )
    session.add(workspace)
    session.commit()
    session.refresh(workspace)
    return workspace


def confirm_booking(
    session: Session,
    *,
    user: User,
    workspace: Workspace,
    booking_slot: TimeSlot,
    status: BookingStatus = BookingStatus.CONFIRMED,
) -> Booking:
    booking = Booking(
        user_id=user.id,
        workspace_id=workspace.id,
        start_at=booking_slot.start_at,
        end_at=booking_slot.end_at,
        status=status,
        total_price=workspace.daily_price,
    )
    session.add(booking)
    session.commit()
    session.refresh(booking)
    return booking


def add_availability_rule(
    session: Session,
    *,
    workspace: Workspace,
    day_of_week: int,
    start_hour: int = 9,
    end_hour: int = 18,
) -> WorkspaceAvailabilityRule:
    rule = WorkspaceAvailabilityRule(
        workspace_id=workspace.id,
        day_of_week=day_of_week,
        start_time=time(start_hour),
        end_time=time(end_hour),
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def add_blackout_date(
    session: Session,
    *,
    workspace: Workspace,
    blackout_date: date,
) -> WorkspaceBlackoutDate:
    blocked = WorkspaceBlackoutDate(
        workspace_id=workspace.id,
        blackout_date=blackout_date,
        reason="Maintenance",
    )
    session.add(blocked)
    session.commit()
    session.refresh(blocked)
    return blocked


def test_overlap_on_same_workspace_is_a_conflict(session: Session):
    user = create_user(session)
    workspace = create_workspace(session)
    confirm_booking(session, user=user, workspace=workspace, booking_slot=slot(15, 9, 18))

    assert workspace_has_conflict(session, workspace.id, [slot(15, 12, 16)]) is True


def test_adjacent_slots_do_not_conflict(session: Session):
    user = create_user(session)
    workspace = create_workspace(session)
    confirm_booking(session, user=user, workspace=workspace, booking_slot=slot(15, 9, 18))

    assert workspace_has_conflict(session, workspace.id, [slot(15, 18, 22)]) is False


def test_different_rota_days_can_share_same_workspace(session: Session):
    user_a = create_user(session, email="a@example.com")
    workspace = create_workspace(session)
    confirm_booking(session, user=user_a, workspace=workspace, booking_slot=slot(15))

    assert workspace_has_conflict(session, workspace.id, [slot(16), slot(17)]) is False


def test_cancelled_booking_does_not_block_availability(session: Session):
    user = create_user(session)
    workspace = create_workspace(session)
    confirm_booking(
        session,
        user=user,
        workspace=workspace,
        booking_slot=slot(15),
        status=BookingStatus.CANCELLED,
    )

    assert workspace_has_conflict(session, workspace.id, [slot(15)]) is False


def test_search_excludes_only_workspaces_with_conflicting_slots(session: Session):
    user = create_user(session)
    busy_workspace = create_workspace(session, title="Busy room")
    available_workspace = create_workspace(session, title="Available room")
    confirm_booking(session, user=user, workspace=busy_workspace, booking_slot=slot(15))

    results = find_available_workspaces(
        session,
        city="Bengaluru",
        max_daily_price=Decimal("1000.00"),
        slots=[slot(15), slot(17)],
    )

    assert [workspace.id for workspace in results] == [available_workspace.id]


def test_search_respects_weekly_workspace_availability(session: Session):
    monday_wednesday_workspace = create_workspace(session, title="MW room")
    tuesday_workspace = create_workspace(session, title="Tuesday room")
    add_availability_rule(session, workspace=monday_wednesday_workspace, day_of_week=0)
    add_availability_rule(session, workspace=monday_wednesday_workspace, day_of_week=2)
    add_availability_rule(session, workspace=tuesday_workspace, day_of_week=1)

    results = find_available_workspaces(
        session,
        city="Bengaluru",
        max_daily_price=Decimal("1000.00"),
        slots=[slot(15), slot(17)],
    )

    assert [workspace.id for workspace in results] == [monday_wednesday_workspace.id]


def test_search_excludes_workspace_when_requested_time_is_outside_rule(session: Session):
    workspace = create_workspace(session)
    add_availability_rule(session, workspace=workspace, day_of_week=0, start_hour=10, end_hour=17)

    results = find_available_workspaces(
        session,
        city="Bengaluru",
        max_daily_price=Decimal("1000.00"),
        slots=[slot(15, 9, 18)],
    )

    assert results == []


def test_search_excludes_workspace_on_blackout_date(session: Session):
    workspace = create_workspace(session)
    add_availability_rule(session, workspace=workspace, day_of_week=0)
    add_blackout_date(session, workspace=workspace, blackout_date=date(2026, 6, 15))

    results = find_available_workspaces(
        session,
        city="Bengaluru",
        max_daily_price=Decimal("1000.00"),
        slots=[slot(15, 9, 18)],
    )

    assert results == []


def test_build_booking_rows_creates_one_row_per_rota_slot(session: Session):
    user = create_user(session)
    workspace = create_workspace(session)

    bookings = build_booking_rows(
        workspace=workspace,
        user_id=user.id,
        slots=[slot(15), slot(17), slot(19)],
        rota_label="June office rota",
    )

    assert len(bookings) == 3
    assert {booking.start_at.day for booking in bookings} == {15, 17, 19}
    assert all(booking.total_price == Decimal("850.00") for booking in bookings)
    assert all(booking.status == BookingStatus.PENDING for booking in bookings)
    assert all(booking.expires_at is not None for booking in bookings)


def test_expired_pending_booking_is_released_for_same_slot(session: Session):
    user = create_user(session)
    other_user = create_user(session, email="other@example.com")
    workspace = create_workspace(session)
    expired_booking = confirm_booking(
        session,
        user=user,
        workspace=workspace,
        booking_slot=slot(15),
        status=BookingStatus.PENDING,
    )
    expired_booking.expires_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session.add(expired_booking)
    session.commit()

    expired_count = expire_stale_pending_bookings(session)
    has_conflict = workspace_has_conflict(session, workspace.id, [slot(15)])
    new_booking = build_booking_rows(
        workspace=workspace,
        user_id=other_user.id,
        slots=[slot(15)],
    )[0]

    assert expired_count == 1
    assert has_conflict is False
    assert expired_booking.status == BookingStatus.EXPIRED
    assert new_booking.status == BookingStatus.PENDING
