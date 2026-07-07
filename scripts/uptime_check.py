from __future__ import annotations

import argparse
import json
import time
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_FRONTEND_URL = "https://hybrid-room-booking.vercel.app"
DEFAULT_BACKEND_READY_URL = "https://hybrid-room-booking-api.onrender.com/health/ready"


class UptimeCheckError(RuntimeError):
    pass


def fetch(url: str, *, timeout: int) -> tuple[int, bytes]:
    request = Request(url, headers={"User-Agent": "hybrid-room-booking-uptime-check/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as exc:
        body = exc.read()
        raise UptimeCheckError(f"{url} returned HTTP {exc.code}: {body[:300]!r}") from exc
    except URLError as exc:
        raise UptimeCheckError(f"{url} could not be reached: {exc.reason}") from exc


def check_frontend(url: str, *, timeout: int) -> None:
    status, body = fetch(url, timeout=timeout)
    if status < 200 or status >= 400:
        raise UptimeCheckError(f"Frontend returned HTTP {status}")
    html = body.decode("utf-8", errors="replace")
    if "Hybrid Stay Booking" not in html:
        raise UptimeCheckError("Frontend did not include expected app shell text")
    print(f"frontend: ok ({status})")


def check_backend(url: str, *, timeout: int, attempts: int, retry_delay: int) -> None:
    last_error: UptimeCheckError | None = None
    for attempt in range(1, attempts + 1):
        try:
            status, body = fetch(url, timeout=timeout)
            break
        except UptimeCheckError as exc:
            last_error = exc
            if attempt == attempts:
                raise
            print(f"backend: attempt {attempt} failed, retrying in {retry_delay}s")
            time.sleep(retry_delay)
    else:
        raise last_error or UptimeCheckError("Backend readiness could not be checked")

    if status != 200:
        raise UptimeCheckError(f"Backend readiness returned HTTP {status}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise UptimeCheckError(f"Backend readiness returned invalid JSON: {body[:300]!r}") from exc
    if payload.get("status") != "ready" or payload.get("database") != "ok":
        raise UptimeCheckError(f"Unexpected backend readiness payload: {payload}")
    print("backend: ok (ready, database ok)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check deployed frontend and backend uptime.")
    parser.add_argument("--frontend-url", default=DEFAULT_FRONTEND_URL)
    parser.add_argument("--backend-ready-url", default=DEFAULT_BACKEND_READY_URL)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--backend-timeout", type=int, default=60)
    parser.add_argument("--backend-attempts", type=int, default=4)
    parser.add_argument("--backend-retry-delay", type=int, default=15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        check_frontend(args.frontend_url, timeout=args.timeout)
        check_backend(
            args.backend_ready_url,
            timeout=args.backend_timeout,
            attempts=args.backend_attempts,
            retry_delay=args.backend_retry_delay,
        )
    except UptimeCheckError as exc:
        print(f"uptime check failed: {exc}", file=sys.stderr)
        return 1
    print("uptime check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
