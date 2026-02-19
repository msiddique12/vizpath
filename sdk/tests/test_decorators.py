"""Tests for global decorator-based tracer behavior."""

from unittest.mock import patch

from vizpath.decorators import GlobalTracer


def test_configure_closes_previous_client():
    """Reconfiguring should close old client to avoid leaked flush threads."""
    tracer = GlobalTracer()

    with patch("vizpath.decorators.Client.close") as mock_close:
        tracer.configure(api_url="http://localhost:8000")
        tracer.configure(api_url="http://localhost:8001")

        assert mock_close.call_count == 1

