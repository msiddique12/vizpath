"""Rate limit behavior tests for public and authenticated flows."""

from datetime import datetime, timezone

import app.rate_limit as rl
from app.auth import hash_api_key
from app.models import Project
from app.rate_limit import InMemoryRateLimitBackend, RateLimiter


def _reset_rate_limiter(monkeypatch):
    monkeypatch.setattr(rl, "_limiter", RateLimiter(InMemoryRateLimitBackend()))


def test_ip_throttle_works(client, monkeypatch):
    monkeypatch.setattr(rl.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rl.settings, "rate_limit_ip_rpm", 1)
    monkeypatch.setattr(rl.settings, "rate_limit_user_rpm", 100)
    monkeypatch.setattr(rl.settings, "rate_limit_burst_multiplier", 1.0)
    _reset_rate_limiter(monkeypatch)

    first = client.get("/health")
    second = client.get("/health")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["scope"] == "ip"


def test_project_throttle_works(client, test_db, monkeypatch):
    monkeypatch.setattr(rl.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rl.settings, "rate_limit_ip_rpm", 100)
    monkeypatch.setattr(rl.settings, "rate_limit_user_rpm", 1)
    monkeypatch.setattr(rl.settings, "rate_limit_burst_multiplier", 1.0)
    _reset_rate_limiter(monkeypatch)

    api_key = "vp_rate_limit_project_key"
    project = Project(name="rl-project", api_key_hash=hash_api_key(api_key))
    test_db.add(project)
    test_db.commit()

    payload = [
        {
            "span_id": "span-rl-1",
            "trace_id": "trace-rl-1",
            "name": "test",
            "start_time": datetime.now(timezone.utc).isoformat(),
        }
    ]
    headers = {"X-API-Key": api_key}

    first = client.post("/api/v1/traces/spans/batch", json=payload, headers=headers)
    second = client.post("/api/v1/traces/spans/batch", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["scope"] == "project"


def test_429_payload_format_is_stable(client, monkeypatch):
    monkeypatch.setattr(rl.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rl.settings, "rate_limit_ip_rpm", 1)
    monkeypatch.setattr(rl.settings, "rate_limit_user_rpm", 100)
    monkeypatch.setattr(rl.settings, "rate_limit_burst_multiplier", 1.0)
    _reset_rate_limiter(monkeypatch)

    client.get("/health")
    blocked = client.get("/health")

    body = blocked.json()
    assert blocked.status_code == 429
    assert "detail" in body
    assert "retry_after_seconds" in body
    assert "scope" in body
    assert "request_id" in body
    assert "error" in body
    assert body["error"]["code"] == "rate_limited"


def test_non_throttled_requests_still_pass(client, monkeypatch):
    monkeypatch.setattr(rl.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rl.settings, "rate_limit_ip_rpm", 100)
    monkeypatch.setattr(rl.settings, "rate_limit_user_rpm", 100)
    monkeypatch.setattr(rl.settings, "rate_limit_burst_multiplier", 1.0)
    _reset_rate_limiter(monkeypatch)

    first = client.get("/health")
    second = client.get("/health")

    assert first.status_code == 200
    assert second.status_code == 200
