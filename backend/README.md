# Room Booking Platform Backend

This folder currently contains the backend foundation through **Step 4**:

- Step 1: database models
- Step 2: FastAPI endpoints for availability search and booking creation
- Step 3: foundational pytest coverage for overlap and rota booking logic
- Step 4: Alembic migrations for PostgreSQL schema setup
- Step 5: authentication foundation with register, login, and current-user flow
- Step 6: authenticated workspace management for hosts
- Step 7: authenticated booking creation using the bearer-token user
- Step 8: booking history endpoints for workers and hosts
- Step 9: booking detail and cancellation endpoints with access controls
- Step 10: CORS/config/Docker setup for frontend and local deployment

## Step 1 Architecture

The first version uses:

- FastAPI-ready Python package layout under `backend/app`
- SQLModel on top of SQLAlchemy
- PostgreSQL as the target database
- One `Booking` row per reserved workspace interval

For a rota like:

- Worker A books Monday, Wednesday, Friday
- Worker B books Tuesday, Thursday

the API should create separate booking intervals for each requested date. That means both workers can share the same workspace as long as their intervals do not overlap.

## Overlap Strategy

The `bookings` table uses a PostgreSQL GiST exclusion constraint:

```sql
EXCLUDE USING gist (
  workspace_id WITH =,
  tstzrange(start_at, end_at, '[)') WITH &&
)
WHERE status IN ('pending', 'confirmed')
```

This prevents two active bookings from reserving the same workspace for overlapping time ranges. Cancelled and expired bookings are ignored.

The interval uses `[)` semantics: the start is included, the end is excluded. So a booking ending at `18:00` does not conflict with another starting at `18:00`.

## Model Files

- `app/models.py`: `User`, `Workspace`, and `Booking` SQLModel definitions
- `app/database.py`: SQLModel engine and session dependency
- `app/config.py`: environment-backed settings
- `app/security.py`: password hashing and signed bearer-token helpers
- `app/auth_service.py`: user registration and login service logic
- `app/dependencies.py`: shared FastAPI dependencies such as current user
- `app/schemas.py`: API request and response schemas
- `app/booking_service.py`: availability and booking helper logic
- `app/main.py`: FastAPI app and routes
- `tests/test_booking_service.py`: booking overlap and search tests
- `requirements.txt`: backend Python dependencies
- `.env.example`: local environment template
- `Dockerfile`: backend container definition
- `../docker-compose.yml`: local PostgreSQL + backend stack
- `alembic.ini`: Alembic configuration
- `migrations/`: database migration environment and version files

## API Endpoints

### `POST /auth/register`

Creates a user and returns a bearer token.

Public registration only accepts `worker` and `host` roles. Admin accounts must
be created through a controlled backend path.

For local development or deployed hosts with shell access, run:

```powershell
$env:ADMIN_EMAIL="admin@example.com"
$env:ADMIN_PASSWORD="replace-with-a-long-admin-password"
$env:ADMIN_FULL_NAME="Platform Admin"
python scripts/create_admin.py
```

On deployed environments without shell access, temporarily set
`ADMIN_BOOTSTRAP_SECRET` to a long random value, redeploy, and call:

```bash
curl -X POST https://your-api.example.com/admin/bootstrap \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "password": "replace-with-a-long-admin-password",
    "full_name": "Platform Admin",
    "bootstrap_secret": "the-temporary-bootstrap-secret"
  }'
```

After the admin account is created, remove `ADMIN_BOOTSTRAP_SECRET` from the
deployed environment and redeploy so `POST /admin/bootstrap` is disabled again.

### `POST /auth/login`

Authenticates an existing user and returns a bearer token.

### `GET /auth/me`

Returns the authenticated user for the supplied bearer token.

### `GET /health`, `GET /health/live`, `GET /health/ready`

`/health` and `/health/live` report that the API process is running.
`/health/ready` also checks database connectivity and is intended for deploy
readiness probes and container health checks.

### `POST /workspaces`

Allows a host/admin user to create a workspace listing.

### `GET /workspaces/mine`

Lists workspace listings owned by the authenticated host/admin user.

### `GET /workspaces/{workspace_id}`

Returns a single workspace by id.

### `PATCH /workspaces/{workspace_id}`

Allows the owning host, or an admin, to update a workspace listing.

### `POST /workspaces/search`

Searches active workspaces by city and price filters, then removes any workspace
that conflicts with one or more requested rota slots.

Example request:

```json
{
  "city": "Bengaluru",
  "max_daily_price": "1000.00",
  "slots": [
    {
      "start_at": "2026-06-15T09:00:00+05:30",
      "end_at": "2026-06-15T18:00:00+05:30"
    },
    {
      "start_at": "2026-06-17T09:00:00+05:30",
      "end_at": "2026-06-17T18:00:00+05:30"
    }
  ]
}
```

### `POST /bookings`

Creates one booking row per requested rota slot for the authenticated user. If
any slot conflicts, the request fails with `409 Conflict`.

Example request:

```json
{
  "workspace_id": "00000000-0000-0000-0000-000000000002",
  "rota_label": "June office rota",
  "slots": [
    {
      "start_at": "2026-06-15T09:00:00+05:30",
      "end_at": "2026-06-15T18:00:00+05:30"
    }
  ]
}
```

### `GET /bookings/mine`

Lists booking rows owned by the authenticated worker/user.

### `GET /bookings/host`

Lists bookings made against workspaces owned by the authenticated host. Admins
can see all bookings through this endpoint.

### `GET /bookings/{booking_id}`

Returns a booking if the authenticated user is the booking owner, the owning
workspace host, or an admin.

### `PATCH /bookings/{booking_id}/cancel`

Cancels a booking if the authenticated user is the booking owner, the owning
workspace host, or an admin.

