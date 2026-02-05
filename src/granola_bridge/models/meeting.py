"""Meeting model for storing transcript data."""

import hashlib
import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from granola_bridge.models.database import Base

if TYPE_CHECKING:
    from granola_bridge.models.action_item import ActionItem


class MeetingSource(str, enum.Enum):
    GRANOLA = "granola"
    MANUAL_UPLOAD = "manual_upload"


class MeetingStatus(str, enum.Enum):
    PENDING = "pending"        # Waiting for transcript to stabilize
    READY = "ready"            # Ready for LLM extraction
    PROCESSING = "processing"  # Currently being processed
    PROCESSED = "processed"    # Successfully processed
    FAILED = "failed"          # Processing failed


def compute_transcript_hash(transcript: str) -> str:
    """Compute SHA256 hash of transcript for change detection."""
    return hashlib.sha256(transcript.encode("utf-8")).hexdigest()


class Meeting(Base):
    """Stores meeting transcripts and metadata."""

    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    granola_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source: Mapped[MeetingSource] = mapped_column(
        SQLEnum(MeetingSource), default=MeetingSource.GRANOLA
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Status tracking for deferred processing
    status: Mapped[MeetingStatus] = mapped_column(
        SQLEnum(MeetingStatus), default=MeetingStatus.PENDING
    )
    transcript_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    stable_since: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationship to action items
    action_items: Mapped[List["ActionItem"]] = relationship(
        "ActionItem", back_populates="meeting", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Meeting(id={self.id}, title={self.title[:50]}...)>"
