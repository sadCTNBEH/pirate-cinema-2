import logging
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Generator

from backend.core.settings import get_data_dir

logger = logging.getLogger(__name__)

DB_PATH = get_data_dir() / "history.sqlite3"
TARGET_SCHEMA_VERSION = 4


def _add_column_if_not_exists(
    conn: sqlite3.Connection, table: str, column_name: str, column_type: str
) -> None:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cursor.fetchall()}
    if cols and column_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")


def _migrate_v1(conn: sqlite3.Connection) -> None:
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
        CREATE INDEX IF NOT EXISTS idx_offline_metadata_cache_imdb ON offline_metadata_cache(imdb_id);
        CREATE INDEX IF NOT EXISTS idx_offline_metadata_cache_created ON offline_metadata_cache(created_at);
        CREATE INDEX IF NOT EXISTS idx_media_types_type ON media_types(media_type);
        CREATE INDEX IF NOT EXISTS idx_media_metadata_year ON media_metadata(year);
        CREATE INDEX IF NOT EXISTS idx_media_file_history_status ON media_file_history(is_watched);
        CREATE INDEX IF NOT EXISTS idx_media_file_history_hash ON media_file_history(torrent_hash);
        CREATE INDEX IF NOT EXISTS idx_media_file_history_hash_status ON media_file_history(torrent_hash, is_watched);
        CREATE INDEX IF NOT EXISTS idx_media_collections_list_created ON media_collections(list_name, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_media_collections_list_media ON media_collections(list_name, media_id);
        CREATE INDEX IF NOT EXISTS idx_online_playlist_items_playlist ON online_playlist_items(playlist_id, position);
        CREATE INDEX IF NOT EXISTS idx_online_history_last_played ON online_history(last_played_at DESC);
    """)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    _add_column_if_not_exists(conn, "media_file_history", "audio_track", "INTEGER DEFAULT 0")
    _add_column_if_not_exists(conn, "media_file_history", "subtitle_track", "INTEGER DEFAULT 0")
    _add_column_if_not_exists(conn, "media_file_history", "season", "INTEGER")
    _add_column_if_not_exists(conn, "media_file_history", "episode", "INTEGER")
    _add_column_if_not_exists(conn, "media_file_history", "imdb_id", "TEXT")
    _add_column_if_not_exists(conn, "media_metadata", "imdb_id", "TEXT")
    _add_column_if_not_exists(conn, "media_metadata", "added_at", "TEXT")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS media_episode_history (
            title_id TEXT NOT NULL,
            season INTEGER NOT NULL,
            episode INTEGER NOT NULL,
            is_watched INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (title_id, season, episode)
        );
        CREATE INDEX IF NOT EXISTS idx_history_logical_episode
            ON media_file_history(imdb_id, season, episode, last_played_at);
        CREATE INDEX IF NOT EXISTS idx_media_metadata_imdb ON media_metadata(imdb_id);
        CREATE INDEX IF NOT EXISTS idx_media_metadata_added_at ON media_metadata(added_at);
        CREATE INDEX IF NOT EXISTS idx_media_file_history_season_ep ON media_file_history(season, episode);
        CREATE INDEX IF NOT EXISTS idx_media_file_history_imdb ON media_file_history(imdb_id);
        CREATE INDEX IF NOT EXISTS idx_media_file_history_imdb_ep ON media_file_history(imdb_id, season, episode);
        CREATE INDEX IF NOT EXISTS idx_media_episode_history_title_ep ON media_episode_history(title_id, season, episode);
        CREATE INDEX IF NOT EXISTS idx_media_file_history_hash_stats ON media_file_history(torrent_hash, is_watched, playback_timecode, last_played_at);
    """)


def _migrate_v3(conn: sqlite3.Connection) -> None:
    _add_column_if_not_exists(conn, "media_file_history", "playback_context", "TEXT")
    _add_column_if_not_exists(conn, "media_metadata", "overview_ru", "TEXT")
    _add_column_if_not_exists(conn, "media_metadata", "total_files", "INTEGER DEFAULT 0")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS playback_sync (
            hash TEXT NOT NULL,
            file_id INTEGER NOT NULL,
            sub_delay REAL NOT NULL DEFAULT 0,
            audio_delay REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(hash, file_id)
        );
        CREATE TABLE IF NOT EXISTS torrent_file_choices (
            hash TEXT,
            intent TEXT,
            file_id INTEGER,
            PRIMARY KEY(hash, intent)
        );
        CREATE TABLE IF NOT EXISTS playback_progress_owner (
            hash TEXT,
            file_id INTEGER,
            generation INTEGER,
            PRIMARY KEY(hash, file_id)
        );
    """)


def _migrate_v4(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_media_file_history_last_played
            ON media_file_history(last_played_at DESC);
        CREATE INDEX IF NOT EXISTS idx_media_file_history_continue
            ON media_file_history(is_watched, last_played_at DESC);
        CREATE INDEX IF NOT EXISTS idx_media_metadata_title
            ON media_metadata(title COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_media_metadata_rating
            ON media_metadata(rating);
        CREATE INDEX IF NOT EXISTS idx_playback_sync_hash
            ON playback_sync(hash);
    """)


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
    (4, _migrate_v4),
]


