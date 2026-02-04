"""Tests for database models."""

import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from granola_bridge.models.database import Base
from granola_bridge.models.meeting import Meeting, MeetingSource
from granola_bridge.models.action_item import ActionItem, ActionItemStatus
from granola_bridge.models.retry_queue import RetryQueue, RetryStatus, OperationType


@pytest.fixture
def session():
    """Create an in-memory database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


class TestMeetingModel:
    def test_create_meeting(self, session):
        """Test creating a meeting."""
        meeting = Meeting(
            granola_id="test-123",
            title="Test Meeting",
            transcript="Hello, this is a test.",
            meeting_date=datetime(2024, 1, 15, 10, 0),
            source=MeetingSource.GRANOLA,
        )
        session.add(meeting)
        session.commit()

        retrieved = session.query(Meeting).first()
        assert retrieved.granola_id == "test-123"
        assert retrieved.title == "Test Meeting"
        assert retrieved.source == MeetingSource.GRANOLA
        assert retrieved.id is not None

    def test_meeting_without_granola_id(self, session):
        """Test creating a manual upload meeting without granola_id."""
        meeting = Meeting(
            title="Manual Upload",
            transcript="Test content",
            source=MeetingSource.MANUAL_UPLOAD,
        )
        session.add(meeting)
        session.commit()

        retrieved = session.query(Meeting).first()
        assert retrieved.granola_id is None
        assert retrieved.source == MeetingSource.MANUAL_UPLOAD

    def test_granola_id_uniqueness(self, session):
        """Test that granola_id must be unique."""
        meeting1 = Meeting(
            granola_id="unique-id",
            title="Meeting 1",
            transcript="Test",
        )
        session.add(meeting1)
        session.commit()

        meeting2 = Meeting(
            granola_id="unique-id",
            title="Meeting 2",
            transcript="Test",
        )
        session.add(meeting2)

        with pytest.raises(Exception):  # IntegrityError
            session.commit()


class TestActionItemModel:
    def test_create_action_item(self, session):
        """Test creating an action item."""
        meeting = Meeting(title="Test", transcript="Test")
        session.add(meeting)
        session.commit()

        action = ActionItem(
            meeting_id=meeting.id,
            title="Do something",
            description="More details",
            context="Said during the meeting",
            assignee="John",
            status=ActionItemStatus.PENDING,
        )
        session.add(action)
        session.commit()

        retrieved = session.query(ActionItem).first()
        assert retrieved.title == "Do something"
        assert retrieved.status == ActionItemStatus.PENDING
        assert retrieved.meeting_id == meeting.id

    def test_action_item_relationship(self, session):
        """Test meeting -> action items relationship."""
        meeting = Meeting(title="Test", transcript="Test")
        session.add(meeting)
        session.commit()

        action1 = ActionItem(meeting_id=meeting.id, title="Action 1")
        action2 = ActionItem(meeting_id=meeting.id, title="Action 2")
        session.add_all([action1, action2])
        session.commit()

        session.refresh(meeting)
        assert len(meeting.action_items) == 2

    def test_action_item_status_transitions(self, session):
        """Test action item status changes."""
        meeting = Meeting(title="Test", transcript="Test")
        session.add(meeting)
        session.commit()

        action = ActionItem(meeting_id=meeting.id, title="Test")
        session.add(action)
        session.commit()

        assert action.status == ActionItemStatus.PENDING

        action.status = ActionItemStatus.SENT
        action.trello_card_id = "card-123"
        action.trello_card_url = "https://trello.com/c/123"
        session.commit()

        retrieved = session.query(ActionItem).first()
        assert retrieved.status == ActionItemStatus.SENT
        assert retrieved.trello_card_id == "card-123"


class TestRetryQueueModel:
    def test_create_retry_item(self, session):
        """Test creating a retry queue item."""
        item = RetryQueue(
            operation_type=OperationType.TRELLO_CREATE_CARD,
            payload=json.dumps({"action_item_id": "123"}),
            max_attempts=5,
        )
        session.add(item)
        session.commit()

        retrieved = session.query(RetryQueue).first()
        assert retrieved.operation_type == OperationType.TRELLO_CREATE_CARD
        assert retrieved.status == RetryStatus.PENDING
        assert retrieved.attempt_count == 0

    def test_payload_serialization(self, session):
        """Test payload JSON serialization."""
        item = RetryQueue(
            operation_type=OperationType.TRELLO_CREATE_CARD,
            payload="{}",
        )

        payload = {"action_item_id": "123", "meeting_id": "456"}
        item.set_payload(payload)
        session.add(item)
        session.commit()

        retrieved = session.query(RetryQueue).first()
        assert retrieved.get_payload() == payload
