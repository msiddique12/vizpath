import pytest
from pydantic import ValidationError

from app.config import Settings

BASE_SETTINGS = {"DATABASE_URL": "sqlite:///./test.db"}


def test_database_url_requires_scheme():
    with pytest.raises(ValidationError) as exc:
        Settings(DATABASE_URL="memorydb")
    assert "DATABASE_URL must include a URL scheme" in str(exc.value)


def test_database_url_defaults_for_non_production():
    settings = Settings(ENVIRONMENT="development")
    assert settings.database_url == "sqlite:///./vizpath.db"


def test_database_url_required_in_production():
    with pytest.raises(ValidationError) as exc:
        Settings(ENVIRONMENT="production")
    assert "DATABASE_URL is required in production" in str(exc.value)


def test_port_must_be_valid_range():
    with pytest.raises(ValidationError) as exc:
        Settings(**BASE_SETTINGS, PORT=0)
    assert "PORT must be between 1 and 65535" in str(exc.value)


def test_positive_int_fields_reject_negative_values():
    with pytest.raises(ValidationError) as exc:
        Settings(**BASE_SETTINGS, RATE_LIMIT_RPM=-1)
    assert "rate_limit_rpm must be 0 or greater" in str(exc.value)


def test_trace_retention_must_be_positive():
    with pytest.raises(ValidationError) as exc:
        Settings(**BASE_SETTINGS, TRACE_RETENTION_DAYS=0)
    assert "TRACE_RETENTION_DAYS must be at least 1" in str(exc.value)


def test_burst_multiplier_must_be_positive():
    with pytest.raises(ValidationError) as exc:
        Settings(**BASE_SETTINGS, RATE_LIMIT_BURST_MULTIPLIER=0.0)
    assert "RATE_LIMIT_BURST_MULTIPLIER must be greater than 0" in str(exc.value)


def test_redis_url_requires_supported_scheme():
    with pytest.raises(ValidationError) as exc:
        Settings(**BASE_SETTINGS, REDIS_URL="http://localhost:6379")
    assert "REDIS_URL must use redis or rediss scheme" in str(exc.value)


def test_max_request_body_bytes_must_be_non_negative():
    with pytest.raises(ValidationError) as exc:
        Settings(**BASE_SETTINGS, MAX_REQUEST_BODY_BYTES=-1)
    assert "max_request_body_bytes must be 0 or greater" in str(exc.value)


def test_allow_unauthenticated_dev_fallback_defaults_to_false():
    settings = Settings(**BASE_SETTINGS)
    assert settings.allow_unauthenticated_dev_fallback is False


def test_enforce_migration_head_defaults_to_false():
    settings = Settings(**BASE_SETTINGS)
    assert settings.enforce_migration_head is False


def test_alert_notification_async_enabled_defaults_to_true():
    settings = Settings(**BASE_SETTINGS)
    assert settings.alert_notification_async_enabled is True
