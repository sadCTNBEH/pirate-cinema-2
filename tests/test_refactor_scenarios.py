import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.core.settings import BASE_DIR
from backend.exceptions import (
    AppException,
    DatabaseError,
    ExternalServiceError,
    NotFoundError,
)
from backend.models.playback import PlayCommand
from backend.repositories.audio import AudioRepository
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.library import LibraryService
from backend.services.magnet import MagnetService
from backend.services.metadata import MetadataService
from backend.services.playback import PlaybackService
from backend.services.search import SearchService
from backend.services.settings import SettingsService


def test_custom_exceptions():
    err = NotFoundError("Episode not found")
    assert err.status_code == 404
    assert err.message == "Episode not found"
    assert isinstance(err, AppException)

    ext = ExternalServiceError("TorrServer down", status_code=502)
    assert ext.status_code == 502

    db_err = DatabaseError("Disk full")
    assert db_err.status_code == 500


def test_repositories_oop_and_parse_ep():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        # Repositories with strict DI
        library_repo = LibraryRepository(db=db)
        history_repo = HistoryRepository(db=db)
        metadata_repo = MetadataRepository(db=db)
        audio_repo = AudioRepository(db=db)
        playback_repo = PlaybackRepository(db=db)

        # parse_ep tests
        assert LibraryRepository.parse_ep("Breaking.Bad.S01E03.mkv")[0:3] == (1, 1, 3)
        assert LibraryRepository.parse_ep("Movie.2023.1080p.mkv")[0] == 0

        # Base repository connection
        with library_repo.connection() as conn:
            assert conn is not None

        # History and audio repo test
        history_repo.mark_played("hash1", 0, "file1.mkv")
        history_repo.update_progress("hash1", 0, 100, 1000, audio_track=2)
        audio_repo.set_audio_track("hash1", 2, file_index=0)
        assert audio_repo.get_audio_track("hash1", file_index=0) == 2

        # Metadata repo
        metadata_repo.save_metadata_title("hash1", "Breaking Bad")
        metadata_repo.save_media_type("hash1", "series")

        recent = library_repo.get_recent_history(limit=10)
        assert len(recent) == 1
        assert recent[0]["torrent_hash"] == "hash1"
        assert recent[0]["title"] == "Breaking Bad"

        # Playback repo
        state = playback_repo.get_state("hash1", 0)
        assert state is not None
        assert state["playback_timecode"] == 100


@pytest.mark.anyio
async def test_services_with_di():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        lib_repo = LibraryRepository(db=db)
        meta_repo = MetadataRepository(db=db)
        mock_torrserver = MagicMock()
        mock_torrserver.get_torrents = AsyncMock(
            return_value=[{"hash": "h1", "title": "Test Movie"}]
        )
        mock_torrserver.torrent_video_files = AsyncMock(
            return_value=[{"id": 1, "name": "S01E01.mkv"}]
        )

        mock_catalog = MagicMock()
        mock_catalog.clean_title = MagicMock(return_value=("Test Movie", None))
        mock_catalog.search_metadata = AsyncMock(return_value=[])
        meta_service = MetadataService(
            metadata_repo=meta_repo,
            library_repo=lib_repo,
            catalog_client=mock_catalog,
            posters_dir=Path(tmp_dir) / "posters",
        )

        lib_service = LibraryService(
            library_repo=lib_repo,
            torrserver_client=mock_torrserver,
            settings_provider=lambda: "http://localhost:8090",
            metadata_service=meta_service,
            posters_dir=Path(tmp_dir) / "posters",
        )

        torrents = await lib_service.get_torrents_list()
        assert torrents == {"Torrents": [{"hash": "h1", "title": "Test Movie"}]}

        files_struct = await lib_service.get_torrent_files_structure("h1")
        assert files_struct["type"] == "series"
        assert "1" in files_struct["seasons"]

        await meta_service.shutdown()


