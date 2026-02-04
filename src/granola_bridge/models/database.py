"""SQLAlchemy database setup."""

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from granola_bridge.config import get_config


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        config = get_config()
        db_path = config.get_database_path()

        # Ensure directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        _engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
    return _engine


def get_session_factory():
    """Get or create the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


def get_session() -> Generator[Session, None, None]:
    """Get a database session (for use as dependency)."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Initialize database tables."""
    # Import models to register them
    from granola_bridge.models import meeting, action_item, retry_queue  # noqa: F401

    Base.metadata.create_all(bind=get_engine())
