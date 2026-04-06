"""Tests for Alembic migration revision validation behavior."""

import pytest

import app.database as database_module
from app.config import settings


def test_validate_migration_head_warns_in_non_strict_mode(monkeypatch):
    """Stale revisions should warn (not fail) outside strict enforcement."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "enforce_migration_head", False)
    monkeypatch.setattr(
        database_module,
        "get_migration_revisions",
        lambda: ("old-revision", "head-revision"),
    )

    database_module.validate_migration_head()


def test_validate_migration_head_raises_in_strict_mode(monkeypatch):
    """Stale revisions should fail fast when enforcement is enabled."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "enforce_migration_head", True)
    monkeypatch.setattr(
        database_module,
        "get_migration_revisions",
        lambda: ("old-revision", "head-revision"),
    )

    with pytest.raises(RuntimeError, match="Database schema is not at Alembic head"):
        database_module.validate_migration_head()


def test_validate_migration_head_raises_when_state_unavailable_in_strict_mode(monkeypatch):
    """Strict mode should fail if revision validation cannot be performed."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "enforce_migration_head", True)

    def _raise():
        raise RuntimeError("no alembic")

    monkeypatch.setattr(database_module, "get_migration_revisions", _raise)

    with pytest.raises(RuntimeError, match="Unable to validate Alembic revision state"):
        database_module.validate_migration_head()
