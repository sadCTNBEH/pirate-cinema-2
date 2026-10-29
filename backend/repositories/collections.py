import json
from typing import Any

from backend.repositories.base import BaseRepository
from backend.repositories.db import Database


class CollectionRepository(BaseRepository):
    """Persistence for user-curated media lists, independent of torrent state."""

    def __init__(self, db: Database):
        super().__init__(db)

    def canonicalize_alias(self, alias, canonical):
        if alias == canonical:
            return
        with self.connection() as conn:
            conn.execute('''INSERT OR IGNORE INTO media_collections
                (list_name,media_id,title,title_ru,poster_url,year,rating,overview,overview_ru,genres_json,media_type,created_at)
                SELECT list_name,?,title,title_ru,poster_url,year,rating,overview,overview_ru,genres_json,media_type,created_at
                FROM media_collections WHERE media_id=?''', (canonical, alias))
            conn.execute('DELETE FROM media_collections WHERE media_id=?', (alias,))

    def list_items(self, list_name: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT media_id, title, title_ru, poster_url, year, rating, overview,
                       overview_ru, genres_json, media_type, created_at
                FROM media_collections
                WHERE list_name = ?
                ORDER BY created_at DESC, title COLLATE NOCASE ASC
                """,
                (list_name,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_memberships(self, media_id: str) -> set[str]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT list_name FROM media_collections WHERE media_id = ?",
                (media_id,),
            ).fetchall()
        return {row["list_name"] for row in rows}

    def save_item(self, list_name: str, item: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_collections (
                    list_name, media_id, title, title_ru, poster_url, year, rating,
                    overview, overview_ru, genres_json, media_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(list_name, media_id) DO UPDATE SET
                    title = excluded.title,
                    title_ru = excluded.title_ru,
                    poster_url = excluded.poster_url,
                    year = excluded.year,
                    rating = excluded.rating,
                    overview = excluded.overview,
                    overview_ru = excluded.overview_ru,
                    genres_json = excluded.genres_json,
                    media_type = excluded.media_type
                """,
                (
                    list_name,
                    item["media_id"],
                    item["title"],
                    item.get("title_ru"),
                    item.get("poster_url"),
                    item.get("year"),
                    item.get("rating"),
                    item.get("overview"),
                    item.get("overview_ru"),
                    json.dumps(item.get("genres") or [], ensure_ascii=False),
                    item.get("media_type"),
                ),
            )

    def remove_item(self, list_name: str, media_id: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM media_collections WHERE list_name = ? AND media_id = ?",
                (list_name, media_id),
            )
        return cursor.rowcount > 0
