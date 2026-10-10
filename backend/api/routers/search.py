import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api import deps
from backend.exceptions import AppException
from backend.services.search import SearchService

logger = logging.getLogger(__name__)

search_router = APIRouter(prefix="/api/search", tags=["search"])


@search_router.get("")
async def search_torrents(
    q: str = Query(..., min_length=1),
    service: Annotated[SearchService, Depends(deps.get_search_service)] = None,
) -> list[dict[str, Any]]:
    try:
        return await service.search_torrents(q)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
