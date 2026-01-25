# Research Agent Example

A multi-tool research agent that demonstrates vizpath's tracing capabilities. The agent searches the web, fetches URLs, takes notes, and generates research reports.

## Features Demonstrated

- **Trace-level tracking**: Full research sessions as traces
- **Span-level tracking**: Individual operations (LLM calls, tool executions)
- **Nested spans**: Parent-child relationships in execution flow
- **Token/cost tracking**: LLM usage metrics
- **Custom attributes**: Rich metadata on spans and traces
- **Tool tracing**: Automatic instrumentation of tool functions

## Setup

1. Install dependencies:

```bash
cd examples/research_agent
pip install -r requirements.txt

# Also install vizpath SDK from source
pip install -e ../../sdk
```

2. Set your NVIDIA API key:

```bash
export NVIDIA_API_KEY="your-api-key"
```

3. (Optional) Start the vizpath server to collect traces:

```bash
cd ../../server
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Usage

### Basic usage

```bash
# From the vizpath root directory
python -m examples.research_agent.run "What are the latest developments in AI agents?"
```

### With custom options

```bash
python -m examples.research_agent.run \
  --model "meta/llama-3.1-70b-instruct" \
  --vizpath-url "http://localhost:8000" \
  "How do transformers work in machine learning?"
```

### Dry run (no vizpath server required)

```bash
python -m examples.research_agent.run --dry-run "Test topic"
```

## Architecture

```
research_agent/
├── agent.py      # Main ResearchAgent class with tracing
├── tools.py      # Tool functions (search, fetch, notes)
├── run.py        # CLI entry point
└── __init__.py   # Package exports
```

## Trace Structure

A typical research session produces this trace structure:

```
research_session (trace)
└── research_loop (agent span)
    ├── llm_call (llm span) - Initial query
    ├── execute_tool (tool span)
    │   └── web_search (tool span)
    ├── llm_call (llm span) - Process results
    ├── execute_tool (tool span)
    │   └── fetch_url (tool span)
    ├── execute_tool (tool span)
    │   └── add_note (tool span)
    ├── llm_call (llm span) - Continue research
    └── generate_report (llm span)
```

## Customization

### Using a different LLM provider

The agent uses OpenAI-compatible APIs. To use a different provider:

```python
agent = ResearchAgent(
    api_key="your-key",
    base_url="https://api.openai.com/v1",  # Or any compatible endpoint
    model="gpt-4",
)
```

### Adding custom tools

Create new tool functions with the `@tracer.tool` decorator:

```python
from vizpath import tracer

@tracer.tool(name="my_tool")
def my_custom_tool(arg: str) -> dict:
    tracer.set_span_attributes({"arg": arg})
    # ... implementation
    return result
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NVIDIA_API_KEY` | NVIDIA NIMs API key | Required |
| `VIZPATH_API_URL` | Vizpath server URL | `http://localhost:8000` |
| `VIZPATH_PROJECT_ID` | Project ID for traces | Auto-generated |
| `VIZPATH_ENABLED` | Enable/disable tracing | `true` |
