import logging
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import httpx

from backend.core.settings import get_data_dir
from backend.exceptions import DatabaseError, ExternalServiceError, NotFoundError
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
        library_repo: LibraryRepository,
        torrserver_client: Any,
        settings_provider: Callable[[], str],
        metadata_service: Any,
        posters_dir: Path | None = None,
    ):
        self._library_repo = library_repo
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider
        self._metadata_service = metadata_service
        self._posters_dir = posters_dir or (get_data_dir() / "posters")

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
            torrents = await self._torrserver.get_torrents(torrserver_url)
        except httpx.HTTPStatusError as e:
            logger.error("TorrServer list HTTP error: %s", e)
            raise ExternalServiceError(
                f"TorrServer returned error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error("TorrServer connection error: %s", e)
            raise ExternalServiceError(
                f"Cannot connect to TorrServer: {e}", status_code=502
            ) from e

        if not torrents:
            return None

        hashes = [
            t.get("hash")
            for t in torrents
            if isinstance(t, dict) and t.get("hash")
        ]

        try:
            poster_map = await anyio.to_thread.run_sync(
                self._library_repo.fetch_poster_meta, hashes
            )
        except sqlite3.Error as e:
            logger.error("Failed to fetch poster metadata from DB: %s", e)
            poster_map = {}

        for t_item in torrents:
            if not isinstance(t_item, dict):
                continue
            h = t_item.get("hash")
            if h and h in poster_map:
                t_item["poster_file"] = poster_map[h]
            else:
                title = t_item.get("title")
                if h and title and self._metadata_service:
                    self._metadata_service.trigger_metadata_fetch(h, title)

        return {"Torrents": torrents}

    async def get_torrent_files_structure(
        self, torrent_hash: str, title: str | None = None
    ) -> dict[str, Any]:
        if title and self._metadata_service:
            self._metadata_service.trigger_metadata_fetch(torrent_hash, title)

        torrserver_url = self._get_ts_url()
        try:
            files = await self._torrserver.torrent_video_files(
                torrserver_url, torrent_hash
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "TorrServer files HTTP error for hash %s: %s", torrent_hash, e
            )
            raise ExternalServiceError(
                f"TorrServer returned error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error(
                "TorrServer connection error for hash %s: %s", torrent_hash, e
            )
            raise ExternalServiceError(
                f"Cannot connect to TorrServer: {e}", status_code=502
            ) from e

        if not files:
            raise NotFoundError(t("err_files_not_found"))

        files = sort_video_files(files)

        try:
            history_map = await anyio.to_thread.run_sync(
                self._library_repo.get_file_history_map, torrent_hash
            )
        except sqlite3.Error as e:
            logger.error(
                "Failed to load file history map for hash %s: %s",
                torrent_hash,
                e,
            )
            history_map = {}

        return _group_files_by_structure(files, history_map)

    def resolve_poster_path(self, torrent_hash: str) -> Path:
        path = self._posters_dir / f"{torrent_hash}.jpg"
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
