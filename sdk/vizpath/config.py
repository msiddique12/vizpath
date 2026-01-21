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
    buffer_size: int = 50
    flush_interval: float = 5.0
    timeout: float = 30.0
    max_retries: int = 3
    enabled: bool = field(default_factory=lambda: os.environ.get("VIZPATH_ENABLED", "true").lower() == "true")

    def __post_init__(self) -> None:
        if self.buffer_size < 1:
            raise ValueError("buffer_size must be at least 1")
        if self.flush_interval < 0.1:
            raise ValueError("flush_interval must be at least 0.1 seconds")
