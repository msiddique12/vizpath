"""Research agent with comprehensive vizpath tracing."""

import json
import os
from typing import Any
from openai import OpenAI

from vizpath import tracer
from .tools import (
    web_search,
    fetch_url,
    NoteTaker,
    TOOL_DEFINITIONS,
)


class ResearchAgent:
    """An AI research agent that searches, reads, and synthesizes information.

    This agent demonstrates vizpath's tracing capabilities:
    - Trace-level tracking of full research sessions
    - Span-level tracking of individual operations
    - LLM call tracing with token/cost tracking
    - Tool execution tracing
    - Nested span hierarchies
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "meta/llama-3.1-70b-instruct",
    ):
        """Initialize the research agent.

        Args:
            api_key: API key for the LLM service. Defaults to NVIDIA_API_KEY env var.
            base_url: Base URL for the LLM API. Defaults to NVIDIA NIMs endpoint.
            model: Model to use for generation.
        """
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        self.base_url = base_url or "https://integrate.api.nvidia.com/v1"
        self.model = model

        if not self.api_key:
            raise ValueError(
                "API key required. Set NVIDIA_API_KEY env var or pass api_key parameter."
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        self.notes = NoteTaker()
        self.max_iterations = 10

        # System prompt for the research agent
        self.system_prompt = """You are a thorough research agent. Your goal is to research topics by:

1. Searching the web for relevant information
2. Fetching and reading promising URLs
3. Taking notes on key findings
4. Synthesizing information into a comprehensive report

Research process:
- Start with a broad search to understand the topic
- Drill down into specific aspects
- Take notes on important findings with sources
- When you have enough information, call generate_report

Be thorough but efficient. Aim to gather diverse perspectives and cite sources."""

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
            "temperature": 0.7,
            "max_tokens": 1024,
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
    def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool and return the result."""
        tracer.set_span_attributes({
            "tool.name": tool_name,
        })

        if tool_name == "web_search":
            result = web_search(arguments["query"])
        elif tool_name == "fetch_url":
            result = fetch_url(arguments["url"])
        elif tool_name == "add_note":
            result = self.notes.add_note(
                title=arguments["title"],
                content=arguments["content"],
                source=arguments.get("source"),
            )
        elif tool_name == "get_notes":
            result = self.notes.get_notes()
        elif tool_name == "generate_report":
            result = {"status": "ready", "summary": arguments["summary"]}
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        return json.dumps(result, indent=2)

    @tracer.span(name="research_loop", span_type="agent")
    def _research_loop(self, topic: str) -> str:
        """Run the research loop until completion or max iterations."""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Research the following topic thoroughly: {topic}"},
        ]

        tracer.set_span_attributes({
            "research.topic": topic,
            "research.max_iterations": self.max_iterations,
        })

        for iteration in range(self.max_iterations):
            tracer.set_span_attributes({
                "research.current_iteration": iteration + 1,
            })

            # Get LLM response
            response = self._call_llm(messages, tools=TOOL_DEFINITIONS)

            # Check if we're done (no tool calls)
            if not response["tool_calls"]:
                tracer.set_span_attributes({
                    "research.completed": True,
                    "research.total_iterations": iteration + 1,
                })
                return response["content"] or "Research complete but no final response generated."

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
                arguments = json.loads(tool_call["arguments"])

                # Check for report generation signal
                if tool_name == "generate_report":
                    tracer.set_span_attributes({
                        "research.completed": True,
                        "research.total_iterations": iteration + 1,
                        "research.summary": arguments.get("summary", ""),
                    })
                    # Generate final report
                    return self._generate_final_report(topic)

                # Execute the tool
                result = self._execute_tool(tool_name, arguments)

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                })

        # Max iterations reached
        tracer.set_span_attributes({
            "research.completed": False,
            "research.reason": "max_iterations_reached",
        })
        return self._generate_final_report(topic)

    @tracer.span(name="generate_report", span_type="llm")
    def _generate_final_report(self, topic: str) -> str:
        """Generate the final research report."""
        notes = self.notes.get_notes()

        tracer.set_span_attributes({
            "report.topic": topic,
            "report.note_count": len(notes),
        })

        notes_text = "\n\n".join(
            f"### {note['title']}\n{note['content']}\nSource: {note.get('source', 'N/A')}"
            for note in notes
        )

        messages = [
            {"role": "system", "content": "You are a research report writer. Create a comprehensive, well-structured report based on the research notes provided."},
            {"role": "user", "content": f"""Create a research report on: {topic}

Based on these research notes:

{notes_text if notes_text else "No notes were recorded."}

Write a comprehensive report with:
1. Executive Summary
2. Key Findings
3. Detailed Analysis
4. Conclusions
5. Sources"""},
        ]

        response = self._call_llm(messages)
        return response["content"] or "Failed to generate report."

    @tracer.trace(name="research_session")
    def research(self, topic: str) -> str:
        """Conduct research on a topic.

        This is the main entry point. It creates a new trace for the
        entire research session and coordinates the research process.

        Args:
            topic: The topic to research.

        Returns:
            A comprehensive research report.
        """
        tracer.set_trace_attributes({
            "research.topic": topic,
            "agent.type": "research",
            "agent.model": self.model,
        })

        # Clear any previous notes
        self.notes.clear_notes()

        # Run the research loop
        report = self._research_loop(topic)

        # Set final trace attributes
        final_notes = self.notes.get_notes()
        tracer.set_trace_attributes({
            "research.note_count": len(final_notes),
            "research.report_length": len(report),
        })

        return report
