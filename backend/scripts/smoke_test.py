from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_PASSWORD = "strong-password"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class SmokeTestError(RuntimeError):
    pass


@dataclass
class ApiClient:
    base_url: str

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected_status: int | tuple[int, ...] = 200,
    ) -> dict[str, Any] | list[Any]:
        expected = (
            expected_status
            if isinstance(expected_status, tuple)
            else (expected_status,)
        )
        request_headers = {"Accept": "application/json", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"

        request = Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read().decode("utf-8")
                if response.status not in expected:
                    raise SmokeTestError(
                        f"{method} {path} returned {response.status}, expected {expected}"
                    )
                return json.loads(payload) if payload else {}
        except HTTPError as exc:
            payload = exc.read().decode("utf-8")
            detail = payload
            try:
                detail = json.dumps(json.loads(payload), indent=2)
            except json.JSONDecodeError:
                pass
            raise SmokeTestError(
                f"{method} {path} returned {exc.code}, expected {expected}:\n{detail}"
            ) from exc
        except URLError as exc:
            raise SmokeTestError(f"Could not reach {self.base_url}: {exc.reason}") from exc


def next_weekday(start_date: date, weekday: int) -> date:
    days_ahead = (weekday - start_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return start_date + timedelta(days=days_ahead)


def rota_slots() -> list[dict[str, str]]:
    india_tz = timezone(timedelta(hours=5, minutes=30))
    monday = next_weekday(date.today(), 0)
    dates = [monday, monday + timedelta(days=2), monday + timedelta(days=4)]
    return [
        {
            "start_at": datetime.combine(slot_date, time(9), india_tz).isoformat(),
            "end_at": datetime.combine(slot_date, time(18), india_tz).isoformat(),
        }
        for slot_date in dates
    ]


def register(client: ApiClient, *, email: str, role: str) -> dict[str, Any]:
    return client.request(
        "POST",
        "/auth/register",
        body={
            "email": email,
            "password": DEFAULT_PASSWORD,
            "full_name": f"Smoke {role.title()}",
            "role": role,
        },
        expected_status=201,
    )


def run_smoke_test(base_url: str, *, complete_mock_payment: bool) -> None:
    client = ApiClient(base_url=base_url)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    print("1. Checking readiness")
    ready = client.request("GET", "/health/ready")
    if ready.get("status") != "ready":
        raise SmokeTestError(f"Unexpected readiness response: {ready}")

    print("2. Registering worker, host, and admin")
    worker = register(client, email=f"smoke-worker-{suffix}@example.com", role="worker")
    host = register(client, email=f"smoke-host-{suffix}@example.com", role="host")
    admin = register(client, email=f"smoke-admin-{suffix}@example.com", role="admin")

    print("3. Creating and approving workspace")
    workspace = client.request(
        "POST",
        "/workspaces",
        token=host["access_token"],
        body={
            "title": f"Smoke test focus room {suffix}",
            "description": "Automated smoke-test workspace.",
            "address_line": "12 Residency Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "daily_price": "850.00",
            "amenities": {"wifi": True, "desk": True, "ac": True},
        },
        expected_status=201,
    )
    client.request(
        "PUT",
        f"/workspaces/{workspace['id']}/availability",
        token=host["access_token"],
        body={
            "rules": [
                {"day_of_week": 0, "start_time": "09:00:00", "end_time": "18:00:00"},
                {"day_of_week": 2, "start_time": "09:00:00", "end_time": "18:00:00"},
                {"day_of_week": 4, "start_time": "09:00:00", "end_time": "18:00:00"},
            ]
        },
    )
    approved = client.request(
        "PATCH",
        f"/admin/workspaces/{workspace['id']}/review",
        token=admin["access_token"],
        body={"review_status": "approved"},
    )
    if approved.get("review_status") != "approved":
        raise SmokeTestError("Workspace was not approved")

    slots = rota_slots()
    print("4. Searching available rota slots")
    search_results = client.request(
        "POST",
        "/workspaces/search",
        body={
            "city": "Bengaluru",
            "max_daily_price": "1000.00",
            "slots": slots,
        },
    )
    if not any(result["id"] == workspace["id"] for result in search_results):
        raise SmokeTestError("Created workspace was not returned by search")

    print("5. Creating rota booking")
    booking_response = client.request(
        "POST",
        "/bookings",
        token=worker["access_token"],
        headers={"Idempotency-Key": f"smoke-{suffix}"},
        body={
            "workspace_id": workspace["id"],
            "rota_label": "Smoke rota",
            "slots": slots,
        },
        expected_status=201,
    )
    bookings = booking_response["bookings"]
    booking_group_id = bookings[0]["booking_group_id"]
    if len(bookings) != 3:
        raise SmokeTestError(f"Expected 3 bookings, received {len(bookings)}")

    print("6. Creating checkout session")
    checkout = client.request(
        "POST",
        f"/booking-groups/{booking_group_id}/checkout-session",
        token=worker["access_token"],
    )
    if checkout["total_amount"] != booking_response["total_price"]:
        raise SmokeTestError("Checkout total does not match booking total")

    if checkout["provider"] != "mock" or not complete_mock_payment:
        print(
            "7. Skipping payment confirmation because provider is "
            f"{checkout['provider']!r}"
        )
        print("Smoke test passed through checkout creation")
        return

    print("7. Confirming mock payment and receipt")
    paid = client.request(
        "POST",
        f"/booking-groups/{booking_group_id}/payment-confirm",
        token=worker["access_token"],
    )
    if paid["total_paid"] != checkout["total_amount"]:
        raise SmokeTestError("Paid total does not match checkout total")
    receipt = client.request(
        "GET",
        f"/booking-groups/{booking_group_id}/receipt",
        token=worker["access_token"],
    )
    if receipt["net_paid"] != checkout["total_amount"]:
        raise SmokeTestError("Receipt net paid does not match checkout total")

    print("8. Verifying worker history, host revenue, and admin audit")
    history = client.request("GET", "/bookings/mine", token=worker["access_token"])
    revenue = client.request("GET", "/bookings/host/revenue", token=host["access_token"])
    audit = client.request("GET", "/admin/audit-events", token=admin["access_token"])
    if history["total"] < 3:
        raise SmokeTestError("Worker history did not include smoke bookings")
    if revenue["confirmed_booking_count"] < 3:
        raise SmokeTestError("Host revenue did not include confirmed bookings")
    if audit["total"] < 1:
        raise SmokeTestError("Admin audit log is empty")

    print("Smoke test passed end to end")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a post-deploy API smoke test.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Backend API base URL. Defaults to {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--skip-payment",
        action="store_true",
        help="Stop after checkout session creation even when the API uses mock payments.",
    )
    args = parser.parse_args()
    run_smoke_test(args.base_url, complete_mock_payment=not args.skip_payment)


if __name__ == "__main__":
    main()
