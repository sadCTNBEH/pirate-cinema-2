import logging

from backend.api import deps
from backend.api.deps import _mpv
from backend.api.schemas.player import MagnetRequest, NextRequest, PlayRequest
from backend.services import player

"""FastAPI routers: library, player, settings, catalog."""
import asyncio
import sqlite3

import httpx
from fastapi import APIRouter, HTTPException

from backend.infrastructure.torrserver import client as torrserver
from backend.services.i18n import t
from backend.services.metadata import fetch_and_save_metadata

logger = logging.getLogger(__name__)

player_router = APIRouter(prefix="/api/player", tags=["player"])

background_tasks = set()


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
        logger.exception("Database preparation failed")
        raise HTTPException(
            status_code=500, detail="Ошибка базы данных при подготовке"
        ) from e
    except (OSError, RuntimeError) as e:
        logger.exception("Failed to launch player process")
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
    _mpv.stop()
    return {"status": "stopped"}


@player_router.post("/add_magnet")
async def add_magnet_endpoint(req: MagnetRequest):
    try:
        title = req.title or req.magnet[:60]
        result = await torrserver.add_magnet(deps._torrserver_url, req.magnet, title)

        task = asyncio.create_task(
            fetch_and_save_metadata(result["hash"], req.title or result["hash"])
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

        return result
    except httpx.HTTPError as e:
        logger.exception("Failed to add magnet to TorrServer")
        raise HTTPException(status_code=502, detail=f"TorrServer error: {e}") from e


@player_router.delete("/torrent/{hash}")
async def delete_torrent(hash: str):
    try:
        await torrserver.remove_torrent(deps._torrserver_url, hash)
        return {"status": "removed"}
    except (ValueError, OSError) as e:
        logger.exception("Failed to delete torrent")
        raise HTTPException(status_code=500, detail=str(e)) from e

