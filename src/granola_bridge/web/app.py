"""FastAPI application setup."""

from pathlib import Path

from fastapi import FastAPI

from granola_bridge.web.routes import dashboard, meetings, upload, retry_queue


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Granola Bridge",
        description="Monitor Granola meeting transcripts and create Trello cards",
        version="0.1.0",
    )

    # Set up templates
    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)

    # Include routers
    app.include_router(dashboard.router)
    app.include_router(meetings.router)
    app.include_router(upload.router)
    app.include_router(retry_queue.router)

    return app
