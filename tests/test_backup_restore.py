import json
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.repositories.collections import CollectionRepository
from backend.repositories.db import Database
from backend.services.settings import SettingsService, validate_zip_member
from backend.services.updater import UpdaterService


def test_validate_zip_member_blocks_traversal_and_escapes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Valid relative members
    assert validate_zip_member("history.sqlite3", data_dir) == data_dir / "history.sqlite3"
    assert validate_zip_member("posters/tt123.jpg", data_dir) == data_dir / "posters" / "tt123.jpg"

    # Relative path traversal
    with pytest.raises(ValueError, match="Path traversal"):
        validate_zip_member("../evil.txt", data_dir)

    with pytest.raises(ValueError, match="Path traversal"):
        validate_zip_member("sub/../../evil.txt", data_dir)

    with pytest.raises(ValueError, match="Path traversal"):
        validate_zip_member("posters/..", data_dir)

    # Absolute paths
    with pytest.raises(ValueError, match="Absolute"):
        validate_zip_member("/etc/passwd", data_dir)

    # Windows drive letters & UNC paths
    with pytest.raises(ValueError, match="Absolute or UNC"):
        validate_zip_member("C:/evil.exe", data_dir)

    with pytest.raises(ValueError, match="Absolute or UNC"):
        validate_zip_member(r"\\attacker\share\payload", data_dir)

    # Null bytes
    with pytest.raises(ValueError, match="Null byte"):
        validate_zip_member("evil\0.txt", data_dir)

    # Empty path
    with pytest.raises(ValueError, match="Invalid empty"):
        validate_zip_member("   ", data_dir)


def test_create_backup_zip_contains_vacuum_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("backend.services.settings.get_data_dir", lambda: data_dir)

    # Initialize live DB and write data
    db = Database(data_dir / "history.sqlite3")
    db.init_db()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO media_metadata (torrent_hash, title) VALUES ('h1', 'Live Title')")

    # Write settings and poster
    (data_dir / "settings.json").write_text(json.dumps({"language": "ru"}), encoding="utf-8")
    posters_dir = data_dir / "posters"
    posters_dir.mkdir()
    (posters_dir / "test.jpg").write_bytes(b"poster_content")

    service = SettingsService(torrserver_client=MagicMock(), settings_provider=lambda: "")
    zip_path = service.create_backup_zip()

    assert zip_path.exists()
    assert zip_path.suffix == ".zip"

    # Verify zip content
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "history.sqlite3" in namelist
        assert "settings.json" in namelist
        assert "posters/test.jpg" in namelist

        # Extract and verify the SQLite snapshot
        extract_dir = tmp_path / "extracted"
        zf.extract("history.sqlite3", extract_dir)
        snap_db = extract_dir / "history.sqlite3"
        with sqlite3.connect(snap_db) as conn:
            row = conn.execute("SELECT title FROM media_metadata WHERE torrent_hash = 'h1'").fetchone()
            assert row[0] == "Live Title"

    zip_path.unlink(missing_ok=True)


def test_restore_backup_zip_successful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("backend.services.settings.get_data_dir", lambda: data_dir)

    service = SettingsService(torrserver_client=MagicMock(), settings_provider=lambda: "")

    # State A
    db = Database(data_dir / "history.sqlite3")
    db.init_db()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO media_metadata (torrent_hash, title) VALUES ('h_original', 'Original Title')")
    (data_dir / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    # Create backup of State A
    backup_zip = service.create_backup_zip()

    # Mutate to State B
    with db.get_connection() as conn:
        conn.execute("UPDATE media_metadata SET title = 'Mutated Title' WHERE torrent_hash = 'h_original'")
    (data_dir / "settings.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8")

    # Restore State A
    service.restore_backup_zip(backup_zip)

    # Verify restoration
    with db.get_connection() as conn:
        row = conn.execute("SELECT title FROM media_metadata WHERE torrent_hash = 'h_original'").fetchone()
        assert row["title"] == "Original Title"

    settings = json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["theme"] == "dark"

    backup_zip.unlink(missing_ok=True)


def test_restore_blocks_malicious_zip_slip_without_touching_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("backend.services.settings.get_data_dir", lambda: data_dir)

    service = SettingsService(torrserver_client=MagicMock(), settings_provider=lambda: "")

    # Create active live DB
    db = Database(data_dir / "history.sqlite3")
    db.init_db()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO media_metadata (torrent_hash, title) VALUES ('live', 'Untouched')")

    # Create malicious ZIP archive with Zip Slip path
    bad_zip = tmp_path / "exploit.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../../evil.txt", "malicious payload")
        zf.writestr("settings.json", "{}")

    outside_file = tmp_path / "evil.txt"
    assert not outside_file.exists()

    with pytest.raises(ValueError, match="Path traversal"):
        service.restore_backup_zip(bad_zip)

    # Outside file must NOT have been created
    assert not outside_file.exists()

    # Active live DB must remain intact
    with db.get_connection() as conn:
        row = conn.execute("SELECT title FROM media_metadata WHERE torrent_hash = 'live'").fetchone()
        assert row["title"] == "Untouched"


