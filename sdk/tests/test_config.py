"""Tests for Config class."""

import os
from unittest.mock import patch

import pytest

from vizpath.config import Config


class TestConfig:
    def test_default_values(self):
        with patch.dict(os.environ, {}, clear=True):
            config = Config()

            assert config.api_key is None
            assert config.base_url == "http://localhost:8000/api/v1"
            assert config.buffer_size == 50
            assert config.flush_interval == 5.0
            assert config.timeout == 30.0
            assert config.max_retries == 3
            assert config.enabled is True
            assert config.circuit_breaker_enabled is True
            assert config.circuit_breaker_failures == 5
            assert config.circuit_breaker_window_seconds == 60.0

    def test_from_environment(self):
        env = {
            "VIZPATH_API_KEY": "test-key",
            "VIZPATH_API_URL": "https://api.example.com/v1",
            "VIZPATH_ENABLED": "false",
            "VIZPATH_CIRCUIT_BREAKER_ENABLED": "false",
            "VIZPATH_CIRCUIT_BREAKER_FAILURES": "7",
            "VIZPATH_CIRCUIT_BREAKER_WINDOW_SECONDS": "120",
        }
        with patch.dict(os.environ, env, clear=True):
            config = Config()

            assert config.api_key == "test-key"
            assert config.base_url == "https://api.example.com/v1"
            assert config.enabled is False
            assert config.circuit_breaker_enabled is False
            assert config.circuit_breaker_failures == 7
            assert config.circuit_breaker_window_seconds == 120.0

    def test_explicit_values(self):
        config = Config(
            api_key="explicit-key",
            base_url="https://custom.api/v1",
            buffer_size=100,
            flush_interval=10.0,
            circuit_breaker_enabled=False,
            circuit_breaker_failures=3,
            circuit_breaker_window_seconds=30,
        )

        assert config.api_key == "explicit-key"
        assert config.base_url == "https://custom.api/v1"
        assert config.buffer_size == 100
        assert config.flush_interval == 10.0
        assert config.circuit_breaker_enabled is False
        assert config.circuit_breaker_failures == 3
        assert config.circuit_breaker_window_seconds == 30

    def test_invalid_buffer_size(self):
        with pytest.raises(ValueError, match="buffer_size must be at least 1"):
            Config(buffer_size=0)

    def test_invalid_flush_interval(self):
        with pytest.raises(ValueError, match="flush_interval must be at least 0.1"):
            Config(flush_interval=0.05)

    def test_invalid_circuit_breaker_failures(self):
        with pytest.raises(ValueError, match="circuit_breaker_failures must be at least 1"):
            Config(circuit_breaker_failures=0)

    def test_invalid_circuit_breaker_window(self):
        with pytest.raises(ValueError, match="circuit_breaker_window_seconds must be at least 1"):
            Config(circuit_breaker_window_seconds=0)
