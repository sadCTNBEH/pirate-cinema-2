"""Local page and assets for the mobile web remote."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

REMOTE_DIR = Path(__file__).with_name("remote_assets")
REMOTE_HTML = (REMOTE_DIR / "index.html").read_text(encoding="utf-8")
ASSET_TYPES = {"remote.css": "text/css", "remote.js": "text/javascript"}
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

remote_page_router = APIRouter()


@remote_page_router.get("/remote", response_class=HTMLResponse)
async def get_remote_page() -> HTMLResponse:
    return HTMLResponse(REMOTE_HTML, headers=NO_CACHE)


@remote_page_router.get("/remote/assets/{name}", include_in_schema=False)
async def get_remote_asset(name: str) -> FileResponse:
    media_type = ASSET_TYPES.get(name)
    if media_type is None:
        raise HTTPException(status_code=404)
    return FileResponse(REMOTE_DIR / name, media_type=media_type, headers=NO_CACHE)
