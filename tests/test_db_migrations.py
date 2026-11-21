import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.repositories.db import TARGET_SCHEMA_VERSION, Database
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository


def create_legacy_v0_database(db_path: Path) -> None:
    """Create an old (v0) unversioned database with early schema and user data."""
    conn = sqlite3.connect(db_path)
    # PRAGMA user_version remains 0 by default
    conn.executescript("""
        CREATE TABLE media_file_history (
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
        CREATE TABLE media_types (
            torrent_hash TEXT PRIMARY KEY,
            media_type TEXT NOT NULL CHECK(media_type IN ('movie','series'))
        );
        CREATE TABLE media_metadata (
            torrent_hash TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            overview TEXT,
            year INTEGER,
            rating REAL,
            poster_file TEXT,
            genres_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE media_collections (
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
    """)

    # Insert user data into legacy schema
    conn.execute(
        """
        INSERT INTO media_metadata (torrent_hash, title, overview, year, rating, genres_json)
        VALUES ('hash_movie_1', 'Inception', 'A thief who steals corporate secrets', 2010, 8.8, '["Sci-Fi","Action"]')
        """
    )
    conn.execute(
        """
        INSERT INTO media_types (torrent_hash, media_type)
        VALUES ('hash_movie_1', 'movie')
        """
    )
    conn.execute(
        """
        INSERT INTO media_file_history (
            torrent_hash, file_index, file_name, file_path, first_played_at,
            playback_timecode, playback_duration, is_watched, last_played_at, launch_count
        )
        VALUES ('hash_movie_1', 0, 'Inception.2010.mkv', '/movies/Inception.mkv',
                '2024-01-01T12:00:00Z', 1500, 9000, 0, '2024-01-01T12:30:00Z', 2)
        """
    )
    conn.execute(
        """
        INSERT INTO media_collections (list_name, media_id, title, year)
        VALUES ('favorites', 'hash_movie_1', 'Inception', 2010)
        """
    )
    conn.commit()
    conn.close()


def test_migration_from_legacy_v0_database_preserves_all_data(tmp_path: Path) -> None:
    db_file = tmp_path / "legacy_v0.sqlite3"
    create_legacy_v0_database(db_file)

    # Verify initial v0 state
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        cols = {r[1] for r in conn.execute("PRAGMA table_info(media_file_history)")}
        assert "playback_context" not in cols
        assert "audio_track" not in cols
        assert "subtitle_track" not in cols
        assert "season" not in cols

    db = Database(db_file)
    db.init_db()

    # 1. Verify schema version and WAL mode
    assert db.get_version() == TARGET_SCHEMA_VERSION
    with db.get_connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(journal_mode).lower() == "wal"

    # 2. Verify integrity check
    assert db.check_integrity() is True

    # 3. Verify user data was 100% preserved
    with db.get_connection() as conn:
        movie = conn.execute(
            "SELECT * FROM media_file_history WHERE torrent_hash = 'hash_movie_1'"
        ).fetchone()
        assert movie is not None
        assert movie["file_name"] == "Inception.2010.mkv"
        assert movie["playback_timecode"] == 1500
        assert movie["playback_duration"] == 9000
        assert movie["is_watched"] == 0
        assert movie["audio_track"] == 0
        assert movie["subtitle_track"] == 0
        assert movie["playback_context"] is None

        meta = conn.execute(
            "SELECT * FROM media_metadata WHERE torrent_hash = 'hash_movie_1'"
        ).fetchone()
        assert meta is not None
        assert meta["title"] == "Inception"
        assert meta["year"] == 2010
        assert meta["rating"] == 8.8

        fav = conn.execute(
            "SELECT * FROM media_collections WHERE media_id = 'hash_movie_1'"
        ).fetchone()
        assert fav is not None
        assert fav["title"] == "Inception"

    # 4. Verify new tables and indexes exist
    with db.get_connection() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "playback_sync" in tables
        assert "media_episode_history" in tables
        assert "torrent_file_choices" in tables
        assert "playback_progress_owner" in tables

        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_media_file_history_last_played" in indexes
        assert "idx_media_file_history_continue" in indexes
        assert "idx_media_metadata_title" in indexes
        assert "idx_media_metadata_rating" in indexes

    # 5. Verify repositories query the migrated DB correctly
    history_repo = HistoryRepository(db)
    continue_list = history_repo.list_continue_watching()
    assert len(continue_list) == 1
    assert continue_list[0]["torrent_hash"] == "hash_movie_1"
    assert continue_list[0]["title"] == "Inception"
    assert continue_list[0]["playback_timecode"] == 1500

    library_repo = LibraryRepository(db)
    recent = library_repo.get_recent_history()
    assert len(recent) == 1
    assert recent[0]["torrent_hash"] == "hash_movie_1"
    assert recent[0]["playback_timecode"] == 1500


