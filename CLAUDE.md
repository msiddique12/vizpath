# Vizpath: Agent Observability & Intelligence Platform

## Architecture

Vizpath comprises three systems:

**System 1: SDK (Python Package)**
- Lightweight tracing instrumentation (`vizpath/sdk/`)
- Framework adapters (LangGraph, LangChain, AutoGen)
- Installed via `pip install -e ./vizpath/sdk`

**System 2: Server (FastAPI + PostgreSQL + Redis)**
- Trace ingestion and query API (`vizpath/server/`)
- Real-time WebSocket streaming
- Curation endpoints for manual labeling
- Intelligence module (`vizpath/server/app/intelligence/`):
  - `llm.py` — Nemotron LLM labeler (analyze, self-analyze, label)
  - `embeddings.py` — NIM embedding API (trace-to-text, embed, cache)
  - `clustering.py` — K-means trace clustering with silhouette optimization
  - `synthetic.py` — Training data generation (variations, corrections, JSONL export)
- Intelligence API routes (`vizpath/server/app/routes/intelligence.py`)
- Run: `cd vizpath/server && DATABASE_URL=sqlite:///vizpath.db uvicorn app.main:app --reload`

**System 3: Dashboard (React + D3.js + Tailwind)**
- Dark theme UI with NVIDIA green (#76B900) accent
- Execution timeline, DAG, heatmap, cost attribution
- Intelligence panel (Nemotron analysis results)
- Synthetic data generation interface
- Run: `cd vizpath/dashboard && npm run dev`

## Data Model

**Trace** -> top-level execution unit (id, name, status, timing, tokens, cost)
**Span** -> individual operation within a trace (parent-child hierarchy, type: llm/tool/agent/retrieval/chain/custom)
**CuratedLabel** -> user-applied labels, quality scores, notes on traces

## Intelligence Layer (Nemotron via NIM)

All LLM and embedding calls go through NVIDIA NIM API (OpenAI-compatible):
- **LLM**: `nvidia/llama-3.1-nemotron-70b-instruct` for trace analysis, self-analysis, labeling
- **Embeddings**: `nvidia/nv-embedqa-e5-v5` (1024-dim) for trace embedding and clustering
- **Synthetic Data**: Nemotron generates training data variations and corrections from real traces
- **Config**: `NVIDIA_API_KEY` env var, base URL `https://integrate.api.nvidia.com/v1`
- **Caching**: Redis-backed caching for labels, embeddings, and cluster results

## Tech Stack

- **Backend**: Python 3.10+, FastAPI, SQLAlchemy, PostgreSQL/SQLite, Redis
- **Frontend**: TypeScript, React 18, Vite, D3.js, Tailwind CSS
- **Intelligence**: NVIDIA NIM (Nemotron), scikit-learn, numpy, openai SDK
- **Testing**: pytest (Python), mocked NIM calls for zero-cost unit tests

## Code Quality Standards

- **Commits**: Conventional commits (`feat`, `fix`, `refactor`, `test`, `chore`, `docs`)
- **Linting**: `ruff check` for Python, ESLint for TypeScript
- **Testing**: Unit tests mock all NIM calls. Integration tests use NIM free tier.
- **Types**: Python type hints, strict TypeScript config

## Development Practices

- Atomic commits - one logical change per commit
- Tests accompany every new feature/module
- Zero external cost for unit tests (all NIM calls mocked)
- Integration tests use NIM free tier (`NVIDIA_API_KEY` required)
- Dashboard changes: visual QA after each change

## Local Dev Setup

```bash
pip install -e ./vizpath/sdk
pip install -e "./vizpath/server[dev]"
cd vizpath/server && DATABASE_URL=sqlite:///vizpath.db uvicorn app.main:app --reload
cd vizpath/dashboard && npm run dev
export NVIDIA_API_KEY="nvapi-..."
```

## Verification

```bash
cd vizpath/server && DATABASE_URL=sqlite:///test.db pytest tests/ -v
cd vizpath/sdk && pytest tests/ -v
cd vizpath/dashboard && npm run dev
```
