"""Research agent tools with vizpath tracing."""

import json
import httpx
from typing import Any
from vizpath import tracer


@tracer.tool(name="web_search")
def web_search(query: str) -> list[dict[str, str]]:
    """Search the web for information.

    In production, this would call a real search API (Brave, SerpAPI, etc.)
    For demo purposes, returns mock results.
    """
    # Mock search results - in production use a real API
    mock_results = [
        {
            "title": f"Result 1 for: {query}",
            "url": f"https://example.com/search?q={query.replace(' ', '+')}&result=1",
            "snippet": f"This is a detailed article about {query}. It covers the main concepts and provides examples.",
        },
        {
            "title": f"Result 2 for: {query}",
            "url": f"https://example.com/search?q={query.replace(' ', '+')}&result=2",
            "snippet": f"An in-depth guide to understanding {query}. Includes best practices and common pitfalls.",
        },
        {
            "title": f"Result 3 for: {query}",
            "url": f"https://example.com/search?q={query.replace(' ', '+')}&result=3",
            "snippet": f"Expert analysis on {query}. Recent developments and future predictions.",
        },
    ]

    tracer.set_span_attributes({
        "search.query": query,
        "search.result_count": len(mock_results),
    })

    return mock_results


@tracer.tool(name="fetch_url")
def fetch_url(url: str) -> dict[str, Any]:
    """Fetch content from a URL.

    For demo purposes, returns mock content based on URL.
    In production, would actually fetch and parse the page.
    """
    # Mock content - in production use httpx to fetch real content
    mock_content = {
        "url": url,
        "title": f"Page content from {url}",
        "content": f"""
This is the main content of the page at {url}.

## Key Points
- First important point about the topic
- Second important point with supporting evidence
- Third point that connects to broader themes

## Details
The article provides extensive coverage of the subject matter,
including historical context, current developments, and future implications.

## Conclusion
A summary of the main findings and their significance.
        """.strip(),
        "word_count": 150,
    }

    tracer.set_span_attributes({
        "fetch.url": url,
        "fetch.word_count": mock_content["word_count"],
    })

    return mock_content


class NoteTaker:
    """Simple note-taking system with vizpath tracing."""

    def __init__(self):
        self.notes: list[dict[str, str]] = []

    @tracer.tool(name="add_note")
    def add_note(self, title: str, content: str, source: str | None = None) -> dict[str, Any]:
        """Add a research note."""
        note = {
            "id": len(self.notes) + 1,
            "title": title,
            "content": content,
            "source": source,
        }
        self.notes.append(note)

        tracer.set_span_attributes({
            "note.id": note["id"],
            "note.title": title,
            "note.has_source": source is not None,
        })

        return note

    @tracer.tool(name="get_notes")
    def get_notes(self) -> list[dict[str, str]]:
        """Get all research notes."""
        tracer.set_span_attributes({
            "notes.count": len(self.notes),
        })
        return self.notes

    @tracer.tool(name="clear_notes")
    def clear_notes(self) -> dict[str, str]:
        """Clear all notes."""
        count = len(self.notes)
        self.notes = []

        tracer.set_span_attributes({
            "notes.cleared_count": count,
        })

        return {"status": "cleared", "count": count}


# Tool definitions for the LLM
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information on a topic. Returns a list of search results with titles, URLs, and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and read the content of a URL. Returns the page title and main content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_note",
            "description": "Save a research note for later reference. Use this to record important findings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the note",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content of the note",
                    },
                    "source": {
                        "type": "string",
                        "description": "Source URL or reference (optional)",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_notes",
            "description": "Retrieve all saved research notes.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": "Signal that research is complete and you're ready to generate the final report. Call this when you have gathered enough information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of research completed",
                    }
                },
                "required": ["summary"],
            },
        },
    },
]
