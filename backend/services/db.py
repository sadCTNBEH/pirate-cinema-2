import sys
import sqlite3
import os
from contextlib import contextmanager
from ..config import get_data_dir

DB_PATH = get_data_dir() / "history.sqlite3"

@contextmanager
def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_connection() as conn:

        try:
            conn.execute("ALTER TABLE media_file_history ADD COLUMN audio_track INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS media_file_history (
                torrent_hash TEXT NOT NULL,
                file_index INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT,
                first_played_at TEXT NOT NULL,
                playback_timecode INTEGER,
                playback_duration INTEGER,
                is_watched INTEGER NOT NULL DEFAULT 0,
                audio_track INTEGER DEFAULT 0,
                last_played_at TEXT NOT NULL,
                launch_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (torrent_hash, file_index)
            );
            CREATE TABLE IF NOT EXISTS media_types (
                torrent_hash TEXT PRIMARY KEY,
                media_type TEXT NOT NULL CHECK(media_type IN ('movie','series'))
            );
            CREATE TABLE IF NOT EXISTS media_audio_tracks (
                torrent_hash TEXT PRIMARY KEY,
                track_id INTEGER NOT NULL CHECK(track_id > 0)
            );
            CREATE TABLE IF NOT EXISTS media_metadata (
                torrent_hash TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                overview TEXT,
                year INTEGER,
                rating REAL,
                poster_file TEXT,
                genres_json TEXT NOT NULL DEFAULT '[]'
            );
        """)


def save_metadata_title(torrent_hash: str, title: str):
    if not title: return
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO media_metadata (torrent_hash, title)
            VALUES (?, ?)
            ON CONFLICT(torrent_hash) DO UPDATE SET title=excluded.title
        """, (torrent_hash, title))

def mark_played(torrent_hash: str, file_index: int, file_name: str, file_path: str = None):
    from datetime import datetime
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO media_file_history (torrent_hash, file_index, file_name, file_path, first_played_at, last_played_at, launch_count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(torrent_hash, file_index) DO UPDATE SET
                last_played_at = excluded.last_played_at,
                launch_count = launch_count + 1
        """, (torrent_hash, file_index, file_name, file_path, now, now))

def update_progress(torrent_hash: str, file_index: int, timecode: int, duration: int, audio_track: int = 0):
    is_watched = 1 if duration > 0 and (duration - timecode) < 180 else 0
    with get_connection() as conn:
        conn.execute("""
            UPDATE media_file_history
            SET playback_timecode = ?, playback_duration = ?, is_watched = CASE WHEN is_watched = 1 THEN 1 ELSE ? END, audio_track = CASE WHEN ? > 0 THEN ? ELSE audio_track END
            WHERE torrent_hash = ? AND file_index = ?
        """, (timecode, duration, is_watched, audio_track, audio_track, torrent_hash, file_index))

def get_audio_track(torrent_hash: str, file_index: int = None) -> int:
    """Return saved audio track id: per-file first, then torrent-wide fallback."""
    with get_connection() as conn:
        if file_index is not None:
            r = conn.execute(
                "SELECT audio_track FROM media_file_history WHERE torrent_hash=? AND file_index=?",
                (torrent_hash, file_index)
            ).fetchone()
            if r and r["audio_track"] and r["audio_track"] > 0:
                return r["audio_track"]
        r = conn.execute(
            "SELECT track_id FROM media_audio_tracks WHERE torrent_hash=?",
            (torrent_hash,)
        ).fetchone()
        return r["track_id"] if r else 0

def set_audio_track(torrent_hash: str, track_id: int, file_index: int = None):
    """Persist audio track preference at file level and torrent-wide level."""
    with get_connection() as conn:
        if file_index is not None:
            conn.execute(
                "UPDATE media_file_history SET audio_track=? WHERE torrent_hash=? AND file_index=?",
                (track_id, torrent_hash, file_index)
            )
        conn.execute(
            "INSERT INTO media_audio_tracks (torrent_hash, track_id) VALUES (?,?) "
            "ON CONFLICT(torrent_hash) DO UPDATE SET track_id=excluded.track_id",
            (torrent_hash, track_id)
        )

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
