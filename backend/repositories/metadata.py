import json
from typing import Any

from backend.repositories.base import BaseRepository
from backend.repositories.db import Database


class MetadataRepository(BaseRepository):
    def __init__(self, db: Database):
        super().__init__(db)

    def save_metadata_title(self, torrent_hash: str, title: str) -> None:
        if not title:
            return
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_metadata (torrent_hash, title)
                VALUES (?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET title=excluded.title
            """,
                (torrent_hash, title),
            )

    def save_media_type(self, torrent_hash: str, media_type: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO media_types (torrent_hash, media_type) VALUES (?, ?) "
                "ON CONFLICT(torrent_hash) DO UPDATE SET media_type=excluded.media_type",
                (torrent_hash, media_type),
            )

    def save_full_metadata(
        self,
        torrent_hash: str,
        title: str,
        overview: str,
        year: int | None,
        rating: float | None,
        poster_file: str,
        genres_json: str,
        overview_ru: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_metadata (torrent_hash, title, overview, year, rating, poster_file, genres_json, overview_ru)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    title=excluded.title,
                    overview=excluded.overview,
                    year=excluded.year,
                    rating=excluded.rating,
                    poster_file=excluded.poster_file,
                    genres_json=excluded.genres_json,
                    overview_ru=COALESCE(excluded.overview_ru, media_metadata.overview_ru)
            """,
                (
                    torrent_hash,
                    title,
                    overview,
                    year,
                    rating,
                    poster_file,
                    genres_json,
                    overview_ru,
                ),
            )

    def get_cached_metadata(
        self, cache_key: str, max_age_seconds: int | None = None
    ) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT data_json,
                       CAST((strftime('%s', 'now') - strftime('%s', created_at)) AS INTEGER) AS age_seconds
                FROM offline_metadata_cache WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
            if (
                row
                and row["data_json"]
                and max_age_seconds is not None
                and row["age_seconds"] is not None
                and row["age_seconds"] >= max_age_seconds
            ):
                return None
            if row and row["data_json"]:
                try:
                    return json.loads(row["data_json"])
                except (json.JSONDecodeError, TypeError):
                    return None
            return None

    def save_cached_metadata(
        self,
        cache_key: str,
        data: dict[str, Any],
        imdb_id: str | None = None,
        title: str | None = None,
    ) -> None:
        data_json = json.dumps(data, ensure_ascii=False)
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO offline_metadata_cache (cache_key, imdb_id, title, data_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    imdb_id=excluded.imdb_id,
                    title=excluded.title,
                    data_json=excluded.data_json,
                    created_at=CURRENT_TIMESTAMP
                """,
                (cache_key, imdb_id, title or data.get("title", ""), data_json),
            )

    def purge_expired_cache(self, max_age_seconds: int) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """
                DELETE FROM offline_metadata_cache
                WHERE CAST((strftime('%s', 'now') - strftime('%s', created_at)) AS INTEGER) >= ?
                """,
                (max_age_seconds,),
            )
            return cur.rowcount
