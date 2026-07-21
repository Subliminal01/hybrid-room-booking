from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlmodel import Session, select

from app.config import get_settings
from app.models import (
    Booking,
    BookingStatus,
    Workspace,
    WorkspaceAvailabilityRule,
    WorkspaceBlackoutDate,
    WorkspaceReviewStatus,
    WorkspaceStatus,
    utc_now,
)
from app.schemas import TimeSlot


ACTIVE_BOOKING_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED)
settings = get_settings()


def booking_overlaps(start_at: datetime, end_at: datetime):
    """Half-open interval overlap: [start_at, end_at)."""
    return (Booking.start_at < end_at) & (Booking.end_at > start_at)


def expire_stale_pending_bookings(session: Session) -> int:
    now = utc_now()
    stale_bookings = session.exec(
        select(Booking).where(
            Booking.status == BookingStatus.PENDING,
            Booking.expires_at.is_not(None),
            Booking.expires_at <= now,
        )
    ).all()
    for booking in stale_bookings:
        booking.status = BookingStatus.EXPIRED
        session.add(booking)

    if stale_bookings:
        session.commit()

    return len(stale_bookings)


def workspace_has_conflict(
    session: Session,
    workspace_id: UUID,
    slots: list[TimeSlot],
) -> bool:
    expire_stale_pending_bookings(session)
    for slot in slots:
        conflict_count = session.exec(
            select(func.count(Booking.id)).where(
                Booking.workspace_id == workspace_id,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                booking_overlaps(slot.start_at, slot.end_at),
            )
        ).one()

        if conflict_count > 0:
            return True

    return False


def slot_fits_availability_rule(slot: TimeSlot, rule: WorkspaceAvailabilityRule) -> bool:
    start_time = slot.start_at.timetz().replace(tzinfo=None)
    end_time = slot.end_at.timetz().replace(tzinfo=None)
    if slot.start_at.date() != slot.end_at.date():
        return (
            slot.start_at.weekday() == rule.day_of_week
            and start_time >= rule.start_time
            and start_time <= rule.end_time
        )

    return (
        slot.start_at.weekday() == rule.day_of_week
        and start_time >= rule.start_time
        and end_time <= rule.end_time
    )


def workspace_is_available_for_slots(
    session: Session,
    workspace: Workspace,
    slots: list[TimeSlot],
) -> bool:
    rules = session.exec(
        select(WorkspaceAvailabilityRule).where(
            WorkspaceAvailabilityRule.workspace_id == workspace.id,
        )
    ).all()

    if not rules:
        return True

    return all(any(slot_fits_availability_rule(slot, rule) for rule in rules) for slot in slots)


def workspace_has_blackout_for_slots(
    session: Session,
    workspace: Workspace,
    slots: list[TimeSlot],
) -> bool:
    requested_dates = set()
    for slot in slots:
        cursor = slot.start_at.date()
        last_occupied_date = (slot.end_at - timedelta(microseconds=1)).date()
        while cursor <= last_occupied_date:
            requested_dates.add(cursor)
            cursor += timedelta(days=1)

    blackout_count = session.exec(
        select(func.count(WorkspaceBlackoutDate.id)).where(
            WorkspaceBlackoutDate.workspace_id == workspace.id,
            WorkspaceBlackoutDate.blackout_date.in_(requested_dates),
        )
    ).one()
    return blackout_count > 0


def find_available_workspaces(
    session: Session,
    *,
    slots: list[TimeSlot],
    city: str | None = None,
    min_daily_price: Decimal | None = None,
    max_daily_price: Decimal | None = None,
) -> list[Workspace]:
    expire_stale_pending_bookings(session)
    query = select(Workspace).where(
        Workspace.status == WorkspaceStatus.ACTIVE,
        Workspace.review_status == WorkspaceReviewStatus.APPROVED,
    )

    if city:
        query = query.where(Workspace.city.ilike(f"%{city}%"))
    if min_daily_price is not None:
        query = query.where(Workspace.daily_price >= min_daily_price)
    if max_daily_price is not None:
        query = query.where(Workspace.daily_price <= max_daily_price)

    candidates = session.exec(query.order_by(Workspace.daily_price)).all()
    return [
        workspace
        for workspace in candidates
        if workspace_is_available_for_slots(session, workspace, slots)
        and not workspace_has_blackout_for_slots(session, workspace, slots)
        and not workspace_has_conflict(session, workspace.id, slots)
    ]


def matching_slots_for_workspace(
    session: Session,
    workspace: Workspace,
    slots: list[TimeSlot],
) -> list[TimeSlot]:
    return [
        slot
        for slot in slots
        if workspace_is_available_for_slots(session, workspace, [slot])
        and not workspace_has_blackout_for_slots(session, workspace, [slot])
        and not workspace_has_conflict(session, workspace.id, [slot])
    ]


def find_workspace_slot_matches(
    session: Session,
    *,
    slots: list[TimeSlot],
    city: str | None = None,
    min_daily_price: Decimal | None = None,
    max_daily_price: Decimal | None = None,
) -> list[tuple[Workspace, list[TimeSlot]]]:
    expire_stale_pending_bookings(session)
    query = select(Workspace).where(
        Workspace.status == WorkspaceStatus.ACTIVE,
        Workspace.review_status == WorkspaceReviewStatus.APPROVED,
    )

    if city:
        query = query.where(Workspace.city.ilike(f"%{city}%"))
    if min_daily_price is not None:
        query = query.where(Workspace.daily_price >= min_daily_price)
    if max_daily_price is not None:
        query = query.where(Workspace.daily_price <= max_daily_price)

    candidates = session.exec(query.order_by(Workspace.daily_price)).all()
    matches = [
        (workspace, matched_slots)
        for workspace in candidates
        if (matched_slots := matching_slots_for_workspace(session, workspace, slots))
    ]
    return sorted(matches, key=lambda match: (-len(match[1]), match[0].daily_price))


def calculate_booking_total(workspace: Workspace, slots: list[TimeSlot]) -> Decimal:
    return workspace.daily_price * len(slots)


def build_booking_rows(
    *,
    workspace: Workspace,
    user_id: UUID,
    slots: list[TimeSlot],
    rota_label: str | None = None,
    notes: str | None = None,
    booking_group_id: UUID | None = None,
) -> list[Booking]:
    expires_at = utc_now() + timedelta(minutes=settings.booking_hold_minutes)
    group_id = booking_group_id or uuid4()
    return [
        Booking(
            booking_group_id=group_id,
            user_id=user_id,
            workspace_id=workspace.id,
            start_at=slot.start_at,
            end_at=slot.end_at,
            status=BookingStatus.PENDING,
            total_price=workspace.daily_price,
            rota_label=rota_label,
            notes=notes,
            expires_at=expires_at,
        )
        for slot in slots
    ]
