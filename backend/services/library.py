import json
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import httpx

from backend.api.schemas.library import LibraryFilter
from backend.core.settings import get_data_dir
from backend.exceptions import DatabaseError, ExternalServiceError, NotFoundError
from backend.repositories.library import LibraryRepository
from backend.services.i18n import t

logger = logging.getLogger(__name__)


def _extract_file_id(f: dict[str, Any]) -> int | None:
    fid = f.get("id")
    if fid is not None:
        return int(fid)
    fid = f.get("file_id")
    if fid is not None:
        return int(fid)
    return None


def _group_files_by_structure(
    files: list[dict[str, Any]], history_map: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    seasons: dict[str, list[dict[str, Any]]] = {}
    movies: list[dict[str, Any]] = []
    has_series = False

    for f in files:
        if not isinstance(f, dict):
            continue

        raw_id = _extract_file_id(f)
        h = None

        if raw_id is not None:
            h = history_map.get(raw_id)

        if h and not h.get("is_watched"):
            f["playback_timecode"] = h.get("playback_timecode", 0)
        else:
            f["playback_timecode"] = 0

        name = f.get("name") or f.get("file_name") or f.get("path") or ""
        parsed = LibraryRepository.parse_ep(name)
        if parsed[0] == 1:
            has_series = True
            season_num = str(parsed[1])
            seasons.setdefault(season_num, []).append(f)
        else:
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
        key=lambda f: LibraryRepository.sort_key(
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
            t.get("hash") for t in torrents if isinstance(t, dict) and t.get("hash")
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
        if torrent_hash.startswith("online:"):
            return {
                "type": "movie",
                "movies": [{"id": 0, "name": title or "Online Stream", "length": 0}],
                "flat_files": [{"id": 0, "name": title or "Online Stream", "length": 0}],
            }

        if title and self._metadata_service:
            self._metadata_service.trigger_metadata_fetch(torrent_hash, title)

        torrserver_url = self._get_ts_url()
        try:
            files = await self._torrserver.torrent_video_files(
                torrserver_url, torrent_hash
            )
        except httpx.HTTPStatusError as e:
            logger.error("TorrServer files HTTP error for hash %s: %s", torrent_hash, e)
            raise ExternalServiceError(
                f"TorrServer returned error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error("TorrServer connection error for hash %s: %s", torrent_hash, e)
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

    async def delete_torrent(self, torrent_hash: str) -> None:
        try:
            await anyio.to_thread.run_sync(
                self._library_repo.delete_torrent, torrent_hash
            )
        except sqlite3.Error as e:
            logger.error("Failed to delete torrent %s: %s", torrent_hash, e)
            raise DatabaseError("Database error while deleting torrent") from e

        try:
            poster_path = self._posters_dir / f"{torrent_hash}.jpg"
            if poster_path.exists():
                poster_path.unlink(missing_ok=True)
        except OSError:
            pass

        torrserver_url = self._get_ts_url()
        try:
            await self._torrserver.remove_torrent(torrserver_url, torrent_hash)
        except (httpx.HTTPError, ValueError) as e:
            logger.debug("TorrServer remove torrent %s skipped/failed: %s", torrent_hash, e)

    async def delete_all_torrents(self) -> None:
        try:
            await anyio.to_thread.run_sync(
                self._library_repo.delete_all_torrents
            )
        except sqlite3.Error as e:
            logger.error("Failed to delete all torrents from DB: %s", e)
            raise DatabaseError("Database error while deleting all torrents") from e

        torrserver_url = self._get_ts_url()
        try:
            ts_torrents = await self._torrserver.get_torrents(torrserver_url)
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.debug("TorrServer clear all torrents skipped/failed: %s", e)
            return

        if isinstance(ts_torrents, list):
            for t_item in ts_torrents:
                if not isinstance(t_item, dict) or not t_item.get("hash"):
                    continue
                try:
                    await self._torrserver.remove_torrent(torrserver_url, t_item["hash"])
                except (httpx.HTTPError, ValueError) as e:
                    logger.debug(
                        "TorrServer remove torrent %s skipped/failed: %s",
                        t_item["hash"],
                        e,
                    )

    async def get_filtered_library(
        self, filter_params: LibraryFilter
    ) -> list[dict[str, Any]]:
        torrserver_url = self._get_ts_url()
        try:
            ts_torrents = await self._torrserver.get_torrents(torrserver_url)
            if isinstance(ts_torrents, list):
                for t_item in ts_torrents:
                    if isinstance(t_item, dict) and t_item.get("hash"):
                        h = t_item["hash"]
                        title = t_item.get("title", h)
                        await anyio.to_thread.run_sync(
                            self._library_repo.ensure_torrent, h, title
                        )
                        if self._metadata_service:
                            # Only fetch if not already enriched (has no overview/title yet)
                            has_meta = await anyio.to_thread.run_sync(
                                self._library_repo.has_full_metadata, h
                            )
                            if not has_meta:
                                self._metadata_service.trigger_metadata_fetch(h, title)
        except (httpx.HTTPError, ExternalServiceError, OSError, RuntimeError) as e:
            logger.debug("TorrServer sync skipped during library query: %s", e)

        try:
            db_rows = await anyio.to_thread.run_sync(
                self._library_repo.query_library,
                filter_params.type,
                filter_params.status,
                filter_params.year,
                filter_params.genre,
                filter_params.sort,
            )
        except sqlite3.Error as e:
            logger.error("Failed to query library from DB: %s", e)
            raise DatabaseError("Database error while querying library") from e

        items: list[dict[str, Any]] = []
        for r in db_rows:
            genres = []
            if r.get("genres_json"):
                try:
                    genres = json.loads(r["genres_json"])
                    if not isinstance(genres, list):
                        genres = []
                except (json.JSONDecodeError, TypeError):
                    genres = []

            total_files = int(r.get("total_files") or 0)
            watched_files = int(r.get("watched_files") or 0)
            max_tc = int(r.get("max_timecode") or 0)

            if total_files > 0 and watched_files >= total_files:
                computed_status = "watched"
            elif watched_files > 0 or max_tc > 0:
                computed_status = "in_progress"
            else:
                computed_status = "unwatched"

            progress = round(watched_files / total_files, 2) if total_files > 0 else 0.0

            h = r.get("torrent_hash", "")
            poster_file = r.get("poster_file")
            poster_url = f"/api/library/poster/{h}" if poster_file else None

            items.append(
                {
                    "hash": h,
                    "torrent_hash": h,
                    "title": r.get("title") or h,
                    "poster_file": poster_file,
                    "poster_url": poster_url,
                    "type": r.get("media_type") or "movie",
                    "media_type": r.get("media_type") or "movie",
                    "year": r.get("year"),
                    "rating": r.get("rating"),
                    "genres": genres,
                    "overview": r.get("overview") or r.get("overview_ru"),
                    "overview_ru": r.get("overview_ru"),
                    "status": computed_status,
                    "progress": progress,
                    "total_files": total_files,
                    "watched_files": watched_files,
                    "last_played_at": r.get("last_played_at"),
                }
            )

        return items

    async def get_season_progress(self, torrent_hash: str) -> dict[str, Any]:
        if torrent_hash.startswith("online:"):
            return {"total_files": 1, "watched_files": 0, "progress_percent": 0.0}

        files: list[dict[str, Any]] = []
        torrserver_url = self._get_ts_url()
        try:
            files = await self._torrserver.torrent_video_files(
                torrserver_url, torrent_hash
            )
        except (httpx.HTTPError, ExternalServiceError, OSError, RuntimeError):
            logger.debug(
                "TorrServer video files failed for %s, falling back to history",
                torrent_hash,
            )

        if not files:
            history_files = await anyio.to_thread.run_sync(
                self._library_repo.get_torrent_files_from_history, torrent_hash
            )
            if history_files:
                files = [
                    {
                        "id": hf["file_index"],
                        "name": hf["file_name"],
                        "length": hf.get("playback_duration") or 0,
                    }
                    for hf in history_files
                ]

        if not files:
            raise NotFoundError(t("err_files_not_found"))

        files = sort_video_files(files)

        try:
            history_map = await anyio.to_thread.run_sync(
                self._library_repo.get_file_history_map, torrent_hash
            )
        except sqlite3.Error as e:
            logger.error("Failed to load history map for %s: %s", torrent_hash, e)
            history_map = {}

        struct = _group_files_by_structure(files, history_map)

        season_results: dict[str, dict[str, Any]] = {}
        seasons = struct.get("seasons", {})
        movies = struct.get("movies", [])

        if seasons:
            sorted_keys = sorted(
                seasons.keys(),
                key=lambda k: int(k) if k.isdigit() else k,
            )
            for s_key in sorted_keys:
                s_files = seasons[s_key]
                total = len(s_files)
                watched = 0
                for f in s_files:
                    f_id = _extract_file_id(f)
                    if f_id is not None and history_map.get(f_id, {}).get("is_watched"):
                        watched += 1
                prog = round(watched / total, 2) if total > 0 else 0.0
                season_results[str(s_key)] = {
                    "season": str(s_key),
                    "total_files": total,
                    "watched_files": watched,
                    "progress": prog,
                    "is_completed": (watched == total) if total > 0 else False,
                    "episodes": s_files,
                }

        if not seasons:
            m_files = movies if movies else files
            total = len(m_files)
            watched = 0
            for f in m_files:
                f_id = _extract_file_id(f)
                if f_id is not None and history_map.get(f_id, {}).get("is_watched"):
                    watched += 1
            prog = round(watched / total, 2) if total > 0 else 0.0
            season_results["1"] = {
                "season": "1",
                "total_files": total,
                "watched_files": watched,
                "progress": prog,
                "is_completed": (watched == total) if total > 0 else False,
                "episodes": m_files,
            }
        elif movies:
            total = len(movies)
            watched = 0
            for f in movies:
                f_id = _extract_file_id(f)
                if f_id is not None and history_map.get(f_id, {}).get("is_watched"):
                    watched += 1
            prog = round(watched / total, 2) if total > 0 else 0.0
            extras_key = "Extras" if "Extras" not in season_results else "Other"
            season_results[extras_key] = {
                "season": extras_key,
                "total_files": total,
                "watched_files": watched,
                "progress": prog,
                "is_completed": (watched == total) if total > 0 else False,
                "episodes": movies,
            }

        total_files = sum(sp["total_files"] for sp in season_results.values())
        watched_files = sum(sp["watched_files"] for sp in season_results.values())
        overall_prog = round(watched_files / total_files, 2) if total_files > 0 else 0.0
        is_completed = (watched_files == total_files) if total_files > 0 else False

        res = {
            "hash": torrent_hash,
            "torrent_hash": torrent_hash,
            "total_files": total_files,
            "watched_files": watched_files,
            "progress": overall_prog,
            "is_completed": is_completed,
            "seasons": season_results,
        }
        for k, v in season_results.items():
            res[k] = v
        return res

    async def get_next_unwatched(self, torrent_hash: str) -> dict[str, Any]:
        if torrent_hash.startswith("online:"):
            return {}

        files: list[dict[str, Any]] = []
        torrserver_url = self._get_ts_url()
        try:
            files = await self._torrserver.torrent_video_files(
                torrserver_url, torrent_hash
            )
        except (httpx.HTTPError, ExternalServiceError, OSError, RuntimeError):
            logger.debug(
                "TorrServer video files failed for %s, falling back to history",
                torrent_hash,
            )

        if not files:
            history_files = await anyio.to_thread.run_sync(
                self._library_repo.get_torrent_files_from_history, torrent_hash
            )
            if history_files:
                files = [
                    {
                        "id": hf["file_index"],
                        "name": hf["file_name"],
                        "length": hf.get("playback_duration") or 0,
                    }
                    for hf in history_files
                ]

        if not files:
            raise NotFoundError(t("err_files_not_found"))

        files = sort_video_files(files)

        try:
            history_map = await anyio.to_thread.run_sync(
                self._library_repo.get_file_history_map, torrent_hash
            )
        except sqlite3.Error as e:
            logger.error("Failed to load history map for %s: %s", torrent_hash, e)
            history_map = {}

        next_file = None
        for f in files:
            raw_id = _extract_file_id(f)
            if raw_id is None:
                continue
            h = history_map.get(raw_id)
            if not h or not h.get("is_watched"):
                next_file = (f, h)
                break

        if not next_file:
            raise NotFoundError("Все файлы уже просмотрены")

        f, h = next_file
        file_id = _extract_file_id(f)
        if file_id is None:
            file_id = 0
        file_name = f.get("name") or f.get("file_name") or ""
        parsed = LibraryRepository.parse_ep(file_name)
        season = parsed[1] if parsed[0] == 1 else None
        episode = parsed[2] if parsed[0] == 1 else None

        return {
            "hash": torrent_hash,
            "torrent_hash": torrent_hash,
            "file_id": file_id,
            "file_name": file_name,
            "playback_timecode": (h.get("playback_timecode", 0) if h else 0) or 0,
            "playback_duration": (h.get("playback_duration", 0) if h else 0) or 0,
            "is_watched": False,
            "season": season,
            "episode": episode,
        }
