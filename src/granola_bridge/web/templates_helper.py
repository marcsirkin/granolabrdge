"""Template helpers for the web dashboard."""

from pathlib import Path
from fastapi.templating import Jinja2Templates


def get_templates() -> Jinja2Templates:
    """Get Jinja2 templates instance."""
    templates_dir = Path(__file__).parent / "templates"
    return Jinja2Templates(directory=str(templates_dir))
