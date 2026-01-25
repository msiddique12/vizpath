"""Research agent example for vizpath.

This example demonstrates vizpath's tracing capabilities through
a research agent that searches, reads, and synthesizes information.
"""

from .agent import ResearchAgent
from .tools import web_search, fetch_url, NoteTaker

__all__ = ["ResearchAgent", "web_search", "fetch_url", "NoteTaker"]
