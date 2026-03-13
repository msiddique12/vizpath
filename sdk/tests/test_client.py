"""Tests for SDK client header behavior."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

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


class TestClientRetry:
    """Test retry/backoff behavior for SDK client response handling."""

    def test_rate_limit_uses_retry_after_header(self) -> None:
        """Retry-After should be honored on 429 responses."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_retries=2,
            enabled=True,
        )
        client = Client(config)
        span = MagicMock()
        span.model_dump.return_value = {"name": "span"}

        with (
            patch.object(client, "_client") as http_client,
            patch("vizpath.client.time.sleep") as sleep,
        ):
            http_client.post.side_effect = [
                httpx.Response(
                    429,
                    headers={"Retry-After": "0.75"},
                ),
                httpx.Response(200),
            ]

            client._send_with_retry([span])

            assert sleep.call_count == 1
            assert sleep.call_args_list[0].args[0] == 0.75
            assert http_client.post.call_count == 2

        client.close()

    def test_stats_track_overflow_and_flush(self) -> None:
        """Stats should track dropped and flushed spans."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_buffer_items=2,
            buffer_size=10,
            drop_oldest_when_full=True,
        )
        client = Client(config)
        client._client = MagicMock()
        client._client.post.return_value = httpx.Response(200)

        client.send(MagicMock(model_dump=MagicMock(return_value={"name": "first"})))
        client.send(MagicMock(model_dump=MagicMock(return_value={"name": "second"})))
        client.send(MagicMock(model_dump=MagicMock(return_value={"name": "third"})))
        assert client.stats()["dropped_spans"] == 1

        client.flush()
        assert client.stats()["flushed_spans"] == 2
        assert client.stats()["buffered"] == 0
        client.close()

    def test_stats_track_flush_failures(self) -> None:
        """Flush failures should be counted after retry exhaustion."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_retries=2,
        )
        client = Client(config)
        span = MagicMock()
        span.model_dump.return_value = {"name": "span"}

        with (
            patch.object(client, "_client") as http_client,
            patch("vizpath.client.time.sleep") as sleep,
        ):
            http_client.post.side_effect = [
                httpx.Response(500),
                httpx.Response(500),
            ]

            client._send_with_retry([span])

            assert client.stats()["flush_failures"] == 1
            assert client.stats()["buffered"] == 1
            assert sleep.call_count == 1

        client.close()

    def test_buffer_full_drops_newest_by_default(self) -> None:
        """When buffer reaches cap and drop_oldest is disabled, keep existing spans."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_buffer_items=2,
            buffer_size=10,
        )
        client = Client(config)
        client._client = MagicMock()
        client._client.post.return_value = httpx.Response(200)

        first = MagicMock()
        first.model_dump.return_value = {"name": "first"}
        second = MagicMock()
        second.model_dump.return_value = {"name": "second"}
        third = MagicMock()
        third.model_dump.return_value = {"name": "third"}

        client.send(first)
        client.send(second)
        client.send(third)
        client.flush()

        payload = client._client.post.call_args_list[0].kwargs["json"]
        assert len(payload) == 2
        assert [item["name"] for item in payload] == ["first", "second"]
        client.close()

    def test_buffer_full_drops_oldest_when_configured(self) -> None:
        """When dropping oldest is enabled, keep newest spans once full."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_buffer_items=2,
            buffer_size=10,
            drop_oldest_when_full=True,
        )
        client = Client(config)
        client._client = MagicMock()
        client._client.post.return_value = httpx.Response(200)

        first = MagicMock()
        first.model_dump.return_value = {"name": "first"}
        second = MagicMock()
        second.model_dump.return_value = {"name": "second"}
        third = MagicMock()
        third.model_dump.return_value = {"name": "third"}

        client.send(first)
        client.send(second)
        client.send(third)
        client.flush()

        payload = client._client.post.call_args_list[0].kwargs["json"]
        assert len(payload) == 2
        assert [item["name"] for item in payload] == ["second", "third"]
        client.close()

    def test_server_error_is_retried_and_rebuffered(self) -> None:
        """5xx responses should be retried and re-buffered if retries are exhausted."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_retries=2,
        )
        client = Client(config)
        span = MagicMock()
        span.model_dump.return_value = {"name": "span"}

        with (
            patch.object(client, "_client") as http_client,
            patch("vizpath.client.time.sleep") as sleep,
        ):
            http_client.post.side_effect = [
                httpx.Response(500),
                httpx.Response(500),
            ]

            client._send_with_retry([span])

            assert sleep.call_count == 1
            assert http_client.post.call_count == 2
            assert client._buffer.qsize() == 1

        client.close()

    def test_payload_chunking_splits_batches_according_to_max_payload_bytes(self) -> None:
        """Large batches should be split by max_payload_bytes and sent in chunks."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_payload_bytes=1,
        )
        client = Client(config)
        client._client = MagicMock()
        client._client.post.return_value = httpx.Response(200)

        payload = {"input": {"x": "y" * 50}}

        for idx in range(3):
            span = MagicMock()
            span.model_dump.return_value = {"name": f"span-{idx}", "payload": payload}
            client.send(span)

        client.flush()
        assert client._client.post.call_count == 3
        payloads = [call.kwargs["json"] for call in client._client.post.call_args_list]
        assert all(len(entry) == 1 for entry in payloads)
        assert [entry[0]["name"] for entry in payloads] == ["span-0", "span-1", "span-2"]
        client.close()

    def test_chunk_send_retries_and_rebuffers_current_and_remaining_spans(self) -> None:
        """If one chunk fails, current and remaining spans should be re-buffered."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_payload_bytes=1,
            max_retries=1,
        )
        client = Client(config)
        client._client = MagicMock()
        client._client.post.side_effect = [
            httpx.Response(200),
            httpx.Response(500),
            httpx.Response(200),
        ]

        payload = {"input": {"x": "y" * 50}}
        spans = []
        for idx in range(3):
            span = MagicMock()
            span.model_dump.return_value = {"name": f"span-{idx}", "payload": payload}
            spans.append(span)
            client.send(span)

        client.flush()

        assert client._client.post.call_count == 2
        assert client._buffer.qsize() == 2
        assert [item.model_dump.return_value["name"] for item in list(client._buffer.queue)] == [
            "span-1",
            "span-2",
        ]
        client.close()


class TestClientCircuitBreaker:
    """Test transport failure circuit-breaker behavior."""

    def test_circuit_breaker_blocks_flushes_after_repeated_transport_failures(self) -> None:
        """Repeated connection failures should open the circuit and skip flushes."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_retries=1,
            circuit_breaker_failures=2,
            circuit_breaker_window_seconds=120,
        )
        client = Client(config)
        span = MagicMock()
        span.model_dump.return_value = {"name": "span"}
        client._client = MagicMock()
        client._client.post.side_effect = httpx.ConnectError("connection failed")

        client.send(span)
        client._send_with_retry([span])
        assert not client._is_circuit_open()
        assert client._client.post.call_count == 1

        client._send_with_retry([span])
        assert client._is_circuit_open()
        assert client._client.post.call_count == 2

        client.send(span)
        client.flush()
        assert client._client.post.call_count == 2

        client._client.post.side_effect = [httpx.Response(200)]
        client._consecutive_failures = 0
        client._circuit_open_until = 0.0
        client._is_circuit_open()
        client.flush()
        assert client._client.post.call_count >= 3

        client.close()


