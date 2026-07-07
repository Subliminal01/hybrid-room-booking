from functools import lru_cache
from os import getenv


DEV_AUTH_SECRET_KEY = "dev-only-change-me"
DEV_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/room_booking"
DEV_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
PRODUCTION_ENV_NAMES = {"prod", "production"}
SUPPORTED_PAYMENT_PROVIDERS = {"mock", "razorpay", "stripe"}
SUPPORTED_EMAIL_PROVIDERS = {"log", "smtp"}
SUPPORTED_STORAGE_PROVIDERS = {"local", "s3"}
WEAK_SECRET_VALUES = {
    "",
    DEV_AUTH_SECRET_KEY,
    "dev-compose-change-me",
    "replace-with-a-long-random-secret",
}


class ConfigError(RuntimeError):
    pass


def parse_csv_env(name: str, default: str) -> list[str]:
    raw_value = getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def parse_int_env(name: str, default: int) -> int:
    raw_value = getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return value


def parse_float_env(name: str, default: float) -> float:
    raw_value = getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    return value


def parse_optional_env(name: str) -> str | None:
    value = getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def parse_bool_env(name: str, default: bool = False) -> bool:
    raw_value = getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def parse_bool_env_strict(name: str, default: bool = False) -> bool:
    raw_value = getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    return value


