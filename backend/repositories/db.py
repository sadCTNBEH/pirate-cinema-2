import os
import sqlite3
from contextlib import contextmanager

from backend.core.config import get_data_dir

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
