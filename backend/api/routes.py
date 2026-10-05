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


# ─── Router: Library ──────────────────────────────────────────────────────────
library_router = APIRouter(prefix="/api/library", tags=["library"])

@library_router.get("/recent")
async def recent():
    with db.get_connection() as conn:
        rows = conn.execute("""
            SELECT h.torrent_hash, h.file_index, h.file_name, h.playback_timecode, h.playback_duration,
                   h.is_watched, h.last_played_at, m.title, m.poster_file, m.year
            FROM media_file_history h
            LEFT JOIN media_metadata m ON h.torrent_hash = m.torrent_hash
            WHERE h.launch_count > 0 AND h.is_watched = 0
            ORDER BY h.last_played_at DESC
            LIMIT 20
        """).fetchall()
    return [dict(r) for r in rows]


@library_router.get("/popular")
async def popular_movies():
    return await catalog_svc.popular()


@library_router.get("/popular/series")
async def popular_series():
    return await catalog_svc.popular_series()


@library_router.get("/meta/{imdb_id}")
async def movie_meta(imdb_id: str, type: str = "movie"):
    meta = await catalog_svc.lookup(imdb_id, type)
    if not meta:
        raise HTTPException(404, t("err_not_found"))
    return meta

@library_router.get("/meta/search")
async def movie_meta_search(q: str, type: str = "movie"):
    candidates = catalog_svc.title_candidates(q)
    if not candidates:
        candidates = [q]

    for candidate in candidates:
        results = await catalog_svc.search_metadata(candidate, type)
        if results:
            return results
    return []

def _fetch_poster_meta(hashes: list[str], placeholders: str) -> dict[str, str]:
    with db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT torrent_hash, poster_file FROM media_metadata WHERE torrent_hash IN ({placeholders})",
            hashes
        ).fetchall()
    return {r["torrent_hash"]: r["poster_file"] for r in rows}


@library_router.get("/torrents")
async def list_torrents():
    try:
        data = await torrserver.read_torrserver(_torrserver_url)
        if not data or not data.get("torrents"):
            return data

        torrents = data["torrents"]
        hashes = [d["hash"] for d in torrents]
        if not hashes:
            return data

        placeholders = ",".join("?" for _ in hashes)

        # 2. АСИНХРОННОСТЬ: Выполняем блокирующее чтение SQLite в фоновом потоке
        try:
            meta_map = await anyio.to_thread.run_sync(_fetch_poster_meta, hashes, placeholders)
        except sqlite3.Error as db_err:
            logger.error("Database fetch in library failed: %s", db_err)
            meta_map = {}  # Падение БД не должно полностью ломать выдачу списка торрентов

        # Применяем метаданные к результату
        for d in torrents:
            pf = meta_map.get(d["hash"])
            if pf:
                d["poster_url"] = f"/api/library/poster/{d['hash']}"

        return data

    except httpx.HTTPError as e:
        # Исправили текст лога на актуальный для этого эндпоинта
        logger.exception("Failed to read torrents list from TorrServer")
        raise HTTPException(status_code=502, detail=f"TorrServer connection error: {e}") from e




def sort_video_files(files):
    def parse_ep(name):
        m = re.search(r'S(\d+)E(\d+)', name, re.IGNORECASE)
        if m: return (1, int(m.group(1)), int(m.group(2)), name)
        m = re.search(r'(\d+)x(\d+)', name, re.IGNORECASE)
        if m: return (1, int(m.group(1)), int(m.group(2)), name)
        return (0, 0, 0, name)
    return sorted(files, key=lambda f: parse_ep(f.get("name", "")))

@library_router.get("/torrents/{hash}/files")
async def torrent_files(hash: str, title: str | None = None):
    try:
        if title:
            asyncio.create_task(fetch_and_save_metadata(hash, title))
        files = await torrserver.torrent_video_files(_torrserver_url, hash)
        files = sort_video_files(files)
        with db.get_connection() as conn:
            rows = conn.execute("SELECT file_index, playback_timecode, is_watched FROM media_file_history WHERE torrent_hash = ?", (hash,)).fetchall()
        history_map = {row["file_index"]: row for row in rows}

        seasons = {}
        movies = []
        has_series = False

        for f in files:
            h = history_map.get(f.get("id"))
            if h and not h["is_watched"]:
                f["playback_timecode"] = h["playback_timecode"]
            else:
                f["playback_timecode"] = 0

            name = f.get("name", "")
            m = re.search(r'S(\d+)E(\d+)', name, re.IGNORECASE)
            if not m:
                m = re.search(r'(\d+)x(\d+)', name, re.IGNORECASE)

            if m:
                has_series = True
                s = str(int(m.group(1)))
                if s not in seasons: seasons[s] = []
                seasons[s].append(f)
                continue

            m = re.search(r'(?:ep|episode|e)\s*(\d+)', name, re.IGNORECASE)
            if m:
                has_series = True
                s = "1"
                if s not in seasons: seasons[s] = []
                seasons[s].append(f)
                continue

            movies.append(f)

        return {
            "type": "series" if has_series else "movie",
            "seasons": seasons,
            "movies": movies,
            "flat_files": files
        }
    except httpx.HTTPError as e:
        logger.exception("TorrServer search failed for query")
        raise HTTPException(status_code=502, detail=f"TorrServer search error: {e}") from e


# ─── Router: Search ────────────────────────────────────────────────────────────
search_router = APIRouter(prefix="/api/search", tags=["search"])

@search_router.get("")
async def search(q: str = Query(..., min_length=1)):
    try:
        return await torrserver.search_all(_torrserver_url, q)
    except httpx.HTTPError as e:
        logger.exception("TorrServer search failed for query")
        raise HTTPException(status_code=502, detail=f"TorrServer search error: {e}") from e


# ─── Router: Player ───────────────────────────────────────────────────────────
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


# ─── Router: Settings ─────────────────────────────────────────────────────────
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


# ─── Router: Global i18n ──────────────────────────────────────────────────────
i18n_router = APIRouter(prefix="/api/i18n", tags=["i18n"])

@i18n_router.get("")
async def get_i18n_strings():
    prefs = _load_settings()
    lang = prefs.get("language", "ru")
    strings = TRANSLATIONS.get(lang, TRANSLATIONS.get("ru", {}))
    return {"lang": lang, "strings": strings}
