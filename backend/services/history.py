import sqlite3

import anyio

from backend.exceptions import DatabaseError, NotFoundError
from backend.repositories.history import HistoryRepository


class HistoryService:
    def __init__(self, history_repo: HistoryRepository):
        self._history_repo = history_repo

    async def get_history(self, limit: int = 200) -> list[dict]:
        try:
            return await anyio.to_thread.run_sync(
                self._history_repo.list_history, limit
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while loading history") from e

    async def mark_watched(self, torrent_hash: str, file_index: int) -> None:
        try:
            updated = await anyio.to_thread.run_sync(
                self._history_repo.mark_watched, torrent_hash, file_index
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while updating history") from e
        if not updated:
            raise NotFoundError("History entry not found")

    async def delete_entry(self, torrent_hash: str, file_index: int) -> None:
        try:
            deleted = await anyio.to_thread.run_sync(
                self._history_repo.delete_entry, torrent_hash, file_index
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while deleting history entry") from e
        if not deleted:
            raise NotFoundError("History entry not found")
