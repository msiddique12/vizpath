"""Configuration for the vizpath SDK."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    """SDK configuration with sensible defaults."""

    api_key: str | None = field(default_factory=lambda: os.environ.get("VIZPATH_API_KEY"))
    base_url: str = field(
        default_factory=lambda: os.environ.get("VIZPATH_API_URL", "http://localhost:8000/api/v1")
    )
    project_id: str | None = field(default_factory=lambda: os.environ.get("VIZPATH_PROJECT_ID"))
    buffer_size: int = 50
    flush_interval: float = 5.0
    timeout: float = 30.0
    max_retries: int = 3
    enabled: bool = field(default_factory=lambda: os.environ.get("VIZPATH_ENABLED", "true").lower() == "true")
    circuit_breaker_enabled: bool = field(
        default_factory=lambda: os.environ.get("VIZPATH_CIRCUIT_BREAKER_ENABLED", "true").lower()
        == "true"
    )
    circuit_breaker_failures: int = field(
        default_factory=lambda: int(os.environ.get("VIZPATH_CIRCUIT_BREAKER_FAILURES", "5"))
    )
    circuit_breaker_window_seconds: float = field(
        default_factory=lambda: float(os.environ.get("VIZPATH_CIRCUIT_BREAKER_WINDOW_SECONDS", "60"))
    )

    def __post_init__(self) -> None:
        if self.buffer_size < 1:
            raise ValueError("buffer_size must be at least 1")
        if self.flush_interval < 0.1:
            raise ValueError("flush_interval must be at least 0.1 seconds")
        if self.circuit_breaker_failures < 1:
            raise ValueError("circuit_breaker_failures must be at least 1")
        if self.circuit_breaker_window_seconds < 1:
            raise ValueError("circuit_breaker_window_seconds must be at least 1 second")
