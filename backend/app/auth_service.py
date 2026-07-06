from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import get_settings
from app.models import AccountToken, AccountTokenPurpose, RefreshToken, User, UserRole, utc_now
from app.security import (
    create_account_token,
    create_access_token,
    create_refresh_token,
    hash_account_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

settings = get_settings()


class AuthError(ValueError):
    pass


class DuplicateEmailError(ValueError):
    pass


class RefreshTokenError(ValueError):
    pass


class AccountTokenError(ValueError):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.exec(select(User).where(User.email == normalize_email(email))).first()


def register_user(
    session: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    phone_number: str | None = None,
    role: UserRole = UserRole.WORKER,
) -> User:
    user = User(
        email=normalize_email(email),
        hashed_password=hash_password(password),
        full_name=full_name.strip(),
        phone_number=phone_number,
        role=role,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateEmailError("Email is already registered") from exc

    session.refresh(user)
    return user


def authenticate_user(session: Session, *, email: str, password: str) -> User:
    user = get_user_by_email(session, email)
    if user is None or not user.is_active:
        raise AuthError("Invalid email or password")
    if not verify_password(password, user.hashed_password):
        raise AuthError("Invalid email or password")
    return user


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def issue_user_token(user: User) -> str:
    return create_access_token(user.id)


def issue_user_session(session: Session, user: User) -> tuple[str, str]:
    refresh_token = create_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=utc_now() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    session.commit()
    return create_access_token(user.id), refresh_token


def revoke_user_refresh_tokens(session: Session, user_id) -> None:
    active_tokens = session.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).all()
    now = utc_now()
    for token_row in active_tokens:
        token_row.revoked_at = now
        session.add(token_row)


def rotate_refresh_token(session: Session, refresh_token: str) -> tuple[User, str, str]:
    token_row = session.exec(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(refresh_token),
        )
    ).first()
    if token_row is None or token_row.revoked_at is not None or as_utc(token_row.expires_at) <= utc_now():
        raise RefreshTokenError("Invalid refresh token")

    user = session.get(User, token_row.user_id)
    if user is None or not user.is_active:
        raise RefreshTokenError("Invalid refresh token")

    token_row.revoked_at = utc_now()
    session.add(token_row)
    access_token, new_refresh_token = issue_user_session(session, user)
    return user, access_token, new_refresh_token


def revoke_refresh_token(session: Session, refresh_token: str) -> None:
    token_row = session.exec(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(refresh_token),
        )
    ).first()
    if token_row is not None and token_row.revoked_at is None:
        token_row.revoked_at = utc_now()
        session.add(token_row)
        session.commit()


def issue_account_token(
    session: Session,
    user: User,
    *,
    purpose: AccountTokenPurpose,
    expires_in: timedelta,
) -> str:
    now = utc_now()
    active_tokens = session.exec(
        select(AccountToken).where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == purpose,
            AccountToken.used_at.is_(None),
        )
    ).all()
    for token_row in active_tokens:
        token_row.used_at = now
        session.add(token_row)

    token = create_account_token()
    session.add(
        AccountToken(
            user_id=user.id,
            token_hash=hash_account_token(token),
            purpose=purpose,
            expires_at=now + expires_in,
        )
    )
    session.commit()
    return token


def request_email_verification_token(session: Session, user: User) -> tuple[User, str]:
    token = issue_account_token(
        session,
        user,
        purpose=AccountTokenPurpose.EMAIL_VERIFICATION,
        expires_in=timedelta(hours=24),
    )
    return user, token


def confirm_email_verification_token(session: Session, token: str) -> User:
    token_row = session.exec(
        select(AccountToken).where(
            AccountToken.token_hash == hash_account_token(token),
            AccountToken.purpose == AccountTokenPurpose.EMAIL_VERIFICATION,
        )
    ).first()
    if token_row is None or token_row.used_at is not None or as_utc(token_row.expires_at) <= utc_now():
        raise AccountTokenError("Invalid or expired email verification token")

    user = session.get(User, token_row.user_id)
    if user is None or not user.is_active:
        raise AccountTokenError("Invalid or expired email verification token")

    now = utc_now()
    user.email_verified_at = now
    token_row.used_at = now
    session.add(user)
    session.add(token_row)
    session.commit()
    session.refresh(user)
    return user


def request_password_reset_token(session: Session, email: str) -> tuple[User, str] | None:
    user = get_user_by_email(session, email)
    if user is None or not user.is_active:
        return None

    token = issue_account_token(
        session,
        user,
        purpose=AccountTokenPurpose.PASSWORD_RESET,
        expires_in=timedelta(hours=1),
    )
    return user, token


def reset_password_with_token(session: Session, token: str, new_password: str) -> User:
    token_row = session.exec(
        select(AccountToken).where(
            AccountToken.token_hash == hash_account_token(token),
            AccountToken.purpose == AccountTokenPurpose.PASSWORD_RESET,
        )
    ).first()
    if token_row is None or token_row.used_at is not None or as_utc(token_row.expires_at) <= utc_now():
        raise AccountTokenError("Invalid or expired password reset token")

    user = session.get(User, token_row.user_id)
    if user is None or not user.is_active:
        raise AccountTokenError("Invalid or expired password reset token")

    now = utc_now()
    user.hashed_password = hash_password(new_password)
    token_row.used_at = now
    revoke_user_refresh_tokens(session, user.id)
    session.add(user)
    session.add(token_row)
    session.commit()
    session.refresh(user)
    return user
