from __future__ import annotations

import tempfile
from pathlib import Path
from subprocess import run

from scripts.check_env import parse_env_file, validate_config
from scripts.export_env import shell_exports


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
            "POSTGRES_HOST_PORT": "abc",
            "REDIS_HOST_PORT": "70000",
            "RATE_LIMIT_RPM": "-1",
            "TRACE_RETENTION_SWEEP_INTERVAL_SECONDS": "-1",
            "TRACE_RETENTION_DAYS": "0",
            "RATE_LIMIT_BURST_MULTIPLIER": "0",
            "REDIS_URL": "http://localhost:6379",
            "NVIDIA_API_KEY": "your_nvidia_api_key_here",
        },
    )

    assert "PORT must be between 1 and 65535" in errors
    assert "POSTGRES_HOST_PORT must be an integer" in errors
    assert "REDIS_HOST_PORT must be between 1 and 65535" in errors
    assert "RATE_LIMIT_RPM must be 0 or greater" in errors
    assert "TRACE_RETENTION_SWEEP_INTERVAL_SECONDS must be at least 1" in errors
    assert "TRACE_RETENTION_DAYS must be at least 1" in errors
    assert "RATE_LIMIT_BURST_MULTIPLIER must be greater than 0" in errors
    assert (
        "REDIS_URL should use redis:// or rediss:// when using Redis" in warnings
    )
    assert (
        "NVIDIA_API_KEY still uses placeholder text from .env.example" in warnings
    )


def test_shell_exports_quotes_values_and_preserves_existing(monkeypatch):
    monkeypatch.setenv("PORT", "9000")

    exports = shell_exports(
        {
            "PORT": "8000",
            "NVIDIA_API_KEY": "nvapi-test value",
            "EMPTY": "",
        },
        preserve_existing=True,
    )

    assert "export PORT=8000" not in exports
    assert "export EMPTY=''" in exports
    assert "export NVIDIA_API_KEY='nvapi-test value'" in exports


def test_check_env_main_uses_shell_env_over_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://vizpath:vizpath@localhost:5433/vizpath",
                "POSTGRES_HOST_PORT=5433",
                "REDIS_HOST_PORT=6380",
                "PORT=70000",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PORT", "8000")

    result = run(
        ["python", "scripts/check_env.py", "--env", str(env_file)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "PORT must be between 1 and 65535" not in result.stdout
