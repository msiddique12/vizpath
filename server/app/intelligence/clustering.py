"""Trace clustering with K-means to identify execution patterns.

Adapted from engine/intelligence/clustering.py to work with vizpath
Trace+Span model using string trace_id keys.
"""

import logging
import pickle
from collections import Counter
from typing import Any

import numpy as np
import redis
from sklearn.cluster import KMeans
from sklearn.metrics import pairwise_distances, silhouette_score
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Span, Trace

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 86400  # 1 day


def _get_redis() -> redis.Redis | None:
    """Get a Redis client, returning None if unavailable."""
    try:
        client = redis.from_url(settings.redis_url, decode_responses=False)
        client.ping()
        return client
    except Exception:
        return None


def optimal_k(embeddings: np.ndarray, max_k: int = 20) -> int:
    """Find the optimal number of clusters using silhouette score."""
    n_samples = embeddings.shape[0]
    if n_samples < 10:
        return 2 if n_samples > 1 else 1

    k_range = range(2, min(max_k + 1, n_samples))
    if not k_range:
        return 1

    # Sub-sample for performance
    if n_samples > 5000:
        indices = np.random.choice(n_samples, 5000, replace=False)
        embeddings_sample = embeddings[indices]
    else:
        embeddings_sample = embeddings

    best_score = -1.0
    best_k = 2

    for k in k_range:
        try:
            kmeans = KMeans(n_clusters=k, random_state=42, n_init="auto").fit(embeddings_sample)
            score = silhouette_score(embeddings_sample, kmeans.labels_)
            if score > best_score:
                best_score = score
                best_k = k
        except Exception as e:
            logger.warning(f"Could not compute silhouette score for k={k}: {e}")

    logger.info(f"Optimal k found: {best_k} with score {best_score:.4f}")
    return best_k


def cluster_traces(
    embeddings: dict[str, np.ndarray], project_id: str
) -> dict[str, Any] | None:
    """Cluster traces using K-means and cache the result.

    Args:
        embeddings: Mapping of trace_id (str) -> embedding array.
        project_id: Used as cache key namespace.

    Returns:
        Dict with "clusters" (id->cluster map) and "centroids", or None.
    """
    cache_key = f"clusters:{str(project_id)}"
    redis_client = _get_redis()

    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return pickle.loads(cached)
        except Exception as e:
            logger.warning(f"Redis GET failed for {cache_key}: {e}")

    if len(embeddings) < 2:
        return None

    ids, embedding_list = zip(*embeddings.items(), strict=True)
    embedding_matrix = np.vstack(embedding_list)

    try:
        k = optimal_k(embedding_matrix)
        if k <= 1:
            return None

        kmeans = KMeans(n_clusters=k, random_state=42, n_init="auto").fit(embedding_matrix)

        id_to_cluster = {
            str(tid): int(label)
            for tid, label in zip(ids, kmeans.labels_, strict=True)
        }
        centroids = kmeans.cluster_centers_

        result = {"clusters": id_to_cluster, "centroids": centroids}

        if redis_client:
            try:
                redis_client.set(cache_key, pickle.dumps(result), ex=CACHE_TTL_SECONDS)
            except Exception as e:
                logger.warning(f"Redis SET failed for {cache_key}: {e}")

        return result
    except Exception as e:
        logger.error(f"Clustering failed for project {project_id}: {e}", exc_info=True)
        return None


def get_cluster_summary(
    trace_ids_per_cluster: dict[int, list[str]],
    embeddings: dict[str, np.ndarray],
    centroids: np.ndarray,
    db: Session,
) -> dict[int, dict[str, Any]]:
    """Generate a summary for each cluster.

    Args:
        trace_ids_per_cluster: Cluster ID -> list of trace IDs.
        embeddings: trace_id -> embedding array.
        centroids: KMeans centroid matrix.
        db: SQLAlchemy session.

    Returns:
        Cluster ID -> summary dict.
    """
    summaries: dict[int, dict[str, Any]] = {}

    for cluster_id, trace_ids in trace_ids_per_cluster.items():
        if not trace_ids:
            continue

        traces = db.query(Trace).filter(Trace.id.in_(trace_ids)).all()
        if not traces:
            continue

        size = len(traces)
        success_count = sum(1 for t in traces if t.status == "success")
        success_rate = success_count / size if size > 0 else 0

        # Get error info from spans
        error_spans = (
            db.query(Span.error)
            .filter(Span.trace_id.in_(trace_ids), Span.error.isnot(None))
            .all()
        )
        error_types = Counter(e[0][:80] for e in error_spans if e[0])
        most_common_error = error_types.most_common(1)[0][0] if error_types else None

        # Top span names (actions)
        span_names = (
            db.query(Span.name).filter(Span.trace_id.in_(trace_ids)).all()
        )
        top_actions = [item[0] for item in Counter(n[0] for n in span_names).most_common(3)]

        # Representative trace (closest to centroid)
        available_embeddings = [embeddings[t.id] for t in traces if t.id in embeddings]
        available_traces = [t for t in traces if t.id in embeddings]
        if available_embeddings:
            cluster_emb_matrix = np.array(available_embeddings)
            centroid = centroids[cluster_id].reshape(1, -1)
            distances = pairwise_distances(cluster_emb_matrix, centroid)
            closest_idx = int(np.argmin(distances))
            representative_id = available_traces[closest_idx].id
        else:
            representative_id = traces[0].id

        summaries[cluster_id] = {
            "cluster_id": cluster_id,
            "size": size,
            "success_rate": round(success_rate, 2),
            "most_common_error": most_common_error,
            "top_actions": top_actions,
            "representative_trace_id": representative_id,
        }

    return summaries
