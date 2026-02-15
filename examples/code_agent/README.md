# Code Analysis Agent

An AI agent that analyzes codebases using real local file tools and NVIDIA Nemotron.

## Overview

The Code Analysis Agent demonstrates Vizpath's tracing capabilities with a practical use case: understanding codebases. Unlike mock-based demos, this agent operates on real files and provides genuine analysis.

## Features

- **Real File Operations**: Searches, reads, and analyzes actual files
- **Nemotron-Powered**: Uses NVIDIA's Llama-3.1-Nemotron-70B for reasoning
- **Full Tracing**: Every operation traced with vizpath
- **Multi-Step Analysis**: Agent loop with tool calling until completion

## Tools

| Tool | Description |
|------|-------------|
| `search_files` | Glob-based file search (e.g., `*.py`, `**/*.ts`) |
| `read_file` | Read file contents with optional line limit |
| `list_directory` | List directory contents |
| `analyze_code` | Extract imports, functions, classes from code |
| `complete_analysis` | Signal analysis completion |

## Usage

```bash
# Set your NVIDIA API key
export NVIDIA_API_KEY="nvapi-..."

# Start Vizpath (if not running)
./demo.sh

# Run the agent (from vizpath root)
python -m examples.code_agent.run "How does the intelligence module work?"

# Analyze a specific directory
python -m examples.code_agent.run "What are the API endpoints?" --codebase ./server

# Verbose mode to see agent reasoning
python -m examples.code_agent.run "Explain the SDK architecture" -v

# Dry run (no tracing to server)
python -m examples.code_agent.run "List all models" --dry-run
```

## Example Questions

Good questions for demo:

- "How does the intelligence module work?"
- "What are the main components of the server?"
- "How is tracing implemented in the SDK?"
- "What API routes are available?"
- "How does the dashboard visualize traces?"

## Viewing Traces

After running the agent:

1. Open http://localhost:3000 (dashboard)
2. Click on the latest trace in the trace list
3. Explore the execution:
   - **Timeline**: See chronological span execution
   - **DAG**: Visualize the call hierarchy
   - **Heatmap**: Identify slow operations
4. Click "Analyze" for Nemotron-powered trace analysis
5. Add labels/scores for training data curation

## Architecture

```
analyze()                    # @tracer.trace - top-level trace
├── _analysis_loop()         # @tracer.span(type="agent")
│   ├── _call_llm()          # @tracer.span(type="llm")
│   ├── _execute_tool()      # @tracer.span(type="tool")
│   │   └── search_files()   # @tracer.tool
│   ├── _call_llm()          # Next iteration
│   ├── _execute_tool()
│   │   └── read_file()      # @tracer.tool
│   └── ...
```

## Customization

```python
from examples.code_agent import CodeAnalysisAgent

agent = CodeAnalysisAgent(
    model="nvidia/llama-3.1-nemotron-70b-instruct",
    max_iterations=20,  # More iterations for complex analysis
    verbose=True,       # Print progress
)

result = agent.analyze(
    question="How does authentication work?",
    codebase="./my-project",
)
```
