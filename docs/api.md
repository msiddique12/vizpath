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
- `GET /api/v1/projects/me/keys` — list additional scoped API keys
- `POST /api/v1/projects/me/keys` — create additional scoped API keys
- `POST /api/v1/projects/me/keys/{key_id}/revoke` — revoke a scoped API key
- `GET /api/v1/projects/me/alerts` — list SLO/alert rules
- `POST /api/v1/projects/me/alerts` — create SLO/alert rule
- `PUT /api/v1/projects/me/alerts/{rule_id}` — update SLO/alert rule
- `DELETE /api/v1/projects/me/alerts/{rule_id}` — delete SLO/alert rule
- `GET /api/v1/projects/me/alerts/evaluate` — evaluate alert rules against rolling trace metrics
- `GET /api/v1/projects/me/budget` — get monthly budget configuration
- `PUT /api/v1/projects/me/budget` — update monthly budget configuration
- `GET /api/v1/projects/me/budget/status` — get current month usage + alert status
- `POST /api/v1/projects/me/api-key/rotate` — rotate key (grace period support included)
- `POST /api/v1/projects/me/api-key/revoke` — revoke current key

Scoped key permissions:

- `read` — trace, intelligence, search, redaction finding, and regression read access
- `ingest` — span ingestion
- `curate` — curation labels/exports and persistent triage/eval/dataset workflow writes
- `admin` — key/budget management and destructive operations (implies all scopes)

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

## Persistent Product Workflows

These endpoints are project-scoped. Reads/downloads require `read`; creates and updates require `curate`.
Legacy project keys keep full access. Existing stateless preview endpoints remain compatible.

### Triage

- `GET /api/v1/triage/items`
  - List durable failure inbox items for the current project.
- `POST /api/v1/triage/items`
  - Create a triage item from a trace. Fields include `trace_id`, `status`, `priority`, `owner`,
    `failure_mode`, `title`, `notes`, and `linked_trace_ids`.
- `PATCH /api/v1/triage/items/{id}`
  - Update status, priority, ownership, notes, or resolver fields.
- `POST /api/v1/triage/items/{id}/links`
  - Add linked traces. Linked traces must belong to the same project.

Triage is separate from curation labels. A failure inbox action can update triage without creating a label.

### Eval Suites

- `POST /api/v1/evals/suites`
  - Persist an eval suite generated from current project traces.
- `GET /api/v1/evals/suites`
  - List saved suites.
- `GET /api/v1/evals/suites/{id}`
  - Fetch suite cases and recent runs.
- `POST /api/v1/evals/suites/{id}/runs`
  - Record a deterministic run against candidate trace IDs. V1 records assertions and results; it does not execute external agents.
- `GET /api/v1/evals/runs/{id}`
  - Fetch run summary and case results.

Compatibility: `POST /api/v1/evals/suite` remains the stateless preview generator.

### Dataset Builds

- `POST /api/v1/datasets/builds`
  - Persist a redacted dataset artifact from selected traces.
- `GET /api/v1/datasets/builds`
  - List saved builds.
- `GET /api/v1/datasets/builds/{id}`
  - Fetch build metadata and artifact summary.
- `GET /api/v1/datasets/builds/{id}/download?format=json|jsonl`
  - Download the saved artifact.

Dataset builds are redacted by default. Raw span input/output is only included when `include_raw=true`
is explicitly sent, and that choice is recorded in build options/audit metadata.

Compatibility: `POST /api/v1/datasets/build` remains the stateless preview builder.

### Sensitive Data Controls

- `GET /api/v1/projects/me/redaction-policy`
  - Fetch the centralized project redaction policy.
- `PUT /api/v1/projects/me/redaction-policy`
  - Update policy `enabled`, `mode`, or `rules`. Requires `admin`.
- `POST /api/v1/redaction/preview`
  - Preview redaction for a stored trace/span or explicit JSON payload.
- `GET /api/v1/redaction/findings`
  - List sensitive-data findings recorded during ingest.

Policy modes:

- `audit_only` records findings but preserves stored span payloads.
- `redact_on_write` stores redacted span fields.
- `block` rejects batches containing high/critical sensitive findings.

Findings include rule IDs, severities, field paths, and non-reversible fingerprints only. Raw matched values are not returned or logged.

### Trace Search v2

- `POST /api/v1/search/traces/v2`
  - Search redacted trace documents across trace name, metadata, span inputs/outputs/errors, and span attributes.

Supported filters include `model`, `tool`, `run_id`, `prompt_version`, `status`, `owner`,
`min_cost`, `max_cost`, `min_latency_ms`, `max_latency_ms`, `has_errors`, and time bounds.

Compatibility: `POST /api/v1/search/traces` remains available with its original response shape.

### Regression Watch

- `GET /api/v1/regressions/watch`
  - List durable automatic regression comparisons.
- `GET /api/v1/regressions/watch/{trace_id}`
  - Fetch the watch result for one trace.
- `POST /api/v1/regressions/watch/{trace_id}/rerun`
  - Recompute the comparison for one trace. Requires `curate`.

Baseline selection prefers recent traces with the same `route`, `task`, `prompt_version`, or `run_id`,
then falls back to the latest comparable project trace for compatibility.

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
