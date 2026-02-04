"""Pytest fixtures for Granola Bridge tests."""

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from granola_bridge.config import AppConfig, set_config
from granola_bridge.models.database import Base


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_config(temp_dir):
    """Create a test configuration."""
    config = AppConfig()
    config.database.path = str(temp_dir / "test.db")
    config.granola.cache_path = str(temp_dir / "cache-v3.json")
    set_config(config)
    return config


@pytest.fixture
def db_session(test_config):
    """Create an in-memory database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_transcript():
    """Sample meeting transcript for testing."""
    return """
John: Let's start the weekly standup. Sarah, what's your update?

Sarah: I finished the API integration yesterday. I'll be working on the dashboard this week.

John: Great progress! Can you also schedule a meeting with the design team to review the mockups?

Sarah: Sure, I'll set that up for Tuesday.

Mike: I'm still working on the database migration. Should be done by Thursday.

John: Sounds good. Mike, can you also update the documentation once that's done?

Mike: Will do.

John: Alright, let's wrap up. Remember to submit your timesheets by Friday.
"""


@pytest.fixture
def sample_granola_cache(temp_dir, sample_transcript):
    """Create a sample Granola cache file."""
    import json

    cache_data = {
        "meetings": [
            {
                "id": "meeting-123",
                "title": "Weekly Standup",
                "transcript": sample_transcript,
                "date": "2024-01-15T10:00:00Z",
                "participants": [
                    {"name": "John"},
                    {"name": "Sarah"},
                    {"name": "Mike"},
                ],
            }
        ]
    }

    cache_path = temp_dir / "cache-v3.json"
    cache_path.write_text(json.dumps(cache_data))
    return cache_path
