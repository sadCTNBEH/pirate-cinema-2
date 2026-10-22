from datetime import datetime, timezone
from typing import Any

from backend.repositories.base import BaseRepository
from backend.repositories.db import Database
from backend.repositories.library import LibraryRepository


class HistoryRepository(BaseRepository):
    def __init__(self, db: Database):
        super().__init__(db)

    def mark_played(
        self,
        torrent_hash: str,
        file_index: int,
        file_name: str,
        file_path: str | None = None,
        season: int | None = None,
        episode: int | None = None,
        imdb_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat() + "Z"
        if season is None or episode is None:
            parsed = LibraryRepository.parse_ep(file_name)
            if parsed[0] == 1:
                season = parsed[1]
                episode = parsed[2]

        with self.connection() as conn:
            if not imdb_id:
                row = conn.execute(
                    "SELECT imdb_id FROM media_metadata WHERE torrent_hash = ?",
                    (torrent_hash,),
                ).fetchone()
                if row and row["imdb_id"]:
                    imdb_id = str(row["imdb_id"])

            conn.execute(
                """
                INSERT INTO media_file_history (
                    torrent_hash, file_index, file_name, file_path, first_played_at,
                    last_played_at, launch_count, season, episode, imdb_id
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(torrent_hash, file_index) DO UPDATE SET
                    last_played_at = excluded.last_played_at,
                    launch_count = launch_count + 1,
                    season = COALESCE(excluded.season, media_file_history.season),
                    episode = COALESCE(excluded.episode, media_file_history.episode),
                    imdb_id = COALESCE(excluded.imdb_id, media_file_history.imdb_id)
            """,
                (
                    torrent_hash,
                    file_index,
                    file_name,
                    file_path,
                    now,
                    now,
                    season,
                    episode,
                    imdb_id,
                ),
            )

    def update_progress(
        self,
        torrent_hash: str,
        file_index: int,
        timecode: int,
        duration: int,
        audio_track: int = 0,
    ) -> None:
        tc = max(0, int(timecode))
        dur = max(0, int(duration))
        if dur > 0 and tc > dur:
            tc = dur
        is_watched = (
            1
            if dur > 0 and ((dur - tc) <= 180 or (tc / dur) >= 0.90)
            else 0
        )
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
                    tc,
                    dur,
                    is_watched,
                    audio_track,
                    audio_track,
                    torrent_hash,
                    file_index,
                ),
            )

    def list_history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT (h.torrent_hash || ':' || h.file_index) AS id,
                       h.torrent_hash, h.file_index, h.file_name, h.file_path,
                       h.playback_timecode, h.playback_duration, h.is_watched,
                       h.season, h.episode, h.imdb_id,
                       h.last_played_at, m.title, m.poster_file, m.year, t.media_type
                FROM media_file_history h
                LEFT JOIN media_metadata m ON h.torrent_hash = m.torrent_hash
                LEFT JOIN media_types t ON h.torrent_hash = t.torrent_hash
                WHERE h.torrent_hash NOT LIKE 'online:%'
                ORDER BY h.last_played_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_continue_watching(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT (h.torrent_hash || ':' || h.file_index) AS id,
                       h.torrent_hash, h.file_index, h.file_name, h.file_path,
                       h.playback_timecode, h.playback_duration, h.is_watched,
                       h.season, h.episode, h.imdb_id,
                       h.last_played_at, m.title, m.poster_file, m.year, t.media_type
                FROM media_file_history h
                LEFT JOIN media_metadata m ON h.torrent_hash = m.torrent_hash
                LEFT JOIN media_types t ON h.torrent_hash = t.torrent_hash
                WHERE h.launch_count > 0 AND h.is_watched = 0 AND h.playback_timecode > 0 AND h.torrent_hash NOT LIKE 'online:%'
                ORDER BY h.last_played_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        items: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            tc = d.get("playback_timecode") or 0
            dur = d.get("playback_duration") or 0
            d["position_seconds"] = float(tc)
            d["duration_seconds"] = float(dur) if dur > 0 else None
            d["watched"] = bool(d.get("is_watched"))
            d["title_id"] = d.get("imdb_id") or d.get("torrent_hash")
            d["infohash"] = d.get("torrent_hash")
            items.append(d)
        return items

    def get_file_entry(
        self, torrent_hash: str, file_index: int
    ) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT (h.torrent_hash || ':' || h.file_index) AS id,
                       h.torrent_hash, h.file_index, h.file_name, h.file_path,
                       h.playback_timecode, h.playback_duration, h.is_watched,
                       h.season, h.episode, h.imdb_id,
                       h.last_played_at, m.title, m.poster_file, m.year, t.media_type
                FROM media_file_history h
                LEFT JOIN media_metadata m ON h.torrent_hash = m.torrent_hash
                LEFT JOIN media_types t ON h.torrent_hash = t.torrent_hash
                WHERE h.torrent_hash = ? AND h.file_index = ?
                """,
                (torrent_hash, file_index),
            ).fetchone()
            if row:
                return dict(row)
        return None

    def mark_watched(
        self, torrent_hash: str, file_index: int, watched: bool = True
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat() + "Z"
        with self.connection() as conn:
            if watched:
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
                    (now, torrent_hash, file_index),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE media_file_history
                    SET is_watched = 0,
                        playback_timecode = 0,
                        last_played_at = ?
                    WHERE torrent_hash = ? AND file_index = ?
                    """,
                    (now, torrent_hash, file_index),
                )

            # If this file has season & episode, also update episode state
            file_row = conn.execute(
                "SELECT season, episode, imdb_id FROM media_file_history WHERE torrent_hash = ? AND file_index = ?",
                (torrent_hash, file_index),
            ).fetchone()
            if file_row and file_row["season"] is not None and file_row["episode"] is not None:
                title_id = file_row["imdb_id"] or torrent_hash
                s = int(file_row["season"])
                e = int(file_row["episode"])
                conn.execute(
                    """
                    INSERT INTO media_episode_history (title_id, season, episode, is_watched, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(title_id, season, episode) DO UPDATE SET
                        is_watched = excluded.is_watched,
                        updated_at = excluded.updated_at
                    """,
                    (title_id, s, e, 1 if watched else 0, now),
                )

        return cursor.rowcount > 0

    def mark_episode_watched(
        self,
        title_id: str,
        season: int,
        episode: int,
        watched: bool = True,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat() + "Z"
        status_val = 1 if watched else 0
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_episode_history (title_id, season, episode, is_watched, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(title_id, season, episode) DO UPDATE SET
                    is_watched = excluded.is_watched,
                    updated_at = excluded.updated_at
                """,
                (title_id, season, episode, status_val, now),
            )

            # Also update any physical files in media_file_history matching this title & season/episode
            if watched:
                conn.execute(
                    """
                    UPDATE media_file_history
                    SET is_watched = 1,
                        playback_timecode = CASE
                            WHEN playback_duration > 0 THEN playback_duration
                            ELSE playback_timecode
                        END,
                        last_played_at = ?
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season = ? AND episode = ?
                    """,
                    (now, title_id, title_id, season, episode),
                )
            else:
                conn.execute(
                    """
                    UPDATE media_file_history
                    SET is_watched = 0,
                        playback_timecode = 0,
                        last_played_at = ?
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season = ? AND episode = ?
                    """,
                    (now, title_id, title_id, season, episode),
                )

        return True

    def get_watched_episodes_map(
        self, title_id: str, season: int | None = None
    ) -> set[tuple[int, int]]:
        watched_set: set[tuple[int, int]] = set()
        with self.connection() as conn:
            # 1. From media_episode_history
            if season is not None:
                rows_ep = conn.execute(
                    """
                    SELECT season, episode FROM media_episode_history
                    WHERE title_id = ? AND season = ? AND is_watched = 1
                    """,
                    (title_id, season),
                ).fetchall()
            else:
                rows_ep = conn.execute(
                    """
                    SELECT season, episode FROM media_episode_history
                    WHERE title_id = ? AND is_watched = 1
                    """,
                    (title_id,),
                ).fetchall()
            for r in rows_ep:
                watched_set.add((int(r["season"]), int(r["episode"])))

            # 2. From media_file_history
            if season is not None:
                rows_file = conn.execute(
                    """
                    SELECT season, episode FROM media_file_history
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season = ? AND is_watched = 1
                    """,
                    (title_id, title_id, season),
                ).fetchall()
            else:
                rows_file = conn.execute(
                    """
                    SELECT season, episode FROM media_file_history
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season IS NOT NULL AND episode IS NOT NULL AND is_watched = 1
                    """,
                    (title_id, title_id),
                ).fetchall()
            for r in rows_file:
                if r["season"] is not None and r["episode"] is not None:
                    watched_set.add((int(r["season"]), int(r["episode"])))

        return watched_set

    def delete_entry(self, torrent_hash: str, file_index: int) -> bool:
        with self.connection() as conn:
            entry = conn.execute(
                """
                SELECT season, episode, imdb_id, is_watched
                FROM media_file_history
                WHERE torrent_hash = ? AND file_index = ?
                """,
                (torrent_hash, file_index),
            ).fetchone()

            cursor = conn.execute(
                "DELETE FROM media_file_history WHERE torrent_hash = ? AND file_index = ?",
                (torrent_hash, file_index),
            )
            deleted = cursor.rowcount > 0

            # If entry had season/episode, recheck logical episode state
            if deleted and entry and entry["season"] is not None and entry["episode"] is not None:
                s = int(entry["season"])
                e = int(entry["episode"])
                title_id = entry["imdb_id"] or torrent_hash

                remaining_watched = conn.execute(
                    """
                    SELECT 1 FROM media_file_history
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season = ? AND episode = ? AND is_watched = 1
                    LIMIT 1
                    """,
                    (title_id, title_id, s, e),
                ).fetchone()

                if not remaining_watched:
                    # Remove from media_episode_history so deleted file doesn't leave false watched state
                    conn.execute(
                        """
                        DELETE FROM media_episode_history
                        WHERE (title_id = ? OR title_id = ?) AND season = ? AND episode = ?
                        """,
                        (title_id, torrent_hash, s, e),
                    )

        return deleted