class TestClientPayloadRedaction:
    """Test payload redaction behavior for sensitive fields."""

    def test_redacts_sensitive_fields_from_nested_payload(self) -> None:
        """Sensitive keys should be replaced before sending spans."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            redaction_fields=["password", "api_key", "TOKEN", "authorization"],
        )
        client = Client(config)
        client._client = MagicMock()
        client._client.post.return_value = httpx.Response(200)

        span = MagicMock()
        span.model_dump.return_value = {
            "name": "login",
            "input": {
                "username": "alice",
                "password": "super-secret",
                "nested": {"Api_Key": "should_mask"},
            },
            "trace_metadata": {
                "model": "gpt-4",
                "metadata": {
                    "request_headers": {"AuthORIZATION": "Bearer x"},
                },
            },
            "events": [
                {"name": "attempt", "attributes": {"token": "abc-123"}},
            ],
        }

        client.send(span)
        client.flush()

        payload = client._client.post.call_args_list[0].kwargs["json"][0]
        assert payload["input"]["password"] == "[REDACTED]"
        assert payload["input"]["nested"]["Api_Key"] == "[REDACTED]"
        assert payload["events"][0]["attributes"]["token"] == "[REDACTED]"
        assert payload["trace_metadata"]["metadata"]["request_headers"]["AuthORIZATION"] == "[REDACTED]"
        assert payload["input"]["username"] == "alice"
        client.close()

    def test_disables_redaction_when_disabled(self) -> None:
        """With redaction disabled, sensitive values should be transmitted unchanged."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            redaction_enabled=False,
            redaction_fields=["password"],
        )
        client = Client(config)
        client._client = MagicMock()
        client._client.post.return_value = httpx.Response(200)

        span = MagicMock()
        span.model_dump.return_value = {"password": "super-secret", "input": {"password": "nested"}}

        client.send(span)
        client.flush()

        payload = client._client.post.call_args_list[0].kwargs["json"][0]
        assert payload["password"] == "super-secret"
        assert payload["input"]["password"] == "nested"
        client.close()

    def test_redaction_preserves_tuple_shapes(self) -> None:
        """Sensitive tuples should keep tuple type after redaction."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            redaction_fields=["secret"],
        )
        client = Client(config)
        client._client = MagicMock()
        client._client.post.return_value = httpx.Response(200)

        span = MagicMock()
        span.model_dump.return_value = {
            "input": ("secret", {"secret": "value"}),
        }

        client.send(span)
        client.flush()

        payload = client._client.post.call_args_list[0].kwargs["json"][0]
        assert isinstance(payload["input"], tuple)
        assert payload["input"][0] == "secret"
        assert payload["input"][1]["secret"] == "[REDACTED]"
        client.close()

    def test_rate_limit_with_invalid_retry_after_falls_back_to_backoff(self) -> None:
        """Invalid Retry-After should use exponential backoff."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_retries=2,
        )
        client = Client(config)
        span = MagicMock()
        span.model_dump.return_value = {"name": "span"}

        with (
            patch.object(client, "_client") as http_client,
            patch("vizpath.client.time.sleep") as sleep,
        ):
            http_client.post.side_effect = [
                httpx.Response(
                    429,
                    headers={"Retry-After": "invalid"},
                ),
                httpx.Response(200),
            ]

            client._send_with_retry([span])

            assert sleep.call_count == 1
            assert sleep.call_args_list[0].args[0] == 1.0
            assert http_client.post.call_count == 2

        client.close()

    def test_rate_limit_with_http_date_retry_after(self) -> None:
        """HTTP-date Retry-After values should be converted to seconds."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            max_retries=2,
        )
        client = Client(config)
        span = MagicMock()
        span.model_dump.return_value = {"name": "span"}

        retry_dt = datetime.now(timezone.utc) + timedelta(seconds=45)
        retry_header = retry_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

        with (
            patch.object(client, "_client") as http_client,
            patch("vizpath.client.time.sleep") as sleep,
        ):
            http_client.post.side_effect = [
                httpx.Response(
                    429,
                    headers={"Retry-After": retry_header},
                ),
                httpx.Response(200),
            ]

            client._send_with_retry([span])

            assert sleep.call_count == 1
            assert sleep.call_args_list[0].args[0] >= 44.0
            assert sleep.call_args_list[0].args[0] <= 46.0
            assert http_client.post.call_count == 2

        client.close()


class TestClientFlush:
    """Test explicit flushing behavior."""

    def test_flush_processes_queued_spans(self) -> None:
        """Calling flush should attempt to send all queued spans."""
        config = Config(
            api_key="vp_test_key",
            base_url="http://localhost:8000/api/v1",
            buffer_size=10,
        )
        client = Client(config)
        span = MagicMock()
        span.model_dump.return_value = {"name": "span"}

        # Keep networking out of unit tests
        client._client = MagicMock()
        client._client.post.return_value = httpx.Response(200)

        client.send(span)
        client.send(span)
        client.flush()

        assert client._client.post.call_count == 1
        payload = client._client.post.call_args_list[0].kwargs["json"]
        assert len(payload) == 2

        client.close()

    def test_close_is_idempotent(self) -> None:
        """Closing the client twice should be a no-op."""
        client = Client(Config(enabled=False))
        client.close()
        client.close()
        assert client._shutdown.is_set()
