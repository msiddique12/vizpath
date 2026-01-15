# vizpath

Observe, debug, and curate your AI agents. From traces to training data.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)

## Overview

vizpath is an open-source observability platform for AI agents. It provides real-time execution tracing, visual debugging through interactive DAG visualization, and intelligent trace curation for building training datasets.

### Key Features

- **Lightweight SDK**: Minimal overhead tracing with async batching
- **Real-time Visualization**: Watch agent execution as it happens
- **Interactive DAG**: Explore execution graphs with zoom, pan, and drill-down
- **Cost Attribution**: Track token usage and costs per operation
- **Framework Support**: Native adapters for LangGraph, LangChain, AutoGen
- **Training Data Curation**: Export curated traces for fine-tuning

## Quick Start

### Installation

```bash
pip install vizpath
```

### Basic Usage

```python
from vizpath import Tracer

tracer = Tracer(api_key="your-api-key")

with tracer.trace("research-task") as trace:
    with trace.span("llm-call", span_type="llm") as span:
        response = llm.invoke(prompt)
        span.set_attributes(tokens=response.usage.total_tokens)

    with trace.span("tool-call", span_type="tool") as span:
        result = search_tool.run(query)
        span.set_output(result)
```

### LangGraph Integration

```python
from vizpath.adapters import LangGraphAdapter

adapter = LangGraphAdapter(api_key="your-api-key")
app = adapter.wrap(your_langgraph_app)

result = app.invoke({"input": "research quantum computing"})
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   SDK       │────▶│   Server    │────▶│  Dashboard  │
│  (Python)   │     │  (FastAPI)  │     │   (React)   │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │ PostgreSQL  │
                    │   + Redis   │
                    └─────────────┘
```

## Project Structure

```
vizpath/
├── sdk/          # Python SDK
├── server/       # FastAPI backend
├── dashboard/    # React frontend
├── examples/     # Example agents
└── docs/         # Documentation
```

## Development

### Prerequisites

- Python 3.10+
- Node.js 20+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker (for local services)

### Quick Setup

```bash
# Clone repository
git clone https://github.com/yourusername/vizpath.git
cd vizpath

# Install all dependencies
make install-dev

# Start services
docker-compose up -d

# Run development servers
make dev-server    # API at http://localhost:8000
make dev-dashboard # UI at http://localhost:5173
```

### Available Commands

```bash
make help          # Show all commands
make lint          # Run linters
make typecheck     # Run type checkers
make test          # Run all tests
make format        # Format code
make build         # Build packages
```

### Manual Setup (without Make)

```bash
# SDK
cd sdk && uv sync --all-extras

# Server
cd server && uv sync --all-extras

# Dashboard
cd dashboard && npm install
```

## Contributing

Contributions are welcome. Please read our [Contributing Guide](CONTRIBUTING.md) before submitting a PR.

## License

Apache 2.0 - See [LICENSE](LICENSE) for details