"""ActionItem model for tracking extracted action items."""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
import enum

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from granola_bridge.models.database import Base

if TYPE_CHECKING:
    from granola_bridge.models.meeting import Meeting


class ActionItemStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class ActionItem(Base):
    """Stores action items extracted from meetings."""

    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assignee: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    trello_card_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    trello_card_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[ActionItemStatus] = mapped_column(
        SQLEnum(ActionItemStatus), default=ActionItemStatus.PENDING
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationship to meeting
    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="action_items")

    def __repr__(self) -> str:
        return f"<ActionItem(id={self.id}, title={self.title[:50]}..., status={self.status})>"
