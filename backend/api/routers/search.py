import logging
from typing import Annotated, Any

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
    titles: Annotated[
        list[str] | None,
        Query(max_length=5, description="Additional full title/season query variants"),
    ] = None,
    service: Annotated[SearchService, Depends(deps.get_search_service)] = None,
) -> list[SearchResult]:
    if min_size is not None and max_size is not None and min_size > max_size:
        raise HTTPException(
            status_code=422,
            detail="min_size cannot be greater than max_size",
        )

    search_kwargs: dict[str, Any] = {}
    if titles:
        search_kwargs["titles"] = titles
    if quality is not None:
        search_kwargs["quality"] = quality
    if min_seeders is not None:
        search_kwargs["min_seeders"] = min_seeders
    if hdr is not None:
        search_kwargs["hdr"] = hdr
    if voiceover is not None:
        search_kwargs["voiceover"] = voiceover
    if language is not None:
        search_kwargs["language"] = language
    if min_size is not None:
        search_kwargs["min_size"] = min_size
    if max_size is not None:
        search_kwargs["max_size"] = max_size
    if source is not None:
        search_kwargs["source"] = source

    try:
        return await service.search_torrents(q, **search_kwargs)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
