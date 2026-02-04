"""Meeting model for storing transcript data."""

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

    # Relationship to action items
    action_items: Mapped[List["ActionItem"]] = relationship(
        "ActionItem", back_populates="meeting", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Meeting(id={self.id}, title={self.title[:50]}...)>"
