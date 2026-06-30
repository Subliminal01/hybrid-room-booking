# Hybrid Room Booking Platform

Marketplace foundation for short-term hybrid work stays. Workers can search for
available rooms by rota schedule, book daily slots, and manage booking history.
Hosts can create workspaces, manage availability, and view bookings. Admins can
review listings and inspect audit events.

## Project Layout

- `backend/`: FastAPI, SQLModel, Alembic, PostgreSQL-targeted API
- `frontend/`: Next.js dashboard application
- `docker-compose.yml`: local PostgreSQL + backend + frontend stack
- `.github/workflows/ci.yml`: backend and frontend quality gate

## Local Checks

Backend:

```bash
cd backend
python scripts/release_check.py
python -m pytest
```

After starting the API, run the HTTP smoke test:

```bash
python scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

Frontend:

```bash
cd frontend
pnpm install
pnpm run typecheck
pnpm run build
```

After starting both the frontend and API, run the frontend smoke test:

```bash
pnpm run smoke -- --frontend-url http://127.0.0.1:3000 --api-url http://127.0.0.1:8000
```

## CI

GitHub Actions runs:

- backend tests on Python 3.12
- backend release check
- Alembic migrations against PostgreSQL 16
- frontend TypeScript checks and production build on Node 24 with pnpm
- backend and frontend Docker image builds

The test suite is intentionally dependency-light and does not require external
payment or email services. The migration job uses a disposable PostgreSQL
service so schema drift is caught before deployment.

## Local Full-Stack Run

```bash
docker compose up --build
```

The frontend runs at `http://localhost:3000` and the API runs at
`http://localhost:8000`.

## Environment Templates

- Backend: copy `backend/.env.example` and set `DATABASE_URL`, `AUTH_SECRET_KEY`,
  `CORS_ORIGINS`, `FRONTEND_BASE_URL`, and payment-provider credentials for the
  target environment.
- Frontend: copy `frontend/.env.example` and set `NEXT_PUBLIC_API_BASE_URL`.

For production, `APP_ENV=production` enables stricter safety checks for HTTPS
origins, PostgreSQL, strong auth secrets, and non-mock payment providers.

See `DEPLOYMENT.md` for the production release checklist, webhook setup, smoke
test, and rollback notes.
