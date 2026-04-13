"""Pytest fixtures for server tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.rate_limit as rate_limit
from app.config import settings
from app.database import Base, get_db
from app.intelligence.budget import _reset_intelligence_budget_state_for_tests
from app.main import app
from app.routes.intelligence import _clear_intelligence_summary_cache
from app.secret_crypto import _get_fernet


@pytest.fixture(scope="function")
def test_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestingSessionLocal()

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(test_db):
    """Create a test client with database override."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _disable_rate_limiting_for_test_suite(monkeypatch):
    """Keep most tests deterministic by disabling rate limits by default."""
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    # Most existing tests exercise business logic and use unauthenticated requests.
    # Keep that behavior in tests while production defaults stay locked down.
    monkeypatch.setattr(settings, "allow_unauthenticated_dev_fallback", True)
    monkeypatch.setattr(
        settings,
        "alert_secret_encryption_key",
        "HYtktxNlD7VQViyVVC29J3m3jBPr04i5pijVjhz9Qss=",
    )
    monkeypatch.setattr(settings, "alert_notification_async_enabled", False)
    _get_fernet.cache_clear()
    monkeypatch.setattr(
        rate_limit,
        "_limiter",
        rate_limit.RateLimiter(rate_limit.InMemoryRateLimitBackend()),
    )


@pytest.fixture(autouse=True)
def _clear_intelligence_summary_cache_between_tests():
    """Prevent cached intelligence summaries from leaking across tests."""
    _clear_intelligence_summary_cache()
    _reset_intelligence_budget_state_for_tests()
