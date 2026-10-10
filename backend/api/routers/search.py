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
    service: Annotated[SearchService, Depends(deps.get_search_service)] = None,
) -> list[SearchResult]:
    try:
        return await service.search_torrents(q)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