@pytest.mark.anyio
async def test_playback_service():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        playback_repo = PlaybackRepository(db=db)
        history_repo = HistoryRepository(db=db)
        metadata_repo = MetadataRepository(db=db)

        mock_controller = MagicMock()
        mock_controller.is_running = True
        mock_controller.launch = MagicMock()
        mock_controller.stop = MagicMock()

        mock_torrserver = MagicMock()
        mock_torrserver.stream_url = MagicMock(
            return_value="http://localhost:8090/stream/1"
        )

        service = PlaybackService(
            playback_repo=playback_repo,
            history_repo=history_repo,
            metadata_repo=metadata_repo,
            mpv_controller_factory=lambda: mock_controller,
            torrserver_client=mock_torrserver,
            settings_provider=lambda: "http://localhost:8090",
        )

        # Domain PlayCommand
        cmd = PlayCommand(hash="h1", file_id=0, file_name="S01E01.mkv")
        res = await service.launch(cmd)
        assert res == "launched"
        assert "h1" in service.active_states

        state = await service.get_state("h1", 0)
        assert state.hash == "h1"
        assert state.file_id == 0

        # Test progress callback handling of string/auto/no and numeric values
        service._handle_progress("h1", "aid", "auto")
        assert service.active_states["h1"].audio_track == 0

        service._handle_progress("h1", "aid", 2)
        assert service.active_states["h1"].audio_track == 2

        service._handle_progress("h1", "aid", "no")
        assert service.active_states["h1"].audio_track == 0

        service._handle_progress("h1", "sid", "auto")
        assert service.active_states["h1"].subtitle_track == 0

        service._handle_progress("h1", "sid", 3)
        assert service.active_states["h1"].subtitle_track == 3

        service._handle_progress("h1", "sid", "no")
        assert service.active_states["h1"].subtitle_track == 0

        service._handle_progress("h1", "time-pos", 125.7)
        assert service.active_states["h1"].timecode == 125

        service._handle_progress("h1", "duration", 3600.0)
        assert service.active_states["h1"].duration == 3600

        # Non-numeric timecode / duration should not crash or corrupt state
        service._handle_progress("h1", "time-pos", "auto")
        assert service.active_states["h1"].timecode == 125

        service._handle_progress("h1", "flush", True)

        # Switching episode in existing player window
        cmd2 = PlayCommand(hash="h1", file_id=1, file_name="S01E02.mkv")
        res2 = await service.launch(cmd2)
        assert res2 == "launched"
        assert service.active_states["h1"].file_id == 1
        assert service.active_states["h1"].timecode == 0
        assert any(
            call[0][0][0] == "loadfile"
            for call in mock_controller.send_command.call_args_list
        )

        await service.stop_all()
        assert len(service.active_states) == 0


@pytest.mark.anyio
async def test_magnet_service():
    mock_torrserver = MagicMock()
    mock_torrserver.add_magnet = AsyncMock(return_value={"hash": "mag123"})
    mock_torrserver.remove_torrent = AsyncMock()

    service = MagnetService(
        torrserver_client=mock_torrserver,
        settings_provider=lambda: "http://localhost:8090",
        metadata_service=None,
    )

    res = await service.add_magnet("magnet:?xt=urn:btih:mag123", "Show Title")
    assert res == {"hash": "mag123"}

    del_res = await service.delete_torrent("mag123")
    assert del_res == {"status": "removed"}


@pytest.mark.anyio
async def test_search_service():
    mock_torrserver = MagicMock()
    mock_torrserver.search_all = AsyncMock(return_value=[{"title": "Movie 1"}])
    search_svc = SearchService(
        torrserver_client=mock_torrserver,
        settings_provider=lambda: "http://localhost:8090",
    )
    res = await search_svc.search_torrents("Matrix")
    assert res == [{"title": "Movie 1"}]


def test_settings_service():
    mock_torrserver = MagicMock()
    service = SettingsService(
        torrserver_client=mock_torrserver,
        settings_provider=lambda: "http://localhost:8090",
    )

    settings = service.get_settings()
    assert "torrserver_url" in settings

    zip_path = service.create_backup_zip()
    assert zip_path.exists()
    zip_path.unlink()


