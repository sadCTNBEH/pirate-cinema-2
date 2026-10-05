import logging

from backend.api import deps

"""FastAPI routers: library, player, settings, catalog."""

import httpx
from fastapi import APIRouter, HTTPException, Query

from backend.infrastructure.torrserver import client as torrserver

logger = logging.getLogger(__name__)

# ─── Router: Search ───

search_router = APIRouter(prefix="/api/search", tags=["search"])

@search_router.get("")
async def search(q: str = Query(..., min_length=1)):
    try:
        return await torrserver.search_all(deps._torrserver_url, q)
    except httpx.HTTPError as e:
        logger.exception("TorrServer search failed for query")
        raise HTTPException(status_code=502, detail=f"TorrServer search error: {e}") from e


