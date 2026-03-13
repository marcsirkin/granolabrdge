"""Search route for semantic search across meeting transcripts."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from granola_bridge.config import get_config
from granola_bridge.services.embedding_service import EmbeddingService
from granola_bridge.models.database import get_session_factory
from granola_bridge.models.meeting import Meeting

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = ""):
    """Semantic search across all meeting transcript segments."""
    results = []
    error = None

    if q.strip():
        config = get_config()
        embedding_service = EmbeddingService(config)

        if not await embedding_service.is_available():
            error = "Embedding service unavailable. Is Ollama running with nomic-embed-text?"
        else:
            try:
                raw_results = await embedding_service.query_async(
                    query_text=q.strip(),
                    n_results=20,
                )

                # Group results by meeting
                meeting_ids = list({r["metadata"]["meeting_id"] for r in raw_results})
                SessionLocal = get_session_factory()
                session = SessionLocal()

                try:
                    meetings_map = {}
                    for m in session.query(Meeting).filter(Meeting.id.in_(meeting_ids)).all():
                        meetings_map[m.id] = m

                    # Build grouped results
                    grouped: dict[str, dict] = {}
                    for r in raw_results:
                        mid = r["metadata"]["meeting_id"]
                        if mid not in grouped:
                            meeting = meetings_map.get(mid)
                            grouped[mid] = {
                                "meeting_id": mid,
                                "meeting_title": meeting.title if meeting else "Unknown",
                                "meeting_date": meeting.meeting_date if meeting else None,
                                "segments": [],
                            }
                        grouped[mid]["segments"].append({
                            "text": r["text"],
                            "speaker": r["metadata"].get("speaker", ""),
                            "source": r["metadata"].get("source", ""),
                            "distance": round(r["distance"], 3),
                        })

                    results = sorted(
                        grouped.values(),
                        key=lambda g: min(s["distance"] for s in g["segments"]),
                    )
                finally:
                    session.close()

            except Exception as e:
                logger.error(f"Search failed: {e}")
                error = f"Search failed: {e}"

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "query": q,
            "results": results,
            "error": error,
        },
    )
