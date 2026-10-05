"""FastAPI routers: library, player, settings, catalog."""
import asyncio
import json
import logging
import re
import sqlite3

import anyio
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend import __version__
from backend.api import deps
from backend.api.routers.etc import sort_video_files
from backend.core.config import get_data_dir
from backend.infrastructure.catalog import cinemeta as catalog_svc
from backend.infrastructure.catalog.cinemeta import clean_title, search_metadata
from backend.infrastructure.torrserver import client as torrserver
from backend.repositories import db, metadata
from backend.services.i18n import t

APP_VERSION = __version__

logger = logging.getLogger(__name__)

# ─── Router: Library ───

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
        data = await torrserver.read_torrserver(deps._torrserver_url)
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

    metadata.save_full_metadata(
        hash,
        meta.get("title", raw_title),
        meta.get("overview", ""),
        meta.get("year"),
        meta.get("rating", 0.0),
        poster_file,
        json.dumps(meta.get("genres", []))
    )

@library_router.get("/torrents/{hash}/files")
async def torrent_files(hash: str, title: str | None = None):
    try:
        if title:
            asyncio.create_task(fetch_and_save_metadata(hash, title))
        files = await torrserver.torrent_video_files(deps._torrserver_url, hash)
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


@library_router.get("/poster/{hash}")
async def get_poster(hash: str):
    p = get_data_dir() / "posters" / f"{hash}.jpg"
    if p.is_file():
        return FileResponse(p)
    raise HTTPException(404, t("err_not_found"))


@library_router.delete("/history/{hash}")
async def delete_history(hash: str):
    with db.get_connection() as conn:
        conn.execute("DELETE FROM media_file_history WHERE torrent_hash=?", (hash,))
        conn.commit()
    return {"status": "ok"}


