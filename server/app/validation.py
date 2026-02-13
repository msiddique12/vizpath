"""Validation helpers for request sanitization."""

import re

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


ID_PATTERN = r"^[A-Za-z0-9._:-]+$"
TAG_PATTERN = r"^[A-Za-z0-9 _.-]+$"
STATUS_PATTERN = r"^(success|error|running)$"
SPAN_TYPE_PATTERN = r"^(agent|llm|tool|retrieval|custom)$"


def normalize_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
    allow_empty: bool = False,
) -> str | None:
    """Trim text and reject control characters/invalid empty values."""
    if value is None:
        return None

    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} cannot be empty")

    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds max length ({max_length})")

    if _CONTROL_CHAR_RE.search(normalized):
        raise ValueError(f"{field_name} contains control characters")

    return normalized
