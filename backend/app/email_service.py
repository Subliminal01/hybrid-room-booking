import logging
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.models import User


logger = logging.getLogger("app.email")


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def expose_tokens_in_response(self) -> bool:
        return not self.settings.is_production

    def send(self, message: EmailMessage) -> None:
        logger.info(
            "email_queued",
            extra={
                "to": message.to,
                "subject": message.subject,
            },
        )

    def send_email_verification(self, user: User, token: str) -> str | None:
        link = f"{self.settings.frontend_base_url}/?verification_token={token}"
        self.send(
            EmailMessage(
                to=user.email,
                subject="Verify your Hybrid Rooms email",
                body=(
                    f"Hi {user.full_name},\n\n"
                    f"Verify your email using this link:\n{link}\n\n"
                    "This link expires in 24 hours."
                ),
            )
        )
        return token if self.expose_tokens_in_response else None

    def send_password_reset(self, user: User, token: str) -> str | None:
        link = f"{self.settings.frontend_base_url}/?reset_token={token}"
        self.send(
            EmailMessage(
                to=user.email,
                subject="Reset your Hybrid Rooms password",
                body=(
                    f"Hi {user.full_name},\n\n"
                    f"Reset your password using this link:\n{link}\n\n"
                    "This link expires in 1 hour."
                ),
            )
        )
        return token if self.expose_tokens_in_response else None


def get_email_service() -> EmailService:
    return EmailService()
