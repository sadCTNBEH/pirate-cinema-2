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
    service: Annotated[SearchService, Depends(deps.get_search_service)] = None,
) -> list[SearchResult]:
    try:
        return await service.search_torrents(
            q, quality=quality, min_seeders=min_seeders
        )
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
