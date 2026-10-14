from datetime import datetime, timezone

from backend.repositories.base import BaseRepository
from backend.repositories.db import Database


class HistoryRepository(BaseRepository):
    def __init__(self, db: Database):
        super().__init__(db)

    def mark_played(
        self,
        torrent_hash: str,
        file_index: int,
        file_name: str,
        file_path: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat() + "Z"
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_file_history (
                    torrent_hash, file_index, file_name, file_path, first_played_at,
                    last_played_at, launch_count
                )
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(torrent_hash, file_index) DO UPDATE SET
                    last_played_at = excluded.last_played_at,
                    launch_count = launch_count + 1
            """,
                (torrent_hash, file_index, file_name, file_path, now, now),
            )

    def update_progress(
        self,
        torrent_hash: str,
        file_index: int,
        timecode: int,
        duration: int,
        audio_track: int = 0,
    ) -> None:
        is_watched = 1 if duration > 0 and (duration - timecode) < 180 else 0
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE media_file_history
                SET playback_timecode = ?, playback_duration = ?,
                    is_watched = CASE WHEN is_watched = 1 THEN 1 ELSE ? END,
                    audio_track = CASE WHEN ? > 0 THEN ? ELSE audio_track END
                WHERE torrent_hash = ? AND file_index = ?
            """,
                (
                    timecode,
                    duration,
                    is_watched,
                    audio_track,
                    audio_track,
                    torrent_hash,
                    file_index,
                ),
            )

    def list_history(self, limit: int = 200) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT h.torrent_hash, h.file_index, h.file_name, h.file_path,
                       h.playback_timecode, h.playback_duration, h.is_watched,
                       h.last_played_at, m.title, m.poster_file, m.year, t.media_type
                FROM media_file_history h
                LEFT JOIN media_metadata m ON h.torrent_hash = m.torrent_hash
                LEFT JOIN media_types t ON h.torrent_hash = t.torrent_hash
                ORDER BY h.last_played_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_watched(self, torrent_hash: str, file_index: int) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE media_file_history
                SET is_watched = 1,
                    playback_timecode = CASE
                        WHEN playback_duration > 0 THEN playback_duration
                        ELSE playback_timecode
                    END,
                    last_played_at = ?
                WHERE torrent_hash = ? AND file_index = ?
                """,
                (
                    datetime.now(timezone.utc).isoformat() + "Z",
                    torrent_hash,
                    file_index,
                ),
            )
        return cursor.rowcount > 0

    def delete_entry(self, torrent_hash: str, file_index: int) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                (
                    "DELETE FROM media_file_history "
                    "WHERE torrent_hash = ? AND file_index = ?"
                ),
                (torrent_hash, file_index),
            )
        return cursor.rowcount > 0
