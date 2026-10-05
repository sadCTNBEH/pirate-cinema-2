"""FastAPI player router."""

import asyncio
import logging
import sqlite3

import httpx
from fastapi import APIRouter, HTTPException

from backend.api import deps
from backend.api.schemas.player import MagnetRequest, NextRequest, PlayRequest
from backend.infrastructure.torrserver import client as torrserver
from backend.services import player
from backend.services.i18n import t
from backend.services.metadata import fetch_and_save_metadata

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
async def play(req: PlayRequest):
    try:
        status = await player.start_playback(
            req.hash, req.file_id, req.file_name, req.start_time
        )
        return {"status": status}
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="External player not found")
    except sqlite3.Error as e:
        logger.error("Database error during playback preparation: %s", e)
        raise HTTPException(
            status_code=500, detail="Ошибка базы данных при подготовке"
        ) from e
    except (OSError, RuntimeError) as e:
        logger.error("Failed to launch player process: %s", e)
        raise HTTPException(
            status_code=500, detail=t("err_mpv_not_found")
        ) from e


@player_router.post("/next")
async def play_next_endpoint(req: NextRequest):
    success = await player.play_next_file(req.hash, req.file_id)
    if success:
        return {"status": "launched"}
    raise HTTPException(status_code=404, detail=t("err_next_ep_not_found"))


@player_router.post("/stop")
async def stop_player():
    mpv_instance = deps.get_mpv()
    if mpv_instance:
        mpv_instance.stop()
    return {"status": "stopped"}


@player_router.post("/add_magnet")
async def add_magnet_endpoint(req: MagnetRequest):
    torrserver_url = deps.get_torrserver_url()
    try:
        title = req.title or req.magnet[:60]
        result = await torrserver.add_magnet(torrserver_url, req.magnet, title)

        task = asyncio.create_task(
            fetch_and_save_metadata(result["hash"], req.title or result["hash"])
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
