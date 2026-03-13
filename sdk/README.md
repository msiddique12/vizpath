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
- `VIZPATH_CIRCUIT_BREAKER_ENABLED` - Pause retries briefly after repeated transport failures (default: `true`)
- `VIZPATH_CIRCUIT_BREAKER_FAILURES` - Consecutive transport failures before cooldown (default: `5`)
- `VIZPATH_CIRCUIT_BREAKER_WINDOW_SECONDS` - Cooldown duration in seconds (default: `60`)
- `VIZPATH_MAX_BUFFER_ITEMS` - Maximum spans retained in memory before dropping (default: `10000`)
- `VIZPATH_DROP_OLDEST_WHEN_BUFFER_FULL` - When full, drop oldest spans to keep newest (default: `false`)
- `VIZPATH_REDACTION_ENABLED` - Redact sensitive values in span payloads before sending (default: `true`)
- `VIZPATH_REDACTION_FIELDS` - Comma-separated keys to redact (default: `authorization,api_key,apikey,password,access_token,refresh_token,secret,private_key`)
- `VIZPATH_REDACTION_REPLACEMENT` - Replacement text for redacted fields (default: `[REDACTED]`)
- `VIZPATH_MAX_PAYLOAD_BYTES` - Maximum JSON payload size per batch request (default: `1048576`)

### Programmatic Configuration

```python
from vizpath import Tracer, Config

config = Config(
    api_key="your-key",
    base_url="https://your-server.com/api/v1",
    buffer_size=100,      # Spans to buffer before flush
    flush_interval=10.0,  # Seconds between flushes
    circuit_breaker_enabled=True,  # Enable cooldown protection on transport failures
    circuit_breaker_failures=7,    # Open circuit after 7 consecutive transport errors
    circuit_breaker_window_seconds=30.0, # Cooldown window in seconds
    max_buffer_items=5000,  # Max spans buffered in memory
    drop_oldest_when_full=True,  # Keep newest spans when buffer is full
    redaction_enabled=True,       # Redact sensitive values before upload
    redaction_fields=["authorization", "api_key", "password"],  # Additional keys to scrub
    redaction_replacement="[REDACTED]",  # Safe placeholder value
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
