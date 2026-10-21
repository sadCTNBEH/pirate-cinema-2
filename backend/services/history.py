import sqlite3
from typing import Any

import anyio

from backend.exceptions import DatabaseError, NotFoundError, ValidationError
from backend.repositories.history import HistoryRepository


class HistoryService:
    def __init__(
        self,
        history_repo: HistoryRepository,
        progress_service: Any = None,
    ):
        self._history_repo = history_repo
        self._progress_service = progress_service

    async def get_history(self, limit: int = 200) -> list[dict[str, Any]]:
        try:
            return await anyio.to_thread.run_sync(
                self._history_repo.list_history, limit
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while loading history") from e

    async def get_continue_watching(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            return await anyio.to_thread.run_sync(
                self._history_repo.list_continue_watching, limit
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while loading continue watching") from e

    async def mark_watched(
        self, torrent_hash: str, file_index: int, watched: bool = True
    ) -> None:
        try:
            updated = await anyio.to_thread.run_sync(
                self._history_repo.mark_watched, torrent_hash, file_index, watched
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while updating history") from e
        if not updated:
            raise NotFoundError("History entry not found")

    async def mark_watched_episode(
        self,
        title_id: str | None = None,
        imdb_id: str | None = None,
        torrent_hash: str | None = None,
        file_index: int | None = None,
        season: int | None = None,
        episode: int | None = None,
        watched: bool = True,
    ) -> None:
        if not title_id and not imdb_id and not torrent_hash:
            raise ValidationError("Either title_id, imdb_id, or torrent_hash is required")

        try:
            if torrent_hash and file_index is not None:
                await anyio.to_thread.run_sync(
                    self._history_repo.mark_watched,
                    torrent_hash,
                    file_index,
                    watched,
                )

            effective_title = imdb_id or title_id or torrent_hash
            if effective_title and season is not None and episode is not None:
                await anyio.to_thread.run_sync(
                    self._history_repo.mark_episode_watched,
                    effective_title,
                    season,
                    episode,
                    watched,
                )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while marking episode watched") from e

    async def delete_entry(self, torrent_hash: str, file_index: int) -> None:
        try:
            deleted = await anyio.to_thread.run_sync(
                self._history_repo.delete_entry, torrent_hash, file_index
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while deleting history entry") from e
        if not deleted:
            raise NotFoundError("History entry not found")

    async def delete_entry_by_id(self, entry_id: str) -> None:
        if ":" in entry_id:
            parts = entry_id.split(":", 1)
            try:
                f_idx = int(parts[1])
            except ValueError as e:
                raise ValidationError("Invalid file_index in history entry id") from e
            await self.delete_entry(parts[0], f_idx)
        else:
            await self.delete_entry(entry_id, 0)

    async def get_next_unwatched(
        self,
        imdb_id: str | None = None,
        season: int | None = None,
        title_id: str | None = None,
        torrent_hash: str | None = None,
    ) -> dict[str, Any] | None:
        ident = imdb_id or title_id or torrent_hash
        if not ident:
            raise ValidationError("Identifier (imdb_id, title_id, or torrent_hash) is required")

        if self._progress_service:
            return await self._progress_service.get_next_unwatched(ident, season)
        return None
