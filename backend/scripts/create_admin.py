from os import getenv

from sqlmodel import Session

from app.auth_service import get_user_by_email, register_user
from app.database import engine
from app.models import UserRole
from app.security import hash_password


def required_env(name: str) -> str:
    value = getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    email = required_env("ADMIN_EMAIL")
    password = required_env("ADMIN_PASSWORD")
    full_name = getenv("ADMIN_FULL_NAME", "Platform Admin").strip() or "Platform Admin"

    if len(password) < 12:
        raise RuntimeError("ADMIN_PASSWORD must be at least 12 characters")

    with Session(engine) as session:
        user = get_user_by_email(session, email)
        if user is None:
            user = register_user(
                session,
                email=email,
                password=password,
                full_name=full_name,
                role=UserRole.ADMIN,
            )
            print(f"created admin user: {user.email}")
            return

        user.role = UserRole.ADMIN
        user.full_name = full_name
        user.hashed_password = hash_password(password)
        session.add(user)
        session.commit()
        print(f"updated admin user: {user.email}")


if __name__ == "__main__":
    main()