def test_api_routes_integration():
    client = TestClient(app)

    # 1. Settings
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert "torrserver_url" in resp.json()

    # 2. i18n
    resp = client.get("/api/i18n")
    assert resp.status_code == 200
    assert "strings" in resp.json()

    # 3. Player stop
    resp = client.post("/api/player/stop")
    assert resp.status_code == 200
    assert resp.json() == {"status": "stopped"}

    # 4. Library recent
    resp = client.get("/api/library/recent")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 5. Settings health
    resp = client.get("/api/settings/health")
    assert resp.status_code == 200

    # 6. Version
    from backend import views  # noqa: F401

    resp = client.get("/version.json")
    assert resp.status_code == 200
    assert resp.json().get("version") == json.loads(
        (BASE_DIR / "version.json").read_text(encoding="utf-8")
    )["version"]


@pytest.mark.anyio
async def test_playback_auto_advances_on_eof_reached():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        playback_repo = PlaybackRepository(db=db)
        history_repo = HistoryRepository(db=db)
        metadata_repo = MetadataRepository(db=db)

        mock_controller = MagicMock()
        mock_controller.is_running = True
        mock_controller.launch = MagicMock()
        mock_controller.send_command = MagicMock()
        mock_controller.stop = MagicMock()

        mock_torrserver = MagicMock()
        mock_torrserver.stream_url = MagicMock(
            return_value="http://localhost:8090/stream/1"
        )
        mock_torrserver.torrent_video_files = AsyncMock(
            return_value=[
                {"id": 0, "name": "S01E01.mkv"},
                {"id": 1, "name": "S01E02.mkv"},
            ]
        )

        service = PlaybackService(
            playback_repo=playback_repo,
            history_repo=history_repo,
            metadata_repo=metadata_repo,
            mpv_controller_factory=lambda: mock_controller,
            torrserver_client=mock_torrserver,
            settings_provider=lambda: "http://localhost:8090",
        )

        cmd = PlayCommand(hash="series1", file_id=0, file_name="S01E01.mkv")
        await service.launch(cmd)
        service.active_states["series1"].duration = 1800
        service.active_states["series1"].timecode = 1795

        # Simulate MPV eof-reached property-change
        service._handle_progress("series1", "eof-reached", True)
        await asyncio.sleep(0.1)

        # Active state should transition to next episode
        assert service.active_states["series1"].file_id == 1
        assert service.active_states["series1"].timecode == 0
        # Running controller should receive command to load next file without relaunching process
        assert any(
            call[0][0][0] == "loadfile"
            for call in mock_controller.send_command.call_args_list
        )

        await service.stop_all()


@pytest.mark.anyio
async def test_playback_does_not_advance_on_quit_or_close():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        playback_repo = PlaybackRepository(db=db)
        history_repo = HistoryRepository(db=db)
        metadata_repo = MetadataRepository(db=db)

        mock_controller = MagicMock()
        mock_controller.is_running = True
        mock_controller.launch = MagicMock()
        mock_controller.stop = MagicMock()

        mock_torrserver = MagicMock()
        mock_torrserver.stream_url = MagicMock(
            return_value="http://localhost:8090/stream/1"
        )
        mock_torrserver.torrent_video_files = AsyncMock(
            return_value=[
                {"id": 0, "name": "S01E01.mkv"},
                {"id": 1, "name": "S01E02.mkv"},
            ]
        )

        service = PlaybackService(
            playback_repo=playback_repo,
            history_repo=history_repo,
            metadata_repo=metadata_repo,
            mpv_controller_factory=lambda: mock_controller,
            torrserver_client=mock_torrserver,
            settings_provider=lambda: "http://localhost:8090",
        )

        cmd = PlayCommand(hash="series2", file_id=0, file_name="S01E01.mkv")
        await service.launch(cmd)
        # Launch resolves availability for the OSD; closing must not resolve/advance again.
        mock_torrserver.torrent_video_files.reset_mock()

        # User closes MPV window (reason="quit")
        service._handle_end("series2", "quit")
        await asyncio.sleep(0.1)

        # Player should be stopped and NOT advance to episode 1
        mock_torrserver.torrent_video_files.assert_not_called()
        assert "series2" not in service.active_states
        assert "series2" not in service.controllers

        # Also test with reason="stop" when controller is stopped
        await service.launch(cmd)
        mock_torrserver.torrent_video_files.reset_mock()
        mock_controller.is_running = False
        service._handle_end("series2", "stop")
        await asyncio.sleep(0.1)
        mock_torrserver.torrent_video_files.assert_not_called()
        assert "series2" not in service.active_states


