"""Code analysis agent for Vizpath demos.

This agent analyzes codebases using real local file tools,
demonstrating Vizpath's tracing capabilities with Nemotron.
"""

from .agent import CodeAnalysisAgent
from .tools import search_files, read_file, list_directory, analyze_code

__all__ = [
    "CodeAnalysisAgent",
    "search_files",
    "read_file",
    "list_directory",
    "analyze_code",
]
