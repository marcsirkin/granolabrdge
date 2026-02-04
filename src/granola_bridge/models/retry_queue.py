"""RetryQueue model for managing failed operations."""

import uuid
import json
from datetime import datetime
from typing import Optional, Any
import enum

from sqlalchemy import String, Text, DateTime, Integer, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from granola_bridge.models.database import Base


class OperationType(str, enum.Enum):
    TRELLO_CREATE_CARD = "trello_create_card"
    LLM_EXTRACTION = "llm_extraction"
    NOTIFICATION = "notification"


class RetryStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED_PERMANENT = "failed_permanent"


class RetryQueue(Base):
    """Queue for retrying failed operations with exponential backoff."""

    __tablename__ = "retry_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    operation_type: Mapped[OperationType] = mapped_column(SQLEnum(OperationType), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[RetryStatus] = mapped_column(
        SQLEnum(RetryStatus), default=RetryStatus.PENDING
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def get_payload(self) -> dict[str, Any]:
        """Deserialize payload JSON."""
        return json.loads(self.payload)

    def set_payload(self, data: dict[str, Any]) -> None:
        """Serialize payload to JSON."""
        self.payload = json.dumps(data)

    def __repr__(self) -> str:
        return f"<RetryQueue(id={self.id}, type={self.operation_type}, status={self.status})>"
