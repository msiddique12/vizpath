from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from urllib.parse import urlparse


PLACEHOLDER_VALUES = {
    "your_nvidia_api_key_here",
    "nvidia_api_key_here",
    "<your-key>",
    "changeme",
    "change_me",
    "placeholder",
}


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if not match:
            continue
        key = match.group(1)
        value = match.group(2)

        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value

    return values


def _is_http_or_file_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme)


def _positive_int_string(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_config(values: dict[str, str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    database_url = values.get("DATABASE_URL")
    if not database_url:
        errors.append("Missing DATABASE_URL")
    elif not _is_http_or_file_url(database_url):
        errors.append("DATABASE_URL must include a URL scheme (for example postgresql://... or sqlite://...)")

    redis_url = values.get("REDIS_URL")
    if redis_url:
        parsed = urlparse(redis_url)
        if not parsed.scheme:
            errors.append("REDIS_URL must include a URL scheme")
        elif parsed.scheme not in {"redis", "rediss", "memory"}:
            warnings.append("REDIS_URL should use redis:// or rediss:// when using Redis")

    port = values.get("PORT")
    if port is not None:
        port_value = _positive_int_string(port)
        if port_value is None:
            errors.append("PORT must be an integer")
        elif not 1 <= port_value <= 65535:
            errors.append("PORT must be between 1 and 65535")

    rate_limit_burst = values.get("RATE_LIMIT_BURST_MULTIPLIER")
    if rate_limit_burst is not None:
        try:
            burst_value = float(rate_limit_burst)
        except ValueError:
            errors.append("RATE_LIMIT_BURST_MULTIPLIER must be a number")
        else:
            if burst_value <= 0:
                errors.append("RATE_LIMIT_BURST_MULTIPLIER must be greater than 0")

    rate_limit_fields = ("RATE_LIMIT_RPM", "RATE_LIMIT_IP_RPM", "RATE_LIMIT_USER_RPM")
    for field in rate_limit_fields:
        value = values.get(field)
        if value is not None:
            parsed = _positive_int_string(value)
            if parsed is None:
                errors.append(f"{field} must be an integer")
            elif parsed < 0:
                errors.append(f"{field} must be 0 or greater")

    trace_retention = values.get("TRACE_RETENTION_DAYS")
    if trace_retention is not None:
        retention = _positive_int_string(trace_retention)
        if retention is None:
            errors.append("TRACE_RETENTION_DAYS must be an integer")
        elif retention < 1:
            errors.append("TRACE_RETENTION_DAYS must be at least 1")

    api_key = values.get("NVIDIA_API_KEY")
    if not api_key:
        warnings.append("NVIDIA_API_KEY is not set. Intelligence endpoints will be limited.")
    elif api_key.lower() in PLACEHOLDER_VALUES:
        warnings.append("NVIDIA_API_KEY still uses placeholder text from .env.example")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate local Vizpath environment files")
    parser.add_argument(
        "--env",
        default=".env",
        help="Path to .env file (default: .env)",
    )
    args = parser.parse_args()

    path = Path(args.env)
    values = {**os.environ}

    if path.exists():
        values.update(parse_env_file(path))
    elif path.name == ".env":
        print("No .env file found. Copy from .env.example and configure values first.")
        return 1

    errors, warnings = validate_config(values)

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f" - {warning}")

    if errors:
        print("Errors:")
        for error in errors:
            print(f" - {error}")
        return 1

    if not warnings:
        print("Environment check passed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