def test_restore_corrupted_database_triggers_rollback_and_preserves_live_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("backend.services.settings.get_data_dir", lambda: data_dir)

    service = SettingsService(torrserver_client=MagicMock(), settings_provider=lambda: "")

    # Create active live DB with valuable user data
    db = Database(data_dir / "history.sqlite3")
    db.init_db()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO media_metadata (torrent_hash, title) VALUES ('live_hash', 'Crucial User Data')")

    # Create corrupted ZIP archive containing garbage database bytes
    corrupt_zip = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(corrupt_zip, "w") as zf:
        zf.writestr("history.sqlite3", b"NOT_A_VALID_SQLITE_DATABASE_CORRUPTED_BYTES" * 10)
        zf.writestr("settings.json", "{}")

    # Attempting to restore corrupt zip must raise ValueError
    with pytest.raises(ValueError, match="corrupted database"):
        service.restore_backup_zip(corrupt_zip)

    # Live DB must have been preserved / rolled back completely intact
    with db.get_connection() as conn:
        row = conn.execute("SELECT title FROM media_metadata WHERE torrent_hash = 'live_hash'").fetchone()
        assert row is not None
        assert row["title"] == "Crucial User Data"


def test_collections_export_import_and_snapshot(tmp_path: Path) -> None:
    db = Database(tmp_path / "test_collections.sqlite3")
    db.init_db()

    repo = CollectionRepository(db)
    repo.save_item(
        "favorites",
        {
            "media_id": "m1",
            "title": "Movie 1",
            "year": 2021,
            "rating": 9.0,
            "genres": ["Drama"],
        },
    )
    repo.save_item(
        "watch_later",
        {
            "media_id": "m2",
            "title": "Movie 2",
            "year": 2022,
            "rating": 8.0,
        },
    )

    # Test export
    exported = repo.export_collections()
    assert "favorites" in exported
    assert "watch_later" in exported
    assert len(exported["favorites"]) == 1
    assert exported["favorites"][0]["title"] == "Movie 1"

    # Test snapshot
    snap_path = tmp_path / "snapshot.sqlite3"
    repo.snapshot_database(snap_path)
    assert snap_path.exists()

    with sqlite3.connect(snap_path) as conn:
        row = conn.execute("SELECT title FROM media_collections WHERE media_id = 'm1'").fetchone()
        assert row[0] == "Movie 1"

    # Test import into another DB
    db2 = Database(tmp_path / "test_collections_dest.sqlite3")
    db2.init_db()
    repo2 = CollectionRepository(db2)
    assert len(repo2.list_items("favorites")) == 0

    repo2.import_collections(exported)
    assert len(repo2.list_items("favorites")) == 1
    assert repo2.list_items("favorites")[0]["title"] == "Movie 1"


def test_updater_vacuum_backup_and_restore(tmp_path: Path) -> None:
    source_db = tmp_path / "updater_src.sqlite3"
    backup_db = tmp_path / "updater_bak.sqlite3"

    db = Database(source_db)
    db.init_db()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO media_metadata (torrent_hash, title) VALUES ('u1', 'Update Title')")

    # Test _backup_database
    UpdaterService._backup_database(source_db, backup_db)
    assert backup_db.exists()

    with sqlite3.connect(backup_db) as conn:
        row = conn.execute("SELECT title FROM media_metadata WHERE torrent_hash = 'u1'").fetchone()
        assert row[0] == "Update Title"

    # Modify source and test _restore_database
    with db.get_connection() as conn:
        conn.execute("UPDATE media_metadata SET title = 'Corrupted Update' WHERE torrent_hash = 'u1'")

    UpdaterService._restore_database(backup_db, source_db)

    with sqlite3.connect(source_db) as conn:
        row = conn.execute("SELECT title FROM media_metadata WHERE torrent_hash = 'u1'").fetchone()
        assert row[0] == "Update Title"
