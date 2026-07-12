from types import SimpleNamespace

from app.email_service import EmailMessage, EmailService
from app.models import User


def make_settings(**overrides):
    defaults = {
        "is_production": False,
        "frontend_base_url": "https://app.example.com",
        "email_from": "support@example.com",
        "email_provider": "log",
        "smtp_host": None,
        "smtp_port": 587,
        "smtp_username": None,
        "smtp_password": None,
        "smtp_use_tls": True,
        "smtp_use_ssl": False,
        "brevo_api_key": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class FakeSmtp:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.sent_messages = []
        self.closed = False
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.sent_messages.append(message)


def test_smtp_email_provider_sends_message(monkeypatch):
    FakeSmtp.instances = []
    monkeypatch.setattr("app.email_service.smtplib.SMTP", FakeSmtp)
    service = EmailService(
        make_settings(
            email_provider="smtp",
            smtp_host="smtp.example.com",
            smtp_username="smtp-user",
            smtp_password="smtp-password",
        )
    )

    service.send(
        EmailMessage(
            to="worker@example.com",
            subject="Reset your password",
            body="Use this link to reset your password.",
        )
    )

    smtp = FakeSmtp.instances[0]
    assert smtp.host == "smtp.example.com"
    assert smtp.port == 587
    assert smtp.timeout == 10
    assert smtp.started_tls is True
    assert smtp.login_args == ("smtp-user", "smtp-password")
    assert smtp.closed is True
    message = smtp.sent_messages[0]
    assert message["From"] == "support@example.com"
    assert message["To"] == "worker@example.com"
    assert message["Subject"] == "Reset your password"
    assert "Use this link" in message.get_content()


def test_smtp_ssl_skips_starttls(monkeypatch):
    FakeSmtp.instances = []
    monkeypatch.setattr("app.email_service.smtplib.SMTP_SSL", FakeSmtp)
    service = EmailService(
        make_settings(
            email_provider="smtp",
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_use_ssl=True,
        )
    )

    service.send(EmailMessage(to="worker@example.com", subject="Hi", body="Hello"))

    smtp = FakeSmtp.instances[0]
    assert smtp.port == 465
    assert smtp.started_tls is False


def test_brevo_email_provider_sends_message(monkeypatch):
    calls = []

    class FakeResponse:
        text = '{"messageId":"abc"}'

        def raise_for_status(self):
            return None

    def fake_post(url, *, json, headers, timeout):
        calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr("app.email_service.httpx.post", fake_post)
    service = EmailService(
        make_settings(
            email_provider="brevo",
            brevo_api_key="brevo-key",
        )
    )

    service.send(
        EmailMessage(
            to="worker@example.com",
            subject="Verify your email",
            body="Use this link to verify your email.",
        )
    )

    assert calls == [
        {
            "url": "https://api.brevo.com/v3/smtp/email",
            "json": {
                "sender": {"email": "support@example.com"},
                "to": [{"email": "worker@example.com"}],
                "subject": "Verify your email",
                "textContent": "Use this link to verify your email.",
            },
            "headers": {
                "accept": "application/json",
                "api-key": "brevo-key",
                "content-type": "application/json",
            },
            "timeout": 10,
        }
    ]


def test_production_email_methods_do_not_expose_tokens():
    service = EmailService(make_settings(is_production=True))
    user = User(
        email="worker@example.com",
        hashed_password="hash",
        full_name="Hybrid Worker",
    )

    assert service.send_email_verification(user, "verify-token") is None
    assert service.send_password_reset(user, "reset-token") is None


def test_development_email_methods_expose_tokens():
    service = EmailService(make_settings(is_production=False))
    user = User(
        email="worker@example.com",
        hashed_password="hash",
        full_name="Hybrid Worker",
    )

    assert service.send_email_verification(user, "verify-token") == "verify-token"
    assert service.send_password_reset(user, "reset-token") == "reset-token"