@pytest.mark.anyio
async def test_playback_auto_advances_on_timepos_end():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        playback_repo = PlaybackRepository(db=db)
        history_repo = HistoryRepository(db=db)
        metadata_repo = MetadataRepository(db=db)

        mock_controller = MagicMock()
        mock_controller.is_running = True
        mock_controller.launch = MagicMock()
        mock_controller.send_command = MagicMock()
        mock_controller.stop = MagicMock()

        mock_torrserver = MagicMock()
        mock_torrserver.stream_url = MagicMock(
            return_value="http://localhost:8090/stream/1"
        )
        mock_torrserver.torrent_video_files = AsyncMock(
            return_value=[
                {"id": 0, "name": "S01E01.mkv"},
                {"id": 1, "name": "S01E02.mkv"},
            ]
        )

        service = PlaybackService(
            playback_repo=playback_repo,
            history_repo=history_repo,
            metadata_repo=metadata_repo,
            mpv_controller_factory=lambda: mock_controller,
            torrserver_client=mock_torrserver,
            settings_provider=lambda: "http://localhost:8090",
        )

        cmd = PlayCommand(hash="series3", file_id=0, file_name="S01E01.mkv")
        await service.launch(cmd)
        service.active_states["series3"].duration = 1800
        service.active_states["series3"].timecode = 1700

        # Simulate time-pos reaching within 2s of duration (1799.0s out of 1800s)
        service._handle_progress("series3", "time-pos", 1799.0)
        await asyncio.sleep(0.1)

        # Active state should transition to next episode
        assert service.active_states["series3"].file_id == 1
        assert service.active_states["series3"].timecode == 0
        assert any(
            call[0][0][0] == "loadfile"
            for call in mock_controller.send_command.call_args_list
        )

        await service.stop_all()


@pytest.mark.anyio
async def test_metadata_poster_fallback_and_protocol_relative_url(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()

        meta_repo = MetadataRepository(db=db)
        lib_repo = LibraryRepository(db=db)

        mock_catalog = MagicMock()
        mock_catalog.clean_title = MagicMock(return_value=("Movie Test", None))
        mock_catalog.search = AsyncMock(
            return_value=[
                {
                    "id": "tt123",
                    "title": "Movie Test",
                    "poster_url": "https://broken.example.com/poster.jpg",
                    "background_url": "//cdn.example.com/valid_bg.jpg",
                    "year": 2024,
                    "rating": 8.0,
                }
            ]
        )

        calls = []

        class MockClient:
            is_closed = False

            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def aclose(self):
                self.is_closed = True

            async def get(self, url, headers=None, **kwargs):
                calls.append(url)
                if "broken.example.com" in url:
                    raise httpx.HTTPStatusError(
                        "403 Forbidden",
                        request=None,
                        response=MagicMock(status_code=403),
                    )
                resp = MagicMock()
                resp.status_code = 200
                resp.content = (
                    b"\xff\xd8\xff\xe0" + b"x" * 200
                )  # valid dummy jpeg bytes (>100 bytes)
                resp.json.return_value = {}
                resp.raise_for_status = MagicMock()
                return resp

        import backend.services.metadata as meta_mod

        monkeypatch.setattr(meta_mod.httpx, "AsyncClient", MockClient)

        posters_path = Path(tmp_dir) / "posters"
        service = MetadataService(
            metadata_repo=meta_repo,
            library_repo=lib_repo,
            catalog_client=mock_catalog,
            posters_dir=posters_path,
        )

        await service.fetch_and_save_metadata("testhash123", "Movie Test 2024")

        # Verify protocol relative URL was normalized to https://
        assert any("https://cdn.example.com/valid_bg.jpg" in c for c in calls)
        # Verify poster file was created on disk
        saved_file = posters_path / "testhash123.jpg"
        assert saved_file.exists()
        assert len(saved_file.read_bytes()) > 100
