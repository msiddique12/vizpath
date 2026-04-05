"""Tests for intelligence clustering cache behavior."""

import json
from unittest.mock import MagicMock, patch

import numpy as np

from app.intelligence.clustering import cluster_traces


def test_cluster_traces_uses_safe_json_cache_format():
    """Cached cluster payloads should deserialize from JSON safely."""
    embeddings = {
        "trace-1": np.array([1.0, 0.0], dtype=np.float32),
        "trace-2": np.array([0.0, 1.0], dtype=np.float32),
    }
    cached_payload = {
        "clusters": {"trace-1": 0, "trace-2": 1},
        "centroids": [[1.0, 0.0], [0.0, 1.0]],
    }
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(cached_payload).encode("utf-8")

    with patch("app.intelligence.clustering._get_redis", return_value=mock_redis):
        result = cluster_traces(embeddings, project_id="project-123")

    assert result is not None
    assert result["clusters"] == {"trace-1": 0, "trace-2": 1}
    assert isinstance(result["centroids"], np.ndarray)
    assert result["centroids"].shape == (2, 2)
