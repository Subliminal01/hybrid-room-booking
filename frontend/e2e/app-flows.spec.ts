import { expect, Page, Route, test } from "@playwright/test";

type Role = "worker" | "host" | "admin";

function userFor(role: Role) {
  return {
    id: `${role}-user-id`,
    email: `${role}@example.com`,
    full_name: `${role[0].toUpperCase()}${role.slice(1)} User`,
    role,
    phone_number: null,
    is_active: true,
    email_verified_at: null,
  };
}

function sessionFor(role: Role) {
  return {
    access_token: `${role}-access-token`,
    refresh_token: `${role}-refresh-token`,
    token_type: "bearer",
    user: userFor(role),
  };
}

function workspace(overrides = {}) {
  return {
    id: "workspace-1",
    owner_id: "host-user-id",
    title: "Koramangala focus room",
    description: "Quiet room with desk and Wi-Fi.",
    address_line: "12 Residency Road",
    city: "Bengaluru",
    state: "Karnataka",
    country: "India",
    postal_code: null,
    photo_url: null,
    daily_price: "850.00",
    estimated_total_price: "1700.00",
    matched_slot_count: 2,
    currency: "INR",
    capacity: 1,
    status: "active",
    review_status: "pending",
    amenities: { wifi: true, desk: true },
    availability_rules: [
      {
        id: "rule-1",
        workspace_id: "workspace-1",
        day_of_week: 0,
        start_time: "09:00:00",
        end_time: "18:00:00",
      },
    ],
    blackout_dates: [],
    ...overrides,
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    headers: {
      "access-control-allow-credentials": "true",
      "access-control-allow-origin": "http://127.0.0.1:3100",
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

async function mockApi(page: Page) {
  await page.route(/https?:\/\/(?:localhost|127\.0\.0\.1):8000\/.*/, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "OPTIONS") {
      return route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-credentials": "true",
          "access-control-allow-headers": "authorization,content-type",
          "access-control-allow-methods": "GET,POST,PATCH,PUT,DELETE,OPTIONS",
          "access-control-allow-origin": "http://127.0.0.1:3100",
        },
      });
    }

    if (method === "POST" && path === "/auth/login") {
      const payload = request.postDataJSON() as { email?: string };
      const email = payload.email ?? "worker@example.com";
      const role = email.startsWith("host")
        ? "host"
        : email.startsWith("admin")
          ? "admin"
          : "worker";
      return fulfillJson(route, sessionFor(role));
    }

    if (method === "POST" && path === "/auth/logout") {
      return route.fulfill({ status: 204 });
    }

    if (method === "POST" && path === "/auth/email-verification/confirm") {
      return fulfillJson(route, {
        ...userFor("worker"),
        email_verified_at: "2026-07-12T10:00:00Z",
      });
    }

    if (method === "GET" && path === "/workspaces/mine") {
      return fulfillJson(route, [workspace({ review_status: "pending" })]);
    }

    if (method === "GET" && path === "/bookings/host") {
      return fulfillJson(route, { items: [], total: 0, limit: 10, offset: 0 });
    }

    if (method === "GET" && path === "/bookings/host/revenue") {
      return fulfillJson(route, {
        total_paid: "0.00",
        total_refunded: "0.00",
        pending_hold_value: "0.00",
        confirmed_booking_count: 0,
        cancelled_booking_count: 0,
        pending_booking_count: 0,
        paid_payment_count: 0,
        currency: "INR",
      });
    }

    if (method === "GET" && path === "/admin/workspaces/review") {
      return fulfillJson(route, [workspace({ id: "review-workspace-1" })]);
    }

    if (method === "GET" && path === "/admin/audit-events") {
      return fulfillJson(route, {
        items: [],
        total: 0,
        limit: 12,
        offset: 0,
      });
    }

    if (method === "GET" && path === "/admin/users") {
      return fulfillJson(route, {
        items: [userFor("worker"), userFor("host"), userFor("admin")],
        total: 3,
        limit: 8,
        offset: 0,
      });
    }

    if (method === "GET" && path === "/admin/bookings") {
      return fulfillJson(route, {
        items: [],
        total: 0,
        limit: 8,
        offset: 0,
      });
    }

    if (method === "GET" && path === "/admin/payments") {
      return fulfillJson(route, {
        items: [],
        total: 0,
        limit: 8,
        offset: 0,
      });
    }

    if (method === "GET" && path === "/admin/email/status") {
      return fulfillJson(route, {
        provider: "log",
        ready: true,
        from_address: "noreply@hybridrooms.local",
        smtp_host: null,
        smtp_port: null,
        smtp_use_tls: true,
        smtp_use_ssl: false,
        required_settings: [],
        missing_settings: [],
        test_supported: true,
      });
    }

    if (method === "GET" && path === "/admin/payment-provider/status") {
      return fulfillJson(route, {
        provider: "mock",
        ready: true,
        webhook_url: "http://localhost:8000/payments/webhooks/mock",
        required_settings: [],
        missing_settings: [],
        manual_confirmation_enabled: true,
      });
    }

    if (method === "GET" && path === "/admin/storage/status") {
      return fulfillJson(route, {
        provider: "local",
        ready: true,
        durable: false,
        public_base_url: null,
        required_settings: [],
        missing_settings: [],
      });
    }

    if (method === "POST" && path === "/admin/email/test") {
      return fulfillJson(route, {
        message: "Test email sent",
        provider: "log",
        recipient: "admin@example.com",
      });
    }

    if (method === "PATCH" && path === "/admin/workspaces/review-workspace-1/review") {
      return fulfillJson(route, workspace({ id: "review-workspace-1", review_status: "approved" }));
    }

    if (method === "POST" && path === "/workspaces/search") {
      return fulfillJson(route, [
        workspace({
          id: "search-workspace-1",
          review_status: "approved",
          estimated_total_price: "1700.00",
          matched_slot_count: 2,
        }),
      ]);
    }

    return fulfillJson(route, { detail: `Unhandled mock route: ${method} ${path}` }, 500);
  });
}

