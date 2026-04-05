"""Unit tests for webhook URL security validation."""

import pytest

from app.webhook_security import validate_webhook_target_url


def test_validate_webhook_target_url_allows_public_https():
    """Public HTTPS URL should be accepted."""
    url = "https://example.com/hooks/alerts"
    assert (
        validate_webhook_target_url(
            url,
            allow_private_targets=False,
            resolve_dns=False,
        )
        == url
    )


def test_validate_webhook_target_url_rejects_localhost():
    """Localhost targets should be blocked by default."""
    with pytest.raises(ValueError):
        validate_webhook_target_url(
            "http://localhost:8080/hook",
            allow_private_targets=False,
            resolve_dns=False,
        )


def test_validate_webhook_target_url_rejects_private_ip():
    """Private RFC1918 addresses should be blocked by default."""
    with pytest.raises(ValueError):
        validate_webhook_target_url(
            "http://10.0.0.5/hook",
            allow_private_targets=False,
            resolve_dns=False,
        )


def test_validate_webhook_target_url_rejects_embedded_credentials():
    """URLs with embedded username/password should be rejected."""
    with pytest.raises(ValueError):
        validate_webhook_target_url(
            "https://user:password@example.com/hook",
            allow_private_targets=False,
            resolve_dns=False,
        )


def test_validate_webhook_target_url_allows_private_when_opted_in():
    """Private targets can be enabled explicitly for controlled environments."""
    url = "http://127.0.0.1:9000/hook"
    assert (
        validate_webhook_target_url(
            url,
            allow_private_targets=True,
            resolve_dns=False,
        )
        == url
    )
