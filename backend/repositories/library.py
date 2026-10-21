from datetime import datetime, timezone
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
                       h.is_watched, h.last_played_at, h.season, h.episode, h.imdb_id,
                       m.title, m.poster_file, m.year
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

    def ensure_torrent(
        self,
        torrent_hash: str,
        title: str | None = None,
        total_files: int | None = None,
        added_at: str | None = None,
    ) -> None:
        now = added_at or (datetime.now(timezone.utc).isoformat() + "Z")
        with self.connection() as conn:
            if total_files and total_files > 0:
                conn.execute(
                    """
                    INSERT INTO media_metadata (torrent_hash, title, total_files, added_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(torrent_hash) DO UPDATE SET
                        title = COALESCE(excluded.title, media_metadata.title),
                        total_files = CASE WHEN excluded.total_files > 0 THEN excluded.total_files ELSE media_metadata.total_files END,
                        added_at = COALESCE(media_metadata.added_at, excluded.added_at)
                    """,
                    (torrent_hash, title or torrent_hash, total_files, now),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO media_metadata (torrent_hash, title, added_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(torrent_hash) DO UPDATE SET
                        title = COALESCE(excluded.title, media_metadata.title),
                        added_at = COALESCE(media_metadata.added_at, excluded.added_at)
                    """,
                    (torrent_hash, title or torrent_hash, now),
                )
            conn.commit()

    def ensure_torrents_batch(self, torrents: list[dict[str, Any]]) -> None:
        if not torrents:
            return
        now = datetime.now(timezone.utc).isoformat() + "Z"
        rows_to_insert = [
            (
                t["hash"],
                t.get("title") or t["hash"],
                int(t.get("total_files") or 0),
                now,
            )
            for t in torrents
            if isinstance(t, dict) and t.get("hash")
        ]
        if not rows_to_insert:
            return
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO media_metadata (torrent_hash, title, total_files, added_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    title = COALESCE(excluded.title, media_metadata.title),
                    total_files = CASE WHEN excluded.total_files > 0 THEN excluded.total_files ELSE media_metadata.total_files END,
                    added_at = COALESCE(media_metadata.added_at, excluded.added_at)
                """,
                rows_to_insert,
            )
            conn.commit()

    def get_missing_metadata_hashes(self, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        placeholders = ",".join("?" for _ in hashes)
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT torrent_hash FROM media_metadata
                WHERE torrent_hash IN ({placeholders})
                  AND (overview IS NOT NULL OR rating IS NOT NULL OR (title != torrent_hash AND title != ''))
                """,
                hashes,
            ).fetchall()
        enriched = {r["torrent_hash"] for r in rows}
        return set(hashes) - enriched

    def save_total_files(self, torrent_hash: str, total_files: int, title: str | None = None) -> None:
        if not total_files or total_files <= 0:
            return
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_metadata (torrent_hash, title, total_files)
                VALUES (?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    total_files = CASE WHEN excluded.total_files > 0 THEN excluded.total_files ELSE media_metadata.total_files END
                """,
                (torrent_hash, title or torrent_hash, total_files),
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

    def _build_library_conditions(
        self,
        media_type: str | None = None,
        status: str | None = None,
        year: int | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        genre: str | list[str] | None = None,
        hashes: list[str] | None = None,
    ) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if media_type and media_type.lower() not in ("all", ""):
            if media_type.lower() == "movie":
                conditions.append("LOWER(COALESCE(t.media_type, 'movie')) = 'movie'")
            elif media_type.lower() == "series":
                conditions.append("LOWER(COALESCE(t.media_type, '')) = 'series'")
            else:
                conditions.append("LOWER(COALESCE(t.media_type, '')) = ?")
                params.append(media_type.lower())

        eff_year_from = year_from if year_from is not None else year
        eff_year_to = year_to if year_to is not None else year

        if eff_year_from is not None and eff_year_to is not None:
            conditions.append("m.year IS NOT NULL AND m.year >= ? AND m.year <= ?")
            params.extend([eff_year_from, eff_year_to])
        elif eff_year_from is not None:
            conditions.append("m.year IS NOT NULL AND m.year >= ?")
            params.append(eff_year_from)
        elif eff_year_to is not None:
            conditions.append("m.year IS NOT NULL AND m.year <= ?")
            params.append(eff_year_to)

        if genre is not None:
            if isinstance(genre, list):
                raw_genres = genre
            else:
                raw_genres = [g.strip() for g in str(genre).split(",") if g.strip()]
            valid_genres = [
                g.lower() for g in raw_genres if g.lower() not in ("all", "")
            ]
            if valid_genres:
                placeholders = ",".join("?" for _ in valid_genres)
                conditions.append(
                    f"(json_valid(COALESCE(m.genres_json, '')) AND EXISTS ("
                    f"SELECT 1 FROM json_each(m.genres_json) WHERE LOWER(value) IN ({placeholders})"
                    f"))"
                )
                params.extend(valid_genres)

        if status and status.lower() not in ("all", ""):
            st = status.lower()
            if st in ("watched", "completed"):
                conditions.append(
                    "COALESCE(NULLIF(m.total_files, 0), h.total_files, 0) > 0 AND "
                    "COALESCE(h.watched_files, 0) >= COALESCE(NULLIF(m.total_files, 0), h.total_files, 0)"
                )
            elif st == "unwatched":
                conditions.append(
                    "COALESCE(h.watched_files, 0) = 0 AND COALESCE(h.max_timecode, 0) = 0"
                )
            elif st in ("in_progress", "watching"):
                conditions.append(
                    "((COALESCE(h.watched_files, 0) > 0 AND COALESCE(h.watched_files, 0) < COALESCE(NULLIF(m.total_files, 0), h.total_files, 0)) "
                    "OR (COALESCE(h.watched_files, 0) = 0 AND COALESCE(h.max_timecode, 0) > 0))"
                )
            elif st == "planned":
                conditions.append("(p1.media_id IS NOT NULL OR p2.media_id IS NOT NULL)")

        if hashes is not None:
            if not hashes:
                conditions.append("1 = 0")
            else:
                placeholders = ",".join("?" for _ in hashes)
                conditions.append(f"a.torrent_hash IN ({placeholders})")
                params.extend(hashes)

        return conditions, params

    def _build_library_order_by(
        self,
        sort: str | None = None,
        order: str | None = None,
    ) -> str:
        s = (sort or "").strip().lower()
        ord_dir = (order or "").strip().lower()

        field = s
        direction = ord_dir

        if s.startswith("-"):
            field = s.lstrip("-")
            direction = ord_dir or "desc"
        elif s.startswith("+"):
            field = s.lstrip("+")
            direction = ord_dir or "asc"
        elif s.endswith("_asc"):
            field = s[:-4]
            direction = ord_dir or "asc"
        elif s.endswith("_desc"):
            field = s[:-5]
            direction = ord_dir or "desc"

        if field == "title":
            dir_str = (direction or "asc").upper()
            return f"ORDER BY COALESCE(m.title, a.torrent_hash) COLLATE NOCASE {dir_str}, a.torrent_hash ASC"

        if field == "year":
            dir_str = (direction or "desc").upper()
            return f"ORDER BY CASE WHEN m.year IS NULL THEN 1 ELSE 0 END, m.year {dir_str}, a.torrent_hash ASC"

        if field in ("added", "date"):
            dir_str = (direction or "desc").upper()
            added_expr = "COALESCE(m.added_at, h.first_played_at, '')"
            return f"ORDER BY CASE WHEN {added_expr} = '' THEN 1 ELSE 0 END, {added_expr} {dir_str}, a.torrent_hash ASC"

        if field == "progress":
            dir_str = (direction or "desc").upper()
            prog_expr = "(CASE WHEN COALESCE(NULLIF(m.total_files, 0), h.total_files, 0) > 0 THEN CAST(COALESCE(h.watched_files, 0) AS REAL) / COALESCE(NULLIF(m.total_files, 0), h.total_files, 0) ELSE 0.0 END)"
            return f"ORDER BY {prog_expr} {dir_str}, a.torrent_hash ASC"

        if field == "rating":
            dir_str = (direction or "desc").upper()
            return f"ORDER BY CASE WHEN m.rating IS NULL THEN 1 ELSE 0 END, m.rating {dir_str}, a.torrent_hash ASC"

        if field in ("recent", "last_played"):
            dir_str = (direction or "desc").upper()
            return f"ORDER BY COALESCE(h.last_played_at, '') {dir_str}, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC, a.torrent_hash ASC"

        # Default ordering
        return "ORDER BY COALESCE(h.last_played_at, '') DESC, COALESCE(m.title, a.torrent_hash) COLLATE NOCASE ASC, a.torrent_hash ASC"

    def query_library(
        self,
        media_type: str | None = None,
        status: str | None = None,
        year: int | None = None,
        genre: str | list[str] | None = None,
        sort: str | None = None,
        hashes: list[str] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions, params = self._build_library_conditions(
            media_type=media_type,
            status=status,
            year=year,
            year_from=year_from,
            year_to=year_to,
            genre=genre,
            hashes=hashes,
        )
        order_by = self._build_library_order_by(sort=sort, order=order)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            WITH all_torrents AS (
                SELECT torrent_hash FROM media_metadata WHERE torrent_hash NOT LIKE 'online:%'
                UNION
                SELECT torrent_hash FROM media_types WHERE torrent_hash NOT LIKE 'online:%'
                UNION
                SELECT torrent_hash FROM media_file_history WHERE torrent_hash NOT LIKE 'online:%'
            ),
            h_stats AS (
                SELECT 
                    torrent_hash,
                    COUNT(*) AS total_files,
                    SUM(CASE WHEN is_watched = 1 THEN 1 ELSE 0 END) AS watched_files,
                    MAX(playback_timecode) AS max_timecode,
                    MAX(last_played_at) AS last_played_at,
                    MIN(first_played_at) AS first_played_at
                FROM media_file_history
                WHERE torrent_hash NOT LIKE 'online:%'
                GROUP BY torrent_hash
            ),
            c_planned AS (
                SELECT media_id FROM media_collections WHERE list_name = 'watch_later'
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
                m.imdb_id,
                m.added_at,
                t.media_type,
                COALESCE(NULLIF(m.total_files, 0), h.total_files, 0) AS total_files,
                COALESCE(h.watched_files, 0) AS watched_files,
                COALESCE(h.max_timecode, 0) AS max_timecode,
                h.last_played_at,
                h.first_played_at,
                CASE WHEN p1.media_id IS NOT NULL OR p2.media_id IS NOT NULL THEN 1 ELSE 0 END AS is_planned
            FROM all_torrents a
            LEFT JOIN media_metadata m ON a.torrent_hash = m.torrent_hash
            LEFT JOIN media_types t ON a.torrent_hash = t.torrent_hash
            LEFT JOIN h_stats h ON a.torrent_hash = h.torrent_hash
            LEFT JOIN c_planned p1 ON a.torrent_hash = p1.media_id
            LEFT JOIN c_planned p2 ON (m.imdb_id IS NOT NULL AND m.imdb_id != '' AND m.imdb_id = p2.media_id)
            {where_clause}
            {order_by}
        """

        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.append(limit)
            params.append(offset or 0)

        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count_library(
        self,
        media_type: str | None = None,
        status: str | None = None,
        year: int | None = None,
        genre: str | list[str] | None = None,
        hashes: list[str] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> int:
        conditions, params = self._build_library_conditions(
            media_type=media_type,
            status=status,
            year=year,
            year_from=year_from,
            year_to=year_to,
            genre=genre,
            hashes=hashes,
        )
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            WITH all_torrents AS (
                SELECT torrent_hash FROM media_metadata WHERE torrent_hash NOT LIKE 'online:%'
                UNION
                SELECT torrent_hash FROM media_types WHERE torrent_hash NOT LIKE 'online:%'
                UNION
                SELECT torrent_hash FROM media_file_history WHERE torrent_hash NOT LIKE 'online:%'
            ),
            h_stats AS (
                SELECT 
                    torrent_hash,
                    COUNT(*) AS total_files,
                    SUM(CASE WHEN is_watched = 1 THEN 1 ELSE 0 END) AS watched_files,
                    MAX(playback_timecode) AS max_timecode,
                    MAX(last_played_at) AS last_played_at,
                    MIN(first_played_at) AS first_played_at
                FROM media_file_history
                WHERE torrent_hash NOT LIKE 'online:%'
                GROUP BY torrent_hash
            ),
            c_planned AS (
                SELECT media_id FROM media_collections WHERE list_name = 'watch_later'
            )
            SELECT COUNT(*) AS total_count
            FROM all_torrents a
            LEFT JOIN media_metadata m ON a.torrent_hash = m.torrent_hash
            LEFT JOIN media_types t ON a.torrent_hash = t.torrent_hash
            LEFT JOIN h_stats h ON a.torrent_hash = h.torrent_hash
            LEFT JOIN c_planned p1 ON a.torrent_hash = p1.media_id
            LEFT JOIN c_planned p2 ON (m.imdb_id IS NOT NULL AND m.imdb_id != '' AND m.imdb_id = p2.media_id)
            {where_clause}
        """

        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row["total_count"]) if row else 0

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
