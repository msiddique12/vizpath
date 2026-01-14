"""Database connection and session management."""

import logging
from contextlib import contextmanager
from typing import Generator

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
            from app import models

            Base.metadata.create_all(bind=engine, checkfirst=True)
            logger.info("Database tables created")
        else:
            logger.info("Skipping table creation - ensure migrations are applied")

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
