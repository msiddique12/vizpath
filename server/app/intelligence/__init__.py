"""Intelligence module — Nemotron-powered trace analysis, embedding, and synthetic data."""

from app.intelligence.embeddings import embed_trace, get_trace_embeddings, trace_to_text
from app.intelligence.llm import LLMLabeler
from app.intelligence.clustering import cluster_traces, get_cluster_summary, optimal_k
from app.intelligence.synthetic import SyntheticDataGenerator

__all__ = [
    "embed_trace",
    "get_trace_embeddings",
    "trace_to_text",
    "LLMLabeler",
    "cluster_traces",
    "get_cluster_summary",
    "optimal_k",
    "SyntheticDataGenerator",
]
