import inspect
import logging
import sqlite3
from collections.abc import Callable
from typing import Any

import anyio
import httpx

from backend.exceptions import DatabaseError, ExternalServiceError, NotFoundError
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository

logger = logging.getLogger(__name__)


class SeasonProgressService:
    def __init__(
        self,
        history_repo: HistoryRepository,
        metadata_repo: MetadataRepository,
        library_repo: LibraryRepository,
        torrserver_client: Any,
        settings_provider: Callable[[], str],
        metadata_service: Any = None,
    ):
        self._history_repo = history_repo
        self._metadata_repo = metadata_repo
        self._library_repo = library_repo
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider
        self._metadata_service = metadata_service

    async def get_season_progress(self, identifier: str) -> dict[str, Any]:
        target = str(identifier or "").strip()
        if not target:
            raise NotFoundError("Identifier is required")

        if target.startswith("online:"):
            return {
                "title_id": target,
                "torrent_hash": target,
                "hash": target,
                "total_files": 1,
                "watched_files": 0,
                "progress": 0.0,
                "is_completed": False,
                "seasons": [
                    {
                        "season": 1,
                        "watched": 0,
                        "total": 1,
                        "progress_percent": 0.0,
                        "next_episode": 1,
                        "total_files": 1,
                        "watched_files": 0,
                        "progress": 0.0,
                        "is_completed": False,
                    }
                ],
            }

        # Step 1: Resolve imdb_id if target is a torrent hash
        imdb_id: str | None = None
        if target.startswith("tt"):
            imdb_id = target
        else:
            try:
                imdb_id = await anyio.to_thread.run_sync(
                    self._metadata_repo.get_imdb_id, target
                )
            except sqlite3.Error as e:
                logger.debug("Could not resolve imdb_id for %s: %s", target, e)

        # Step 2: Try to get canonical episode catalog from metadata service
        episodes_by_season: dict[int, list[int]] = {}
        if imdb_id and self._metadata_service:
            try:
                meta = None
                fetcher = getattr(self._metadata_service, "movie_meta", None) or getattr(
                    self._metadata_service, "details", None
                )
                if callable(fetcher):
                    res = fetcher(imdb_id, "series")
                    if inspect.isawaitable(res):
                        meta = await res
                    else:
                        meta = res

                if meta and isinstance(meta.get("videos"), list):
                    for v in meta["videos"]:
                        if isinstance(v, dict) and "season" in v and "episode" in v:
                            try:
                                s = int(v["season"])
                                e = int(v["episode"])
                                if s > 0 and e > 0:
                                    episodes_by_season.setdefault(s, []).append(e)
                            except (ValueError, TypeError):
                                pass
            except (ExternalServiceError, NotFoundError, httpx.HTTPError, ValueError, KeyError) as e:
                logger.debug("Failed to fetch series catalog for %s: %s", imdb_id, e)

        # Step 3: Fallback to torrent video files if catalog has no episodes
        if not episodes_by_season and not target.startswith("tt"):
            files: list[dict[str, Any]] = []
            torrserver_url = self._get_ts_url()
            try:
                files = await self._torrserver.torrent_video_files(
                    torrserver_url, target
                )
            except (httpx.HTTPError, ExternalServiceError, OSError, RuntimeError, ValueError):
                logger.debug("TorrServer video files failed for %s, falling back to history", target)

            if not files:
                try:
                    history_files = await anyio.to_thread.run_sync(
                        self._library_repo.get_torrent_files_from_history, target
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
                except sqlite3.Error as e:
                    logger.debug("History query failed for %s: %s", target, e)

            if files:
                try:
                    await anyio.to_thread.run_sync(
                        self._library_repo.save_total_files, target, len(files)
                    )
                except sqlite3.Error:
                    pass

            unmatched_files = []
            for f in files:
                name = f.get("name") or f.get("file_name") or ""
                parsed = LibraryRepository.parse_ep(name)
                if parsed[0] == 1:
                    s = int(parsed[1])
                    e = int(parsed[2])
                    episodes_by_season.setdefault(s, []).append(e)
                else:
                    unmatched_files.append(f)

            if not episodes_by_season and unmatched_files:
                for idx, _ in enumerate(unmatched_files, start=1):
                    episodes_by_season.setdefault(1, []).append(idx)

        if not episodes_by_season:
            has_meta = False
            try:
                has_meta = await anyio.to_thread.run_sync(
                    self._library_repo.has_full_metadata, target
                )
            except sqlite3.Error:
                pass
            if not has_meta and not target.startswith("tt"):
                raise NotFoundError(f"Media '{target}' not found")

        # Step 4: Get watched episodes
        try:
            watched_set = await anyio.to_thread.run_sync(
                self._history_repo.get_watched_episodes_map, target
            )
            if imdb_id and imdb_id != target:
                imdb_watched = await anyio.to_thread.run_sync(
                    self._history_repo.get_watched_episodes_map, imdb_id
                )
                watched_set.update(imdb_watched)
        except sqlite3.Error as e:
            logger.error("Failed to load watched episodes map for %s: %s", target, e)
            raise DatabaseError("Database error while loading watched episodes") from e

        seasons_list: list[dict[str, Any]] = []
        seasons_dict: dict[str, dict[str, Any]] = {}
        for s in sorted(episodes_by_season.keys()):
            known_eps = sorted(set(episodes_by_season[s]))
            total = len(known_eps)
            watched = sum(1 for ep in known_eps if (s, ep) in watched_set)
            prog_pct = round((watched / total) * 100.0, 1) if total > 0 else 0.0
            next_ep = next((ep for ep in known_eps if (s, ep) not in watched_set), None)
            is_comp = (watched == total) if total > 0 else False

            item = {
                "season": s,
                "watched": watched,
                "total": total,
                "progress_percent": prog_pct,
                "next_episode": next_ep,
                "watched_files": watched,
                "total_files": total,
                "progress": round(prog_pct / 100.0, 2),
                "is_completed": is_comp,
                "episodes": [
                    {"season": s, "episode": ep, "is_watched": (s, ep) in watched_set}
                    for ep in known_eps
                ],
            }
            seasons_list.append(item)
            seasons_dict[str(s)] = item

        total_files = sum(s["total"] for s in seasons_list)
        watched_files = sum(s["watched"] for s in seasons_list)
        overall_progress = (
            round(watched_files / total_files, 2) if total_files > 0 else 0.0
        )
        is_all_completed = (watched_files == total_files) if total_files > 0 else False

        return {
            "title_id": target,
            "torrent_hash": target,
            "hash": target,
            "total_files": total_files,
            "watched_files": watched_files,
            "progress": overall_progress,
            "is_completed": is_all_completed,
            "seasons": seasons_dict,
            "seasons_list": seasons_list,
            "watched_episode_keys": [f"{s}:{ep}" for s, ep in watched_set],
        }

    async def get_next_unwatched(
        self,
        identifier: str,
        season: int | None = None,
    ) -> dict[str, Any] | None:
        progress = await self.get_season_progress(identifier)
        seasons_list = progress.get("seasons_list", [])
        if not seasons_list and isinstance(progress.get("seasons"), dict):
            seasons_list = list(progress["seasons"].values())
        if not seasons_list:
            return None

        chosen_season = None
        if season is not None:
            chosen_season = next(
                (s for s in seasons_list if str(s.get("season")) == str(season)), None
            )
        else:
            chosen_season = next(
                (s for s in seasons_list if s.get("next_episode") is not None), None
            )

        if not chosen_season or chosen_season.get("next_episode") is None:
            return None

        s_num = chosen_season["season"]
        ep_num = chosen_season["next_episode"]

        target_hash = identifier
        if identifier.startswith("tt"):
            try:
                def _get_hash_for_imdb():
                    with self._metadata_repo._db.get_connection() as conn:
                        row = conn.execute(
                            "SELECT torrent_hash FROM media_metadata WHERE imdb_id = ? AND torrent_hash IS NOT NULL AND torrent_hash != '' LIMIT 1",
                            (identifier,),
                        ).fetchone()
                        if row and row["torrent_hash"]:
                            return str(row["torrent_hash"])
                        row = conn.execute(
                            "SELECT torrent_hash FROM media_file_history WHERE imdb_id = ? AND torrent_hash IS NOT NULL AND torrent_hash != '' LIMIT 1",
                            (identifier,),
                        ).fetchone()
                        if row and row["torrent_hash"]:
                            return str(row["torrent_hash"])
                    return None

                found_hash = await anyio.to_thread.run_sync(_get_hash_for_imdb)
                if found_hash:
                    target_hash = found_hash
            except sqlite3.Error:
                pass

        files: list[dict[str, Any]] = []
        if not target_hash.startswith("tt") and not target_hash.startswith("online:") and hasattr(self._torrserver, "torrent_video_files"):
            torrserver_url = self._get_ts_url()
            try:
                res = self._torrserver.torrent_video_files(
                    torrserver_url, target_hash
                )
                if inspect.isawaitable(res):
                    files = await res
                elif isinstance(res, list):
                    files = res
            except (httpx.HTTPError, ExternalServiceError, OSError, RuntimeError, ValueError):
                pass

        if not files:
            try:
                history_files = await anyio.to_thread.run_sync(
                    self._library_repo.get_torrent_files_from_history, target_hash
                )
                if history_files:
                    files = [
                        {
                            "id": hf.get("file_index", 0),
                            "name": hf.get("file_name", ""),
                            "length": hf.get("playback_duration") or 0,
                        }
                        for hf in history_files
                    ]
            except sqlite3.Error:
                pass

        file_id = 0
        file_name = ""
        matched = False
        unmatched_files: list[dict[str, Any]] = []

        for f in files:
            fname = f.get("name") or f.get("file_name") or ""
            parsed = LibraryRepository.parse_ep(fname)
            if parsed[0] == 1:
                if parsed[1] == s_num and parsed[2] == ep_num:
                    file_id = f.get("id", 0)
                    file_name = fname
                    matched = True
                    break
            else:
                unmatched_files.append(f)

        if not matched and unmatched_files and s_num == 1 and 1 <= ep_num <= len(unmatched_files):
            target_f = unmatched_files[ep_num - 1]
            file_id = target_f.get("id", 0)
            file_name = target_f.get("name") or target_f.get("file_name") or ""

        return {
            "found": True,
            "title_id": identifier,
            "torrent_hash": target_hash,
            "hash": target_hash,
            "file_id": file_id,
            "file_index": file_id,
            "file_name": file_name,
            "season": s_num,
            "episode": ep_num,
            "next_episode": ep_num,
        }
