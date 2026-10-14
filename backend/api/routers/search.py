import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api import deps
from backend.exceptions import AppException
from backend.models.search import SearchResult
from backend.services.search import SearchService

logger = logging.getLogger(__name__)

search_router = APIRouter(prefix="/api/search", tags=["search"])


@search_router.get("", response_model=list[SearchResult])
async def search_torrents(
    q: str = Query(..., min_length=1),
    quality: str | None = Query(
        None, description="Filter by quality (e.g. 2160p, 1080p, 720p)"
    ),
    min_seeders: int | None = Query(
        None, ge=0, description="Minimum number of seeders"
    ),
    hdr: str | None = Query(None, pattern="^(all|hdr|dolby_vision)$"),
    voiceover: str | None = Query(None, max_length=100),
    language: str | None = Query(None, pattern="^(all|russian|english|original)$"),
    min_size: int | None = Query(None, ge=0),
    max_size: int | None = Query(None, ge=0),
    source: str | None = Query(None, max_length=100),
    service: Annotated[SearchService, Depends(deps.get_search_service)] = None,
) -> list[SearchResult]:
    if min_size is not None and max_size is not None and min_size > max_size:
        raise HTTPException(
            status_code=422,
            detail="min_size cannot be greater than max_size",
        )

    try:
        return await service.search_torrents(
            q,
            quality=quality,
            min_seeders=min_seeders,
            hdr=hdr,
            voiceover=voiceover,
            language=language,
            min_size=min_size,
            max_size=max_size,
            source=source,
        )
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
