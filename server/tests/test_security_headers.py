"""Security middleware header tests."""

from app.config import settings
from app.security import HSTS_HEADER_VALUE, MINIMAL_CSP, PERMISSIONS_POLICY


def test_security_headers_are_applied_by_default(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Content-Security-Policy"] == MINIMAL_CSP
    assert response.headers["Permissions-Policy"] == PERMISSIONS_POLICY
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_enabled_in_strict_mode(client, monkeypatch):
    original = settings.security_strict_mode
    monkeypatch.setattr(settings, "security_strict_mode", True)

    try:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers["Strict-Transport-Security"] == HSTS_HEADER_VALUE
    finally:
        monkeypatch.setattr(settings, "security_strict_mode", original)
