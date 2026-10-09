from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from whisp import __version__

REPO_URL = "https://github.com/binhle3920/whisp"

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request) -> Response:
    # Static marketing content only: nothing from the store or settings, so the public
    # page cannot leak mailbox or deployment details.
    return templates.TemplateResponse(
        request, "landing.html", {"repo_url": REPO_URL, "version": __version__}
    )
