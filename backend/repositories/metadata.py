from backend.repositories.db import get_connection


def save_metadata_title(torrent_hash: str, title: str):
    if not title: return
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO media_metadata (torrent_hash, title)
            VALUES (?, ?)
            ON CONFLICT(torrent_hash) DO UPDATE SET title=excluded.title
        """, (torrent_hash, title))

def save_media_type(torrent_hash: str, media_type: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO media_types (torrent_hash, media_type) VALUES (?, ?) "
            "ON CONFLICT(torrent_hash) DO UPDATE SET media_type=excluded.media_type",
            (torrent_hash, media_type)
        )

def save_full_metadata(torrent_hash: str, title: str, overview: str, year: int, rating: float, poster_file: str, genres_json: str):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO media_metadata (torrent_hash, title, overview, year, rating, poster_file, genres_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(torrent_hash) DO UPDATE SET
                title=excluded.title,
                overview=excluded.overview,
                year=excluded.year,
                rating=excluded.rating,
                poster_file=excluded.poster_file,
                genres_json=excluded.genres_json
        """, (torrent_hash, title, overview, year, rating, poster_file, genres_json))
