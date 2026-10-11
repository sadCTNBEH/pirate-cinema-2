"""Catalog posters delivery endpoint with path traversal validation and caching."""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from backend.core.settings import get_data_dir

logger = logging.getLogger(__name__)

posters_router = APIRouter(prefix="/api/posters", tags=["posters"])
posters_direct_router = APIRouter(prefix="/posters", tags=["posters"])

IMDB_REGEX = re.compile(r"^tt\d{1,12}$")


def get_catalog_posters_dir() -> Path:
    return (get_data_dir() / "posters" / "catalog").resolve()


@posters_router.get("/catalog/{imdb_id}.jpg")
@posters_direct_router.get("/catalog/{imdb_id}.jpg", include_in_schema=False)
async def get_catalog_poster(imdb_id: str, request: Request):
    """Serve locally cached catalog poster image by IMDb ID with HTTP caching."""
    clean_id = imdb_id.strip()
    if not IMDB_REGEX.match(clean_id):
        raise HTTPException(status_code=404, detail="Invalid IMDb ID")

    catalog_dir = get_catalog_posters_dir()
    file_path = (catalog_dir / f"{clean_id}.jpg").resolve()

    # Path traversal protection
    try:
        file_path.relative_to(catalog_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid poster path")

    if not file_path.is_file():
        legacy_dir = (get_data_dir() / "cache" / "popular").resolve()
        legacy_file = (legacy_dir / f"{clean_id}.jpg").resolve()
        try:
            legacy_file.relative_to(legacy_dir)
            if legacy_file.is_file():
                file_path = legacy_file
            else:
                raise HTTPException(status_code=404, detail="Poster not found")
        except ValueError:
            raise HTTPException(status_code=404, detail="Poster not found")

    stat = file_path.stat()
    etag = f'"{int(stat.st_mtime)}-{stat.st_size}"'

    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": "public, max-age=86400",
            },
        )

    return FileResponse(
        path=str(file_path),
        media_type="image/jpeg",
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=86400",
        },
    )
