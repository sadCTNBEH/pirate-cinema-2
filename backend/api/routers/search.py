from backend.api.deps import _mpv, _load_settings, _save_settings
import backend.api.deps as deps
"""FastAPI routers: library, player, settings, catalog."""
import json
import logging

import httpx
from fastapi import APIRouter, HTTPException, Query

from backend.core.config import get_data_dir
from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.torrserver import client as torrserver





# ─── Router: Search ───

search_router = APIRouter(prefix="/api/search", tags=["search"])

@search_router.get("")
async def search(q: str = Query(..., min_length=1)):
    try:
        return await torrserver.search_all(deps._torrserver_url, q)
    except httpx.HTTPError as e:
        logger.exception("TorrServer search failed for query")
        raise HTTPException(status_code=502, detail=f"TorrServer search error: {e}") from e


