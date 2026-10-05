"""FastAPI routers: library, player, settings, catalog."""
import asyncio
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import aiofiles
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from backend import __version__
from backend.api import deps
from backend.api.deps import _load_settings, _save_settings
from backend.api.schemas.settings import SettingsUpdate
from backend.core.config import get_data_dir
from backend.infrastructure.torrserver import client as torrserver
from backend.services.i18n_service import t
from backend.services.settings_service import create_backup_zip, restore_backup_zip

APP_VERSION = __version__

logger = logging.getLogger(__name__)



# ─── Router: Settings ───

settings_router = APIRouter(prefix="/api/settings", tags=["settings"])

@settings_router.get("/health")
async def health(request: Request):
    return {"error": getattr(request.app.state, "startup_error", None)}

@settings_router.get("")
async def get_settings():
    prefs = _load_settings()
    return {
        "torrserver_url": deps._torrserver_url,
        "language": prefs.get("language", "ru"),
        "jackett_url": prefs.get("jackett_url", ""),
        "jackett_api_key": prefs.get("jackett_api_key", ""),
    }

@settings_router.post("")
async def update_settings(body: SettingsUpdate):
    from backend.api import deps
    prefs = _load_settings()

    if body.torrserver_url is not None:
        deps._torrserver_url = body.torrserver_url.rstrip('/')
        prefs["torrserver_endpoint"] = deps._torrserver_url

    if body.language is not None:
        prefs["language"] = body.language

    if body.jackett_url is not None:
        prefs["jackett_url"] = body.jackett_url

    if body.jackett_api_key is not None:
        prefs["jackett_api_key"] = body.jackett_api_key

    _save_settings(prefs)
    return {"torrserver_url": deps._torrserver_url}

@settings_router.get("/status")
async def server_status():
    active = await torrserver.probe(deps._torrserver_url)
    return {"active": active, "url": deps._torrserver_url}


@settings_router.get("/updates")
async def check_updates():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.github.com/repos/sadCTNBEH/pirate-cinema-2/releases/latest", timeout=5.0)
            if r.status_code == 403:
                return {"has_update": False, "latest": t("err_github_limit"), "current": APP_VERSION, "url": ""}
            if r.status_code == 404:
                return {"has_update": False, "latest": t("err_releases_not_found"), "current": APP_VERSION, "url": ""}
            r.raise_for_status()
            data = r.json()
            latest = data.get("tag_name", "")
            latest_clean = latest.lstrip("v").strip()
            current_clean = APP_VERSION.lstrip("v").strip()
            
            def parse_ver(v):
                parts = []
                for p in v.split('.'):
                    if p.isdigit():
                        parts.append(int(p))
                    else:
                        break
                return tuple(parts)
                
            has_update = bool(latest_clean) and parse_ver(latest_clean) > parse_ver(current_clean)
            
            url = data.get("html_url", "")
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
        ts_probe = await torrserver.probe(deps._torrserver_url)
    except httpx.HTTPError:
        ts_probe = False

    ts_ver = "unknown"
    if ts_probe:
        try:
            res = await torrserver.read_torrserver(deps._torrserver_url)
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

