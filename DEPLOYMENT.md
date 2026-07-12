# Deployment Runbook

This runbook covers the production checklist for the hybrid room booking MVP.

## 1. Pre-Release Checks

Run these from a clean checkout:

```bash
cd backend
python scripts/release_check.py
python -m pytest

cd ../frontend
pnpm install
pnpm run typecheck
pnpm run build
```

CI should also pass the backend tests, backend release check, PostgreSQL
migrations, frontend typecheck, and frontend production build.

## 2. Backend Environment

Start from `backend/.env.example` and set production values:

```bash
APP_ENV=production
DATABASE_URL=postgresql+psycopg://...
AUTH_SECRET_KEY=<long-random-secret>
# Optional; set only while creating the first admin without shell access.
ADMIN_BOOTSTRAP_SECRET=<temporary-long-random-secret>
CORS_ORIGINS=https://your-frontend.example.com
FRONTEND_BASE_URL=https://your-frontend.example.com
PUBLIC_API_BASE_URL=https://your-api.example.com
AUTH_RATE_LIMIT_PER_MINUTE=120
TRUST_PROXY_HEADERS=1
UPLOAD_DIR=uploads
MAX_UPLOAD_BYTES=5242880
SENTRY_DSN=<sentry-backend-dsn>
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=<git-sha-or-release-name>
SENTRY_TRACES_SAMPLE_RATE=0.05
EMAIL_FROM=noreply@your-domain.example
EMAIL_PROVIDER=brevo
BREVO_API_KEY=<brevo-api-key>
PAYMENT_PROVIDER=razorpay
```

For SMTP instead of Brevo:

```bash
EMAIL_PROVIDER=smtp
SMTP_HOST=<smtp-host>
SMTP_PORT=587
SMTP_USERNAME=<smtp-username>
SMTP_PASSWORD=<smtp-password>
SMTP_USE_TLS=1
SMTP_USE_SSL=0
```

For Razorpay:

```bash
RAZORPAY_KEY_ID=<key-id>
RAZORPAY_KEY_SECRET=<key-secret>
RAZORPAY_WEBHOOK_SECRET=<webhook-secret>
```

For Stripe:

```bash
PAYMENT_PROVIDER=stripe
STRIPE_SECRET_KEY=<secret-key>
STRIPE_WEBHOOK_SECRET=<webhook-secret>
```

Production rejects weak auth secrets, non-PostgreSQL databases, insecure CORS
origins, non-HTTPS frontend URLs, log-only emails, and mock payments unless
explicitly allowed for a staging/demo environment.

`ADMIN_BOOTSTRAP_SECRET` enables `POST /admin/bootstrap` for creating or
promoting an admin user when the hosting provider does not provide free shell
access. Remove this environment variable and redeploy immediately after the
first admin account is created.

For a free demo deployment, use a free external PostgreSQL provider such as Neon
or Supabase and set `DATABASE_URL` manually in the backend host. Keep
`PAYMENT_PROVIDER=mock` with `ALLOW_MOCK_PAYMENTS_IN_PRODUCTION=1` only for demo
validation, then switch to Razorpay or Stripe before accepting real payments.
Similarly, `EMAIL_PROVIDER=log` with `ALLOW_LOG_EMAIL_IN_PRODUCTION=1` is only
for demo validation. Switch to Brevo or SMTP before relying on verification or
password reset emails.

After Brevo or SMTP credentials are configured, sign in as an admin and use
**Send email test** in Admin Operations. A successful response means the API
could connect to the email provider and send to the admin account email.
The email provider status block in Admin Operations shows whether the provider
is configured and which safe, non-secret settings are still missing.

Workspace photo uploads are stored under `UPLOAD_DIR` and served from
`/uploads`. This is acceptable for demos, but local instance storage is not
durable on many free hosts. Before public launch, move uploads to object storage
such as S3, Cloudflare R2, or another managed media store.

To enable durable S3-compatible storage, set:

```env
STORAGE_PROVIDER=s3
S3_BUCKET=your-bucket
S3_REGION=auto
S3_ENDPOINT_URL=https://your-account.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_PUBLIC_BASE_URL=https://your-public-bucket-domain
```

`S3_PUBLIC_BASE_URL` must be an HTTPS URL that serves public workspace photos.
Admins can verify the active storage mode from Admin Operations. The upload
storage status block shows whether uploads are using local disk or durable
S3-compatible object storage, plus any missing S3 settings.

