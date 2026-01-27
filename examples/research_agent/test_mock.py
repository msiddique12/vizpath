#!/usr/bin/env python3
"""Test the research agent with mock LLM responses.

This script tests the agent structure without requiring:
- NVIDIA API key
- Vizpath server running

Usage:
    python -m examples.research_agent.test_mock
"""

import json
from unittest.mock import MagicMock, patch

# Mock OpenAI before importing agent
mock_response = MagicMock()
mock_response.choices = [MagicMock()]
mock_response.choices[0].message.content = "This is a test research report about AI agents."
mock_response.choices[0].message.tool_calls = None
mock_response.choices[0].finish_reason = "stop"
mock_response.usage = MagicMock()
mock_response.usage.prompt_tokens = 100
mock_response.usage.completion_tokens = 50


def test_tools():
    """Test that tools work correctly."""
    from examples.research_agent.tools import (
        NoteTaker,
        fetch_url,
        web_search,
    )

    # Test web search
    results = web_search("AI agents")
    assert len(results) == 3
    assert all("title" in r and "url" in r and "snippet" in r for r in results)
    print("web_search: OK")

    # Test URL fetch
    content = fetch_url("https://example.com/article")
    assert "url" in content
    assert "content" in content
    print("fetch_url: OK")

    # Test note taker
    notes = NoteTaker()
    note = notes.add_note("Test Note", "This is a test", "https://example.com")
    assert note["id"] == 1
    assert note["title"] == "Test Note"

    all_notes = notes.get_notes()
    assert len(all_notes) == 1

    cleared = notes.clear_notes()
    assert cleared["count"] == 1
    assert len(notes.get_notes()) == 0
    print("NoteTaker: OK")


def test_agent_structure():
    """Test agent initialization and method structure."""
    with patch("examples.research_agent.agent.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from examples.research_agent.agent import ResearchAgent

        agent = ResearchAgent(api_key="test-key")

        assert agent.api_key == "test-key"
        assert agent.model == "meta/llama-3.1-70b-instruct"
        assert agent.max_iterations == 10
        assert hasattr(agent, "research")
        assert hasattr(agent, "_call_llm")
        assert hasattr(agent, "_execute_tool")
        assert hasattr(agent, "_research_loop")
        assert hasattr(agent, "_generate_final_report")
        print("ResearchAgent structure: OK")


def test_agent_research():
    """Test a mock research session."""
    with patch("examples.research_agent.agent.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from examples.research_agent.agent import ResearchAgent

        agent = ResearchAgent(api_key="test-key")
        report = agent.research("Test topic")

        assert isinstance(report, str)
        assert len(report) > 0
        print("ResearchAgent.research: OK")


def main():
    print("Running research agent tests with mocks...\n")

    print("Testing tools...")
    test_tools()
    print()

    print("Testing agent structure...")
    test_agent_structure()
    print()

    print("Testing mock research session...")
    test_agent_research()
    print()

    print("All tests passed!")


if __name__ == "__main__":
    main()
