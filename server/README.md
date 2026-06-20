# vizpath-server

FastAPI server for vizpath agent observability platform.

## Setup

```bash
pip install -e ".[dev]"
```

## Run

```bash
uvicorn app.main:app --reload
```

## Database Migrations

```bash
# Apply latest schema migrations
alembic upgrade head

# Create a new migration from model changes
alembic revision --autogenerate -m "describe change"
```

For existing local databases created before Alembic was added, stamp the current schema once:

```bash
alembic stamp head
```

## Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `NVIDIA_API_KEY`: Optional, enables NIM-backed intelligence features
- `NVIDIA_BASE_URL`: Optional, NVIDIA NIM-compatible API base URL
- `NVIDIA_LLM_MODEL`: Optional, model used by intelligence features
- `ENFORCE_MIGRATION_HEAD`: `true` to fail startup when DB revision is not at Alembic head

## API Docs

Visit `/docs` for interactive API documentation.
