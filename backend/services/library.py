import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

import anyio

from backend.api import deps
from backend.core.settings import get_data_dir
from backend.infrastructure.torrserver import client as torrserver
from backend.repositories import library as library_repo

logger = logging.getLogger(__name__)


async def get_recent_media() -> list[dict[str, Any]]:
    return await anyio.to_thread.run_sync(library_repo.get_recent_history)


async def get_torrents_list() -> dict[str, Any] | None:
    torrserver_url = deps.get_torrserver_url()
    data = await torrserver.read_torrserver(torrserver_url)
    if not data or not data.get("torrents"):
        return data

    torrents = data["torrents"]
    hashes = [d["hash"] for d in torrents if isinstance(d, dict) and "hash" in d]
    if not hashes:
        return data

    try:
        meta_map = await anyio.to_thread.run_sync(
            library_repo.fetch_poster_meta, hashes
        )
    except sqlite3.Error as db_err:
        logger.error("Failed to fetch poster metadata from DB: %s", db_err)
        meta_map = {}

    for d in torrents:
        if isinstance(d, dict) and d.get("hash") in meta_map:
            d["poster_url"] = f"/api/library/poster/{d['hash']}"

    return data


def _group_files_by_structure(
    files: list[dict[str, Any]], history_map: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    seasons: dict[str, list[dict[str, Any]]] = {}
    movies: list[dict[str, Any]] = []
    has_series = False

    for f in files:
        if not isinstance(f, dict):
            continue

        file_id = f.get("id")
        h = history_map.get(file_id) if file_id is not None else None

        if h and not h.get("is_watched"):
            f["playback_timecode"] = h.get("playback_timecode", 0)
        else:
            f["playback_timecode"] = 0

        name = f.get("name", "")
        m = re.search(r"S(\d+)E(\d+)", name, re.IGNORECASE)
        if not m:
            m = re.search(r"(\d+)x(\d+)", name, re.IGNORECASE)

        if m:
            has_series = True
            try:
                s = str(int(m.group(1)))
            except (ValueError, IndexError):
                s = "1"
            seasons.setdefault(s, []).append(f)
            continue

        m = re.search(r"(?:ep|episode|e)\s*(\d+)", name, re.IGNORECASE)
        if m:
            has_series = True
            s = "1"
            seasons.setdefault(s, []).append(f)
            continue

        movies.append(f)

    return {
        "type": "series" if has_series else "movie",
        "seasons": seasons,
        "movies": movies,
        "flat_files": files,
    }

def sort_video_files(files):
    return sorted(files, key=lambda f: library_repo.parse_ep(f.get("name", "")))

async def get_torrent_files_structure(torrent_hash: str) -> dict[str, Any]:
    torrserver_url = deps.get_torrserver_url()
    files = await torrserver.torrent_video_files(
        torrserver_url, torrent_hash
    )
    files = sort_video_files(files)

    try:
        history_map = await anyio.to_thread.run_sync(
            library_repo.get_file_history_map, torrent_hash
        )
    except sqlite3.Error as db_err:
        logger.error("Failed to read file history from DB for %s: %s", torrent_hash, db_err)
        history_map = {}

    return _group_files_by_structure(files, history_map)


def resolve_poster_path(torrent_hash: str) -> Path:
    return get_data_dir() / "posters" / f"{torrent_hash}.jpg"


async def clear_history(torrent_hash: str) -> None:
    await anyio.to_thread.run_sync(
        library_repo.delete_history_by_hash, torrent_hash
    )
