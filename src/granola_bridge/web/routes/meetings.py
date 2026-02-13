"""Meeting routes - list and detail views."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from granola_bridge.config import get_config
from granola_bridge.models import Meeting, ActionItem, ActionItemStatus, MeetingStatus, RetryQueue
from granola_bridge.models.database import get_session_factory
from granola_bridge.services.trello_client import TrelloClient, TrelloError
from granola_bridge.services.trello_helpers import format_card_description
from granola_bridge.web.templates_helper import get_templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings")


@router.get("", response_class=HTMLResponse)
async def list_meetings(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Paginated meeting list."""
    templates = get_templates()
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        # Count total
        total = session.query(Meeting).count()
        total_pages = (total + per_page - 1) // per_page

        # Get page
        meetings = (
            session.query(Meeting)
            .order_by(Meeting.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        # Get action item counts for each meeting
        meeting_data = []
        for meeting in meetings:
            action_count = (
                session.query(ActionItem)
                .filter(ActionItem.meeting_id == meeting.id)
                .count()
            )
            meeting_data.append({
                "meeting": meeting,
                "action_count": action_count,
            })

        return templates.TemplateResponse(
            "meetings.html",
            {
                "request": request,
                "meetings": meeting_data,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
            },
        )
    finally:
        session.close()


@router.get("/{meeting_id}", response_class=HTMLResponse)
async def meeting_detail(
    request: Request,
    meeting_id: str,
    llm_pending: Optional[int] = Query(0),
):
    """Meeting detail page with action items."""
    templates = get_templates()
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        meeting = session.get(Meeting, meeting_id)

        if not meeting:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": "Meeting not found"},
                status_code=404,
            )

        action_items = (
            session.query(ActionItem)
            .filter(ActionItem.meeting_id == meeting_id)
            .order_by(ActionItem.created_at)
            .all()
        )

        return templates.TemplateResponse(
            "meeting_detail.html",
            {
                "request": request,
                "meeting": meeting,
                "action_items": action_items,
                "llm_pending": bool(llm_pending),
            },
        )
    finally:
        session.close()


@router.post("/{meeting_id}/delete")
async def delete_meeting(meeting_id: str):
    """Delete meeting and cascade to action items + retry queue."""
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        meeting = session.get(Meeting, meeting_id)

        if not meeting:
            return RedirectResponse(url="/meetings", status_code=303)

        # Clean up retry queue entries that reference this meeting's action items
        action_item_ids = [
            ai.id for ai in session.query(ActionItem.id)
            .filter(ActionItem.meeting_id == meeting_id)
            .all()
        ]

        if action_item_ids:
            # Delete retry queue entries that contain these action item IDs in payload
            retry_entries = session.query(RetryQueue).all()
            for entry in retry_entries:
                try:
                    payload = entry.get_payload()
                    if payload.get("action_item_id") in action_item_ids:
                        session.delete(entry)
                    elif payload.get("meeting_id") == meeting_id:
                        session.delete(entry)
                except Exception:
                    pass

        # Delete meeting (cascades to action_items via relationship)
        session.delete(meeting)
        session.commit()

        logger.info(f"Deleted meeting: {meeting_id}")

        return RedirectResponse(url="/meetings", status_code=303)

    except Exception as e:
        logger.error(f"Error deleting meeting: {e}")
        session.rollback()
        return RedirectResponse(url="/meetings", status_code=303)
    finally:
        session.close()


@router.post("/{meeting_id}/reprocess")
async def reprocess_meeting(meeting_id: str):
    """Delete existing action items and re-queue for processing."""
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        meeting = session.get(Meeting, meeting_id)

        if not meeting:
            return RedirectResponse(url="/meetings", status_code=303)

        # Get action item IDs before deletion for retry queue cleanup
        action_item_ids = [
            ai.id for ai in session.query(ActionItem.id)
            .filter(ActionItem.meeting_id == meeting_id)
            .all()
        ]

        # Clean up retry queue entries
        if action_item_ids:
            retry_entries = session.query(RetryQueue).all()
            for entry in retry_entries:
                try:
                    payload = entry.get_payload()
                    if payload.get("action_item_id") in action_item_ids:
                        session.delete(entry)
                    elif payload.get("meeting_id") == meeting_id:
                        session.delete(entry)
                except Exception:
                    pass

        # Delete existing action items
        session.query(ActionItem).filter(ActionItem.meeting_id == meeting_id).delete()

        # Reset meeting status to READY for reprocessing
        meeting.status = MeetingStatus.READY
        meeting.processed_at = None

        session.commit()

        logger.info(f"Meeting queued for reprocessing: {meeting_id}")

        return RedirectResponse(url=f"/meetings/{meeting_id}", status_code=303)

    except Exception as e:
        logger.error(f"Error reprocessing meeting: {e}")
        session.rollback()
        return RedirectResponse(url=f"/meetings/{meeting_id}", status_code=303)
    finally:
        session.close()


def _check_review_complete(session, meeting: Meeting) -> None:
    """If no PENDING action items remain, transition meeting to PROCESSED."""
    pending_count = (
        session.query(ActionItem)
        .filter(ActionItem.meeting_id == meeting.id)
        .filter(ActionItem.status == ActionItemStatus.PENDING)
        .count()
    )
    if pending_count == 0:
        meeting.status = MeetingStatus.PROCESSED
        meeting.processed_at = datetime.utcnow()


@router.post("/{meeting_id}/actions/{action_id}/approve", response_class=HTMLResponse)
async def approve_action(meeting_id: str, action_id: str):
    """Approve a single action item — push to Trello and mark SENT."""
    config = get_config()
    SessionLocal = get_session_factory()
    session = SessionLocal()
    templates = get_templates()

    try:
        meeting = session.get(Meeting, meeting_id)
        action_item = session.get(ActionItem, action_id)

        if not meeting or not action_item or action_item.meeting_id != meeting_id:
            return HTMLResponse('<div class="error">Not found</div>', status_code=404)

        if action_item.status != ActionItemStatus.PENDING:
            return HTMLResponse('<div class="error">Already reviewed</div>', status_code=400)

        # Push to Trello
        trello_client = TrelloClient(config)
        description = format_card_description(action_item, meeting)

        try:
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

        _check_review_complete(session, meeting)
        session.commit()

        # Return updated action item HTML fragment for htmx swap
        return templates.TemplateResponse(
            "partials/action_item_row.html",
            {"request": {}, "item": action_item, "meeting": meeting},
        )

    except Exception as e:
        logger.error(f"Error approving action item: {e}")
        session.rollback()
        return HTMLResponse(f'<div class="error">Error: {e}</div>', status_code=500)
    finally:
        session.close()


@router.post("/{meeting_id}/actions/{action_id}/reject", response_class=HTMLResponse)
async def reject_action(meeting_id: str, action_id: str):
    """Reject a single action item — mark SKIPPED."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    templates = get_templates()

    try:
        meeting = session.get(Meeting, meeting_id)
        action_item = session.get(ActionItem, action_id)

        if not meeting or not action_item or action_item.meeting_id != meeting_id:
            return HTMLResponse('<div class="error">Not found</div>', status_code=404)

        if action_item.status != ActionItemStatus.PENDING:
            return HTMLResponse('<div class="error">Already reviewed</div>', status_code=400)

        action_item.status = ActionItemStatus.SKIPPED

        _check_review_complete(session, meeting)
        session.commit()

        return templates.TemplateResponse(
            "partials/action_item_row.html",
            {"request": {}, "item": action_item, "meeting": meeting},
        )

    except Exception as e:
        logger.error(f"Error rejecting action item: {e}")
        session.rollback()
        return HTMLResponse(f'<div class="error">Error: {e}</div>', status_code=500)
    finally:
        session.close()


@router.post("/{meeting_id}/approve-all")
async def approve_all_actions(meeting_id: str):
    """Approve all remaining PENDING action items."""
    config = get_config()
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        meeting = session.get(Meeting, meeting_id)
        if not meeting:
            return RedirectResponse(url="/meetings", status_code=303)

        pending_items = (
            session.query(ActionItem)
            .filter(ActionItem.meeting_id == meeting_id)
            .filter(ActionItem.status == ActionItemStatus.PENDING)
            .all()
        )

        trello_client = TrelloClient(config)

        for action_item in pending_items:
            description = format_card_description(action_item, meeting)
            try:
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

        _check_review_complete(session, meeting)
        session.commit()

        return RedirectResponse(url=f"/meetings/{meeting_id}", status_code=303)

    except Exception as e:
        logger.error(f"Error approving all actions: {e}")
        session.rollback()
        return RedirectResponse(url=f"/meetings/{meeting_id}", status_code=303)
    finally:
        session.close()