## PostgreSQL Note

For UUID equality inside a GiST exclusion constraint, PostgreSQL usually needs the `btree_gist` extension enabled in the database migration:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

The first migration enables this extension before creating the booking overlap constraint.

## Database Migrations

Set `DATABASE_URL` to your PostgreSQL database, then run migrations from the
`backend` directory:

```bash
alembic upgrade head
```

PowerShell example:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/room_booking"
alembic upgrade head
```

The FastAPI app no longer creates tables on startup. Database schema changes
should go through Alembic.

## Local Run Sketch

Install dependencies, run migrations, point `DATABASE_URL` at PostgreSQL, then run:

```bash
uvicorn app.main:app --reload
```

Run the command from the `backend` directory.

Before releasing or deploying, run the lightweight release check:

```bash
python scripts/release_check.py
```

It validates environment-backed settings, imports the FastAPI app, and verifies
that Alembic has a single migration head.

## Environment Safety

`APP_ENV` defaults to `development`, which allows local defaults for quick setup.
For production, set:

```bash
APP_ENV=production
DATABASE_URL=postgresql+psycopg://...
AUTH_SECRET_KEY=<long-random-secret>
CORS_ORIGINS=https://your-frontend.example.com
FRONTEND_BASE_URL=https://your-frontend.example.com
EMAIL_FROM=support@your-domain.example
EMAIL_PROVIDER=brevo
BREVO_API_KEY=<brevo-api-key>
PAYMENT_PROVIDER=razorpay
RAZORPAY_KEY_ID=<razorpay-key-id>
RAZORPAY_KEY_SECRET=<razorpay-key-secret>
RAZORPAY_WEBHOOK_SECRET=<razorpay-webhook-secret>
PLATFORM_COMMISSION_RATE=0.10
```

For SMTP instead of Brevo, set:

```bash
EMAIL_PROVIDER=smtp
SMTP_HOST=<smtp-host>
SMTP_PORT=587
SMTP_USERNAME=<smtp-username>
SMTP_PASSWORD=<smtp-password>
SMTP_USE_TLS=1
SMTP_USE_SSL=0
```

When `APP_ENV=production`, the API refuses to start if the auth secret is weak,
the database is not PostgreSQL, CORS contains `*`, or any CORS origin is not
HTTPS. `FRONTEND_BASE_URL` must also use HTTPS because email links are built
from it.

`EMAIL_PROVIDER` can be `log`, `smtp`, or `brevo`. Production rejects `log` unless
`ALLOW_LOG_EMAIL_IN_PRODUCTION=1` is explicitly set for a demo deployment.
Use `brevo` or `smtp` with provider credentials before public launch so email
verification and password reset links reach users. Brevo sends over HTTPS,
which avoids hosted-platform SMTP port restrictions. SMTP providers usually use
port `587` with `SMTP_USE_TLS=1`, or port `465` with `SMTP_USE_SSL=1`.

`PAYMENT_PROVIDER` can be `mock`, `razorpay`, or `stripe`. Production rejects
`mock` unless `ALLOW_MOCK_PAYMENTS_IN_PRODUCTION=1` is explicitly set for a
staging/demo deployment. Razorpay production config requires `RAZORPAY_KEY_ID`,
`RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET`. Stripe production config
requires `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`.

Payment success and failure should be confirmed through the provider webhook endpoint:
`POST /payments/webhooks/{provider}`. The endpoint verifies the provider
signature before marking a payment as succeeded or failed. `payment.succeeded`
confirms its booking; `payment.failed` leaves the booking pending so the worker
can retry checkout. Razorpay checkout uses Orders; send Razorpay webhooks to
`/payments/webhooks/razorpay` and enable `payment.captured` plus
`payment.failed`.
Mock/dev webhooks use `X-Mock-Signature`; Razorpay uses
`X-Razorpay-Signature`; Stripe uses `Stripe-Signature`.

The manual payment-confirm endpoints are available only when
`PAYMENT_PROVIDER=mock`. Razorpay and Stripe deployments must rely on signed
webhooks for payment confirmation.

`PLATFORM_COMMISSION_RATE` controls the commission shown in host revenue and
payout summaries. The default is `0.10`, meaning 10% platform commission and
90% host net earnings after refunds.

`AUTH_RATE_LIMIT_PER_MINUTE` controls the in-memory rate limit for sensitive
auth endpoints such as login, registration, refresh, and password reset. For a
multi-instance production deployment, move this limiter to a shared store such
as Redis.

Email verification and password reset responses include dev tokens only outside
production. In production, tokens are sent through the email service boundary
and are not returned by the API response.

## Docker Compose

From the repository root:

```bash
docker compose up --build
```

The backend will run migrations and start at `http://localhost:8000`.

## Demo Data

After migrations are applied, seed a host, worker, and demo workspaces:

```bash
python scripts/seed_demo.py
```

Demo accounts use `strong-password`:

- `host@example.com`
- `worker@example.com`

## Smoke Test

After the API is running, verify the deployed HTTP flow:

```bash
python scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

The smoke test registers fresh worker, host, and admin accounts, creates and
approves a workspace, searches a Monday/Wednesday/Friday rota, creates a booking
group, creates checkout, and verifies history, revenue, receipt, and audit data.
For non-mock payment providers, it stops after checkout creation because real
payment confirmation must arrive through the provider webhook.

From the `frontend` directory, verify the running frontend shell and API
connectivity:

```bash
pnpm run smoke -- --frontend-url http://127.0.0.1:3000 --api-url http://127.0.0.1:8000
```

## Tests

After installing dependencies, run:

```bash
pytest
```

The first test suite uses SQLite in memory for fast service-level checks. The
production PostgreSQL exclusion constraint remains the final double-booking
guard under concurrent requests.
