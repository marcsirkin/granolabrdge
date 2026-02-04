"""Dashboard route - main overview page."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from granola_bridge.config import get_config
from granola_bridge.models import Meeting, ActionItem, ActionItemStatus, RetryQueue, RetryStatus
from granola_bridge.models.database import get_session_factory
from granola_bridge.services.action_extractor import ActionExtractor
from granola_bridge.services.llm_client import LLMClient, LLMError
from granola_bridge.services.trello_client import TrelloClient, TrelloError
from granola_bridge.web.templates_helper import get_templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    templates = get_templates()
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        # Get stats
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        week_start = today_start - timedelta(days=7)

        total_meetings = session.query(Meeting).count()
        meetings_today = (
            session.query(Meeting).filter(Meeting.created_at >= today_start).count()
        )
        meetings_week = (
            session.query(Meeting).filter(Meeting.created_at >= week_start).count()
        )

        total_actions = session.query(ActionItem).count()
        actions_sent = (
            session.query(ActionItem)
            .filter(ActionItem.status == ActionItemStatus.SENT)
            .count()
        )
        actions_pending = (
            session.query(ActionItem)
            .filter(ActionItem.status == ActionItemStatus.PENDING)
            .count()
        )
        actions_failed = (
            session.query(ActionItem)
            .filter(ActionItem.status == ActionItemStatus.FAILED)
            .count()
        )

        retry_pending = (
            session.query(RetryQueue)
            .filter(RetryQueue.status == RetryStatus.PENDING)
            .count()
        )

        # Unprocessed meetings (LLM was unavailable)
        unprocessed_count = (
            session.query(Meeting)
            .filter(Meeting.processed_at.is_(None))
            .count()
        )

        # Recent meetings
        recent_meetings = (
            session.query(Meeting)
            .order_by(Meeting.created_at.desc())
            .limit(10)
            .all()
        )

        # Failed actions needing attention
        failed_actions = (
            session.query(ActionItem)
            .filter(ActionItem.status == ActionItemStatus.FAILED)
            .order_by(ActionItem.created_at.desc())
            .limit(5)
            .all()
        )

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "stats": {
                    "total_meetings": total_meetings,
                    "meetings_today": meetings_today,
                    "meetings_week": meetings_week,
                    "total_actions": total_actions,
                    "actions_sent": actions_sent,
                    "actions_pending": actions_pending,
                    "actions_failed": actions_failed,
                    "retry_pending": retry_pending,
                    "unprocessed_count": unprocessed_count,
                },
                "recent_meetings": recent_meetings,
                "failed_actions": failed_actions,
            },
        )
    finally:
        session.close()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@router.post("/process-unprocessed")
async def process_unprocessed(request: Request):
    """Process meetings that haven't been extracted yet (LLM was unavailable)."""
    config = get_config()
    SessionLocal = get_session_factory()
    session = SessionLocal()

    processed_count = 0
    failed_count = 0

    try:
        # Get unprocessed meetings
        unprocessed = (
            session.query(Meeting)
            .filter(Meeting.processed_at.is_(None))
            .all()
        )

        if not unprocessed:
            return RedirectResponse(url="/", status_code=303)

        # Initialize services
        llm_client = LLMClient(config)
        extractor = ActionExtractor(llm_client)
        trello_client = TrelloClient(config)

        for meeting in unprocessed:
            try:
                logger.info(f"Processing unprocessed meeting: {meeting.title}")

                # Extract action items
                extracted = await extractor.extract(meeting.title, meeting.transcript)

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
                    try:
                        description = _format_card_description(action_item, meeting)
                        card = await trello_client.create_card(
                            name=action_item.title,
                            desc=description,
                        )
                        action_item.trello_card_id = card["id"]
                        action_item.trello_card_url = card.get("shortUrl") or card.get("url")
                        action_item.status = ActionItemStatus.SENT
                    except TrelloError as e:
                        action_item.status = ActionItemStatus.FAILED
                        action_item.error_message = str(e)
                        logger.error(f"Failed to create Trello card: {e}")

                    session.commit()

                # Mark meeting as processed
                meeting.processed_at = datetime.utcnow()
                session.commit()
                processed_count += 1
                logger.info(f"Meeting processed: {meeting.title}")

            except LLMError as e:
                logger.error(f"LLM extraction failed for {meeting.title}: {e}")
                failed_count += 1
                continue

    except Exception as e:
        logger.error(f"Error processing unprocessed meetings: {e}")
        session.rollback()
    finally:
        session.close()

    # Redirect back to dashboard
    return RedirectResponse(url="/", status_code=303)


def _format_card_description(action_item: ActionItem, meeting: Meeting) -> str:
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
