"""Main daemon orchestration."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from granola_bridge.config import AppConfig
from granola_bridge.core.notifier import Notifier
from granola_bridge.core.scheduler import RetryScheduler, add_to_retry_queue
from granola_bridge.core.watcher import GranolaWatcher
from granola_bridge.models import (
    ActionItem,
    ActionItemStatus,
    Meeting,
    MeetingSource,
    OperationType,
    RetryQueue,
)
from granola_bridge.models.database import get_session_factory
from granola_bridge.services.action_extractor import ActionExtractor
from granola_bridge.services.granola_parser import GranolaParser
from granola_bridge.services.llm_client import LLMClient, LLMError
from granola_bridge.services.trello_client import TrelloClient, TrelloError

logger = logging.getLogger(__name__)


class Daemon:
    """Main daemon that orchestrates file watching and processing."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._process_queue: asyncio.Queue = asyncio.Queue()

        # Initialize components
        self.parser = GranolaParser(config.get_granola_cache_path())
        self.llm_client = LLMClient(config)
        self.trello_client = TrelloClient(config)
        self.extractor = ActionExtractor(self.llm_client)
        self.notifier = Notifier(config)
        self.scheduler = RetryScheduler(config)

        # Set up watcher
        self.watcher = GranolaWatcher(
            config.get_granola_cache_path(),
            self._on_file_change,
            config.granola.watch_debounce_ms,
        )

        # Register retry handlers
        self.scheduler.register_handler(
            OperationType.TRELLO_CREATE_CARD,
            self._retry_trello_card,
        )

    async def run(self) -> None:
        """Run the daemon."""
        self._running = True
        self._loop = asyncio.get_event_loop()

        logger.info("Daemon starting...")

        # Start web server FIRST so dashboard is available immediately
        web_task = asyncio.create_task(self._run_web_server())
        logger.info(f"Web dashboard starting at http://{self.config.web.host}:{self.config.web.port}")

        # Give web server a moment to start
        await asyncio.sleep(0.5)

        # Start other components
        self.watcher.start(self._loop)
        self.scheduler.start()
        self.notifier.start_daily_scheduler()

        # Process any existing unprocessed meetings (runs in background)
        asyncio.create_task(self._process_existing_meetings())

        # Main processing loop
        try:
            while self._running:
                try:
                    # Wait for file change signal
                    await asyncio.wait_for(
                        self._process_queue.get(),
                        timeout=5.0,
                    )
                    await self._process_changes()
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Processing error: {e}")

        finally:
            web_task.cancel()
            self.stop()

    async def _run_web_server(self) -> None:
        """Run the web dashboard server."""
        import uvicorn
        from granola_bridge.web.app import create_app

        app = create_app()
        config = uvicorn.Config(
            app,
            host=self.config.web.host,
            port=self.config.web.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        await server.serve()

    def _on_file_change(self) -> None:
        """Called when the Granola cache file changes."""
        if self._loop:
            self._loop.call_soon_threadsafe(
                lambda: self._process_queue.put_nowait(True)
            )

    async def _process_existing_meetings(self) -> None:
        """Process any meetings that exist but haven't been processed."""
        SessionLocal = get_session_factory()
        session = SessionLocal()

        try:
            # Get known IDs from database
            known_ids = {
                m.granola_id
                for m in session.query(Meeting.granola_id).filter(
                    Meeting.granola_id.isnot(None)
                )
            }

            # Get new meetings from Granola
            new_meetings = self.parser.get_new_meetings(known_ids)

            for meeting_data in new_meetings:
                await self._process_meeting(session, meeting_data)

        except Exception as e:
            logger.error(f"Error processing existing meetings: {e}")
            session.rollback()
        finally:
            session.close()

    async def _process_changes(self) -> None:
        """Process new meetings from Granola."""
        SessionLocal = get_session_factory()
        session = SessionLocal()

        try:
            # Get known IDs
            known_ids = {
                m.granola_id
                for m in session.query(Meeting.granola_id).filter(
                    Meeting.granola_id.isnot(None)
                )
            }

            # Get new meetings
            new_meetings = self.parser.get_new_meetings(known_ids)

            for meeting_data in new_meetings:
                await self._process_meeting(session, meeting_data)

        except Exception as e:
            logger.error(f"Error processing changes: {e}")
            session.rollback()
        finally:
            session.close()

    async def _process_meeting(self, session: Session, meeting_data) -> None:
        """Process a single meeting: store, extract actions, create cards."""
        from granola_bridge.services.granola_parser import GranolaMeeting

        logger.info(f"Processing meeting: {meeting_data.title}")

        # Create meeting record
        meeting = Meeting(
            granola_id=meeting_data.granola_id,
            title=meeting_data.title,
            transcript=meeting_data.transcript,
            meeting_date=meeting_data.meeting_date,
            source=MeetingSource.GRANOLA,
        )
        session.add(meeting)
        session.commit()

        # Extract action items
        try:
            extracted = await self.extractor.extract(
                meeting_data.title,
                meeting_data.transcript,
            )
        except LLMError as e:
            logger.error(f"LLM extraction failed: {e}")
            await self.notifier.send_alert(
                "LLM Extraction Failed",
                f"Meeting: {meeting_data.title}\nError: {e}",
                error=True,
            )
            return

        logger.info(f"Extracted {len(extracted)} action items")

        # Create action items and Trello cards
        for item in extracted:
            action_item = ActionItem(
                meeting_id=meeting.id,
                title=item.title,
                description=item.description,
                context=item.context,
                assignee=item.assignee,
                status=ActionItemStatus.PENDING,
            )
            session.add(action_item)
            session.commit()

            # Create Trello card
            await self._create_trello_card(session, action_item, meeting)

        # Mark meeting as processed
        meeting.processed_at = datetime.utcnow()
        session.commit()

        logger.info(f"Meeting processed: {meeting.title}")

    async def _create_trello_card(
        self,
        session: Session,
        action_item: ActionItem,
        meeting: Meeting,
    ) -> None:
        """Create a Trello card for an action item."""
        description = self._format_card_description(action_item, meeting)

        try:
            card = await self.trello_client.create_card(
                name=action_item.title,
                desc=description,
            )

            action_item.trello_card_id = card["id"]
            action_item.trello_card_url = card.get("shortUrl") or card.get("url")
            action_item.status = ActionItemStatus.SENT
            session.commit()

            logger.info(f"Created Trello card: {action_item.trello_card_url}")

        except TrelloError as e:
            logger.error(f"Failed to create Trello card: {e}")
            action_item.status = ActionItemStatus.FAILED
            action_item.error_message = str(e)
            action_item.retry_count += 1
            session.commit()

            # Add to retry queue
            add_to_retry_queue(
                session,
                OperationType.TRELLO_CREATE_CARD,
                {
                    "action_item_id": action_item.id,
                    "meeting_id": meeting.id,
                },
                max_attempts=self.config.retry.max_attempts,
            )

    def _format_card_description(
        self,
        action_item: ActionItem,
        meeting: Meeting,
    ) -> str:
        """Format the Trello card description."""
        parts = []

        if action_item.context:
            parts.append(f"**Context:** {action_item.context}")

        if action_item.description:
            parts.append(f"\n{action_item.description}")

        if action_item.assignee:
            parts.append(f"\n**Assignee:** {action_item.assignee}")

        parts.append(f"\n---\n*From meeting: {meeting.title}*")

        if meeting.meeting_date:
            parts.append(f"\n*Date: {meeting.meeting_date.strftime('%Y-%m-%d')}*")

        return "\n".join(parts)

    async def _retry_trello_card(self, payload: dict) -> bool:
        """Retry handler for failed Trello card creation."""
        SessionLocal = get_session_factory()
        session = SessionLocal()

        try:
            action_item = session.get(ActionItem, payload["action_item_id"])
            meeting = session.get(Meeting, payload["meeting_id"])

            if not action_item or not meeting:
                logger.error("Action item or meeting not found for retry")
                return False

            description = self._format_card_description(action_item, meeting)
            card = await self.trello_client.create_card(
                name=action_item.title,
                desc=description,
            )

            action_item.trello_card_id = card["id"]
            action_item.trello_card_url = card.get("shortUrl") or card.get("url")
            action_item.status = ActionItemStatus.SENT
            action_item.error_message = None
            session.commit()

            return True

        except TrelloError as e:
            logger.error(f"Retry failed: {e}")
            return False
        finally:
            session.close()

    def stop(self) -> None:
        """Stop the daemon."""
        logger.info("Stopping daemon...")
        self._running = False
        self.watcher.stop()
        self.scheduler.stop()
        self.notifier.stop()
