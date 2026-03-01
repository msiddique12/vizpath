"""Framework adapters for automatic tracing."""

from vizpath.adapters.autogen import AutoGenTracer, VizpathAutoGenCallback, wrap_autogen_agent
from vizpath.adapters.crewai import CrewAIAdapter, TracedCrew, VizpathCrewCallback
from vizpath.adapters.haystack import HaystackAdapter, TracedPipeline, VizpathHaystackTracer
from vizpath.adapters.langchain import VizpathCallbackHandler
from vizpath.adapters.langgraph import LangGraphAdapter
from vizpath.adapters.llamaindex import VizpathLlamaIndexCallback
from vizpath.adapters.openai_agents import VizpathAgentsTraceProcessor
from vizpath.adapters.semantic_kernel import SemanticKernelAdapter, VizpathKernelFilter

__all__ = [
    # AutoGen
    "AutoGenTracer",
    "VizpathAutoGenCallback",
    "wrap_autogen_agent",
    # CrewAI
    "CrewAIAdapter",
    "TracedCrew",
    "VizpathCrewCallback",
    # Haystack
    "HaystackAdapter",
    "TracedPipeline",
    "VizpathHaystackTracer",
    # LangChain
    "VizpathCallbackHandler",
    # LangGraph
    "LangGraphAdapter",
    # LlamaIndex
    "VizpathLlamaIndexCallback",
    # OpenAI Agents
    "VizpathAgentsTraceProcessor",
    # Semantic Kernel
    "SemanticKernelAdapter",
    "VizpathKernelFilter",
]