`AUTH_RATE_LIMIT_PER_MINUTE` applies to sensitive auth routes by both source IP
and normalized account email where available. Set `TRUST_PROXY_HEADERS=1` only
when the app is behind a trusted platform proxy such as Render; otherwise leave
it off so clients cannot spoof `X-Forwarded-For`.

## 3. Frontend Environment

Set the public API URL at build time:

```bash
NEXT_PUBLIC_API_BASE_URL=https://your-api.example.com
```

The frontend Dockerfile uses Next.js standalone output.

## 4. Database

Create the PostgreSQL database and enable the required extension:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

Apply migrations before serving traffic:

```bash
cd backend
alembic upgrade head
```

## 5. Payment Webhooks

Configure the payment provider to call:

```text
POST https://your-api.example.com/payments/webhooks/{provider}
```

Providers:

- `razorpay` uses `X-Razorpay-Signature`
- `stripe` uses `Stripe-Signature`
- `mock` uses `X-Mock-Signature` for local/dev testing

Real providers must confirm payments through signed webhooks. Manual payment
confirmation endpoints are mock-only.

Admins can verify the active payment configuration from the dashboard under
Admin Operations. The payment provider status block shows the active provider,
whether required secrets are present, and the exact webhook URL to paste into
the provider dashboard. For the Render deployment, the Razorpay webhook URL is:

```text
https://hybrid-room-booking-api.onrender.com/payments/webhooks/razorpay
```

## 6. Health Checks

Use:

```text
GET /health/live
GET /health/ready
```

`/health/ready` checks database connectivity and should be used by load
balancers or orchestrators.

## 7. Container Security Baseline

- Backend and frontend containers run as non-root users.
- Do not bake `.env` files or provider credentials into images.
- Keep payment provider secrets in the runtime secret manager for your platform.
- Expose only the public frontend and API ports required by your ingress layer.

## 8. Post-Deploy Smoke Test

Run the API smoke test against the deployed backend:

```bash
cd backend
python scripts/smoke_test.py --base-url https://your-api.example.com
```

The script registers fresh worker, host, and admin accounts, creates and
approves a workspace, searches a Monday/Wednesday/Friday rota, creates a booking
group, and creates checkout. When `PAYMENT_PROVIDER=mock`, it also confirms
payment and verifies booking history, receipt, host revenue, and admin audit
events.

For Razorpay or Stripe production deployments, complete one provider sandbox
payment and verify the signed webhook marks the booking group as paid.

Run the frontend smoke test against the deployed frontend and API:

```bash
cd frontend
pnpm run smoke -- --frontend-url https://your-frontend.example.com --api-url https://your-api.example.com
```

This verifies the frontend shell, baseline security headers, static assets, and
backend readiness from the public deployment URLs.

## 9. Uptime Monitoring

The repository includes `.github/workflows/uptime.yml`, a free scheduled monitor
that checks:

- `https://hybrid-room-booking.vercel.app`
- `https://hybrid-room-booking-api.onrender.com/health/ready`

It runs every 15 minutes and can be triggered manually from GitHub Actions using
the `Uptime Monitor` workflow. GitHub will mark the workflow failed if the
frontend shell is unavailable, the backend readiness endpoint fails, or database
readiness is not `ok`. Backend readiness checks retry with a longer timeout so
Render free-tier cold starts do not create avoidable false alarms.

You can run the same check locally:

```bash
python scripts/uptime_check.py
```

This is a useful free baseline. Before a serious public launch, add a dedicated
monitoring provider such as Better Stack, Sentry, Axiom, Grafana Cloud, or
UptimeRobot for alert routing, incident history, and error traces.

Backend error tracing is Sentry-ready. Create a Sentry Python/FastAPI project,
then set `SENTRY_DSN` in Render. Keep `SENTRY_TRACES_SAMPLE_RATE` low in
production, for example `0.05`, to sample performance traces without creating
too much noise. Unhandled backend exceptions include the app request ID,
HTTP method, and path in Sentry context.

## 10. Rollback Notes

- Roll back application containers first.
- Avoid rolling back database migrations unless a migration is known to be
  reversible and no new production data depends on it.
- If payment webhooks are failing, pause provider webhook retries only after
  capturing request IDs and provider event IDs for investigation.
