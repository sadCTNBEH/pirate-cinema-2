import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Optional

import anyio
import httpx

from backend.core.settings import get_data_dir, get_torrserver_url
from backend.exceptions import DatabaseError, ExternalServiceError, NotFoundError
from backend.infrastructure.torrserver import client as torrserver
from backend.repositories.library import LibraryRepository
from backend.services.i18n import t

logger = logging.getLogger(__name__)


def _group_files_by_structure(
    files: list[dict[str, Any]], history_map: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    seasons: dict[str, list[dict[str, Any]]] = {}
    movies: list[dict[str, Any]] = []
    has_series = False

    for f in files:
        if not isinstance(f, dict):
            continue

        raw_id = f.get("id") or f.get("file_id")
        h = None

        if isinstance(raw_id, (int, str)):
            h = history_map.get(int(raw_id))

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


def sort_video_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        files,
        key=lambda f: LibraryRepository.parse_ep(
            f.get("name") or f.get("file_name") or f.get("path") or ""
        ),
    )


class LibraryService:
    def __init__(
        self,
        library_repo: Optional[LibraryRepository] = None,
        torrserver_client: Any = None,
        settings_provider: Optional[Callable[[], str]] = None,
        metadata_service: Any = None,
    ):
        self._library_repo = library_repo or LibraryRepository()
        self._torrserver = torrserver_client or torrserver
        self._get_ts_url = settings_provider or get_torrserver_url
        self._metadata_service = metadata_service

    async def get_recent_media(self) -> list[dict[str, Any]]:
        try:
            return await anyio.to_thread.run_sync(
                self._library_repo.get_recent_history, 20
            )
        except sqlite3.Error as e:
            logger.error("Failed to load recent media from DB: %s", e)
            raise DatabaseError("Database error while fetching recent history") from e

    async def get_torrents_list(self) -> dict[str, Any] | None:
        torrserver_url = self._get_ts_url()
        try:
            data = await self._torrserver.read_torrserver(torrserver_url)
        except httpx.HTTPStatusError as e:
            logger.error("TorrServer status error while reading torrents: %s", e)
            raise ExternalServiceError(
                f"TorrServer error: {e.response.status_code}", status_code=502
            ) from e
        except httpx.RequestError as e:
            logger.error("TorrServer connection error while listing torrents: %s", e)
            raise ExternalServiceError(
                f"TorrServer connection error: {e}", status_code=502
            ) from e

        if not data or not data.get("torrents"):
            return data

        torrents = data["torrents"]
        hashes = [d["hash"] for d in torrents if isinstance(d, dict) and "hash" in d]
        if not hashes:
            return data

        try:
            meta_map = await anyio.to_thread.run_sync(
                self._library_repo.fetch_poster_meta, hashes
            )
        except sqlite3.Error as db_err:
            logger.error("Failed to fetch poster metadata from DB: %s", db_err)
            meta_map = {}

        for d in torrents:
            if isinstance(d, dict) and d.get("hash") in meta_map:
                d["poster_url"] = f"/api/library/poster/{d['hash']}"

        return data

    async def get_torrent_files_structure(
        self, torrent_hash: str, title: Optional[str] = None
    ) -> dict[str, Any]:
        if title and self._metadata_service:
            self._metadata_service.trigger_metadata_fetch(torrent_hash, title)

        torrserver_url = self._get_ts_url()
        try:
            files = await self._torrserver.torrent_video_files(
                torrserver_url, torrent_hash
            )
        except httpx.HTTPStatusError as e:
            logger.error("TorrServer status error for files of hash %s: %s", torrent_hash, e)
            raise ExternalServiceError(
                f"TorrServer error: {e.response.status_code}", status_code=502
            ) from e
        except httpx.RequestError as e:
            logger.error("TorrServer connection error for files of hash %s: %s", torrent_hash, e)
            raise ExternalServiceError(
                f"TorrServer connection error: {e}", status_code=502
            ) from e

        files = sort_video_files(files)

        try:
            history_map = await anyio.to_thread.run_sync(
                self._library_repo.get_file_history_map, torrent_hash
            )
        except sqlite3.Error as db_err:
            logger.error(
                "Failed to read file history from DB for %s: %s",
                torrent_hash,
                db_err,
            )
            history_map = {}

        return _group_files_by_structure(files, history_map)

    def resolve_poster_path(self, torrent_hash: str) -> Path:
        path = get_data_dir() / "posters" / f"{torrent_hash}.jpg"
        if not path.is_file():
            raise NotFoundError(t("err_not_found"))
        return path

    async def clear_history(self, torrent_hash: str) -> None:
        try:
            await anyio.to_thread.run_sync(
                self._library_repo.delete_history_by_hash, torrent_hash
            )
        except sqlite3.Error as e:
            logger.error("Failed to delete history for %s: %s", torrent_hash, e)
            raise DatabaseError("Database error while deleting history") from e


# Функции модуля для обратной совместимости
_default_library_service = LibraryService()
get_recent_media = _default_library_service.get_recent_media
get_torrents_list = _default_library_service.get_torrents_list
get_torrent_files_structure = _default_library_service.get_torrent_files_structure
resolve_poster_path = _default_library_service.resolve_poster_path
clear_history = _default_library_service.clear_history
