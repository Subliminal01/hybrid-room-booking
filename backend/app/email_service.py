import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as SmtpEmailMessage

import httpx

from app.config import Settings, get_settings
from app.models import User


logger = logging.getLogger("app.email")
BREVO_EMAIL_URL = "https://api.brevo.com/v3/smtp/email"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailDeliveryError(RuntimeError):
    pass


class EmailService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def expose_tokens_in_response(self) -> bool:
        return not self.settings.is_production

    def send(self, message: EmailMessage) -> None:
        if self.settings.email_provider == "brevo":
            self._send_brevo(message)
            return

        if self.settings.email_provider == "smtp":
            self._send_smtp(message)
            return

        logger.info(
            "email_queued",
            extra={
                "to": message.to,
                "subject": message.subject,
            },
        )

    def _send_smtp(self, message: EmailMessage) -> None:
        smtp_message = SmtpEmailMessage()
        smtp_message["From"] = self.settings.email_from
        smtp_message["To"] = message.to
        smtp_message["Subject"] = message.subject
        smtp_message.set_content(message.body)

        smtp_host = self.settings.smtp_host
        if not smtp_host:
            raise RuntimeError("SMTP_HOST is required when EMAIL_PROVIDER=smtp")

        smtp_class = smtplib.SMTP_SSL if self.settings.smtp_use_ssl else smtplib.SMTP
        try:
            with smtp_class(smtp_host, self.settings.smtp_port, timeout=10) as smtp:
                if self.settings.smtp_use_tls and not self.settings.smtp_use_ssl:
                    smtp.starttls()
                if self.settings.smtp_username and self.settings.smtp_password:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(smtp_message)
        except OSError as exc:
            raise EmailDeliveryError(f"SMTP connection failed: {exc}") from exc
        except smtplib.SMTPException as exc:
            raise EmailDeliveryError(f"SMTP delivery failed: {exc}") from exc

        logger.info(
            "email_sent",
            extra={
                "to": message.to,
                "subject": message.subject,
                "provider": self.settings.email_provider,
            },
        )

    def _send_brevo(self, message: EmailMessage) -> None:
        if not self.settings.brevo_api_key:
            raise EmailDeliveryError("BREVO_API_KEY is required when EMAIL_PROVIDER=brevo")

        payload = {
            "sender": {"email": self.settings.email_from},
            "to": [{"email": message.to}],
            "subject": message.subject,
            "textContent": message.body,
        }
        headers = {
            "accept": "application/json",
            "api-key": self.settings.brevo_api_key,
            "content-type": "application/json",
        }

        try:
            response = httpx.post(BREVO_EMAIL_URL, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:240]
            raise EmailDeliveryError(
                f"Brevo email delivery failed with status {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise EmailDeliveryError(f"Brevo email delivery failed: {exc}") from exc

        logger.info(
            "email_sent",
            extra={
                "to": message.to,
                "subject": message.subject,
                "provider": self.settings.email_provider,
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

    def send_admin_test_email(self, user: User) -> None:
        self.send(
            EmailMessage(
                to=user.email,
                subject="Hybrid Rooms email delivery test",
                body=(
                    f"Hi {user.full_name},\n\n"
                    "This confirms transactional email delivery is configured for "
                    "Hybrid Rooms.\n\n"
                    f"Provider: {self.settings.email_provider}"
                ),
            )
        )


def get_email_service(settings: Settings | None = None) -> EmailService:
    return EmailService(settings)
