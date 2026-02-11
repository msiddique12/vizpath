"""Trace embedding via NVIDIA NIM API (nv-embedqa-e5-v5, 1024-dim).

Adapted from engine/intelligence/embeddings.py to work with vizpath
Trace + Span dicts instead of legacy Trajectory objects.
"""

import logging
import pickle
from typing import Any

import numpy as np
import redis
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024  # nv-embedqa-e5-v5 output dimension
CACHE_TTL_SECONDS = 86400 * 30  # 30 days

# Lazy NIM embedding client
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazy-initialize the NIM embedding client."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
        )
    return _client


def _get_redis() -> redis.Redis | None:
    """Get a Redis client, returning None if unavailable."""
    try:
        client = redis.from_url(settings.redis_url, decode_responses=False)
        client.ping()
        return client
    except Exception:
        return None


def _get_zero_vector() -> np.ndarray:
    """Return a zero vector of the embedding dimension."""
    return np.zeros(EMBEDDING_DIM, dtype=np.float32)


def trace_to_text(trace_data: dict[str, Any]) -> str:
    """Convert a Trace+Spans dict into a deterministic text summary for embedding.

    Works with vizpath's Trace.to_dict() / Span.to_dict() output.

    Args:
        trace_data: Dict with trace-level fields and a "spans" list.

    Returns:
        Deterministic natural-language summary string.
    """
    name = trace_data.get("name", "unnamed")
    status = trace_data.get("status", "unknown")
    duration = trace_data.get("duration_ms")
    tokens = trace_data.get("total_tokens")

    steps_summary = []
    for span in trace_data.get("spans", []):
        action = span.get("name", "unnamed")
        span_type = span.get("span_type", "unknown")
        entry = f"{action} (type={span_type}"
        if span.get("duration_ms"):
            entry += f", duration={span['duration_ms']}ms"
        if span.get("tokens"):
            entry += f", tokens={span['tokens']}"
        if span.get("error"):
            entry += f", error={span['error']}"
        entry += ")"
        steps_summary.append(entry)

    steps_str = "; ".join(steps_summary) if steps_summary else "no spans"
    duration_str = f" Duration: {duration}ms." if duration else ""
    tokens_str = f" Tokens: {tokens}." if tokens else ""

    return f"Trace: {name}. Status: {status}.{duration_str}{tokens_str} Steps: {steps_str}."


async def embed_trace(trace_id: str, trace_text: str) -> np.ndarray:
    """Generate or retrieve a cached embedding for a single trace.

    Args:
        trace_id: The trace identifier (string).
        trace_text: Pre-computed text from trace_to_text().

    Returns:
        numpy array of shape (EMBEDDING_DIM,). Zero vector on failure.
    """
    cache_key = f"embedding:{trace_id}"
    redis_client = _get_redis()

    # 1. Check cache
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for embedding: {trace_id}")
                return pickle.loads(cached)
        except Exception as e:
            logger.warning(f"Redis GET failed for {cache_key}: {e}")

    # 2. Generate via NIM
    try:
        client = _get_client()
        response = await client.embeddings.create(
            model=settings.nvidia_embedding_model,
            input=trace_text,
        )
        embedding = np.array(response.data[0].embedding, dtype=np.float32)
    except Exception as e:
        logger.error(f"Failed to embed trace {trace_id}: {e}", exc_info=True)
        return _get_zero_vector()

    # 3. Cache
    if redis_client:
        try:
            redis_client.set(cache_key, pickle.dumps(embedding), ex=CACHE_TTL_SECONDS)
        except Exception as e:
            logger.warning(f"Redis SET failed for {cache_key}: {e}")

    return embedding


async def get_trace_embeddings(traces: dict[str, str]) -> dict[str, np.ndarray]:
    """Batch-embed traces with Redis caching.

    Args:
        traces: Mapping of trace_id (str) -> trace_text (str).

    Returns:
        Mapping of trace_id -> numpy embedding array.
    """
    results: dict[str, np.ndarray] = {}
    if not traces:
        return results

    trace_ids = list(traces.keys())
    redis_client = _get_redis()

    # 1. Bulk cache check
    if redis_client:
        try:
            cache_keys = [f"embedding:{tid}" for tid in trace_ids]
            cached_results = redis_client.mget(cache_keys)

            for i, cached in enumerate(cached_results):
                if cached:
                    results[trace_ids[i]] = pickle.loads(cached)

            logger.debug(f"Cache hit for {len(results)}/{len(trace_ids)} embeddings.")
        except Exception as e:
            logger.warning(f"Redis MGET failed: {e}")

    # 2. Batch-embed misses
    missed_ids = [tid for tid in trace_ids if tid not in results]
    if missed_ids:
        try:
            client = _get_client()
            batch_size = 10
            for batch_start in range(0, len(missed_ids), batch_size):
                batch_ids = missed_ids[batch_start : batch_start + batch_size]
                batch_texts = [traces[tid] for tid in batch_ids]

                response = await client.embeddings.create(
                    model=settings.nvidia_embedding_model,
                    input=batch_texts,
                )

                for j, emb_data in enumerate(response.data):
                    results[batch_ids[j]] = np.array(emb_data.embedding, dtype=np.float32)

            # 3. Bulk cache new results
            if redis_client:
                try:
                    pipe = redis_client.pipeline()
                    for tid in missed_ids:
                        if tid in results:
                            pipe.set(f"embedding:{tid}", pickle.dumps(results[tid]), ex=CACHE_TTL_SECONDS)
                    pipe.execute()
                except Exception as e:
                    logger.warning(f"Redis pipeline SET failed: {e}")

        except Exception as e:
            logger.error(f"Failed to batch embed traces: {e}", exc_info=True)
            for tid in missed_ids:
                if tid not in results:
                    results[tid] = _get_zero_vector()

    return results
