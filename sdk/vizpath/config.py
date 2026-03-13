"""Configuration for the vizpath SDK."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_bool_env(value: str | None, default: bool) -> bool:
    """Parse a boolean env value with strict true/false handling."""
    if value is None:
        return default
    return value.strip().lower() == "true"


def _parse_csv_list(value: str, default: list[str]) -> list[str]:
    """Parse comma-separated values into a normalized list."""
    values = [item.strip() for item in value.split(",")]
    parsed = [value for value in values if value]
    normalized = [value.lower() for value in parsed]

    if not normalized:
        return default

    # Deduplicate while preserving order for deterministic snapshots.
    deduped: list[str] = []
    seen = set[str]()
    for item in normalized:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


_DEFAULT_REDACTION_FIELDS = [
    "authorization",
    "api_key",
    "apikey",
    "password",
    "access_token",
    "refresh_token",
    "secret",
    "private_key",
]


@dataclass
class Config:
    """SDK configuration with sensible defaults."""

    api_key: str | None = field(default_factory=lambda: os.environ.get("VIZPATH_API_KEY"))
    base_url: str = field(
        default_factory=lambda: os.environ.get("VIZPATH_API_URL", "http://localhost:8000/api/v1")
    )
    project_id: str | None = field(default_factory=lambda: os.environ.get("VIZPATH_PROJECT_ID"))
    buffer_size: int = 50
    max_buffer_items: int = field(
        default_factory=lambda: int(os.environ.get("VIZPATH_MAX_BUFFER_ITEMS", "10000"))
    )
    flush_interval: float = 5.0
    drop_oldest_when_full: bool = field(
        default_factory=lambda: os.environ.get("VIZPATH_DROP_OLDEST_WHEN_BUFFER_FULL", "false").lower()
        == "true"
    )
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
    redaction_enabled: bool = field(
        default_factory=lambda: _parse_bool_env(os.environ.get("VIZPATH_REDACTION_ENABLED"), True)
    )
    redaction_fields: list[str] = field(
        default_factory=lambda: _parse_csv_list(
            os.environ.get(
                "VIZPATH_REDACTION_FIELDS",
                ",".join(_DEFAULT_REDACTION_FIELDS),
            ),
            _DEFAULT_REDACTION_FIELDS,
        )
    )
    redaction_replacement: str = field(
        default_factory=lambda: os.environ.get("VIZPATH_REDACTION_REPLACEMENT", "[REDACTED]")
    )
    max_payload_bytes: int = field(
        default_factory=lambda: int(os.environ.get("VIZPATH_MAX_PAYLOAD_BYTES", "1048576"))
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
        if self.max_buffer_items < 1:
            raise ValueError("max_buffer_items must be at least 1")
        if self.max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        if self.max_payload_bytes < 1:
            raise ValueError("max_payload_bytes must be at least 1")
        if not self.redaction_replacement:
            raise ValueError("redaction_replacement cannot be empty")
        if self.redaction_fields:
            # Keep normalized for predictable matching behavior.
            self.redaction_fields = _parse_csv_list(",".join(self.redaction_fields), self.redaction_fields)
