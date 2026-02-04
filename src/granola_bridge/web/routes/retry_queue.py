"""Retry queue management routes."""

from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from granola_bridge.models import RetryQueue, RetryStatus
from granola_bridge.models.database import get_session_factory
from granola_bridge.web.templates_helper import get_templates

router = APIRouter(prefix="/retry-queue")


@router.get("", response_class=HTMLResponse)
async def list_retry_queue(request: Request):
    """View retry queue items."""
    templates = get_templates()
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        # Get pending items
        pending = (
            session.query(RetryQueue)
            .filter(RetryQueue.status == RetryStatus.PENDING)
            .order_by(RetryQueue.next_retry_at)
            .all()
        )

        # Get in-progress items
        in_progress = (
            session.query(RetryQueue)
            .filter(RetryQueue.status == RetryStatus.IN_PROGRESS)
            .all()
        )

        # Get recent failures
        failed = (
            session.query(RetryQueue)
            .filter(RetryQueue.status == RetryStatus.FAILED_PERMANENT)
            .order_by(RetryQueue.updated_at.desc())
            .limit(20)
            .all()
        )

        # Get recent successes
        succeeded = (
            session.query(RetryQueue)
            .filter(RetryQueue.status == RetryStatus.SUCCEEDED)
            .order_by(RetryQueue.updated_at.desc())
            .limit(10)
            .all()
        )

        return templates.TemplateResponse(
            "retry_queue.html",
            {
                "request": request,
                "pending": pending,
                "in_progress": in_progress,
                "failed": failed,
                "succeeded": succeeded,
            },
        )
    finally:
        session.close()


@router.post("/{item_id}/retry")
async def trigger_retry(item_id: str):
    """Manually trigger a retry for a failed item."""
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        item = session.get(RetryQueue, item_id)

        if not item:
            return RedirectResponse(url="/retry-queue", status_code=303)

        # Reset item for retry
        item.status = RetryStatus.PENDING
        item.next_retry_at = datetime.utcnow()
        item.attempt_count = max(0, item.attempt_count - 1)  # Give one more attempt
        session.commit()

        return RedirectResponse(url="/retry-queue", status_code=303)

    finally:
        session.close()


@router.post("/{item_id}/delete")
async def delete_item(item_id: str):
    """Delete a retry queue item."""
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        item = session.get(RetryQueue, item_id)

        if item:
            session.delete(item)
            session.commit()

        return RedirectResponse(url="/retry-queue", status_code=303)

    finally:
        session.close()
