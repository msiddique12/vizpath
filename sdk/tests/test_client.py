"""Tests for SDK client header behavior."""

from vizpath.client import Client
from vizpath.config import Config


class TestClientHeaders:
    """Test that Client sends correct headers based on API key configuration."""

    def test_headers_with_api_key(self):
        """When api_key is set, X-API-Key header is included."""
        config = Config(api_key="vp_test_key", base_url="http://localhost:8000/api/v1")
        client = Client(config)

        try:
            assert client._client is not None
            assert client._client.headers["X-API-Key"] == "vp_test_key"
            assert "Authorization" not in client._client.headers
        finally:
            client.close()

    def test_headers_without_api_key(self):
        """When api_key is None, no auth header is sent."""
        config = Config(api_key=None, base_url="http://localhost:8000/api/v1")
        client = Client(config)

        try:
            assert client._client is not None
            assert "X-API-Key" not in client._client.headers
            assert "Authorization" not in client._client.headers
        finally:
            client.close()

    def test_content_type_always_set(self):
        """Content-Type is always application/json regardless of auth."""
        for api_key in ["vp_test_key", None]:
            config = Config(api_key=api_key, base_url="http://localhost:8000/api/v1")
            client = Client(config)
            try:
                assert client._client.headers["Content-Type"] == "application/json"
            finally:
                client.close()

    def test_disabled_client_has_no_http_client(self):
        """When enabled=False, no HTTP client is created."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            enabled=False,
        )
        client = Client(config)

        assert client._client is None
