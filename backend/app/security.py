from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from secrets import token_bytes
from uuid import UUID

from app.config import get_settings

settings = get_settings()
AUTH_SECRET_KEY = settings.auth_secret_key
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_BYTES = 32
ACCOUNT_TOKEN_BYTES = 32
PBKDF2_ITERATIONS = 390_000


class TokenError(ValueError):
    pass


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    salt = token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return "pbkdf2_sha256${iterations}${salt}${digest}".format(
        iterations=PBKDF2_ITERATIONS,
        salt=_b64url_encode(salt),
        digest=_b64url_encode(derived_key),
    )


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        algorithm, iterations, salt, expected_digest = hashed_password.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        _b64url_decode(salt),
        int(iterations),
    )
    return hmac.compare_digest(_b64url_encode(derived_key), expected_digest)


def create_access_token(user_id: UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}

    signing_input = ".".join(
        [
            _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        AUTH_SECRET_KEY.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def create_refresh_token() -> str:
    return _b64url_encode(token_bytes(REFRESH_TOKEN_BYTES))


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_account_token() -> str:
    return _b64url_encode(token_bytes(ACCOUNT_TOKEN_BYTES))


def hash_account_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_access_token(token: str) -> UUID:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
    except ValueError as exc:
        raise TokenError("Malformed token") from exc

    signing_input = f"{encoded_header}.{encoded_payload}"
    expected_signature = hmac.new(
        AUTH_SECRET_KEY.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    actual_signature = _b64url_decode(encoded_signature)
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise TokenError("Invalid token signature")

    try:
        payload = json.loads(_b64url_decode(encoded_payload))
        expires_at = int(payload["exp"])
        subject = payload["sub"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TokenError("Invalid token payload") from exc

    if expires_at <= int(datetime.now(timezone.utc).timestamp()):
        raise TokenError("Token has expired")

    try:
        return UUID(subject)
    except ValueError as exc:
        raise TokenError("Invalid token subject") from exc