def _ensure_schema_integrity(conn: sqlite3.Connection) -> None:
    """Ensure all expected columns and tables exist even if altered out-of-band."""
    for _, migration_func in MIGRATIONS:
        migration_func(conn)


class Database:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DB_PATH

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self.db_path.parent and str(self.db_path.parent) not in ("", "."):
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

    def _should_backup_on_error(self) -> bool:
        if str(self.db_path) == ":memory:":
            return False
        return self.db_path.exists() and self.db_path.stat().st_size > 0

    def create_backup(self, destination: str | Path | None = None) -> Path:
        """Create a backup of the database file preserving WAL state."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file does not exist: {self.db_path}")

        if destination is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            backup_path = self.db_path.with_name(f"{self.db_path.name}.bak_{timestamp}")
        else:
            backup_path = Path(destination)

        if backup_path.parent and str(backup_path.parent) not in ("", "."):
            os.makedirs(backup_path.parent, exist_ok=True)

        try:
            with sqlite3.connect(self.db_path) as src, sqlite3.connect(backup_path) as dst:
                src.backup(dst)
        except (sqlite3.Error, OSError) as err:
            logger.warning("Online backup failed (%s), falling back to file copy", err)
            shutil.copy2(self.db_path, backup_path)
            for extra in ("-wal", "-shm"):
                src_extra = self.db_path.with_name(self.db_path.name + extra)
                if src_extra.exists():
                    shutil.copy2(src_extra, backup_path.with_name(backup_path.name + extra))

        return backup_path

    def restore_backup(self, backup_path: str | Path) -> None:
        """Safely restore database from a backup file."""
        src = Path(backup_path)
        if not src.exists():
            raise FileNotFoundError(f"Backup file not found: {src}")

        if self._should_backup_on_error():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            safety_copy = self.db_path.with_name(f"{self.db_path.name}.pre_restore_{timestamp}.bak")
            self.create_backup(safety_copy)

        try:
            with sqlite3.connect(src) as src_conn, sqlite3.connect(self.db_path) as dst_conn:
                src_conn.backup(dst_conn)
        except (sqlite3.Error, OSError):
            shutil.copy2(src, self.db_path)
            for extra in ("-wal", "-shm"):
                src_extra = src.with_name(src.name + extra)
                dst_extra = self.db_path.with_name(self.db_path.name + extra)
                if src_extra.exists():
                    shutil.copy2(src_extra, dst_extra)
                elif dst_extra.exists():
                    dst_extra.unlink(missing_ok=True)

        self.check_integrity()
        self.migrate()

    def get_version(self) -> int:
        """Return the current schema user_version."""
        with self.get_connection() as conn:
            cursor = conn.execute("PRAGMA user_version")
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def check_integrity(self) -> bool:
        """Run quick_check to verify SQLite database integrity."""
        with self.get_connection() as conn:
            cursor = conn.execute("PRAGMA quick_check")
            rows = cursor.fetchall()
            if not rows or rows[0][0] != "ok":
                errors = [row[0] for row in rows]
                raise sqlite3.DatabaseError(f"Database quick_check failed: {errors}")
        return True

    def migrate(self) -> None:
        """Execute stepwise idempotent schema migrations in isolated transactions."""
        with self.get_connection() as conn:
            cursor = conn.execute("PRAGMA user_version")
            row = cursor.fetchone()
            current_version = int(row[0]) if row else 0

            if current_version < TARGET_SCHEMA_VERSION:
                logger.info(
                    "Migrating database from version %d to %d",
                    current_version,
                    TARGET_SCHEMA_VERSION,
                )
                for version, migration_func in MIGRATIONS:
                    if version > current_version:
                        logger.info("Applying database migration to version %d", version)
                        conn.execute("BEGIN IMMEDIATE")
                        try:
                            migration_func(conn)
                            conn.execute(f"PRAGMA user_version = {version}")
                            conn.commit()
                        except (sqlite3.Error, OSError, RuntimeError, ValueError):
                            conn.rollback()
                            raise

            _ensure_schema_integrity(conn)

    def init_db(self) -> None:
        """Initialize database, enable WAL, check integrity, and apply migrations."""
        try:
            with self.get_connection() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            self.check_integrity()
            self.migrate()
        except (sqlite3.Error, OSError, RuntimeError, ValueError) as exc:
            logger.exception("Database initialization failed: %s", exc)
            if self._should_backup_on_error():
                backup_path = self.create_backup()
                logger.error("Created safety backup of database at %s", backup_path)
            raise


_default_db = Database()


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    with _default_db.get_connection() as conn:
        yield conn


def init_db() -> None:
    _default_db.init_db()


def check_integrity() -> bool:
    return _default_db.check_integrity()


def create_backup(destination: str | Path | None = None) -> Path:
    return _default_db.create_backup(destination)


def restore_backup(backup_path: str | Path) -> None:
    _default_db.restore_backup(backup_path)
