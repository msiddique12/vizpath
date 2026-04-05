"""Tests for WebSocket endpoints."""

from unittest.mock import MagicMock

import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.models import Project
from app.routes.ws import (
    _verify_ws_api_key,
    active_connections,
    broadcast_message,
    notify_span_ingested,
)


class TestWebSocketAuth:
    """Tests for WebSocket authentication."""

    def test_verify_ws_api_key_no_key(self):
        """Returns None when no API key provided."""
        result = _verify_ws_api_key(None)
        assert result is None

    def test_verify_ws_api_key_invalid(self, test_db):
        """Returns None for invalid API key."""
        result = _verify_ws_api_key("invalid-key", db=test_db)
        assert result is None

    def test_verify_ws_api_key_valid(self, test_db):
        """Returns project for valid API key."""
        from app.auth import generate_api_key, hash_api_key

        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)

        project = Project(name="test-ws", api_key_hash=key_hash)
        test_db.add(project)
        test_db.commit()

        result = _verify_ws_api_key(api_key, db=test_db)
        assert result is not None
        assert result.name == "test-ws"

    def test_verify_ws_api_key_db_error_returns_none(self, test_db):
        """DB errors during verification should fail closed."""
        from unittest.mock import patch

        with patch("app.routes.ws.get_project_by_api_key", side_effect=RuntimeError("db error")):
            result = _verify_ws_api_key("some-key", db=test_db)
            assert result is None

    def test_strict_mode_rejects_missing_key(self, client, monkeypatch):
        """Production-like strict mode should reject websocket connections without an API key."""
        original = settings.security_strict_mode
        monkeypatch.setattr(settings, "security_strict_mode", True)

        try:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws/traces"):
                    pass

            assert exc_info.value.code == 4001
            assert exc_info.value.reason == "Unauthorized: Invalid or missing API key"
        finally:
            monkeypatch.setattr(settings, "security_strict_mode", original)

    def test_fallback_disabled_rejects_missing_key(self, client, monkeypatch):
        """Missing key is rejected when dev fallback is disabled, even without strict mode."""
        original_fallback = settings.allow_unauthenticated_dev_fallback
        original_strict = settings.security_strict_mode
        monkeypatch.setattr(settings, "allow_unauthenticated_dev_fallback", False)
        monkeypatch.setattr(settings, "security_strict_mode", False)

        try:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws/traces"):
                    pass

            assert exc_info.value.code == 4001
            assert exc_info.value.reason == "Unauthorized: Invalid or missing API key"
        finally:
            monkeypatch.setattr(
                settings, "allow_unauthenticated_dev_fallback", original_fallback
            )
            monkeypatch.setattr(settings, "security_strict_mode", original_strict)

    def test_strict_mode_allows_valid_key(self, client, test_db, monkeypatch):
        """Strict mode still allows authenticated websocket connections."""
        from app.auth import generate_api_key, hash_api_key

        api_key = generate_api_key()
        project = Project(name="strict-project", api_key_hash=hash_api_key(api_key))
        test_db.add(project)
        test_db.commit()

        original = settings.security_strict_mode
        monkeypatch.setattr(settings, "security_strict_mode", True)
        try:
            with client.websocket_connect(f"/ws/traces?api_key={api_key}") as socket:
                socket.send_text("ping")
                assert socket.receive_text() == "pong"
        finally:
            monkeypatch.setattr(settings, "security_strict_mode", original)

    def test_strict_mode_allows_valid_header_key(self, client, test_db, monkeypatch):
        """Strict mode should accept API key via X-API-Key header."""
        from app.auth import generate_api_key, hash_api_key

        api_key = generate_api_key()
        project = Project(name="strict-header-project", api_key_hash=hash_api_key(api_key))
        test_db.add(project)
        test_db.commit()

        original = settings.security_strict_mode
        monkeypatch.setattr(settings, "security_strict_mode", True)
        try:
            with client.websocket_connect(
                "/ws/traces",
                headers={"X-API-Key": api_key},
            ) as socket:
                socket.send_text("ping")
                assert socket.receive_text() == "pong"
        finally:
            monkeypatch.setattr(settings, "security_strict_mode", original)


class TestBroadcastMessage:
    """Tests for broadcast_message function."""

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self):
        """No error when broadcasting to no connections."""
        active_connections.clear()
        await broadcast_message({"type": "test"})
        assert len(active_connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_filters_by_project(self):
        """Messages are only sent to matching project connections."""
        active_connections.clear()

        mock_ws1 = MagicMock()
        mock_ws1.send_text = MagicMock(return_value=None)
        mock_ws2 = MagicMock()
        mock_ws2.send_text = MagicMock(return_value=None)

        # Make send_text async
        async def mock_send(data):
            pass

        mock_ws1.send_text = mock_send
        mock_ws2.send_text = mock_send

        active_connections[mock_ws1] = "project-1"
        active_connections[mock_ws2] = "project-2"

        await broadcast_message({"type": "test"}, project_id="project-1")

        # Clean up
        active_connections.clear()


class TestNotifySpanIngested:
    """Tests for notify_span_ingested function."""

    @pytest.mark.asyncio
    async def test_notify_creates_correct_message(self):
        """notify_span_ingested broadcasts correct message format."""
        active_connections.clear()

        messages_sent = []

        async def capture_send(data):
            messages_sent.append(data)

        mock_ws = MagicMock()
        mock_ws.send_text = capture_send
        active_connections[mock_ws] = "project-1"

        await notify_span_ingested("trace-123", 5, project_id="project-1")

        assert len(messages_sent) == 1
        import json
        msg = json.loads(messages_sent[0])
        assert msg["type"] == "span_ingested"
        assert msg["trace_id"] == "trace-123"
        assert msg["span_count"] == 5

        active_connections.clear()
