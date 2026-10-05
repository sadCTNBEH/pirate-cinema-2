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


def _handle_bg_task_exception(task: asyncio.Task) -> None:
    """Логирует исключения, возникшие в фоновом asyncio.Task."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Background metadata task failed")


@library_router.get("/recent")
async def recent():
    try:
        return await library.get_recent_media()
    except sqlite3.Error as e:
        logger.error("Failed to load recent media from DB: %s", e)
        raise HTTPException(
            status_code=500, detail="Database error while fetching recent history"
        ) from e


@library_router.get("/popular")
async def popular_movies():
    try:
        return await catalog_svc.popular()
    except httpx.HTTPStatusError as e:
        logger.error("Catalog API returned status error: %s", e)
        raise HTTPException(
            status_code=502, detail=f"Catalog service error: {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        logger.error("Catalog connection error: %s", e)
        raise HTTPException(
            status_code=502, detail=f"Catalog network error: {e}"
        ) from e


@library_router.get("/popular/series")
async def popular_series():
    try:
        return await catalog_svc.popular_series()
    except httpx.HTTPStatusError as e:
        logger.error("Catalog API returned status error for series: %s", e)
        raise HTTPException(
            status_code=502, detail=f"Catalog service error: {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        logger.error("Catalog connection error for series: %s", e)
        raise HTTPException(
            status_code=502, detail=f"Catalog network error: {e}"
        ) from e


@library_router.get("/meta/{imdb_id}")
async def movie_meta(imdb_id: str, type: str = "movie"):
    try:
        meta = await catalog_svc.lookup(imdb_id, type)
    except httpx.HTTPStatusError as e:
        logger.error("Catalog metadata lookup status error for %s: %s", imdb_id, e)
        raise HTTPException(
            status_code=502, detail=f"Catalog service error: {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        logger.error("Catalog connection error during lookup for %s: %s", imdb_id, e)
        raise HTTPException(
            status_code=502, detail=f"Catalog network error: {e}"
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
    except httpx.HTTPStatusError as e:
        logger.error("Catalog search status error for query '%s': %s", q, e)
        raise HTTPException(
            status_code=502, detail=f"Catalog search error: {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        logger.error("Catalog connection error during search for query '%s': %s", q, e)
        raise HTTPException(
            status_code=502, detail=f"Catalog network error: {e}"
        ) from e


@library_router.get("/torrents")
async def list_torrents():
    try:
        return await library.get_torrents_list()
    except httpx.HTTPStatusError as e:
        logger.error("TorrServer status error while reading torrents: %s", e)
        raise HTTPException(
            status_code=502, detail=f"TorrServer error: {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        logger.error("TorrServer connection error while listing torrents: %s", e)
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
            task.add_done_callback(_handle_bg_task_exception)

        return await library.get_torrent_files_structure(hash)
    except httpx.HTTPStatusError as e:
        logger.error("TorrServer status error for files of hash %s: %s", hash, e)
        raise HTTPException(
            status_code=502, detail=f"TorrServer error: {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        logger.error("TorrServer connection error for files of hash %s: %s", hash, e)
        raise HTTPException(
            status_code=502, detail=f"TorrServer connection error: {e}"
        ) from e


@library_router.get("/poster/{hash}")
async def get_poster(hash: str):
    try:
        poster_path = library.resolve_poster_path(hash)
        if poster_path.is_file():
            return FileResponse(poster_path)
    except (OSError, ValueError) as e:
        logger.error("Error reading poster file for %s: %s", hash, e)

    raise HTTPException(status_code=404, detail=t("err_not_found"))


@library_router.delete("/history/{hash}")
async def delete_history(hash: str):
    try:
        await library.clear_history(hash)
        return {"status": "ok"}
    except sqlite3.Error as e:
        logger.error("Failed to delete history for %s: %s", hash, e)
        raise HTTPException(
            status_code=500, detail="Database error while deleting history"
        ) from e