class Settings:
    def __init__(self) -> None:
        self.app_env = getenv("APP_ENV", "development").strip().lower()
        self.database_url = normalize_database_url(getenv("DATABASE_URL", DEV_DATABASE_URL))
        self.sql_echo = getenv("SQL_ECHO") == "1"
        self.log_level = getenv("LOG_LEVEL", "INFO").strip().upper()
        self.sentry_dsn = parse_optional_env("SENTRY_DSN")
        self.sentry_environment = getenv("SENTRY_ENVIRONMENT", self.app_env).strip()
        self.sentry_release = parse_optional_env("SENTRY_RELEASE")
        self.sentry_traces_sample_rate = parse_float_env("SENTRY_TRACES_SAMPLE_RATE", 0.0)
        self.auth_secret_key = getenv("AUTH_SECRET_KEY", DEV_AUTH_SECRET_KEY)
        self.access_token_expire_minutes = parse_int_env("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
        self.refresh_token_expire_days = parse_int_env("REFRESH_TOKEN_EXPIRE_DAYS", 30)
        self.booking_hold_minutes = parse_int_env("BOOKING_HOLD_MINUTES", 30)
        self.auth_rate_limit_per_minute = parse_int_env("AUTH_RATE_LIMIT_PER_MINUTE", 120)
        self.trust_proxy_headers = parse_bool_env_strict("TRUST_PROXY_HEADERS")
        self.upload_dir = getenv("UPLOAD_DIR", "uploads").strip() or "uploads"
        self.max_upload_bytes = parse_int_env("MAX_UPLOAD_BYTES", 5 * 1024 * 1024)
        self.public_api_base_url = parse_optional_env("PUBLIC_API_BASE_URL")
        self.storage_provider = getenv("STORAGE_PROVIDER", "local").strip().lower()
        self.s3_bucket = parse_optional_env("S3_BUCKET")
        self.s3_region = getenv("S3_REGION", "auto").strip()
        self.s3_endpoint_url = parse_optional_env("S3_ENDPOINT_URL")
        self.s3_access_key_id = parse_optional_env("S3_ACCESS_KEY_ID")
        self.s3_secret_access_key = parse_optional_env("S3_SECRET_ACCESS_KEY")
        self.s3_public_base_url = parse_optional_env("S3_PUBLIC_BASE_URL")
        self.frontend_base_url = getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
        self.email_from = getenv("EMAIL_FROM", "noreply@hybridrooms.local")
        self.email_provider = getenv("EMAIL_PROVIDER", "log").strip().lower()
        self.smtp_host = parse_optional_env("SMTP_HOST")
        self.smtp_port = parse_int_env("SMTP_PORT", 587)
        self.smtp_username = parse_optional_env("SMTP_USERNAME")
        self.smtp_password = parse_optional_env("SMTP_PASSWORD")
        self.smtp_use_tls = parse_bool_env("SMTP_USE_TLS", True)
        self.smtp_use_ssl = parse_bool_env("SMTP_USE_SSL", False)
        self.allow_log_email_in_production = parse_bool_env("ALLOW_LOG_EMAIL_IN_PRODUCTION")
        self.payment_provider = getenv("PAYMENT_PROVIDER", "mock").strip().lower()
        self.razorpay_key_id = parse_optional_env("RAZORPAY_KEY_ID")
        self.razorpay_key_secret = parse_optional_env("RAZORPAY_KEY_SECRET")
        self.razorpay_webhook_secret = parse_optional_env("RAZORPAY_WEBHOOK_SECRET")
        self.stripe_secret_key = parse_optional_env("STRIPE_SECRET_KEY")
        self.stripe_webhook_secret = parse_optional_env("STRIPE_WEBHOOK_SECRET")
        self.allow_mock_payments_in_production = (
            getenv("ALLOW_MOCK_PAYMENTS_IN_PRODUCTION") == "1"
        )
        self.cors_origins = parse_csv_env("CORS_ORIGINS", DEV_CORS_ORIGINS)
        self.validate()

    @property
    def is_production(self) -> bool:
        return self.app_env in PRODUCTION_ENV_NAMES

    def validate(self) -> None:
        if "*" in self.cors_origins:
            raise ConfigError("CORS_ORIGINS cannot contain '*'")

        if self.payment_provider not in SUPPORTED_PAYMENT_PROVIDERS:
            raise ConfigError(
                "PAYMENT_PROVIDER must be one of: "
                + ", ".join(sorted(SUPPORTED_PAYMENT_PROVIDERS))
            )

        if self.email_provider not in SUPPORTED_EMAIL_PROVIDERS:
            raise ConfigError(
                "EMAIL_PROVIDER must be one of: "
                + ", ".join(sorted(SUPPORTED_EMAIL_PROVIDERS))
            )

        if self.storage_provider not in SUPPORTED_STORAGE_PROVIDERS:
            raise ConfigError(
                "STORAGE_PROVIDER must be one of: "
                + ", ".join(sorted(SUPPORTED_STORAGE_PROVIDERS))
            )

        if self.storage_provider == "s3":
            missing = [
                name
                for name, value in {
                    "S3_BUCKET": self.s3_bucket,
                    "S3_ACCESS_KEY_ID": self.s3_access_key_id,
                    "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
                    "S3_PUBLIC_BASE_URL": self.s3_public_base_url,
                }.items()
                if not value
            ]
            if missing:
                raise ConfigError(f"Missing S3 storage settings: {', '.join(missing)}")
            if self.s3_public_base_url and not self.s3_public_base_url.startswith("https://"):
                raise ConfigError("S3_PUBLIC_BASE_URL must use https://")

        if not 0 <= self.sentry_traces_sample_rate <= 1:
            raise ConfigError("SENTRY_TRACES_SAMPLE_RATE must be between 0 and 1")

        if self.sentry_dsn and not self.sentry_environment:
            raise ConfigError("SENTRY_ENVIRONMENT is required when SENTRY_DSN is set")

        if not self.is_production:
            return

        if len(self.auth_secret_key) < 32 or self.auth_secret_key in WEAK_SECRET_VALUES:
            raise ConfigError("AUTH_SECRET_KEY must be a strong production secret")

        if not self.database_url.startswith("postgresql"):
            raise ConfigError("DATABASE_URL must point to PostgreSQL in production")

        if not self.cors_origins:
            raise ConfigError("CORS_ORIGINS must include at least one production origin")

        insecure_origins = [
            origin for origin in self.cors_origins if not origin.startswith("https://")
        ]
        if insecure_origins:
            raise ConfigError("CORS_ORIGINS must use https:// origins in production")

        if not self.frontend_base_url.startswith("https://"):
            raise ConfigError("FRONTEND_BASE_URL must use https:// in production")

        if self.email_provider == "log" and not self.allow_log_email_in_production:
            raise ConfigError("EMAIL_PROVIDER cannot be log in production")

        if self.email_provider == "smtp":
            missing = [
                name
                for name, value in {
                    "SMTP_HOST": self.smtp_host,
                    "SMTP_USERNAME": self.smtp_username,
                    "SMTP_PASSWORD": self.smtp_password,
                }.items()
                if not value
            ]
            if missing:
                raise ConfigError(f"Missing SMTP email settings: {', '.join(missing)}")

        if self.payment_provider == "mock" and not self.allow_mock_payments_in_production:
            raise ConfigError("PAYMENT_PROVIDER cannot be mock in production")

        if self.payment_provider == "razorpay":
            missing = [
                name
                for name, value in {
                    "RAZORPAY_KEY_ID": self.razorpay_key_id,
                    "RAZORPAY_KEY_SECRET": self.razorpay_key_secret,
                    "RAZORPAY_WEBHOOK_SECRET": self.razorpay_webhook_secret,
                }.items()
                if not value
            ]
            if missing:
                raise ConfigError(f"Missing Razorpay payment settings: {', '.join(missing)}")

        if self.payment_provider == "stripe":
            missing = [
                name
                for name, value in {
                    "STRIPE_SECRET_KEY": self.stripe_secret_key,
                    "STRIPE_WEBHOOK_SECRET": self.stripe_webhook_secret,
                }.items()
                if not value
            ]
            if missing:
                raise ConfigError(f"Missing Stripe payment settings: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
