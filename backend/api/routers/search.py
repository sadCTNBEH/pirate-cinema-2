import logging

import httpx
from fastapi import APIRouter, HTTPException, Query

from backend.api import deps
from backend.infrastructure.torrserver import client as torrserver

logger = logging.getLogger(__name__)

search_router = APIRouter(prefix="/api/search", tags=["search"])


@search_router.get("")
async def search_torrents(q: str = Query(..., min_length=1)):
    torrserver_url = deps.get_torrserver_url()
    try:
        return await torrserver.search_all(torrserver_url, q)
    except httpx.HTTPStatusError as e:
        logger.error(
            "TorrServer search returned HTTP status error for query '%s': %s",
            q,
            e,
        )
        raise HTTPException(
            status_code=502,
            detail=f"TorrServer search returned error: {e.response.status_code}",
        ) from e
    except httpx.RequestError as e:
        logger.error(
            "TorrServer connection/network error during search for query '%s': %s",
            q,
            e,
        )
        raise HTTPException(
            status_code=502, detail=f"TorrServer connection error: {e}"
        ) from e
