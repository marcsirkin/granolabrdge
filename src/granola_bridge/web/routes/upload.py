"""Manual transcript upload routes."""

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from granola_bridge.config import get_config
from granola_bridge.models import Meeting, MeetingSource, MeetingStatus, ActionItem, ActionItemStatus
from granola_bridge.models.database import get_session_factory
from granola_bridge.services.action_extractor import ActionExtractor
from granola_bridge.services.llm_client import LLMClient, LLMError
from granola_bridge.services.trello_client import TrelloClient, TrelloError
from granola_bridge.services.trello_helpers import format_card_description
from granola_bridge.web.templates_helper import get_templates

router = APIRouter(prefix="/upload")


@router.get("", response_class=HTMLResponse)
async def upload_form(request: Request):
    """Show the manual upload form."""
    templates = get_templates()
    return templates.TemplateResponse(
        "upload.html",
        {"request": request},
    )


@router.post("", response_class=HTMLResponse)
async def process_upload(
    request: Request,
    title: str = Form(...),
    transcript: str = Form(default=""),
    file: Optional[UploadFile] = File(default=None),
):
    """Process an uploaded transcript."""
    templates = get_templates()
    config = get_config()
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        # Get transcript from form or file
        if file and file.filename:
            content = await file.read()
            transcript_text = content.decode("utf-8")
        else:
            transcript_text = transcript

        if not transcript_text.strip():
            return templates.TemplateResponse(
                "upload.html",
                {
                    "request": request,
                    "error": "Please provide a transcript (paste text or upload file)",
                },
            )

        # Create meeting record
        meeting = Meeting(
            granola_id=None,  # Manual upload has no granola_id
            title=title,
            transcript=transcript_text,
            meeting_date=datetime.utcnow(),
            source=MeetingSource.MANUAL_UPLOAD,
        )
        session.add(meeting)
        session.commit()

        # Extract action items
        llm_client = LLMClient(config)
        extractor = ActionExtractor(llm_client)
        trello_client = TrelloClient(config)

        try:
            extracted = await extractor.extract(title, transcript_text)
        except LLMError as e:
            # Meeting is saved but LLM failed - redirect to detail page with pending status
            # processed_at remains NULL, indicating extraction is pending
            return RedirectResponse(
                url=f"/meetings/{meeting.id}?llm_pending=1",
                status_code=303,
            )

        # Create action items
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

            # Only push to Trello immediately if auto_push is enabled
            if config.trello.auto_push:
                try:
                    description = format_card_description(action_item, meeting)
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

                session.commit()

        if config.trello.auto_push:
            meeting.status = MeetingStatus.PROCESSED
            meeting.processed_at = datetime.utcnow()
        else:
            meeting.status = MeetingStatus.REVIEW
        session.commit()

        # Redirect to meeting detail page
        return RedirectResponse(
            url=f"/meetings/{meeting.id}",
            status_code=303,
        )

    except Exception as e:
        session.rollback()
        return templates.TemplateResponse(
            "upload.html",
            {
                "request": request,
                "error": f"Error processing transcript: {e}",
            },
        )
    finally:
        session.close()


