# vizpath SDK

Lightweight tracing SDK for AI agent observability.

## Installation

```bash
pip install vizpath
```

For LangGraph integration:
```bash
pip install vizpath[langgraph]
```

## Quick Start

### Basic Usage

```python
from vizpath import Tracer, SpanType

tracer = Tracer(api_key="your-api-key")

with tracer.trace("my-agent-task") as trace:
    # Create a span for an LLM call
    with trace.span("generate-response", span_type=SpanType.LLM) as span:
        span.set_input({"prompt": "Hello, world!"})
        response = your_llm.generate("Hello, world!")
        span.set_output(response)
        span.set_tokens(150, cost=0.002)

    # Create a span for a tool call
    with trace.span("search", span_type=SpanType.TOOL) as span:
        span.set_input({"query": "python docs"})
        results = search_tool.run("python docs")
        span.set_output(results)
```

### LangGraph Integration

```python
from vizpath.adapters import LangGraphAdapter
from langgraph.graph import StateGraph

# Build your graph
graph = StateGraph(...)
compiled = graph.compile()

# Wrap with vizpath
adapter = LangGraphAdapter(api_key="your-api-key")
traced_graph = adapter.wrap(compiled)

# Use as normal - traces are captured automatically
result = traced_graph.invoke({"input": "research quantum computing"})
```

## Configuration

### Environment Variables

- `VIZPATH_API_KEY` - Your API key
- `VIZPATH_API_URL` - Server URL (default: `http://localhost:8000/api/v1`)
- `VIZPATH_ENABLED` - Enable/disable tracing (default: `true`)

### Programmatic Configuration

```python
from vizpath import Tracer, Config

config = Config(
    api_key="your-key",
    base_url="https://your-server.com/api/v1",
    buffer_size=100,      # Spans to buffer before flush
    flush_interval=10.0,  # Seconds between flushes
)

tracer = Tracer(config=config)
```

## API Reference

### Tracer

The main entry point for creating traces.

```python
tracer = Tracer(api_key="...", base_url="...")

# Create a trace
with tracer.trace("task-name") as trace:
    ...

# Manual flush
tracer.flush()

# Cleanup
tracer.close()
```

### Trace

Represents a complete execution unit.

```python
with tracer.trace("my-task") as trace:
    trace.set_metadata(user_id="123", version="1.0")

    # Create spans
    span = trace.span("operation", span_type=SpanType.LLM)
```

### Span

Represents a single operation within a trace.

```python
with trace.span("llm-call", span_type=SpanType.LLM) as span:
    span.set_input(prompt)
    span.set_output(response)
    span.set_tokens(token_count, cost=estimated_cost)
    span.set_attributes(model="gpt-4", temperature=0.7)
    span.add_event("retry", attempt=2)

    # Nested spans
    with span.span("parse-output") as child:
        ...
```

### Span Types

- `SpanType.LLM` - Language model calls
- `SpanType.TOOL` - Tool/function executions
- `SpanType.AGENT` - Agent decision steps
- `SpanType.RETRIEVAL` - Vector search/retrieval
- `SpanType.CHAIN` - Chain orchestration
- `SpanType.CUSTOM` - Custom operations

## License

Apache 2.0