async function loginAs(page: Page, role: Role) {
  await page.goto("/");
  await page.locator("#email").fill(`${role}@example.com`);
  await page.locator("#password").fill("strong-password");
  await page.getByRole("button", { name: "Login" }).nth(1).click();
  await expect(page.getByText(`Signed in as ${role}@example.com`)).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("worker can search a rota and see matching workspaces", async ({ page }) => {
  await loginAs(page, "worker");

  await expect(page.getByLabel("Current dashboard mode")).toHaveText("Worker dashboard");
  await expect(page.getByRole("heading", { name: "Search Rota" })).toBeVisible();
  await page.getByRole("button", { name: "Tue/Thu" }).click();
  await page.getByRole("button", { name: "Search" }).click();

  await expect(page.getByText("Koramangala focus room")).toBeVisible();
  await expect(page.getByText("for 2 days")).toBeVisible();
});

test("worker email verification link updates saved session", async ({ page }) => {
  const session = sessionFor("worker");
  await page.goto("/");
  await page.evaluate((storedSession) => {
    window.localStorage.setItem("hybrid-room-booking-session", JSON.stringify(storedSession));
  }, session);

  await page.goto("/?verification_token=verify-token");

  await expect(page.getByText("Email verified.")).toBeVisible();
  await expect(page.locator(".security-row").getByText("verified")).toBeVisible();
  await expect(page).not.toHaveURL(/verification_token/);
});

test("email verification link works without an active session", async ({ page }) => {
  await page.goto("/?verification_token=verify-token");

  await expect(page.getByText("Email verified. Please sign in to continue.")).toBeVisible();
  await expect(page).not.toHaveURL(/verification_token/);
});

test("host sees host dashboard and listing manager only", async ({ page }) => {
  await loginAs(page, "host");

  await expect(page.getByLabel("Current dashboard mode")).toHaveText("Host dashboard");
  await expect(page.getByRole("heading", { name: "Host Workspace Manager" })).toBeVisible();
  await expect(page.getByText("Koramangala focus room")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Search Rota" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Workspace Review" })).toHaveCount(0);
});

test("admin can review a pending workspace", async ({ page }) => {
  await loginAs(page, "admin");

  await expect(page.getByLabel("Current dashboard mode")).toHaveText("Admin dashboard");
  await expect(page.getByRole("heading", { name: "Workspace Review" })).toBeVisible();
  await expect(page.getByText("Koramangala focus room")).toBeVisible();
  await page.getByLabel("Review note").fill("Looks good.");
  await page.getByRole("button", { name: "Approve" }).click();

  await expect(page.getByText("Koramangala focus room marked approved.")).toBeVisible();
  await expect(page.getByText("No listings are waiting for review.")).toBeVisible();
});
