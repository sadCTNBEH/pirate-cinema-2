import re
from typing import Any

from backend.repositories import db


def get_recent_history(limit: int = 20) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
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


def fetch_poster_meta(hashes: list[str]) -> dict[str, str]:
    if not hashes:
        return {}
    placeholders = ",".join("?" for _ in hashes)
    with db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT torrent_hash, poster_file FROM media_metadata WHERE torrent_hash IN ({placeholders})",
            hashes,
        ).fetchall()
    return {r["torrent_hash"]: r["poster_file"] for r in rows if r["poster_file"]}


def get_file_history_map(torrent_hash: str) -> dict[int, dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT file_index, playback_timecode, is_watched FROM media_file_history WHERE torrent_hash = ?",
            (torrent_hash,),
        ).fetchall()
    return {row["file_index"]: dict(row) for row in rows}


def has_poster(torrent_hash: str) -> bool:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT poster_file FROM media_metadata WHERE torrent_hash = ?",
            (torrent_hash,),
        ).fetchone()
        return bool(row and row["poster_file"])


def delete_history_by_hash(torrent_hash: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "DELETE FROM media_file_history WHERE torrent_hash=?", (torrent_hash,)
        )
        conn.commit()


def parse_ep(name):
    name = str(name or "")

    def natural_key(text):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]

    base_sort_name = natural_key(name)

    # 1. S01E05, S1 E5, S01.E05, S01_E05
    # [\.\-\s_]* означает "любое количество точек, тире, пробелов или подчеркиваний между S и E"
    m = re.search(r'S(\d+)[\.\-\s_]*E(\d+)', name, re.IGNORECASE)
    if m:
        return (1, int(m.group(1)), int(m.group(2)), base_sort_name)

    # 2. 1x05, 01x05
    m = re.search(r'(\d+)x(\d+)', name, re.IGNORECASE)
    if m:
        return (1, int(m.group(1)), int(m.group(2)), base_sort_name)

    # 3. Episode 05, Ep 05, E05, Ep.5, E 5
    # (?: ... ) - это группа, которую мы не запоминаем, нам важно только число в конце
    m = re.search(r'(?:Episode|Ep|E)[\.\-\s_]*(\d+)', name, re.IGNORECASE)
    if m:
        # Так как сезон не указан, дефолтим к 1 сезону (1, 1, номер_серии)
        return (1, 1, int(m.group(1)), base_sort_name)

    # 4. Фильмы или неизвестный формат
    return (0, 0, 0, base_sort_name)