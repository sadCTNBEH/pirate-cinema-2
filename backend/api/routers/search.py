import logging

import httpx
from fastapi import APIRouter, HTTPException, Query

from backend.api import deps
from backend.infrastructure.torrserver import client as torrserver

logger = logging.getLogger(__name__)

search_router = APIRouter(prefix="/api/search", tags=["search"])


@search_router.get("")
async def search_torrents(q: str = Query(..., min_length=1)):
    try:
        return await torrserver.search_all(deps._torrserver_url, q)
    except httpx.HTTPError as e:
        logger.exception("TorrServer search failed for query: %s", q)
        raise HTTPException(
            status_code=502, detail=f"TorrServer search error: {e}"
        ) from e
