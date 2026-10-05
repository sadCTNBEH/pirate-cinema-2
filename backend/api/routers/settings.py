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



# ─── Router: Settings ───

settings_router = APIRouter(prefix="/api/settings", tags=["settings"])

@settings_router.get("/health")
async def health(request: Request):
    return {"error": getattr(request.app.state, "startup_error", None)}

@settings_router.get("")
async def get_settings():
    prefs = _load_settings()
    return {
        "torrserver_url": _torrserver_url,
        "language": prefs.get("language", "ru"),
        "jackett_url": prefs.get("jackett_url", ""),
        "jackett_api_key": prefs.get("jackett_api_key", ""),
    }

class SettingsUpdate(BaseModel):
    torrserver_url: str | None = None
    language: str | None = None
    jackett_url: str | None = None
    jackett_api_key: str | None = None

@settings_router.post("")
async def update_settings(body: SettingsUpdate):
    global _torrserver_url
    prefs = _load_settings()

    if body.torrserver_url is not None:
        _torrserver_url = body.torrserver_url.rstrip('/')
        prefs["torrserver_endpoint"] = _torrserver_url

    if body.language is not None:
        prefs["language"] = body.language

    if body.jackett_url is not None:
        prefs["jackett_url"] = body.jackett_url

    if body.jackett_api_key is not None:
        prefs["jackett_api_key"] = body.jackett_api_key

    _save_settings(prefs)
    return {"torrserver_url": _torrserver_url}

@settings_router.get("/status")
async def server_status():
    active = await torrserver.probe(_torrserver_url)
    return {"active": active, "url": _torrserver_url}



async def fetch_and_save_metadata(hash: str, raw_title: str):
    with db.get_connection() as conn:
        row = conn.execute("SELECT poster_file FROM media_metadata WHERE torrent_hash = ?", (hash,)).fetchone()
        if row and row["poster_file"]:
            return

    clean, _ = clean_title(raw_title)
    if not clean: return
    results = await search_metadata(clean)
    if not results: return
    meta = results[0]

    poster_file = ""
    if meta.get("poster_url"):


        poster_dir = get_data_dir() / "posters"
        poster_dir.mkdir(exist_ok=True)
        poster_path = poster_dir / f"{hash}.jpg"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(meta["poster_url"], timeout=10)
                r.raise_for_status()
                poster_path.write_bytes(r.content)
                poster_file = f"{hash}.jpg"
        except (httpx.HTTPError, OSError):
            pass

    db.save_full_metadata(
        hash,
        meta.get("title", raw_title),
        meta.get("overview", ""),
        meta.get("year"),
        meta.get("rating", 0.0),
        poster_file,
        json.dumps(meta.get("genres", []))
    )

@library_router.get("/poster/{hash}")
async def get_poster(hash: str):
    p = get_data_dir() / "posters" / f"{hash}.jpg"
    if p.is_file():
        return FileResponse(p)
    raise HTTPException(404, t("err_not_found"))





APP_VERSION = __version__

@settings_router.get("/updates")
async def check_updates():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.github.com/repos/sadCTNBEH/pirate-cinema/releases/latest", timeout=5.0)
            if r.status_code == 403:
                return {"has_update": False, "latest": t("err_github_limit"), "current": APP_VERSION, "url": ""}
            if r.status_code == 404:
                return {"has_update": False, "latest": t("err_releases_not_found"), "current": APP_VERSION, "url": ""}
            r.raise_for_status()
            data = r.json()
            latest = data.get("tag_name", "")
            url = data.get("html_url", "")
            has_update = latest and latest != APP_VERSION
            return {"has_update": has_update, "latest": latest, "current": APP_VERSION, "url": url}
    except httpx.HTTPError as e:
        logger.exception("Failed to check for updates from GitHub")
        return {"error": str(e)}

@settings_router.get("/backup")
async def backup_data():
    tmp_path = create_backup_zip()
    return FileResponse(tmp_path, filename="pirate_cinema_backup.zip", background=BackgroundTask(lambda: os.remove(tmp_path)))

@settings_router.post("/restore")
async def restore_data(request: Request):
    fd, tmp_path_str = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    tmp_path = Path(tmp_path_str)

    try:
        content = await request.body()

        async with aiofiles.open(tmp_path, "wb") as f:
            await f.write(content)

        restore_backup_zip(tmp_path)

        return {"status": "ok"}

    except (ValueError, OSError) as e:
        logger.exception("Failed to restore backup")
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        tmp_path.unlink(missing_ok=True)




@settings_router.post("/open_folder")
async def open_data_folder():
    data_dir = get_data_dir()
    path_str = str(data_dir)

    if os.name == 'nt':
        cmd = ["explorer.exe", path_str]
    elif sys.platform == 'darwin':
        cmd = ["open", path_str]
    else:
        cmd = ["xdg-open", path_str]

    try:
        await asyncio.create_subprocess_exec(*cmd)
    except OSError as e:
        logger.error("Failed to open data folder %s: %s", path_str, e)
        return {"status": "error", "message": str(e)}

    return {"status": "ok"}

@settings_router.get("/diagnostics")
async def diagnostics():
    data_dir = get_data_dir()
    db_file = data_dir / "history.sqlite3"
    db_size = db_file.stat().st_size if db_file.exists() else 0

    mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv.exe"
    if not mpv_bin.is_file():
        mpv_bin = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "MPV Player" / "mpv.exe"
    if not mpv_bin.is_file():
        which_mpv = shutil.which("mpv")
        mpv_bin = Path(which_mpv) if which_mpv else Path("mpv")

    try:
        ts_probe = await torrserver.probe(_torrserver_url)
    except httpx.HTTPError:
        ts_probe = False

    ts_ver = "unknown"
    if ts_probe:
        try:
            res = await torrserver.read_torrserver(_torrserver_url)
            if isinstance(res, dict):
                ts_ver = res.get("version", "unknown")
        except httpx.HTTPError:
            pass

    log_file = data_dir / "mpv_debug.log"
    last_error = ""
    if log_file.exists():
        try:
            async with aiofiles.open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = await f.read()
            lines = content.splitlines()
            errs = [l for l in lines[-100:] if "error" in l.lower() or "exception" in l.lower()]
            if errs:
                last_error = errs[-1]
        except OSError as e:
            logger.warning("Failed to read MPV log file: %s", e)

    return {
        "torrserver_version": ts_ver,
        "mpv_path": str(mpv_bin),
        "db_size": db_size,
        "data_folder": str(data_dir),
        "last_error": last_error
    }

@library_router.delete("/history/{hash}")
async def delete_history(hash: str):
    with db.get_connection() as conn:
        conn.execute("DELETE FROM media_file_history WHERE torrent_hash=?", (hash,))
        conn.commit()
    return {"status": "ok"}


