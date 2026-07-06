import pytest

from app.config import ConfigError, get_settings, normalize_database_url


def clear_settings_cache():
    get_settings.cache_clear()


def test_normalize_database_url_accepts_platform_postgres_urls():
    assert (
        normalize_database_url("postgres://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )
    assert (
        normalize_database_url("postgresql+psycopg://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )


def test_development_allows_local_defaults(monkeypatch):
    clear_settings_cache()
    for name in [
        "APP_ENV",
        "DATABASE_URL",
        "AUTH_SECRET_KEY",
        "CORS_ORIGINS",
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "REFRESH_TOKEN_EXPIRE_DAYS",
        "BOOKING_HOLD_MINUTES",
        "TRUST_PROXY_HEADERS",
        "PAYMENT_PROVIDER",
        "RAZORPAY_KEY_ID",
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "ALLOW_MOCK_PAYMENTS_IN_PRODUCTION",
        "EMAIL_PROVIDER",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_USE_TLS",
        "SMTP_USE_SSL",
        "ALLOW_LOG_EMAIL_IN_PRODUCTION",
    ]:
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.app_env == "development"
    assert settings.auth_secret_key == "dev-only-change-me"
    assert settings.payment_provider == "mock"
    assert "http://localhost:3000" in settings.cors_origins

    clear_settings_cache()


def test_rejects_invalid_proxy_header_boolean(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "maybe")

    with pytest.raises(ConfigError, match="TRUST_PROXY_HEADERS"):
        get_settings()

    clear_settings_cache()


def test_production_rejects_weak_auth_secret(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "dev-only-change-me")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("ALLOW_LOG_EMAIL_IN_PRODUCTION", "1")

    with pytest.raises(ConfigError, match="AUTH_SECRET_KEY"):
        get_settings()

    clear_settings_cache()


def test_production_rejects_non_postgres_database(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./dev.db")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("ALLOW_LOG_EMAIL_IN_PRODUCTION", "1")

    with pytest.raises(ConfigError, match="DATABASE_URL"):
        get_settings()

    clear_settings_cache()


def test_production_rejects_insecure_cors_origin(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "http://app.example.com")
    monkeypatch.setenv("ALLOW_LOG_EMAIL_IN_PRODUCTION", "1")

    with pytest.raises(ConfigError, match="https"):
        get_settings()

    clear_settings_cache()


def test_production_accepts_hardened_settings(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://admin.example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_live_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "rzp_webhook_secret")
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-password")

    settings = get_settings()

    assert settings.is_production is True
    assert settings.cors_origins == ["https://app.example.com", "https://admin.example.com"]
    assert settings.payment_provider == "razorpay"
    assert settings.razorpay_key_id == "rzp_live_key"
    assert settings.email_provider == "smtp"
    assert settings.smtp_host == "smtp.example.com"

    clear_settings_cache()


def test_production_rejects_mock_payment_provider(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.setenv("ALLOW_LOG_EMAIL_IN_PRODUCTION", "1")

    with pytest.raises(ConfigError, match="PAYMENT_PROVIDER"):
        get_settings()

    clear_settings_cache()


def test_rejects_unknown_payment_provider(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("PAYMENT_PROVIDER", "cash")

    with pytest.raises(ConfigError, match="PAYMENT_PROVIDER"):
        get_settings()

    clear_settings_cache()


def test_production_rejects_missing_razorpay_credentials(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_key")
    monkeypatch.setenv("ALLOW_LOG_EMAIL_IN_PRODUCTION", "1")

    with pytest.raises(ConfigError, match="RAZORPAY_KEY_SECRET"):
        get_settings()

    clear_settings_cache()


def test_production_rejects_missing_stripe_credentials(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("PAYMENT_PROVIDER", "stripe")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_secret")
    monkeypatch.setenv("ALLOW_LOG_EMAIL_IN_PRODUCTION", "1")

    with pytest.raises(ConfigError, match="STRIPE_WEBHOOK_SECRET"):
        get_settings()

    clear_settings_cache()


def test_rejects_unknown_email_provider(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("EMAIL_PROVIDER", "mailbox")

    with pytest.raises(ConfigError, match="EMAIL_PROVIDER"):
        get_settings()

    clear_settings_cache()


def test_production_rejects_log_email_provider_without_override(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.setenv("ALLOW_MOCK_PAYMENTS_IN_PRODUCTION", "1")
    monkeypatch.setenv("EMAIL_PROVIDER", "log")

    with pytest.raises(ConfigError, match="EMAIL_PROVIDER"):
        get_settings()

    clear_settings_cache()


def test_production_rejects_missing_smtp_credentials(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.setenv("ALLOW_MOCK_PAYMENTS_IN_PRODUCTION", "1")
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

    with pytest.raises(ConfigError, match="SMTP_USERNAME"):
        get_settings()

    clear_settings_cache()
