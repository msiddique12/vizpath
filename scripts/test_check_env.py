from __future__ import annotations

import tempfile
from pathlib import Path

from scripts.check_env import parse_env_file, validate_config


def test_parse_env_file_reads_comments_and_quotes():
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tmp:
        tmp.write("PORT=8000\n")
        tmp.write("DATABASE_URL=sqlite:///./test.db\n")
        tmp.write("'UNUSED='\"ignored\"\n")
        tmp.write("NVIDIA_API_KEY=\"your_nvidia_api_key_here\"\n")
        tmp.write("EMPTY=\n")
        tmp.write("# comment\n")
        path = Path(tmp.name)

    values = parse_env_file(path)
    assert values == {
        "PORT": "8000",
        "DATABASE_URL": "sqlite:///./test.db",
        "NVIDIA_API_KEY": "your_nvidia_api_key_here",
        "EMPTY": "",
    }


def test_validate_config_reports_errors_and_warnings():
    errors, warnings = validate_config(
        {
            "DATABASE_URL": "sqlite://tmp.db",
            "PORT": "70000",
            "RATE_LIMIT_RPM": "-1",
            "TRACE_RETENTION_DAYS": "0",
            "RATE_LIMIT_BURST_MULTIPLIER": "0",
            "REDIS_URL": "http://localhost:6379",
            "NVIDIA_API_KEY": "your_nvidia_api_key_here",
        },
    )

    assert "PORT must be between 1 and 65535" in errors
    assert "RATE_LIMIT_RPM must be 0 or greater" in errors
    assert "TRACE_RETENTION_DAYS must be at least 1" in errors
    assert "RATE_LIMIT_BURST_MULTIPLIER must be greater than 0" in errors
    assert (
        "REDIS_URL should use redis:// or rediss:// when using Redis" in warnings
    )
    assert (
        "NVIDIA_API_KEY still uses placeholder text from .env.example" in warnings
    )
