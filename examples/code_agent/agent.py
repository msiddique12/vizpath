"""Code analysis agent with vizpath tracing.

Analyzes codebases using local file tools + Nemotron.
"""

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from vizpath import tracer

from .tools import (
    search_files,
    read_file,
    list_directory,
    analyze_code,
    TOOL_DEFINITIONS,
)


class CodeAnalysisAgent:
    """An AI agent that analyzes codebases using local file tools.

    This agent demonstrates vizpath's tracing capabilities:
    - Trace-level tracking of full analysis sessions
    - Span-level tracking of individual operations
    - LLM call tracing with token/cost tracking
    - Tool execution tracing (real file operations)
    - Nested span hierarchies
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "nvidia/llama-3.1-nemotron-70b-instruct",
        max_iterations: int = 15,
        verbose: bool = False,
    ):
        """Initialize the code analysis agent.

        Args:
            api_key: API key for the LLM service. Defaults to NVIDIA_API_KEY env var.
            base_url: Base URL for the LLM API. Defaults to NVIDIA NIM endpoint.
            model: Model to use for generation.
            max_iterations: Maximum agent loop iterations.
            verbose: Print detailed progress during analysis.
        """
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        self.base_url = base_url or "https://integrate.api.nvidia.com/v1"
        self.model = model
        self.verbose = verbose
        self.max_iterations = max_iterations

        if not self.api_key:
            raise ValueError(
                "API key required. Set NVIDIA_API_KEY env var or pass api_key parameter."
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        # System prompt for the code analysis agent
        self.system_prompt = """You are a code analysis agent. Your goal is to analyze codebases to answer questions by:

1. Exploring the directory structure to understand the project layout
2. Searching for relevant files using glob patterns
3. Reading files to understand their contents
4. Analyzing code structure (imports, functions, classes)
5. Synthesizing findings into a clear, detailed answer

Analysis process:
- Start by listing the directory to understand the project structure
- Search for files matching the topic (e.g., *.py files in a specific module)
- Read and analyze relevant files
- When you have enough information, call complete_analysis

