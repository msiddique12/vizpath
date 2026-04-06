"""Database connection and session management."""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    echo=settings.debug,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def _get_alembic_config() -> AlembicConfig:
    config_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not config_path.exists():
        raise FileNotFoundError(f"Alembic config not found: {config_path}")
    config = AlembicConfig(str(config_path))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def get_migration_revisions() -> tuple[str | None, str | None]:
    """Return (current_db_revision, alembic_head_revision)."""
    alembic_config = _get_alembic_config()
    script = ScriptDirectory.from_config(alembic_config)
    head_revision = script.get_current_head()

    with engine.connect() as connection:
        migration_context = MigrationContext.configure(connection)
        current_revision = migration_context.get_current_revision()

    return current_revision, head_revision


def validate_migration_head() -> None:
    """Warn or fail when DB schema is not at Alembic head revision."""
    strict_enforcement = settings.is_production or settings.enforce_migration_head
    try:
        current_revision, head_revision = get_migration_revisions()
    except Exception as exc:
        message = f"Unable to validate Alembic revision state: {exc}"
        if strict_enforcement:
            raise RuntimeError(message) from exc
        logger.warning(message)
        return

    if head_revision is None:
        return

    if current_revision != head_revision:
        message = (
            "Database schema is not at Alembic head "
            f"(current={current_revision}, head={head_revision}). "
            "Run `cd server && alembic upgrade head`."
        )
        if strict_enforcement:
            raise RuntimeError(message)
        logger.warning(message)
    else:
        logger.info("Database schema revision verified at head (%s)", head_revision)


def check_db_connection() -> bool:
    """Check if database connection is healthy."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False


def init_db() -> None:
    """Initialize database and optionally create tables."""
    logger.info("Connecting to database...")

    try:
        if not check_db_connection():
            raise OperationalError("Database connection check failed", None, None)

        logger.info("Database connection successful")

        if settings.auto_create_tables:
            if settings.is_production:
                logger.warning(
                    "AUTO_CREATE_TABLES is enabled in production - use migrations instead"
                )
            logger.info("Creating database tables...")

            Base.metadata.create_all(bind=engine, checkfirst=True)
            logger.info("Database tables created")
        else:
            logger.info("Skipping table creation - ensure migrations are applied")

        validate_migration_head()

    except OperationalError as e:
        logger.critical(f"Database connection failed: {e}")
        raise
    except Exception as e:
        logger.critical(f"Database initialization error: {e}")
        raise


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions outside FastAPI."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