def test_migration_idempotence(tmp_path: Path) -> None:
    db_file = tmp_path / "idempotent.sqlite3"
    create_legacy_v0_database(db_file)

    db = Database(db_file)
    # First init
    db.init_db()
    assert db.get_version() == TARGET_SCHEMA_VERSION

    # Second init (should be a no-op, idempotent)
    db.init_db()
    assert db.get_version() == TARGET_SCHEMA_VERSION

    # Third init
    db.init_db()
    assert db.get_version() == TARGET_SCHEMA_VERSION


def test_stepwise_migration_from_v2(tmp_path: Path) -> None:
    db_file = tmp_path / "v2.sqlite3"
    db = Database(db_file)
    db.init_db()

    # Manually downgrade user_version to 2 to simulate intermediate version
    with db.get_connection() as conn:
        conn.execute("PRAGMA user_version = 2")
    assert db.get_version() == 2

    # Re-run migrate
    db.migrate()
    assert db.get_version() == TARGET_SCHEMA_VERSION


def test_quick_check_failure_raises_and_creates_backup(tmp_path: Path) -> None:
    db_file = tmp_path / "corrupted.sqlite3"
    # Create valid db first
    db = Database(db_file)
    db.init_db()

    # Corrupt the file content
    with open(db_file, "r+b") as f:
        f.seek(100)
        f.write(b"\xff" * 200)

    # Attempting init_db should catch quick_check corruption and create backup
    with pytest.raises(sqlite3.DatabaseError):
        db.init_db()

    # Original corrupted file must NOT be deleted
    assert db_file.exists()

    # A backup file must have been created
    backups = list(tmp_path.glob("corrupted.sqlite3.bak*"))
    assert len(backups) >= 1
    assert backups[0].exists()


def test_migration_failure_rolls_back_and_creates_backup(tmp_path: Path) -> None:
    db_file = tmp_path / "fail_migrate.sqlite3"
    create_legacy_v0_database(db_file)

    db = Database(db_file)

    def failing_migration(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE temporary_broken (id INT)")
        raise sqlite3.OperationalError("Simulated migration failure")

    with patch("backend.repositories.db.MIGRATIONS", [(1, failing_migration)]):
        with pytest.raises(sqlite3.OperationalError):
            db.init_db()

    # Database file must NOT be deleted
    assert db_file.exists()

    # user_version must NOT have been updated
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # Transaction must have rolled back table creation
        assert "temporary_broken" not in tables
        # Original user data must still be intact
        movie = conn.execute(
            "SELECT title FROM media_metadata WHERE torrent_hash = 'hash_movie_1'"
        ).fetchone()
        assert movie[0] == "Inception"

    # Backup must have been created
    backups = list(tmp_path.glob("fail_migrate.sqlite3.bak*"))
    assert len(backups) >= 1


def test_create_and_restore_backup(tmp_path: Path) -> None:
    db_file = tmp_path / "main.sqlite3"
    db = Database(db_file)
    db.init_db()

    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO media_metadata (torrent_hash, title) VALUES ('h1', 'First Title')"
        )

    # Create backup snapshot
    backup_file = db.create_backup()
    assert backup_file.exists()

    # Modify main database
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE media_metadata SET title = 'Altered Title' WHERE torrent_hash = 'h1'"
        )
        row = conn.execute(
            "SELECT title FROM media_metadata WHERE torrent_hash = 'h1'"
        ).fetchone()
        assert row["title"] == "Altered Title"

    # Restore backup
    db.restore_backup(backup_file)

    # Verify restored title
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT title FROM media_metadata WHERE torrent_hash = 'h1'"
        ).fetchone()
        assert row["title"] == "First Title"
