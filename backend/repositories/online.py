"""Repository for online playlists, playlist items, and online history."""

import uuid
from datetime import datetime, timezone

from backend.api.schemas.online import OnlineSearchResult, Playlist
from backend.repositories.base import BaseRepository
from backend.repositories.db import Database


class OnlineRepository(BaseRepository):
    def __init__(self, db: Database):
        super().__init__(db)

    # ─── Playlists ───

    def create_playlist(self, title: str, playlist_id: str | None = None) -> Playlist:
        pid = playlist_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        now_str = now.isoformat() + "Z"
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO online_playlists (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (pid, title.strip(), now_str, now_str),
            )
        return Playlist(id=pid, title=title.strip(), items=[], created_at=now)

    def list_playlists(self) -> list[Playlist]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, title, created_at
                FROM online_playlists
                ORDER BY updated_at DESC
                """
            ).fetchall()

            playlists: list[Playlist] = []
            for row in rows:
                item_rows = conn.execute(
                    """
                    SELECT item_id, provider, title, thumbnail, duration
                    FROM online_playlist_items
                    WHERE playlist_id = ?
                    ORDER BY position ASC
                    """,
                    (row["id"],),
                ).fetchall()

                items = [
                    OnlineSearchResult(
                        id=ir["item_id"],
                        title=ir["title"],
                        provider=ir["provider"],
                        thumbnail=ir["thumbnail"],
                        duration=ir["duration"],
                        is_playlist=False,
                    )
                    for ir in item_rows
                ]

                try:
                    dt = datetime.fromisoformat(row["created_at"].rstrip("Z")).replace(
                        tzinfo=timezone.utc
                    )
                except (ValueError, TypeError):
                    dt = datetime.now(timezone.utc)

                playlists.append(
                    Playlist(
                        id=row["id"],
                        title=row["title"],
                        items=items,
                        created_at=dt,
                    )
                )
        return playlists

    def get_playlist(self, playlist_id: str) -> Playlist | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, title, created_at
                FROM online_playlists
                WHERE id = ?
                """,
                (playlist_id,),
            ).fetchone()

            if not row:
                return None

            item_rows = conn.execute(
                """
                SELECT item_id, provider, title, thumbnail, duration
                FROM online_playlist_items
                WHERE playlist_id = ?
                ORDER BY position ASC
                """,
                (playlist_id,),
            ).fetchall()

            items = [
                OnlineSearchResult(
                    id=ir["item_id"],
                    title=ir["title"],
                    provider=ir["provider"],
                    thumbnail=ir["thumbnail"],
                    duration=ir["duration"],
                    is_playlist=False,
                )
                for ir in item_rows
            ]

            try:
                dt = datetime.fromisoformat(row["created_at"].rstrip("Z")).replace(
                    tzinfo=timezone.utc
                )
            except (ValueError, TypeError):
                dt = datetime.now(timezone.utc)

            return Playlist(
                id=row["id"],
                title=row["title"],
                items=items,
                created_at=dt,
            )

    def update_playlist(self, playlist_id: str, title: str) -> bool:
        now_str = datetime.now(timezone.utc).isoformat() + "Z"
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE online_playlists
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                (title.strip(), now_str, playlist_id),
            )
        return cursor.rowcount > 0

    def delete_playlist(self, playlist_id: str) -> bool:
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM online_playlist_items WHERE playlist_id = ?",
                (playlist_id,),
            )
            cursor = conn.execute(
                "DELETE FROM online_playlists WHERE id = ?",
                (playlist_id,),
            )
        return cursor.rowcount > 0

    def add_item_to_playlist(
        self, playlist_id: str, item: OnlineSearchResult, position: int | None = None
    ) -> bool:
        now_str = datetime.now(timezone.utc).isoformat() + "Z"
        item_uid = str(uuid.uuid4())
        with self.connection() as conn:
            # Verify playlist exists
            pl = conn.execute(
                "SELECT id FROM online_playlists WHERE id = ?", (playlist_id,)
            ).fetchone()
            if not pl:
                return False

            if position is None:
                max_pos = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM online_playlist_items WHERE playlist_id = ?",
                    (playlist_id,),
                ).fetchone()
                pos = max_pos["next_pos"] if max_pos else 0
            else:
                pos = position

            conn.execute(
                """
                INSERT INTO online_playlist_items (
                    id, playlist_id, item_id, provider, title, thumbnail, duration, position, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_uid,
                    playlist_id,
                    item.id,
                    item.provider,
                    item.title,
                    item.thumbnail,
                    item.duration,
                    pos,
                    now_str,
                ),
            )
            conn.execute(
                "UPDATE online_playlists SET updated_at = ? WHERE id = ?",
                (now_str, playlist_id),
            )
        return True

    def remove_item_from_playlist(self, playlist_id: str, item_id: str) -> bool:
        now_str = datetime.now(timezone.utc).isoformat() + "Z"
        with self.connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM online_playlist_items
                WHERE playlist_id = ? AND item_id = ?
                """,
                (playlist_id, item_id),
            )
            if cursor.rowcount > 0:
                conn.execute(
                    "UPDATE online_playlists SET updated_at = ? WHERE id = ?",
                    (now_str, playlist_id),
                )
                # Resequence positions to keep contiguous order
                items = conn.execute(
                    "SELECT id FROM online_playlist_items WHERE playlist_id = ? ORDER BY position ASC",
                    (playlist_id,),
                ).fetchall()
                for idx, itm in enumerate(items):
                    conn.execute(
                        "UPDATE online_playlist_items SET position = ? WHERE id = ?",
                        (idx, itm["id"]),
                    )
        return cursor.rowcount > 0

    # ─── Online History ───

    def mark_played(
        self,
        provider: str,
        item_id: str,
        title: str,
        thumbnail: str | None = None,
        duration: int | None = None,
    ) -> None:
        now_str = datetime.now(timezone.utc).isoformat() + "Z"
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO online_history (
                    provider, item_id, title, thumbnail, duration,
                    first_played_at, last_played_at, launch_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(provider, item_id) DO UPDATE SET
                    last_played_at = excluded.last_played_at,
                    launch_count = launch_count + 1,
                    title = excluded.title,
                    thumbnail = COALESCE(excluded.thumbnail, online_history.thumbnail),
                    duration = COALESCE(excluded.duration, online_history.duration)
                """,
                (provider, item_id, title, thumbnail, duration, now_str, now_str),
            )

    def update_progress(
        self,
        provider: str,
        item_id: str,
        timecode: int,
        duration: int,
    ) -> None:
        is_watched = 1 if duration > 0 and (duration - timecode) < 180 else 0
        now_str = datetime.now(timezone.utc).isoformat() + "Z"
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE online_history
                SET playback_timecode = ?,
                    playback_duration = ?,
                    is_watched = CASE WHEN is_watched = 1 THEN 1 ELSE ? END,
                    last_played_at = ?
                WHERE provider = ? AND item_id = ?
                """,
                (timecode, duration, is_watched, now_str, provider, item_id),
            )

    def get_progress(self, provider: str, item_id: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT provider, item_id, title, thumbnail, duration,
                       playback_timecode, playback_duration, is_watched, last_played_at
                FROM online_history
                WHERE provider = ? AND item_id = ?
                """,
                (provider, item_id),
            ).fetchone()
        return dict(row) if row else None

    def list_history(self, limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT provider, item_id, title, thumbnail, duration,
                       playback_timecode, playback_duration, is_watched,
                       last_played_at, launch_count
                FROM online_history
                ORDER BY last_played_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_history_item(self, provider: str, item_id: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM online_history WHERE provider = ? AND item_id = ?",
                (provider, item_id),
            )
        return cursor.rowcount > 0

    def clear_history(self) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM online_history")
