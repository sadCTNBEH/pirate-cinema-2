import asyncio
import logging
import sqlite3

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.infrastructure.catalog import cinemeta as catalog_svc
from backend.services import library, metadata
from backend.services.i18n import t

logger = logging.getLogger(__name__)

library_router = APIRouter(prefix="/api/library", tags=["library"])
_background_tasks: set[asyncio.Task] = set()


@library_router.get("/recent")
async def recent():
    try:
        return await library.get_recent_media()
    except sqlite3.Error as e:
        logger.exception("Failed to load recent media from DB")
        raise HTTPException(
            status_code=500, detail="Database error while fetching recent history"
        ) from e


@library_router.get("/popular")
async def popular_movies():
    try:
        return await catalog_svc.popular()
    except httpx.HTTPError as e:
        logger.exception("Failed to fetch popular movies from catalog")
        raise HTTPException(
            status_code=502, detail=f"Catalog service error: {e}"
        ) from e


@library_router.get("/popular/series")
async def popular_series():
    try:
        return await catalog_svc.popular_series()
    except httpx.HTTPError as e:
        logger.exception("Failed to fetch popular series from catalog")
        raise HTTPException(
            status_code=502, detail=f"Catalog service error: {e}"
        ) from e


@library_router.get("/meta/{imdb_id}")
async def movie_meta(imdb_id: str, type: str = "movie"):
    try:
        meta = await catalog_svc.lookup(imdb_id, type)
    except httpx.HTTPError as e:
        logger.exception("Catalog metadata lookup failed for %s", imdb_id)
        raise HTTPException(
            status_code=502, detail=f"Catalog service error: {e}"
        ) from e

    if not meta:
        raise HTTPException(status_code=404, detail=t("err_not_found"))
    return meta


@library_router.get("/meta/search")
async def movie_meta_search(q: str, type: str = "movie"):
    try:
        candidates = catalog_svc.title_candidates(q) or [q]

        for candidate in candidates:
            results = await catalog_svc.search_metadata(candidate, type)
            if results:
                return results
        return []
    except httpx.HTTPError as e:
        logger.exception("Catalog metadata search failed for query: %s", q)
        raise HTTPException(
            status_code=502, detail=f"Catalog search error: {e}"
        ) from e


@library_router.get("/torrents")
async def list_torrents():
    try:
        return await library.get_torrents_list()
    except httpx.HTTPError as e:
        logger.exception("Failed to read torrents list from TorrServer")
        raise HTTPException(
            status_code=502, detail=f"TorrServer connection error: {e}"
        ) from e


@library_router.get("/torrents/{hash}/files")
async def torrent_files(hash: str, title: str | None = None):
    try:
        if title:
            task = asyncio.create_task(
                metadata.fetch_and_save_metadata(hash, title)
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        return await library.get_torrent_files_structure(hash)
    except httpx.HTTPError as e:
        logger.exception("TorrServer error while fetching torrent files")
        raise HTTPException(
            status_code=502, detail=f"TorrServer search error: {e}"
        ) from e


@library_router.get("/poster/{hash}")
async def get_poster(hash: str):
    try:
        poster_path = library.resolve_poster_path(hash)
        if poster_path.is_file():
            return FileResponse(poster_path)
    except OSError as e:
        logger.error("OS error when reading poster file for %s: %s", hash, e)

    raise HTTPException(status_code=404, detail=t("err_not_found"))


@library_router.delete("/history/{hash}")
async def delete_history(hash: str):
    try:
        await library.clear_history(hash)
        return {"status": "ok"}
    except sqlite3.Error as e:
        logger.exception("Failed to delete history for %s", hash)
        raise HTTPException(
            status_code=500, detail="Database error while deleting history"
        ) from e
