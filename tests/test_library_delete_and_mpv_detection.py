import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.api.schemas.library import LibraryFilter
from backend.core.settings import find_mpv_binary, resolve_mpv_binary
from backend.repositories.db import Database
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.services.library import LibraryService
from backend.services.magnet import MagnetService


def test_library_repository_delete_torrent_removes_from_all_tables():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite3"
        db = Database(db_path=db_path)
        db.init_db()

        repo = LibraryRepository(db=db)
        meta_repo = MetadataRepository(db=db)

        test_hash = "abc1234567890abcdef1234567890abcdef1234"

        # Populate tables
        meta_repo.save_full_metadata(
            torrent_hash=test_hash,
            title="Test Movie",
            overview="Test Overview",
            year=2023,
            rating=8.0,
            poster_file=f"{test_hash}.jpg",
            genres_json=json.dumps(["Action"]),
        )
        repo.save_media_type(test_hash, "movie")

        with db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO media_file_history (
                    torrent_hash, file_index, file_name, file_path, first_played_at,
                    playback_timecode, playback_duration, is_watched, last_played_at, launch_count
                ) VALUES (?, 0, 'test.mkv', 'test.mkv', '2023-01-01', 100, 1000, 0, '2023-01-01', 1)
                """,
                (test_hash,),
            )
            conn.execute(
                "INSERT INTO media_audio_tracks (torrent_hash, track_id) VALUES (?, 1)",
                (test_hash,),
            )
            conn.commit()

        # Verify item appears in query_library
        items = repo.query_library()
        assert len(items) == 1
        assert items[0]["torrent_hash"] == test_hash

        # Delete torrent
        repo.delete_torrent(test_hash)

        # Verify all tables are cleared of this hash
        with db.get_connection() as conn:
            assert conn.execute("SELECT count(*) FROM media_metadata WHERE torrent_hash = ?", (test_hash,)).fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM media_types WHERE torrent_hash = ?", (test_hash,)).fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM media_file_history WHERE torrent_hash = ?", (test_hash,)).fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM media_audio_tracks WHERE torrent_hash = ?", (test_hash,)).fetchone()[0] == 0

        # Verify query_library is empty
        assert repo.query_library() == []


@pytest.mark.anyio
async def test_library_service_delete_torrent_and_not_reappearing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite3"
        posters_dir = Path(tmp_dir) / "posters"
        posters_dir.mkdir(parents=True, exist_ok=True)

        db = Database(db_path=db_path)
        db.init_db()

        repo = LibraryRepository(db=db)
        test_hash = "def1234567890abcdef1234567890abcdef1234"
        repo.ensure_torrent(test_hash, "My Series")
        repo.save_media_type(test_hash, "series")

        # Create dummy poster file
        poster_file = posters_dir / f"{test_hash}.jpg"
        poster_file.write_bytes(b"dummy image data")
        assert poster_file.exists()

        mock_ts = MagicMock()
        mock_ts.get_torrents = AsyncMock(return_value=[])
        mock_ts.remove_torrent = AsyncMock()

        service = LibraryService(
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            library_repo=repo,
            metadata_service=None,
            posters_dir=posters_dir,
        )

        # Before deletion: query returns 1 item
        items_before = await service.get_filtered_library(LibraryFilter())
        assert len(items_before) == 1

        # Delete torrent
        await service.delete_torrent(test_hash)

        # Verify poster deleted
        assert not poster_file.exists()
        # Verify TorrServer remove called
        mock_ts.remove_torrent.assert_awaited_once_with("http://localhost:8090", test_hash)

        # After reload / re-querying: item does NOT return
        items_after = await service.get_filtered_library(LibraryFilter())
        assert len(items_after) == 0


@pytest.mark.anyio
async def test_library_service_delete_all_continues_after_torrserver_error():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        mock_ts = MagicMock()
        mock_ts.get_torrents = AsyncMock(
            return_value=[{"hash": "first"}, {"hash": "second"}]
        )
        mock_ts.remove_torrent = AsyncMock(
            side_effect=[httpx.ConnectError("offline"), None]
        )

        service = LibraryService(
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            library_repo=LibraryRepository(db=db),
            metadata_service=None,
        )

        await service.delete_all_torrents()

        assert mock_ts.remove_torrent.await_count == 2
        mock_ts.remove_torrent.assert_any_await("http://localhost:8090", "first")
        mock_ts.remove_torrent.assert_any_await("http://localhost:8090", "second")


@pytest.mark.anyio
async def test_magnet_service_delete_torrent_cleans_db():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite3"
        db = Database(db_path=db_path)
        db.init_db()

        repo = LibraryRepository(db=db)
        test_hash = "1111222233334444555566667777888899990000"
        repo.ensure_torrent(test_hash, "Magnet Movie")

        mock_ts = MagicMock()
        mock_ts.remove_torrent = AsyncMock()

        service = MagnetService(
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=None,
            library_repo=repo,
        )

        res = await service.delete_torrent(test_hash)
        assert res == {"status": "removed"}
        mock_ts.remove_torrent.assert_awaited_once_with("http://localhost:8090", test_hash)

        # DB is clean
        assert repo.query_library() == []


def test_find_mpv_binary_custom_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_mpv = Path(tmp_dir) / "custom_mpv.exe"
        fake_mpv.write_text("fake binary")

        prefs = {"player_path": str(fake_mpv)}
        found = find_mpv_binary(prefs)
        assert found == fake_mpv.resolve()


def test_find_mpv_binary_dir_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_dir = Path(tmp_dir)
        fake_mpv = fake_dir / "mpv.exe"
        fake_mpv.write_text("fake binary")

        prefs = {"player_path": str(fake_dir)}
        found = find_mpv_binary(prefs)
        assert found == fake_mpv.resolve()


def test_resolve_mpv_binary_fallback():
    # When no mpv is found and prefs is empty
    empty_prefs = {"player_path": "non_existent_file_12345.exe"}
    res = resolve_mpv_binary(empty_prefs)
    assert res is not None


@pytest.mark.anyio
async def test_delete_online_item_never_calls_torrserver():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite3"
        db = Database(db_path=db_path)
        db.init_db()

        repo = LibraryRepository(db=db)
        online_hash = "online:rutube:6e62ad497b0bfb57c9c0b108e9d97911"

        mock_ts = MagicMock()
        mock_ts.remove_torrent = AsyncMock()

        magnet_svc = MagnetService(
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=None,
            library_repo=repo,
        )

        res = await magnet_svc.delete_torrent(online_hash)
        assert res == {"status": "removed"}
        mock_ts.remove_torrent.assert_not_called()

        lib_svc = LibraryService(
            library_repo=repo,
            torrserver_client=mock_ts,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=None,
            posters_dir=Path(tmp_dir) / "posters",
        )
        await lib_svc.delete_torrent(online_hash)
        mock_ts.remove_torrent.assert_not_called()
