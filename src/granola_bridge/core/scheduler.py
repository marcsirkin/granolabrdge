"""Retry queue processor with exponential backoff."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Callable, Awaitable, Optional

from sqlalchemy.orm import Session

from granola_bridge.config import AppConfig
from granola_bridge.models import RetryQueue, RetryStatus, OperationType
from granola_bridge.models.database import get_session_factory

logger = logging.getLogger(__name__)


class RetryScheduler:
    """Process failed operations with exponential backoff."""

    def __init__(
        self,
        config: AppConfig,
        handlers: Optional[dict[OperationType, Callable[[dict], Awaitable[bool]]]] = None,
    ):
        """Initialize the scheduler.

        Args:
            config: Application config
            handlers: Dict mapping operation types to async handler functions.
                     Each handler receives the payload dict and returns True on success.
        """
        self.config = config
        self.handlers = handlers or {}
        self.max_attempts = config.retry.max_attempts
        self.base_delay = config.retry.base_delay_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def register_handler(
        self,
        operation_type: OperationType,
        handler: Callable[[dict], Awaitable[bool]],
    ) -> None:
        """Register a handler for an operation type."""
        self.handlers[operation_type] = handler

    def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Retry scheduler started")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._process_pending()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            await asyncio.sleep(60)  # Check every minute

    async def _process_pending(self) -> None:
        """Process all pending retry items."""
        SessionLocal = get_session_factory()
        session = SessionLocal()

        try:
            now = datetime.utcnow()

            # Get items ready for retry
            items = (
                session.query(RetryQueue)
                .filter(
                    RetryQueue.status == RetryStatus.PENDING,
                    RetryQueue.next_retry_at <= now,
                )
                .all()
            )

            if items:
                logger.info(f"Processing {len(items)} retry items")

            for item in items:
                await self._process_item(session, item)

            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Error processing retry queue: {e}")
        finally:
            session.close()

    async def _process_item(self, session: Session, item: RetryQueue) -> None:
        """Process a single retry item."""
        handler = self.handlers.get(item.operation_type)

        if not handler:
            logger.warning(f"No handler for operation type: {item.operation_type}")
            return

        item.status = RetryStatus.IN_PROGRESS
        item.attempt_count += 1
        session.commit()

        try:
            payload = item.get_payload()
            success = await handler(payload)

            if success:
                item.status = RetryStatus.SUCCEEDED
                logger.info(f"Retry succeeded: {item.id}")
            else:
                self._handle_failure(item, "Handler returned False")

        except Exception as e:
            self._handle_failure(item, str(e))

    def _handle_failure(self, item: RetryQueue, error: str) -> None:
        """Handle a failed retry attempt."""
        item.error_message = error

        if item.attempt_count >= item.max_attempts:
            item.status = RetryStatus.FAILED_PERMANENT
            logger.error(
                f"Retry permanently failed after {item.attempt_count} attempts: "
                f"{item.id} - {error}"
            )
        else:
            item.status = RetryStatus.PENDING
            # Exponential backoff: base_delay * 2^attempt
            delay = self.base_delay * (2 ** (item.attempt_count - 1))
            item.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
            logger.warning(
                f"Retry failed (attempt {item.attempt_count}), "
                f"next retry in {delay}s: {item.id}"
            )

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Retry scheduler stopped")


def add_to_retry_queue(
    session: Session,
    operation_type: OperationType,
    payload: dict,
    max_attempts: int = 5,
) -> RetryQueue:
    """Add an operation to the retry queue.

    Args:
        session: Database session
        operation_type: Type of operation to retry
        payload: Data needed to retry the operation
        max_attempts: Maximum retry attempts

    Returns:
        The created RetryQueue entry
    """
    item = RetryQueue(
        operation_type=operation_type,
        payload=json.dumps(payload),
        max_attempts=max_attempts,
        status=RetryStatus.PENDING,
        next_retry_at=datetime.utcnow(),
    )
    session.add(item)
    session.commit()
    logger.info(f"Added to retry queue: {operation_type.value}")
    return item
