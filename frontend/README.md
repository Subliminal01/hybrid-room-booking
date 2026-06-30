# Hybrid Room Booking Frontend

Next.js frontend for the hybrid workday room booking platform.

## Local Setup

```bash
pnpm install
pnpm run dev
```

Set the API URL if the backend is not running on `http://localhost:8000`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Run type checks before pushing:

```bash
pnpm run typecheck
```

## Container Build

The frontend has a production Dockerfile using Next.js standalone output. From
the repository root, the full stack can run with:

```bash
docker compose up --build
```

## Current Screens

- Register/login
- Rota-based workspace search
- Available workspace results with estimated rota total
- Authenticated booking creation
- Booking history and cancellation
- Grouped rota booking history
- Mock checkout flow with provider-ready checkout-session support
- Receipt view after payment
- Host workspace management, availability, blackout dates, revenue summary
- Admin workspace review and audit trail
