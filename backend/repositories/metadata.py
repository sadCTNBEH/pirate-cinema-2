from typing import Optional

from backend.repositories.base import BaseRepository
from backend.repositories.db import Database


class MetadataRepository(BaseRepository):
    def __init__(self, db: Optional[Database] = None):
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
        year: int,
        rating: float,
        poster_file: str,
        genres_json: str,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_metadata (torrent_hash, title, overview, year, rating, poster_file, genres_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    title=excluded.title,
                    overview=excluded.overview,
                    year=excluded.year,
                    rating=excluded.rating,
                    poster_file=excluded.poster_file,
                    genres_json=excluded.genres_json
            """,
                (
                    torrent_hash,
                    title,
                    overview,
                    year,
                    rating,
                    poster_file,
                    genres_json,
                ),
            )


# Функции модуля для обратной совместимости
_default_repo = MetadataRepository()
save_metadata_title = _default_repo.save_metadata_title
save_media_type = _default_repo.save_media_type
save_full_metadata = _default_repo.save_full_metadata
