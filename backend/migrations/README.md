# Database Migrations

Alembic migrations live here.

Set `DATABASE_URL` before running migration commands:

```bash
set DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/room_booking
alembic upgrade head
```

Use PowerShell syntax when appropriate:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/room_booking"
alembic upgrade head
```
