# API Reference (Developer)

This document is a quick guide to the `vizpath` server API for local development and integrations.

## Base URL

By default, the server runs at:

- `http://localhost:8000`
- API base: `/api/v1`
- Docs: `/docs`

When deployed, replace host/port accordingly.

---

## Authentication

Most protected endpoints use the `X-API-Key` header.

```http
X-API-Key: vp_xxxxxxxxxxxxxxxxxx
```

Project and key lifecycle endpoints:

- `POST /api/v1/projects/` — create a project and receive an API key
- `GET /api/v1/projects/me` — get current project metadata
- `GET /api/v1/projects/me/budget` — get monthly budget configuration
- `PUT /api/v1/projects/me/budget` — update monthly budget configuration
- `GET /api/v1/projects/me/budget/status` — get current month usage + alert status
- `POST /api/v1/projects/me/api-key/rotate` — rotate key (grace period support included)
- `POST /api/v1/projects/me/api-key/revoke` — revoke current key

Unauthenticated fallback is disabled by default. For local-only demo workflows,
set `ALLOW_UNAUTHENTICATED_DEV_FALLBACK=true` explicitly.

---

## Health

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/` | service info |
| `GET` | `/health` | basic health check |
| `GET` | `/health/detailed` | DB + Redis + intelligence status |

Example:

```bash
curl http://localhost:8000/health/detailed
```

---

## Traces

- `POST /api/v1/traces/spans/batch`
  - Batch ingest spans (current SDK/default endpoint)
- `GET /api/v1/traces/`
  - List traces with pagination + filtering
- `GET /api/v1/traces/{trace_id}`
  - Fetch trace detail
- `GET /api/v1/traces/{trace_id}/spans`
  - Fetch trace spans

Query and body parameters are documented in generated OpenAPI (`/docs`).

---

## Curation

- `POST /api/v1/curation/labels`
  - Create/update label
- `DELETE /api/v1/curation/labels/{trace_id}`
  - Delete label and all labels for trace
- `GET /api/v1/curation/traces`
- `GET /api/v1/curation/traces/export`

---

## Intelligence

- `POST /api/v1/intelligence/analyze`
  - Analyze a trace into a quality score and suggestions
- `POST /api/v1/intelligence/self-analyze`
  - Self-evaluation for an entire trace
- `GET /api/v1/intelligence/clusters`
  - List trace clusters (embeddings + K-means)
- `POST /api/v1/intelligence/generate-synthetic`
  - Generate synthetic/variation traces

Set `NVIDIA_API_KEY` on server side to enable these endpoints.

---

## WebSocket

- `ws://localhost:8000/ws/traces?api_key=<project_api_key>`
  - Subscribe to real-time trace ingest events.

Event payload:

```json
{
  "type": "span_ingested",
  "trace_id": "...",
  "span_count": 5
}
```

---

## Common Exit States

- `401` unauthorized: missing/invalid API key for protected endpoint
- `422` validation: request body/path/query invalid
- `429` rate limited (when enabled)
- `429` budget hard-stop exceeded (`detail.code = budget_exceeded`)
- `503` intelligence backend unavailable

---

## Practical First Calls

### Create project and capture key

```bash
curl -X POST http://localhost:8000/api/v1/projects/ \
  -H "Content-Type: application/json" \
  -d '{"name":"my-project"}'
```

### List traces

```bash
curl -H "X-API-Key: $VIZPATH_API_KEY" \
  http://localhost:8000/api/v1/traces/?limit=20
```

### Export curated traces

```bash
curl -H "X-API-Key: $VIZPATH_API_KEY" \
  "http://localhost:8000/api/v1/curation/traces/export?format=jsonl"
```
