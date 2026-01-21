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

## Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `OPENAI_API_KEY`: Optional, for AI features

## API Docs

Visit `/docs` for interactive API documentation.
