import pytest

from app.config import ConfigError, get_settings


def clear_settings_cache():
    get_settings.cache_clear()


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
        "PAYMENT_PROVIDER",
        "RAZORPAY_KEY_ID",
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "ALLOW_MOCK_PAYMENTS_IN_PRODUCTION",
    ]:
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.app_env == "development"
    assert settings.auth_secret_key == "dev-only-change-me"
    assert settings.payment_provider == "mock"
    assert "http://localhost:3000" in settings.cors_origins

    clear_settings_cache()


def test_production_rejects_weak_auth_secret(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "dev-only-change-me")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")

    with pytest.raises(ConfigError, match="AUTH_SECRET_KEY"):
        get_settings()

    clear_settings_cache()


def test_production_rejects_non_postgres_database(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./dev.db")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")

    with pytest.raises(ConfigError, match="DATABASE_URL"):
        get_settings()

    clear_settings_cache()


def test_production_rejects_insecure_cors_origin(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "http://app.example.com")

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

    settings = get_settings()

    assert settings.is_production is True
    assert settings.cors_origins == ["https://app.example.com", "https://admin.example.com"]
    assert settings.payment_provider == "razorpay"
    assert settings.razorpay_key_id == "rzp_live_key"

    clear_settings_cache()


def test_production_rejects_mock_payment_provider(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/room_booking")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-real-production-secret-with-enough-length")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")

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

    with pytest.raises(ConfigError, match="STRIPE_WEBHOOK_SECRET"):
        get_settings()

    clear_settings_cache()
