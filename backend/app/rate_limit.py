from collections import defaultdict, deque
from time import monotonic

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.observability import REQUEST_ID_HEADER


AUTH_RATE_LIMIT_PATHS = {
    "/auth/register",
    "/auth/login",
    "/auth/refresh",
    "/auth/password-reset/request",
    "/auth/password-reset/confirm",
    "/auth/email-verification/confirm",
}


class InMemoryRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        self._requests.clear()

    def _prune(self, key: str, now: float) -> deque[float]:
        cutoff = now - self.window_seconds
        timestamps = self._requests[key]
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        return timestamps

    def check(self, key: str) -> tuple[bool, int, int]:
        now = monotonic()
        timestamps = self._prune(key, now)

        if len(timestamps) >= self.limit:
            retry_after = max(1, int(self.window_seconds - (now - timestamps[0])))
            return False, 0, retry_after

        timestamps.append(now)
        return True, self.limit - len(timestamps), 0

    def check_many(self, keys: list[str]) -> tuple[bool, int, int]:
        now = monotonic()
        timestamp_sets = [(key, self._prune(key, now)) for key in keys]
        limited_sets = [timestamps for _, timestamps in timestamp_sets if len(timestamps) >= self.limit]
        if limited_sets:
            retry_after = max(
                1,
                max(int(self.window_seconds - (now - timestamps[0])) for timestamps in limited_sets),
            )
            return False, 0, retry_after

        for _, timestamps in timestamp_sets:
            timestamps.append(now)
        remaining = min(self.limit - len(timestamps) for _, timestamps in timestamp_sets)
        return True, remaining, 0


def client_ip(request: Request, *, trust_proxy_headers: bool) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if trust_proxy_headers and forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


async def account_rate_limit_subject(request: Request) -> str | None:
    if request.url.path not in {"/auth/register", "/auth/login", "/auth/password-reset/request"}:
        return None
    try:
        body = await request.json()
    except Exception:
        return None
    email = body.get("email") if isinstance(body, dict) else None
    if not isinstance(email, str):
        return None
    normalized = email.strip().lower()
    return normalized or None


async def rate_limit_keys(request: Request, *, trust_proxy_headers: bool) -> list[str]:
    ip_key = f"ip:{client_ip(request, trust_proxy_headers=trust_proxy_headers)}:{request.url.path}"
    subject = await account_rate_limit_subject(request)
    if subject is None:
        return [ip_key]
    return [ip_key, f"account:{subject}:{request.url.path}"]


def rate_limit_response(request: Request, *, retry_after: int) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        request_id = request.headers.get(REQUEST_ID_HEADER, "")
    response = JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": "Too many requests. Please try again soon.",
            "error_code": "rate_limited",
            "request_id": request_id,
        },
        headers={"Retry-After": str(retry_after)},
    )
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


def configure_rate_limiting(
    app: FastAPI,
    *,
    auth_limit_per_minute: int,
    trust_proxy_headers: bool = False,
) -> None:
    limiter = InMemoryRateLimiter(limit=auth_limit_per_minute)
    app.state.rate_limiter = limiter
    app.state.trust_proxy_headers = trust_proxy_headers

    @app.middleware("http")
    async def auth_rate_limit_middleware(request: Request, call_next):
        if request.url.path not in AUTH_RATE_LIMIT_PATHS:
            return await call_next(request)

        allowed, remaining, retry_after = limiter.check_many(
            await rate_limit_keys(
                request,
                trust_proxy_headers=bool(getattr(app.state, "trust_proxy_headers", False)),
            )
        )
        if not allowed:
            return rate_limit_response(request, retry_after=retry_after)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limiter.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
