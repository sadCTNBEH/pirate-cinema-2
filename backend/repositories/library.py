import re
from typing import Any

from backend.repositories.base import BaseRepository
from backend.repositories.db import Database


class LibraryRepository(BaseRepository):
    def __init__(self, db: Database):
        super().__init__(db)

    def get_recent_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT h.torrent_hash, h.file_index, h.file_name, h.playback_timecode, h.playback_duration,
                       h.is_watched, h.last_played_at, m.title, m.poster_file, m.year
                FROM media_file_history h
                LEFT JOIN media_metadata m ON h.torrent_hash = m.torrent_hash
                WHERE h.launch_count > 0 AND h.is_watched = 0
                ORDER BY h.last_played_at DESC
                LIMIT ?
            """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def fetch_poster_meta(self, hashes: list[str]) -> dict[str, str]:
        if not hashes:
            return {}
        placeholders = ",".join("?" for _ in hashes)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT torrent_hash, poster_file FROM media_metadata WHERE torrent_hash IN ({placeholders})",
                hashes,
            ).fetchall()
        return {r["torrent_hash"]: r["poster_file"] for r in rows if r["poster_file"]}

    def get_file_history_map(self, torrent_hash: str) -> dict[int, dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT file_index, playback_timecode, is_watched FROM media_file_history WHERE torrent_hash = ?",
                (torrent_hash,),
            ).fetchall()
        return {row["file_index"]: dict(row) for row in rows}

    def has_poster(self, torrent_hash: str) -> bool:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT poster_file FROM media_metadata WHERE torrent_hash = ?",
                (torrent_hash,),
            ).fetchone()
            return bool(row and row["poster_file"])

    def has_full_metadata(self, torrent_hash: str) -> bool:
        """Return True if full metadata (title/overview) has already been fetched and saved,
        even if poster download failed. Used to prevent repeated re-fetch attempts."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT title, overview, rating FROM media_metadata WHERE torrent_hash = ?",
                (torrent_hash,),
            ).fetchone()
            if not row:
                return False
            # If we have any enriched data (not just the hash itself as title), metadata was fetched
            title = row["title"] or ""
            return bool(row["overview"] or row["rating"] or (title and title != torrent_hash))

    def delete_history_by_hash(self, torrent_hash: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM media_file_history WHERE torrent_hash=?", (torrent_hash,)
            )
            conn.commit()

    def delete_torrent(self, torrent_hash: str) -> None:
        raw_hash = str(torrent_hash or "").strip()
        if not raw_hash:
            return
        hashes = list({raw_hash, raw_hash.lower(), raw_hash.upper()})
        placeholders = ",".join("?" for _ in hashes)
        with self.connection() as conn:
            conn.execute(
                f"DELETE FROM media_metadata WHERE torrent_hash IN ({placeholders})",
                hashes,
            )
            conn.execute(
                f"DELETE FROM media_types WHERE torrent_hash IN ({placeholders})",
                hashes,
            )
            conn.execute(
                f"DELETE FROM media_audio_tracks WHERE torrent_hash IN ({placeholders})",
                hashes,
            )
            conn.execute(
                f"DELETE FROM media_file_history WHERE torrent_hash IN ({placeholders})",
                hashes,
            )
            conn.commit()

    def delete_all_torrents(self) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM media_metadata")
            conn.execute("DELETE FROM media_types")
            conn.execute("DELETE FROM media_audio_tracks")
            conn.execute("DELETE FROM media_file_history")
            conn.commit()

    def get_torrent_files_from_history(self, torrent_hash: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT file_index, file_name, file_path, playback_timecode, playback_duration, is_watched, last_played_at
                FROM media_file_history
                WHERE torrent_hash = ?
                ORDER BY file_index ASC
                """,
                (torrent_hash,),
            ).fetchall()
        return [dict(r) for r in rows]

    def ensure_torrent(self, torrent_hash: str, title: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_metadata (torrent_hash, title)
                VALUES (?, ?)
                ON CONFLICT(torrent_hash) DO NOTHING
                """,
                (torrent_hash, title or torrent_hash),
            )
            conn.commit()

    def save_media_type(self, torrent_hash: str, media_type: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_types (torrent_hash, media_type)
                VALUES (?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET media_type=excluded.media_type
                """,
                (torrent_hash, media_type),
            )
            conn.commit()

    def query_library(
        self,
        media_type: str | None = None,
        status: str | None = None,
        year: int | None = None,
        genre: str | None = None,
        sort: str | None = None,
        hashes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if media_type and media_type.lower() not in ("all", ""):
            if media_type.lower() == "movie":
                conditions.append("LOWER(COALESCE(t.media_type, 'movie')) = 'movie'")
            else:
                conditions.append("LOWER(COALESCE(t.media_type, '')) = ?")
                params.append(media_type.lower())

        if year is not None:
            conditions.append("m.year = ?")
            params.append(year)

        genre_val = genre
        if genre_val is not None:
            raw_genres = (
                genre_val
                if isinstance(genre_val, list)
                else [g.strip() for g in str(genre_val).split(",") if g.strip()]
            )
            valid_genres = [
                g.lower() for g in raw_genres if g.lower() not in ("all", "")
            ]
            if valid_genres:
                clauses = [
                    "LOWER(COALESCE(m.genres_json, '')) LIKE ?" for _ in valid_genres
                ]
                conditions.append(f"({' OR '.join(clauses)})")
                for g in valid_genres:
                    params.append(f"%{g}%")

        if status and status.lower() not in ("all", ""):
            st = status.lower()
            if st in ("watched", "completed"):
                conditions.append(
                    "COALESCE(h.watched_files, 0) > 0 AND COALESCE(h.watched_files, 0) >= COALESCE(h.total_files, 0)"
                )
            elif st == "unwatched":
                conditions.append(
                    "COALESCE(h.watched_files, 0) = 0 AND COALESCE(h.max_timecode, 0) = 0"
                )
            elif st in ("in_progress", "watching"):
                conditions.append(
                    "((COALESCE(h.watched_files, 0) > 0 AND COALESCE(h.watched_files, 0) < COALESCE(h.total_files, 0)) "
                    "OR (COALESCE(h.watched_files, 0) = 0 AND COALESCE(h.max_timecode, 0) > 0))"
                )

        if hashes is not None:
            if not hashes:
                return []
            placeholders = ",".join("?" for _ in hashes)
            conditions.append(f"a.torrent_hash IN ({placeholders})")
            params.extend(hashes)

        order_by = "ORDER BY COALESCE(h.last_played_at, '') DESC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"

        if sort:
            s = sort.strip().lower()
            if s in ("title", "title_asc"):
                order_by = (
                    "ORDER BY COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"
                )
            elif s in ("title_desc", "-title"):
                order_by = (
                    "ORDER BY COALESCE(m.title, a.torrent_hash) COLLATE NOCASE DESC"
                )
            elif s in ("year", "year_desc", "-year"):
                order_by = "ORDER BY CASE WHEN m.year IS NULL THEN 1 ELSE 0 END, m.year DESC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"
            elif s in ("year_asc", "+year"):
                order_by = "ORDER BY CASE WHEN m.year IS NULL THEN 1 ELSE 0 END, m.year ASC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"
            elif s in ("rating", "rating_desc", "-rating"):
                order_by = "ORDER BY CASE WHEN m.rating IS NULL THEN 1 ELSE 0 END, m.rating DESC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"
            elif s in ("rating_asc", "+rating"):
                order_by = "ORDER BY CASE WHEN m.rating IS NULL THEN 1 ELSE 0 END, m.rating ASC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"
            elif s in (
                "added",
                "added_desc",
                "-added",
                "date",
                "recent",
                "last_played",
                "last_played_desc",
                "-last_played",
                "-date",
            ):
                order_by = "ORDER BY COALESCE(h.last_played_at, '') DESC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"
            elif s in ("added_asc", "+added", "last_played_asc", "+last_played", "+date"):
                order_by = "ORDER BY COALESCE(h.last_played_at, '') ASC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"
            elif s in ("progress", "progress_desc", "-progress"):
                order_by = "ORDER BY (CASE WHEN COALESCE(h.total_files, 0) > 0 THEN CAST(h.watched_files AS REAL)/h.total_files ELSE 0 END) DESC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"
            elif s in ("progress_asc", "+progress"):
                order_by = "ORDER BY (CASE WHEN COALESCE(h.total_files, 0) > 0 THEN CAST(h.watched_files AS REAL)/h.total_files ELSE 0 END) ASC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC"

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            WITH all_torrents AS (
                SELECT torrent_hash FROM media_metadata
                UNION
                SELECT torrent_hash FROM media_types
                UNION
                SELECT torrent_hash FROM media_file_history
            ),
            h_stats AS (
                SELECT 
                    torrent_hash,
                    COUNT(*) AS total_files,
                    SUM(CASE WHEN is_watched = 1 THEN 1 ELSE 0 END) AS watched_files,
                    MAX(playback_timecode) AS max_timecode,
                    MAX(last_played_at) AS last_played_at
                FROM media_file_history
                GROUP BY torrent_hash
            )
            SELECT 
                a.torrent_hash,
                COALESCE(m.title, a.torrent_hash) AS title,
                m.overview,
                m.year,
                m.rating,
                m.poster_file,
                m.genres_json,
                m.overview_ru,
                t.media_type,
                COALESCE(h.total_files, 0) AS total_files,
                COALESCE(h.watched_files, 0) AS watched_files,
                COALESCE(h.max_timecode, 0) AS max_timecode,
                h.last_played_at
            FROM all_torrents a
            LEFT JOIN media_metadata m ON a.torrent_hash = m.torrent_hash
            LEFT JOIN media_types t ON a.torrent_hash = t.torrent_hash
            LEFT JOIN h_stats h ON a.torrent_hash = h.torrent_hash
            {where_clause}
            {order_by}
        """

        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def natural_key(text: str) -> list[int | str]:
        return [
            int(c) if c.isdigit() else c.lower()
            for c in re.split(r"(\d+)", str(text or ""))
        ]

    @staticmethod
    def parse_ep(name: str) -> tuple:
        name = str(name or "")
        base_sort_name = LibraryRepository.natural_key(name)

        # 1. S01E05, S1 E5, S01.E05, S01_E05
        m = re.search(r"S(\d+)[\.\-\s_]*E(\d+)", name, re.IGNORECASE)
        if m:
            return (1, int(m.group(1)), int(m.group(2)), base_sort_name)

        # 2. 1x05, 01x05
        m = re.search(r"(\d+)x(\d+)", name, re.IGNORECASE)
        if m:
            return (1, int(m.group(1)), int(m.group(2)), base_sort_name)

        # 3. Episode 05, Ep 05, E05, Ep.5, E 5
        m = re.search(r"\b(?:Episode|Ep|E)[\.\-\s_]*(\d+)", name, re.IGNORECASE)
        if m:
            return (1, 1, int(m.group(1)), base_sort_name)

        # 4. Фильмы или неизвестный формат
        return (0, 0, 0, base_sort_name)

    @staticmethod
    def sort_key(name: str) -> tuple:
        parsed = LibraryRepository.parse_ep(name)
        is_series, season, episode, base_sort_name = parsed
        type_priority = 0 if is_series == 1 else 1
        return (type_priority, season, episode, base_sort_name)
