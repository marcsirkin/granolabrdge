"""Meeting routes - list and detail views."""

from typing import Optional

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse

from granola_bridge.models import Meeting, ActionItem
from granola_bridge.models.database import get_session_factory
from granola_bridge.web.templates_helper import get_templates

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