Be thorough but efficient. Focus on answering the specific question asked.
Cite specific files and line numbers when possible."""

    def _log(self, message: str, indent: int = 0) -> None:
        """Print verbose log message if verbose mode is enabled."""
        if self.verbose:
            prefix = "  " * indent
            print(f"{prefix}[Agent] {message}")

    def _resolve_tool_path(self, requested_path: str, codebase: str, expect_dir: bool = False) -> tuple[str | None, str | None]:
        """Resolve tool paths relative to codebase and prevent escape."""
        codebase_root = Path(codebase).resolve()
        requested = requested_path or "."

        try:
            candidate = Path(requested)
            resolved = (codebase_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
            resolved.relative_to(codebase_root)
        except Exception:
            return None, (
                f"Path '{requested}' is outside codebase '{codebase_root}'. "
                "Use paths within the selected codebase."
            )

        if expect_dir and not resolved.is_dir():
            return None, f"Directory not found: {resolved}"
        if not expect_dir and not resolved.is_file():
            return None, f"File not found: {resolved}"

        return str(resolved), None

    @tracer.span(name="llm_call", span_type="llm")
    def _call_llm(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Make an LLM call with tracing."""
        tracer.set_span_attributes({
            "llm.model": self.model,
            "llm.message_count": len(messages),
            "llm.has_tools": tools is not None,
        })

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,  # Lower temp for more focused analysis
            "max_tokens": 2048,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**kwargs)

        # Extract usage for tracing
        usage = response.usage
        if usage:
            tracer.set_span_tokens(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            )
            # Estimate cost (adjust based on actual model pricing)
            estimated_cost = (usage.prompt_tokens * 0.001 + usage.completion_tokens * 0.002) / 1000
            tracer.set_span_cost(estimated_cost)
            self._log(f"LLM call: {usage.prompt_tokens}+{usage.completion_tokens} tokens", indent=1)

        message = response.choices[0].message

        result = {
            "content": message.content,
            "tool_calls": None,
            "finish_reason": response.choices[0].finish_reason,
        }

        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in message.tool_calls
            ]
            tracer.set_span_attributes({
                "llm.tool_call_count": len(message.tool_calls),
            })

        return result

    @tracer.span(name="execute_tool", span_type="tool")
    def _execute_tool(self, tool_name: str, arguments: dict[str, Any], codebase: str) -> str:
        """Execute a tool and return the result."""
        tracer.set_span_attributes({
            "tool.name": tool_name,
        })

        self._log(f"Executing tool: {tool_name}", indent=2)

        if tool_name == "search_files":
            requested_dir = arguments.get("directory", ".")
            search_dir, err = self._resolve_tool_path(requested_dir, codebase, expect_dir=True)
            if err:
                result = {"error": err}
                return json.dumps(result, indent=2)
            result = search_files(
                pattern=arguments["pattern"],
                directory=search_dir,
            )
            self._log(f"  Found {len(result)} files for '{arguments['pattern']}'", indent=2)

        elif tool_name == "read_file":
            resolved_path, err = self._resolve_tool_path(arguments["path"], codebase, expect_dir=False)
            if err:
                result = {"error": err}
                return json.dumps(result, indent=2)
            result = read_file(
                path=resolved_path,
                max_lines=arguments.get("max_lines", 200),
            )
            if "error" not in result:
                self._log(f"  Read {result.get('lines', 0)} lines from {arguments['path']}", indent=2)
            else:
                self._log(f"  Error: {result['error']}", indent=2)

        elif tool_name == "list_directory":
            requested_dir = arguments.get("path", ".")
            list_dir, err = self._resolve_tool_path(requested_dir, codebase, expect_dir=True)
            if err:
                result = {"error": err}
                return json.dumps(result, indent=2)
            result = list_directory(path=list_dir)
            self._log(f"  Listed {len(result)} items in {arguments.get('path', '.')}", indent=2)

        elif tool_name == "analyze_code":
            resolved_path, err = self._resolve_tool_path(arguments["file_path"], codebase, expect_dir=False)
            if err:
                result = {"error": err}
                return json.dumps(result, indent=2)
            result = analyze_code(file_path=resolved_path)
            if "error" not in result:
                self._log(
                    f"  Analyzed {arguments['file_path']}: "
                    f"{len(result.get('functions', []))} functions, "
                    f"{len(result.get('classes', []))} classes",
                    indent=2,
                )
            else:
                self._log(f"  Error: {result['error']}", indent=2)

        elif tool_name == "complete_analysis":
            result = {"status": "ready", "summary": arguments.get("summary", "")}
            self._log("  Analysis complete signal received", indent=2)

        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        return json.dumps(result, indent=2)

    @tracer.span(name="analysis_loop", span_type="agent")
    def _analysis_loop(self, question: str, codebase: str) -> str:
        """Run the analysis loop until completion or max iterations."""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Analyze this codebase to answer: {question}\n\nCodebase root: {codebase}"},
        ]

        tracer.set_span_attributes({
            "analysis.question": question,
            "analysis.codebase": codebase,
            "analysis.max_iterations": self.max_iterations,
        })

        for iteration in range(self.max_iterations):
            self._log(f"Iteration {iteration + 1}/{self.max_iterations}")
            tracer.set_span_attributes({
                "analysis.current_iteration": iteration + 1,
            })

            # Get LLM response
            response = self._call_llm(messages, tools=TOOL_DEFINITIONS)

            # Check if we're done (no tool calls)
            if not response["tool_calls"]:
                tracer.set_span_attributes({
                    "analysis.completed": True,
                    "analysis.total_iterations": iteration + 1,
                    "analysis.reason": "no_tool_calls",
                })
                return response["content"] or "Analysis complete but no response generated."

            # Process tool calls
            # Add assistant message with tool calls
            assistant_message = {"role": "assistant", "content": response["content"]}
            if response["tool_calls"]:
                assistant_message["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in response["tool_calls"]
                ]
            messages.append(assistant_message)

            # Execute each tool call
            for tool_call in response["tool_calls"]:
                tool_name = tool_call["name"]
                try:
                    arguments = json.loads(tool_call["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                # Check for completion signal
                if tool_name == "complete_analysis":
                    tracer.set_span_attributes({
                        "analysis.completed": True,
                        "analysis.total_iterations": iteration + 1,
                        "analysis.summary": arguments.get("summary", ""),
                    })
                    # Get final response from LLM
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps({"status": "ready"}),
                    })
                    final_response = self._call_llm(messages)
                    return final_response["content"] or arguments.get("summary", "Analysis complete.")

                # Execute the tool
                result = self._execute_tool(tool_name, arguments, codebase)

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                })

        # Max iterations reached
        tracer.set_span_attributes({
            "analysis.completed": False,
            "analysis.reason": "max_iterations_reached",
        })

        # Ask for final response anyway
        messages.append({
            "role": "user",
            "content": "Please provide your best answer based on what you've found so far.",
        })
        final_response = self._call_llm(messages)
        return final_response["content"] or "Analysis incomplete: max iterations reached."

    @tracer.trace(name="code_analysis")
    def analyze(self, question: str, codebase: str = ".") -> str:
        """Analyze a codebase to answer a question.

        This is the main entry point. It creates a new trace for the
        entire analysis session and coordinates the process.

        Args:
            question: The question to answer about the codebase.
            codebase: Root directory of the codebase (default: current directory).

        Returns:
            A detailed answer to the question.
        """
        tracer.set_trace_attributes({
            "analysis.question": question,
            "analysis.codebase": codebase,
            "agent.type": "code_analysis",
            "agent.model": self.model,
            "agent.provider": "nvidia-nim",
        })

        self._log(f"Analyzing: {question}")
        self._log(f"Codebase: {codebase}")

        # Run the analysis loop
        answer = self._analysis_loop(question, codebase)

        # Set final trace attributes
        tracer.set_trace_attributes({
            "analysis.answer_length": len(answer),
        })

        return answer
