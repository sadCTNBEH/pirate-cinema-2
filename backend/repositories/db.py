import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.core.settings import get_data_dir

DB_PATH = get_data_dir() / "history.sqlite3"


class Database:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else DB_PATH

    @contextmanager
    def get_connection(self):
        os.makedirs(self.db_path.parent, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
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

    def init_db(self):
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "ALTER TABLE media_file_history ADD COLUMN audio_track INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute(
                    "ALTER TABLE media_file_history ADD COLUMN subtitle_track INTEGER DEFAULT 0"
                )
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
                    subtitle_track INTEGER DEFAULT 0,
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
                CREATE TABLE IF NOT EXISTS offline_metadata_cache (
                    cache_key TEXT PRIMARY KEY,
                    imdb_id TEXT,
                    title TEXT,
                    data_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_offline_metadata_cache_imdb ON offline_metadata_cache(imdb_id);
                CREATE INDEX IF NOT EXISTS idx_offline_metadata_cache_created ON offline_metadata_cache(created_at);
                CREATE INDEX IF NOT EXISTS idx_media_types_type ON media_types(media_type);
                CREATE INDEX IF NOT EXISTS idx_media_metadata_year ON media_metadata(year);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_status ON media_file_history(is_watched);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_hash ON media_file_history(torrent_hash);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_hash_status ON media_file_history(torrent_hash, is_watched);
            """)

            try:
                conn.execute("ALTER TABLE media_metadata ADD COLUMN overview_ru TEXT")
            except sqlite3.OperationalError:
                pass


_default_db = Database()


@contextmanager
def get_connection():
    with _default_db.get_connection() as conn:
        yield conn


def init_db():
    _default_db.init_db()
