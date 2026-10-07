"""FastAPI player router."""

import asyncio
import logging
import sqlite3

import httpx
from fastapi import APIRouter, HTTPException, Depends

from backend.api.deps import get_playback_service
from backend.api import deps
from backend.api.schemas.player import MagnetRequest, NextRequest, PlayRequest
from backend.infrastructure.torrserver import client as torrserver
from backend.services.i18n import t
from backend.services.metadata import fetch_and_save_metadata
from backend.services.playback import MpvService

logger = logging.getLogger(__name__)

player_router = APIRouter(prefix="/api/player", tags=["player"])
background_tasks: set[asyncio.Task] = set()


def _handle_bg_task_exception(task: asyncio.Task) -> None:
    """Логирует исключения, возникшие в фоновой задаче сохранения метаданных."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except (sqlite3.Error, httpx.HTTPError, OSError, ValueError, RuntimeError):
        logger.exception("Background metadata task failed")


@player_router.post("/play")
async def play(request: PlayRequest, service: MpvService = Depends(get_playback_service)):
    status = await service.launch(request)
    return {"status": status}


@player_router.post("/next")
async def play_next_endpoint(request: NextRequest, service: MpvService = Depends(get_playback_service)):
    success = await service.play_next_file(request.hash, request.file_id)
    if success:
        return {"status": "launched"}
    raise HTTPException(status_code=404, detail=t("err_next_ep_not_found"))


@player_router.post("/stop")
async def stop_player(service: MpvService = Depends(get_playback_service)):
    mpv_instance = service.stop()
    if mpv_instance:
        mpv_instance.stop()
    return {"status": "stopped"}


@player_router.post("/add_magnet")
async def add_magnet_endpoint(request: MagnetRequest):
    torrserver_url = deps.get_torrserver_url()
    try:
        title = request.title or request.magnet[:60]
        result = await torrserver.add_magnet(torrserver_url, request.magnet, title)

        task = asyncio.create_task(
            fetch_and_save_metadata(result["hash"], request.title or result["hash"])
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        task.add_done_callback(_handle_bg_task_exception)

        return result
    except httpx.HTTPStatusError as e:
        logger.error("TorrServer status error while adding magnet: %s", e)
        raise HTTPException(
            status_code=502, detail=f"TorrServer error: {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        logger.error("TorrServer connection error while adding magnet: %s", e)
        raise HTTPException(
            status_code=502, detail=f"TorrServer network error: {e}"
        ) from e


@player_router.delete("/torrent/{hash}")
async def delete_torrent(hash: str):
    torrserver_url = deps.get_torrserver_url()
    try:
        await torrserver.remove_torrent(torrserver_url, hash)
        return {"status": "removed"}
    except httpx.HTTPStatusError as e:
        logger.error("TorrServer status error while removing torrent %s: %s", hash, e)
        raise HTTPException(
            status_code=502, detail=f"TorrServer error: {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        logger.error("TorrServer connection error while removing torrent %s: %s", hash, e)
        raise HTTPException(
            status_code=502, detail=f"TorrServer network error: {e}"
        ) from e
    except (ValueError, OSError) as e:
        logger.error("Failed to delete torrent %s: %s", hash, e)
        raise HTTPException(status_code=500, detail=str(e)) from e
