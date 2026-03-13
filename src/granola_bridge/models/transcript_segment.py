"""TranscriptSegment model for storing structured transcript data."""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from granola_bridge.models.database import Base

if TYPE_CHECKING:
    from granola_bridge.models.meeting import Meeting


class TranscriptSegment(Base):
    """Stores individual speaker turns from meeting transcripts."""

    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id"), nullable=False
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_timestamp: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    end_timestamp: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    embedding_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="segments")

    def __repr__(self) -> str:
        preview = self.text[:40] if self.text else ""
        return f"<TranscriptSegment(id={self.id}, speaker={self.speaker}, text={preview}...)>"
