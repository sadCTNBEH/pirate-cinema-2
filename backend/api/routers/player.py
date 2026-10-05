"""FastAPI routers: library, player, settings, catalog."""
import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from urllib import error

import aiofiles
import anyio
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from backend.services.backup import create_backup_zip, restore_backup_zip
from backend.services.catalog import clean_title, search_metadata

from .. import __version__
from ..config import get_data_dir
from ..services import catalog as catalog_svc
from ..services import db, torrserver
from ..services.i18n import TRANSLATIONS, t
from ..services.mpv import MPVController

# ─── Shared state ─────────────────────────────────────────────────────────────
_mpv = MPVController()
logger = logging.getLogger(__name__)

def _load_settings():
    settings_file = get_data_dir() / "preferences.json"
    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

def _save_settings(data):
    settings_dir = get_data_dir()
    
    try:
        with open(settings_dir / "preferences.json", "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        logger.exception("Failed to save preferences")

_torrserver_url = _load_settings().get("torrserver_endpoint", "http://127.0.0.1:8090")



# ─── Router: Player ───

player_router = APIRouter(prefix="/api/player", tags=["player"])

class PlayRequest(BaseModel):
    hash: str
    file_id: int
    file_name: str
    start_time: int = 0


def _sync_db_prep(req_hash: str, file_id: int, file_name: str):
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT playback_timecode, is_watched FROM media_file_history WHERE torrent_hash=? AND file_index=?",
            (req_hash, file_id)
        ).fetchone()

    audio_track = db.get_audio_track(req_hash, file_id)

    m = re.search(r"S\d+E\d+|\d+x\d+|(?:ep|episode|e)\s*\d+", file_name, re.IGNORECASE)
    db.save_media_type(req_hash, "series" if m else "movie")
    db.mark_played(req_hash, file_id, file_name)

    return row, audio_track


@player_router.post("/play")
async def play(req: PlayRequest):
    if sys.platform == "win32":
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv.exe"
        if not mpv_bin.is_file():
            prog_files = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "MPV Player" / "mpv.exe"
            if prog_files.is_file():
                mpv_bin = prog_files
    else:
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv"

    if not mpv_bin.is_file():
        which_mpv = shutil.which("mpv")
        mpv_bin = Path(which_mpv) if which_mpv else Path("mpv")

    url = torrserver.stream_url(_torrserver_url, req.hash, req.file_id, req.file_name)

    try:
        row, audio_track = await anyio.to_thread.run_sync(_sync_db_prep, req.hash, req.file_id, req.file_name)
    except sqlite3.Error as e:
        logger.exception("Database preparation failed")
        raise HTTPException(status_code=500, detail="Ошибка базы данных при подготовке") from e

    if row and not row["is_watched"] and row["playback_timecode"]:
        req.start_time = row["playback_timecode"]

    def on_progress(prop, value):
        if value is None:
            return
        if prop == "time-pos":
            _mpv._last_timecode = int(value)
        if prop == "duration":
            _mpv._last_duration = int(value)
        if prop == "aid":
            try:
                new_aid = int(value)
                if new_aid > 0 and new_aid != getattr(_mpv, "_last_aid", None):
                    _mpv._last_aid = new_aid
                    try:
                        db.set_audio_track(req.hash, new_aid, req.file_id)
                    except sqlite3.Error as e:
                        logger.warning("Failed to save audio track to DB: %s", e)
            except (ValueError, TypeError):
                pass

        tc = getattr(_mpv, "_last_timecode", 0)
        dur = getattr(_mpv, "_last_duration", 0)

        now = time.time()
        last_save = getattr(_mpv, "_last_save_time", 0)

        if tc and dur and (now - last_save >= 3 or prop == "flush"):
            aid = getattr(_mpv, "_last_aid", 0)
            try:
                db.update_progress(req.hash, req.file_id, tc, dur, aid)
                _mpv._last_save_time = now
            except sqlite3.Error as e:
                logger.warning("Failed to save progress to DB: %s", e)

    _mpv.on_progress = on_progress

    # 4. Callback завершения воспроизведения (исправлены сетевые исключения и кавычки)
    def handle_end(reason):
        if reason == "eof":
            def play_next():
                try:
                    data = json.dumps({"hash": req.hash, "file_id": req.file_id}).encode("utf-8")
                    req_play = urllib.request.Request(
                        "http://127.0.0.1:8000/api/player/next",
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req_play, timeout=5):
                        pass
                except (error.URLError, error.HTTPError, OSError):
                    logger.exception("Failed to play next episode via webhook")

            threading.Thread(target=play_next, daemon=True).start()

    _mpv.on_end = handle_end

    # 5. Запуск плеера (исправлен перехват ошибок операционной системы)
    try:
        _mpv.launch(str(mpv_bin), url, req.file_name, req.start_time, audio_track)
    except (FileNotFoundError, OSError) as e:
        logger.exception("Failed to launch MPV process")
        raise HTTPException(status_code=500, detail=t("err_mpv_not_found")) from e

    return {"status": "launched"}


class NextRequest(BaseModel):
    hash: str
    file_id: int

@player_router.post("/next")
async def play_next_endpoint(req: NextRequest):
    files = await torrserver.torrent_video_files(_torrserver_url, req.hash)
    files = sort_video_files(files)
    idx = next((i for i,f in enumerate(files) if f["id"] == req.file_id), -1)
    if idx >= 0 and idx + 1 < len(files):
        next_f = files[idx + 1]
        play_req = PlayRequest(hash=req.hash, file_id=next_f["id"], file_name=next_f["name"], start_time=0)
        return await play(play_req)
    raise HTTPException(404, t("err_next_ep_not_found"))

@player_router.post("/stop")
async def stop_player():
    _mpv.stop()
    return {"status": "stopped"}


class MagnetRequest(BaseModel):
    magnet: str
    title: str = ""

background_tasks = set()

@player_router.post("/add_magnet")
async def add_magnet_endpoint(req: MagnetRequest):
    try:
        result = await torrserver.add_magnet(_torrserver_url, req.magnet, req.title or req.magnet[:60])

        task = asyncio.create_task(fetch_and_save_metadata(result["hash"], req.title or result["hash"]))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

        return result

    except httpx.HTTPError as e:
        logger.exception("Failed to add magnet to TorrServer")
        raise HTTPException(status_code=502, detail=f"TorrServer error: {e}") from e


@player_router.delete("/torrent/{hash}")
async def delete_torrent(hash: str):
    try:
        await torrserver.remove_torrent(_torrserver_url, hash)
        return {"status": "removed"}
    except (ValueError, OSError) as e:
        logger.exception("Failed to delete torrent")
        raise HTTPException(status_code=500, detail=str(e)) from e


