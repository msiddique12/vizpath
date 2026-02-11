# vizpath

Observe, debug, and curate your AI agents. From traces to training data.

Powered by **NVIDIA Nemotron** for intelligent trace analysis, auto-labeling, and synthetic data generation.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)

## Overview

vizpath is an open-source observability and intelligence platform for AI agents. It provides real-time execution tracing, visual debugging, Nemotron-powered trace analysis, and intelligent curation for building training datasets.

### Key Features

- **Lightweight SDK**: Minimal overhead tracing with async batching
- **Real-time Visualization**: Watch agent execution as it happens via WebSocket
- **Interactive DAG**: Explore execution graphs with D3.js zoom, pan, and drag
- **Cost Attribution**: Track token usage and costs per operation
- **Framework Support**: Native adapters for LangGraph, LangChain, AutoGen
- **Nemotron Intelligence**: Auto-analyze traces, detect issues, suggest improvements
- **Self-Analysis**: Deep agent evaluation for effectiveness, reasoning quality, and tool usage
- **Synthetic Data**: Generate training data variations and corrections from real traces
- **Trace Clustering**: K-means clustering with NIM embeddings for pattern discovery
- **Training Data Curation**: Label, score, and export curated traces for fine-tuning

## Quick Start

### Installation

```bash
# SDK
pip install -e ./sdk

# Server
pip install -e "./server[dev]"

# Dashboard
cd dashboard && npm install
```

### Basic Usage

```python
from vizpath import tracer

@tracer.trace(name="research-task")
def research(topic):
    result = call_llm(topic)
    return result

# Traces are automatically sent to the vizpath server
research("quantum computing advances")
```

### Decorator-based Tracing

```python
from vizpath import tracer

@tracer.span(name="llm_call", span_type="llm")
def call_llm(prompt):
    response = client.chat.completions.create(
        model="nvidia/llama-3.1-nemotron-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
    )
    tracer.set_span_tokens(
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )
    return response.choices[0].message.content
```

### LangGraph Integration

```python
from vizpath.adapters import LangGraphAdapter

adapter = LangGraphAdapter()
app = adapter.wrap(your_langgraph_app)

result = app.invoke({"input": "research quantum computing"})
```

## Architecture

```
┌─────────────┐     ┌─────────────────────────────┐     ┌─────────────┐
│   SDK       │────▶│   Server (FastAPI)           │────▶│  Dashboard  │
│  (Python)   │     │  ├── Traces API              │     │  (React)    │
└─────────────┘     │  ├── Curation API            │     │  Dark Theme │
                    │  ├── Intelligence API         │     │  D3.js DAG  │
                    │  │   ├── Nemotron Analysis    │     └─────────────┘
                    │  │   ├── Self-Analysis        │
                    │  │   ├── Clustering           │
                    │  │   └── Synthetic Data       │
                    │  └── WebSocket (live traces)  │
                    └─────────────────────────────┘
                               │
                        ┌──────┴──────┐
                        │ PostgreSQL  │
                        │   + Redis   │
                        └─────────────┘
```

## Intelligence (Nemotron via NIM)

vizpath includes a built-in intelligence layer powered by NVIDIA NIM:

```bash
export NVIDIA_API_KEY="nvapi-..."
```

**Trace Analysis** — Quality scoring, auto-labeling, and improvement suggestions:
```bash
curl -X POST http://localhost:8000/api/v1/intelligence/analyze \
  -H "Content-Type: application/json" \
  -d '{"trace_id": "your-trace-id"}'
```

**Self-Analysis** — Deep evaluation of agent effectiveness:
```bash
python examples/self_analyze.py --trace-id <uuid>
```

**Synthetic Data** — Generate training data from real traces:
```bash
curl -X POST http://localhost:8000/api/v1/intelligence/generate-synthetic \
  -H "Content-Type: application/json" \
  -d '{"trace_id": "your-trace-id", "type": "variations", "count": 5}'
```

## Project Structure

```
vizpath/
├── sdk/                    # Python tracing SDK
├── server/                 # FastAPI backend
│   ├── app/
│   │   ├── intelligence/   # Nemotron-powered analysis
│   │   │   ├── llm.py      # LLM labeler (analyze, self-analyze)
│   │   │   ├── embeddings.py # NIM embedding API
│   │   │   ├── clustering.py # K-means trace clustering
│   │   │   └── synthetic.py  # Training data generation
│   │   ├── routes/         # API endpoints
│   │   └── models.py       # SQLAlchemy ORM
│   └── tests/              # pytest test suite
├── dashboard/              # React + Tailwind dark theme UI
├── examples/               # Example agents and demos
│   ├── research_agent/     # Full research agent with tracing
│   └── self_analyze.py     # Trace self-analysis CLI demo
└── docs/                   # Documentation
```

## Development

### Prerequisites

- Python 3.10+
- Node.js 20+
- NVIDIA API key (for intelligence features)

### Setup

```bash
# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate

# Install SDK
pip install -e ./sdk

# Install server with dev dependencies
pip install -e "./server[dev]"

# Install dashboard
cd dashboard && npm install

# Set environment variables
export NVIDIA_API_KEY="nvapi-..."
export DATABASE_URL="sqlite:///vizpath.db"
```

### Run

```bash
# Start the API server
cd server && uvicorn app.main:app --reload

# Start the dashboard (separate terminal)
cd dashboard && npm run dev
```

The API is at http://localhost:8000, the dashboard at http://localhost:5173.

### Test

```bash
cd server && DATABASE_URL=sqlite:///test.db pytest tests/ -v
```

## Contributing

Contributions are welcome. Please read our [Contributing Guide](CONTRIBUTING.md) before submitting a PR.

## License

Apache 2.0 - See [LICENSE](LICENSE) for details
