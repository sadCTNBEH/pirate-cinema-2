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
        except sqlite3.Error:
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

            try:
                conn.execute(
                    "ALTER TABLE media_file_history ADD COLUMN season INTEGER"
                )
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute(
                    "ALTER TABLE media_file_history ADD COLUMN episode INTEGER"
                )
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute(
                    "ALTER TABLE media_file_history ADD COLUMN imdb_id TEXT"
                )
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute(
                    "ALTER TABLE media_metadata ADD COLUMN imdb_id TEXT"
                )
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute(
                    "ALTER TABLE media_metadata ADD COLUMN added_at TEXT"
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
                    season INTEGER,
                    episode INTEGER,
                    imdb_id TEXT,
                    last_played_at TEXT NOT NULL,
                    launch_count INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (torrent_hash, file_index)
                );
                CREATE INDEX IF NOT EXISTS idx_history_logical_episode
                    ON media_file_history(imdb_id, season, episode, last_played_at);
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
                    genres_json TEXT NOT NULL DEFAULT '[]',
                    overview_ru TEXT,
                    imdb_id TEXT,
                    total_files INTEGER DEFAULT 0,
                    added_at TEXT
                );
                CREATE TABLE IF NOT EXISTS offline_metadata_cache (
                    cache_key TEXT PRIMARY KEY,
                    imdb_id TEXT,
                    title TEXT,
                    data_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS media_collections (
                    list_name TEXT NOT NULL CHECK(list_name IN ('favorites', 'watch_later')),
                    media_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    title_ru TEXT,
                    poster_url TEXT,
                    year INTEGER,
                    rating REAL,
                    overview TEXT,
                    overview_ru TEXT,
                    genres_json TEXT NOT NULL DEFAULT '[]',
                    media_type TEXT CHECK(media_type IN ('movie', 'series')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (list_name, media_id)
                );
                CREATE TABLE IF NOT EXISTS online_playlists (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS online_playlist_items (
                    id TEXT PRIMARY KEY,
                    playlist_id TEXT NOT NULL REFERENCES online_playlists(id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    title TEXT NOT NULL,
                    thumbnail TEXT,
                    duration INTEGER,
                    position INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS online_history (
                    provider TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    thumbnail TEXT,
                    duration INTEGER,
                    playback_timecode INTEGER NOT NULL DEFAULT 0,
                    playback_duration INTEGER NOT NULL DEFAULT 0,
                    is_watched INTEGER NOT NULL DEFAULT 0,
                    launch_count INTEGER NOT NULL DEFAULT 1,
                    first_played_at TEXT NOT NULL,
                    last_played_at TEXT NOT NULL,
                    PRIMARY KEY (provider, item_id)
                );
                CREATE TABLE IF NOT EXISTS media_episode_history (
                    title_id TEXT NOT NULL,
                    season INTEGER NOT NULL,
                    episode INTEGER NOT NULL,
                    is_watched INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (title_id, season, episode)
                );
                CREATE INDEX IF NOT EXISTS idx_offline_metadata_cache_imdb ON offline_metadata_cache(imdb_id);
                CREATE INDEX IF NOT EXISTS idx_offline_metadata_cache_created ON offline_metadata_cache(created_at);
                CREATE INDEX IF NOT EXISTS idx_media_types_type ON media_types(media_type);
                CREATE INDEX IF NOT EXISTS idx_media_metadata_year ON media_metadata(year);
                CREATE INDEX IF NOT EXISTS idx_media_metadata_imdb ON media_metadata(imdb_id);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_status ON media_file_history(is_watched);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_hash ON media_file_history(torrent_hash);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_hash_status ON media_file_history(torrent_hash, is_watched);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_season_ep ON media_file_history(season, episode);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_imdb ON media_file_history(imdb_id);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_imdb_ep ON media_file_history(imdb_id, season, episode);
                CREATE INDEX IF NOT EXISTS idx_media_episode_history_title_ep ON media_episode_history(title_id, season, episode);
                CREATE INDEX IF NOT EXISTS idx_media_collections_list_created ON media_collections(list_name, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_media_collections_list_media ON media_collections(list_name, media_id);
                CREATE INDEX IF NOT EXISTS idx_media_metadata_added_at ON media_metadata(added_at);
                CREATE INDEX IF NOT EXISTS idx_media_file_history_hash_stats ON media_file_history(torrent_hash, is_watched, playback_timecode, last_played_at);
                CREATE INDEX IF NOT EXISTS idx_online_playlist_items_playlist ON online_playlist_items(playlist_id, position);
                CREATE INDEX IF NOT EXISTS idx_online_history_last_played ON online_history(last_played_at DESC);
            """)

            columns = {row[1] for row in conn.execute('PRAGMA table_info(media_file_history)')}
            conn.execute('''CREATE TABLE IF NOT EXISTS playback_sync (
                hash TEXT NOT NULL, file_id INTEGER NOT NULL,
                sub_delay REAL NOT NULL DEFAULT 0, audio_delay REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(hash, file_id))''')
            if 'playback_context' not in columns:
                conn.execute('ALTER TABLE media_file_history ADD COLUMN playback_context TEXT')

            try:
                conn.execute("ALTER TABLE media_metadata ADD COLUMN overview_ru TEXT")
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute(
                    "ALTER TABLE media_metadata ADD COLUMN total_files INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass


_default_db = Database()


@contextmanager
def get_connection():
    with _default_db.get_connection() as conn:
        yield conn


def init_db():
    _default_db.init_db()
